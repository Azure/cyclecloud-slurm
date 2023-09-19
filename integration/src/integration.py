import argparse
import json
import os
import shutil
from subprocess import check_output
import sys
import time
from typing import Dict, List


CWD = os.path.dirname(os.path.realpath(__file__))
DEFAULT_TEMPLATE = os.path.realpath(os.path.join(CWD, "../../templates/slurm.txt"))
CLUSTERS_DIR = os.path.realpath(os.path.join(CWD, "../clusters"))
CSEXEC = os.path.join(os.environ["CS_HOME"], "cycle_server")
NFS_CLUSTER_NAME = "integration-nfs"


DEFAULTS = {
    "configuration_slurm_accounting_enabled": True,
    "additional_slurm_config": "SuspendTimeout=60",
}


def _image(image_name: str) -> Dict:
    return {
        "HPCImageName": image_name,
        "HTCImageName": image_name,
        "DynamicImageName": image_name,
        "SchedulerImageName": image_name,
    }


def _cluster_def(*dicts: Dict) ->Dict:
    items = list(DEFAULTS.items())
    for d in dicts:
        items += list(d.items())
    return dict(items)

CLUSTER_DEFS = {
    "basic-centos7": _cluster_def(_image("cycle.image.centos7")),
    "basic-almalinux8": _cluster_def(_image("almalinux8")),
    "basic-ubuntu20": _cluster_def(_image("cycle.image.ubuntu20")),
    "basic-sles15": _cluster_def(_image("cycle.image.sles15-hpc"), {
        "configuration_slurm_accounting_enabled": False,
    }),
    "ha-ubuntu20": _cluster_def(_image("cycle.image.ubuntu20"), {
        "configuration_slurm_ha_enabled": True,
        "AdditonalNFSAddress": "$cli_nfs_address",
        "NFSAddress": "$cli_nfs_address",
    }),
    "nfs-ubuntu20": _cluster_def(_image("cycle.image.ubuntu20"), {
        "configuration_slurm_ha_enabled": False,
        "AdditonalNFSAddress": "$cli_nfs_address",
        "AdditionalNAS": True,
        "NFSAddress": "$cli_nfs_address",
        "NFSSchedDisable": True,
        "NFSType": "External",
        "__slurm_versionless__": True,
    }),
    "manual-scale": _cluster_def(_image("cycle.image.ubuntu20"), {
        "additional_slurm_config": "SuspendTime=-1",
    }),
}


def generate_clusters(basic_properties: Dict, skip_stage_resources: bool = False, nfs_address: str = "") -> None:
    nfs_address = nfs_address or get_nfs_ip()

    # clear out prior clusters
    for fil in os.listdir(CLUSTERS_DIR):
        os.remove(os.path.join(CLUSTERS_DIR, fil))

    version_helper_path = os.path.realpath(
        "../slurm/install/slurm_supported_version.py"
    )

    supported_slurm_versions = (
        check_output([sys.executable, version_helper_path], cwd=CWD).decode().split()
    )

    for slurm_version in supported_slurm_versions:
        for base_cluster_name, cluster_def in CLUSTER_DEFS.items():
            if cluster_def.get("__slurm_versionless__"):
                if slurm_version != supported_slurm_versions[0]:
                    continue
            for key in list(cluster_def.keys()):
                value = cluster_def[key]
                if value == "$cli_nfs_address":
                    cluster_def[key] = nfs_address

            cluster_name = f"{base_cluster_name}-{slurm_version}"
            cluster_properties = dict(basic_properties)
            with open(f"clusters/{cluster_name}.json", "w") as f:
                cluster_properties.update(cluster_def)
                cluster_properties["configuration_slurm_version"] = slurm_version + "-1"
                json.dump(cluster_properties, f, indent=2)

                _add_cluster_init(
                    cluster_properties["SchedulerImageName"],
                    cluster_name,
                    skip_stage_resources,
                )


def _add_cluster_init(
    scheduler_image_name: str, cluster_name: str, skip_stage_resources: bool
) -> None:
    if "sles" in scheduler_image_name:
        cloud_init = """#!/bin/bash
zypper install -y mariadb
systemctl start mariadb
"""
    elif "ubuntu20" in scheduler_image_name:
        cloud_init = """#!/bin/bash
apt update
apt install -y mariadb-server
systemctl enable mariadb.service
systemctl start mariadb.service
mysql --connect-timeout=120 -u root -e "UPDATE mysql.user SET plugin='mysql_native_password' WHERE user='root'; FLUSH privileges;"
"""
    elif "ubuntu22" in scheduler_image_name:
        cloud_init = """#!/bin/bash
apt update
apt install -y mariadb-server
systemctl enable mariadb.service
systemctl start mariadb.service
"""
    else:
        cloud_init = """#!/bin/bash
yum install -y mariadb-server
systemctl enable mariadb.service
systemctl start mariadb.service
"""
    with open(DEFAULT_TEMPLATE) as fr:
        with open(f"clusters/{cluster_name}.txt", "w") as fw:
            for line in fr:
                fw.write(line)
                if "[[node defaults]]" in line:
                    fw.write(f"    StageResources={not skip_stage_resources}\n")
                if "[[node scheduler]]" in line:
                    fw.write(f"    CloudInit='''{cloud_init}'''\n")


def _cluster_names(include_nfs: bool = False) -> List[str]:
    ret = sorted(list(set([x.rsplit(".", 1)[0] for x in os.listdir(CLUSTERS_DIR)])))
    if include_nfs:
        ret.append(NFS_CLUSTER_NAME)
    return ret


