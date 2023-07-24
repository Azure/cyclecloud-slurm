import argparse
import json
import os
from subprocess import check_output
import sys
from typing import Dict, List

CWD = os.path.dirname(os.path.realpath(__file__))
DEFAULT_TEMPLATE = os.path.realpath(os.path.join(CWD, "../../templates/slurm.txt"))
CLUSTERS_DIR = os.path.realpath(os.path.join(CWD, "../clusters"))
CSEXEC = os.path.join(os.environ["CS_HOME"], "cycle_server")

CLUSTER_DEFS = {
    "basic-centos7": {
        "HPCImageName": "cycle.image.centos7",
        "HTCImageName": "cycle.image.centos7",
        "DynamicImageName": "cycle.image.centos7",
        "SchedulerImageName": "cycle.image.centos7",
        "additional_slurm_config": "SuspendTimeout=60",
    },
    "basic-almalinux8": {
        "HPCImageName": "almalinux8",
        "HTCImageName": "almalinux8",
        "DynamicImageName": "almalinux8",
        "SchedulerImageName": "almalinux8",
        "additional_slurm_config": "SuspendTimeout=60",
    },
    "basic-ubuntu20": {
        "HPCImageName": "cycle.image.ubuntu20",
        "HTCImageName": "cycle.image.ubuntu20",
        "DynamicImageName": "cycle.image.ubuntu20",
        "SchedulerImageName": "cycle.image.ubuntu20",
        "additional_slurm_config": "SuspendTimeout=60",
    },
    "basic-ubuntu22": {
        "HPCImageName": "cycle.image.ubuntu22",
        "HTCImageName": "cycle.image.ubuntu22",
        "DynamicImageName": "cycle.image.ubuntu22",
        "SchedulerImageName": "cycle.image.ubuntu22",
        "additional_slurm_config": "SuspendTimeout=60",
    },
    "basic-sles15": {
        "HPCImageName": "cycle.image.sles15-hpc",
        "HTCImageName": "cycle.image.sles15-hpc",
        "DynamicImageName": "cycle.image.sles15-hpc",
        "SchedulerImageName": "cycle.image.sles15-hpc",
        "additional_slurm_config": "SuspendTimeout=60",
    },
    "manual-scale": {
        "HPCImageName": "almalinux8",
        "HTCImageName": "almalinux8",
        "DynamicImageName": "almalinux8",
        "SchedulerImageName": "almalinux8",
        "additional_slurm_config": "SuspendTime=-1",
    },
}


def generate_clusters(basic_properties: Dict, stage_resources: bool = False) -> None:
    version_helper_path = os.path.realpath(
        "../slurm/install/slurm_supported_version.py"
    )
    supported_slurm_versions = (
        check_output([sys.executable, version_helper_path], cwd=CWD).decode().split()
    )
    for slurm_version in supported_slurm_versions:
        for base_cluster_name, cluster_def in CLUSTER_DEFS.items():
            if "sles" in base_cluster_name and slurm_version > "22.05.9999":
                continue
            cluster_name = f"{base_cluster_name}-{slurm_version}"
            cluster_properties = dict(basic_properties)
            with open(f"clusters/{cluster_name}.json", "w") as f:
                cluster_properties.update(cluster_def)
                cluster_properties["configuration_slurm_version"] = slurm_version
                json.dump(cluster_properties, f, indent=2)

                _add_cluster_init(
                    cluster_properties["SchedulerImageName"],
                    cluster_name,
                    stage_resources,
                )


def _add_cluster_init(
    scheduler_image_name: str, cluster_name: str, stage_resources: bool
) -> None:
    if "sles" in scheduler_image_name:
        cloud_init = """#!/bin/bash
zypper install -y mariadb
systemctl start mariadb
"""
    elif "ubuntu" in scheduler_image_name:
        cloud_init = """#!/bin/bash
apt update
apt install -y mariadb-server
systemctl enable mariadb.service
systemctl start mariadb.service
mysql --connect-timeout=120 -u root -e "UPDATE mysql.user SET plugin='mysql_native_password' WHERE user='root'; FLUSH privileges;"
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
                    fw.write(f"    StageResources={stage_resources}\n")
                if "[[node scheduler]]" in line:
                    fw.write(f"    CloudInit='''{cloud_init}'''\n")


def _cluster_names() -> List[str]:
    return sorted(list(set([x.rsplit(".", 1)[0] for x in os.listdir(CLUSTERS_DIR)])))


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
        args = ["cyclecloud", "start_cluster", cluster_name]
        if not skip_tests:
            args.append("--test")
        check_output(args, cwd=CWD)


def shutdown_clusters() -> None:
    cluster_names = _cluster_names()
    for cluster_name in cluster_names:
        print(f"Shutting down {cluster_name}")
        try:
            check_output(["cyclecloud", "show_cluster", cluster_name])
        except:
            continue
        args = ["cyclecloud", "terminate_cluster", cluster_name]
        check_output(args, cwd=CWD)


def delete_clusters() -> None:
    cluster_names = _cluster_names()
    for cluster_name in cluster_names:
        print(f"Deleting {cluster_name}")
        try:
            check_output(["cyclecloud", "show_cluster", cluster_name])
        except:
            continue
        args = ["cyclecloud", "delete_cluster", cluster_name]
        check_output(args, cwd=CWD)


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")

    import_clusters_parser = subparsers.add_parser("import")
    import_clusters_parser.add_argument("--stage-resources", action="store_true")
    import_clusters_parser.add_argument("--properties", "-p", type=str, required=True)

    start_clusters_parser = subparsers.add_parser("start")
    start_clusters_parser.add_argument("--skip-tests", action="store_true")

    subparsers.add_parser("shutdown")
    subparsers.add_parser("delete")

    args = parser.parse_args()
    if args.command == "import":
        with open(args.properties) as f:
            basic_properties = json.load(f)
        generate_clusters(basic_properties, args.stage_resources)
        import_clusters()
    elif args.command == "start":
        start_clusters(args.skip_tests)
    elif args.command == "shutdown":
        shutdown_clusters()
    elif args.command == "delete":
        delete_clusters()
    else:
        raise ValueError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