def import_clusters() -> None:

    cluster_names = _cluster_names()

    for cluster_name in cluster_names:
        print(f"Importing {cluster_name}")
        props_file = f"{CLUSTERS_DIR}/{cluster_name}.json"
        args = ["cyclecloud", "import_cluster", "--force", "-p", props_file]

        custom_template = os.path.join(CLUSTERS_DIR, f"{cluster_name}.txt")
        if os.path.exists(custom_template):
            args.extend(["-f", custom_template])
        else:
            args.extend(["-f", DEFAULT_TEMPLATE])
        args.extend(["-c", "Slurm", cluster_name])
        print(f"Running `{' '.join(args)}`")
        check_output(args, cwd=CWD)


def start_clusters(skip_tests: bool = False) -> None:
    cluster_names = _cluster_names()

    for cluster_name in cluster_names:
        print(f"Starting {cluster_name}")
        env = dict(os.environ)
        env["CycleCloudDevel"] = "1"
        # check_output(["cyclecloud", "await_target_state", cluster_name], env=env)
        args = ["cyclecloud", "start_cluster", cluster_name]
        if not skip_tests:
            args.append("--test")
        check_output(args, cwd=CWD)


def shutdown_clusters(include_nfs: bool) -> None:
    cluster_names = _cluster_names(include_nfs)
    
    for cluster_name in cluster_names:
        print(f"Shutting down {cluster_name}")
        try:
            check_output(["cyclecloud", "show_cluster", cluster_name])
        except:
            continue
        args = ["cyclecloud", "terminate_cluster", cluster_name]
        check_output(args, cwd=CWD)


def delete_clusters(include_nfs: bool) -> None:
    cluster_names = _cluster_names(include_nfs)
    for cluster_name in cluster_names:
        print(f"Deleting {cluster_name}")
        try:
            check_output(["cyclecloud", "show_cluster", cluster_name])
        except:
            continue

        try:
            check_output(["cyclecloud", "await_target_state", cluster_name])
        except:
            continue

        args = ["cyclecloud", "delete_cluster", cluster_name]
        check_output(args, cwd=CWD)


def setup_nfs(properties_file: str) -> None:
    args = ["cyclecloud", "create_cluster", "nfs_template_1.1.0", NFS_CLUSTER_NAME, "-p", properties_file, "--force"]
    check_output(args, cwd=CWD)

    cs_home = os.getenv("CS_HOME")
    assert cs_home, "Please set CS_HOME"
    nfs_cloud_init_tmp = os.path.join(cs_home, "config", "data", "integration-nfs.txt.tmp")
    nfs_cloud_init = os.path.join(cs_home, "config", "data", "integration-nfs.txt")

    with open(nfs_cloud_init_tmp, "w") as fw:
        fw.write('AdType = "Cloud.Node"\n')
        fw.write('ClusterName = NFS_CLUSTER_NAME\n')
        fw.write('Name = "filer"\n')
        fw.write('CloudInit = "#!/bin/bash\\n')
        fw.write("echo '/mnt/exports/sched *(rw,sync,no_root_squash)' >> /etc/exports\\n")
        fw.write("echo '/mnt/exports/shared *(rw,sync,no_root_squash)' >> /etc/exports\"")

    shutil.move(nfs_cloud_init_tmp, nfs_cloud_init)
    while os.path.exists(nfs_cloud_init):
        time.sleep(.5)

    args = ["cyclecloud", "start_cluster", NFS_CLUSTER_NAME]
    check_output(args, cwd=CWD)


def get_nfs_ip() -> str:
    args = ["cyclecloud", "show_nodes", "filer", "-c", NFS_CLUSTER_NAME, "--format", "json"]
    
    def _show_node() -> List[Dict]:
        return json.loads(check_output(args, cwd=CWD).decode())
    
    show_nodes_out = _show_node()
    while show_nodes_out[0].get("State") != "Started":
        print(f"Waiting for integration-nfs to start - current state: {show_nodes_out[0].get('State')}")
        time.sleep(5)
        show_nodes_out = _show_node()

    return show_nodes_out[0]["Instance"]["PrivateIp"]


def main() -> None:
    parser = argparse.ArgumentParser(usage="""See README.md for usage, but the basic idea is
    # create props.json
    python3 src/integration.py setup_nfs -p props.json 
    python3 src/integration.py import -p props.json 
    python3 src/integration.py start
    python3 src/integration.py shutdown --include-nfs
    python3 src/integration.py delete --include-nfs
    """)
    subparsers = parser.add_subparsers(dest="command")

    setup_nfs_parser = subparsers.add_parser("setup_nfs")
    setup_nfs_parser.add_argument("--properties", "-p", type=str, required=True)

    import_clusters_parser = subparsers.add_parser("import")
    import_clusters_parser.add_argument("--skip-stage-resources", action="store_true")
    import_clusters_parser.add_argument("--properties", "-p", type=str, required=True)
    import_clusters_parser.add_argument("--nfs-address", "-n", type=str, required=False)

    start_clusters_parser = subparsers.add_parser("start")
    start_clusters_parser.add_argument("--skip-tests", action="store_true")

    shutdown_parser = subparsers.add_parser("shutdown")
    shutdown_parser.add_argument("--include-nfs", action="store_true", default=False)
    delete_parser = subparsers.add_parser("delete")
    delete_parser.add_argument("--include-nfs", action="store_true", default=False)

    args = parser.parse_args()

    if args.command == "setup_nfs":
        setup_nfs(os.path.abspath(args.properties))
    elif args.command == "import":
        with open(args.properties) as f:
            basic_properties = json.load(f)
            
        generate_clusters(basic_properties, args.skip_stage_resources, args.nfs_address)
        import_clusters()
    elif args.command == "start":
        start_clusters(args.skip_tests)
    elif args.command == "shutdown":
        shutdown_clusters(args.include_nfs)
    elif args.command == "delete":
        delete_clusters(args.include_nfs)
    else:
        raise ValueError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
