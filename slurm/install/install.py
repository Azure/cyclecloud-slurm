import argparse
from hashlib import md5
import json
import logging
import logging.config
import os
import subprocess
import installlib as ilib
from typing import Dict, Optional


class InstallSettings:
    def __init__(self, config: Dict, platform_family: str) -> None:
        if "slurm" not in config:
            config["slurm"] = {}

        if "accounting" not in config["slurm"]:
            config["slurm"]["acccounting"] = {}

        if "user" not in config["slurm"]:
            config["slurm"]["user"] = {}

        if "munge" not in config:
            config["munge"] = {}

        if "user" not in config["munge"]:
            config["munge"]["user"] = {}

        self.autoscale_dir = (
            config["slurm"].get("autoscale_dir") or "/opt/azurehpc/slurm"
        )
        self.cluster_name = config["cluster_name"]
        self.node_name = config["node_name"]
        self.hostname = config["hostname"]
        self.slurmver = config["slurm"]["version"]
        self.vm_size = config["azure"]["metadata"]["compute"]["vmSize"]

        self.slurm_user: str = config["slurm"]["user"].get("name") or "slurm"
        self.slurm_grp: str = config["slurm"]["user"].get("group") or "slurm"
        self.slurm_uid: str = config["slurm"]["user"].get("uid") or "11100"
        self.slurm_gid: str = config["slurm"]["user"].get("gid") or "11100"

        self.munge_user: str = config["munge"]["user"].get("name") or "munge"
        self.munge_grp: str = config["munge"]["user"].get("group") or "munge"
        self.munge_uid: str = config["munge"]["user"].get("uid") or "11101"
        self.munge_gid: str = config["munge"]["user"].get("gid") or "11101"

        self.acct_enabled: bool = config["slurm"]["accounting"].get("enabled", False)
        self.acct_user: Optional[str] = config["slurm"]["accounting"].get("user")
        self.acct_pass: Optional[str] = config["slurm"]["accounting"].get("password")
        self.acct_url: Optional[str] = config["slurm"]["accounting"].get("url")
        self.acct_cert_url = config["slurm"]["accounting"].get(
            "certificate_url",
            "https://www.digicert.com/CACerts/BaltimoreCyberTrustRoot.crt.pem",
        )

        self.use_nodename_as_hostname = config["slurm"].get(
            "use_nodename_as_hostname", False
        )
        self.ensure_waagent_monitor_hostname = config["slurm"].get(
            "ensure_waagent_monitor_hostname", True
        )

        self.platform_family = platform_family

        self.dynamic_config = config["slurm"].get("dynamic_config")
        if self.dynamic_config:
            self.dynamic_config = _inject_vm_size(self.dynamic_config, self.vm_size)
        self.dynamic_config

        self.max_node_count = int(config["slurm"].get("max_node_count", 10000))

        self.additonal_slurm_config = config["slurm"].get("additional", {}).get("config")


def _inject_vm_size(dynamic_config: str, vm_size: str) -> str:
    lc = dynamic_config.lower()
    if "feature=" not in lc:
        logging.warning("Dynamic config is specified but no 'Feature={some_flag}' is set under slurm.dynamic_config.")
        return dynamic_config
    else:
        ret = []
        for tok in dynamic_config.split():
            if tok.lower().startswith("feature="):
                ret.append(f"Feature={vm_size},{tok[len('Feature='):]}")
            else:
                ret.append(tok)
        return " ".join(ret)


def setup_users(s: InstallSettings) -> None:
    # Set up users for Slurm and Munge
    ilib.group(s.slurm_grp, gid=s.slurm_gid)

    ilib.user(
        s.slurm_user,
        comment="User to run slurmctld",
        shell="/bin/false",
        uid=s.slurm_uid,
        gid=s.slurm_gid,
    )

    ilib.group(s.munge_user, gid=s.munge_gid)

    ilib.user(
        s.munge_user,
        comment="User to run munged",
        shell="/bin/false",
        uid=s.munge_uid,
        gid=s.munge_gid,
    )


def run_installer(s: InstallSettings, path: str, mode: str) -> None:
    subprocess.check_call([path, mode, s.slurmver])


def fix_permissions(s: InstallSettings) -> None:
    # Fix munge permissions and create key
    ilib.directory(
        "/var/lib/munge",
        owner=s.munge_user,
        group=s.munge_grp,
        mode=711,
        recursive=True,
    )

    ilib.directory(
        "/var/log/munge", owner="root", group="root", mode=700, recursive=True
    )

    ilib.directory(
        "/run/munge", owner=s.munge_user, group=s.munge_grp, mode=755, recursive=True
    )

    ilib.directory("/sched/munge", owner=s.munge_user, group=s.munge_grp, mode=700)

    # Set up slurm
    ilib.user(s.slurm_user, comment="User to run slurmctld", shell="/bin/false")

    # add slurm to cyclecloud so it has access to jetpack / userdata
    if os.path.exists("/opt/cycle/jetpack"):
        ilib.group_members("cyclecloud", members=[s.slurm_user], append=True)

    ilib.directory("/var/spool/slurmd", owner=s.slurm_user, group=s.slurm_grp)

    ilib.directory("/var/log/slurmd", owner=s.slurm_user, group=s.slurm_grp)
    ilib.directory("/var/log/slurmctld", owner=s.slurm_user, group=s.slurm_grp)


def munge_key(s: InstallSettings) -> None:

    ilib.directory(
        "/etc/munge", owner=s.munge_user, group=s.munge_grp, mode=700, recursive=True
    )

    if not os.path.exists("/sched/munge.key"):
        with open("/dev/urandom", "rb") as fr:
            buf = bytes()
            while len(buf) < 1024:
                buf = buf + fr.read(1024 - len(buf))
        ilib.file(
            "/sched/munge.key",
            content=buf,
            owner=s.munge_user,
            group=s.munge_grp,
            mode=700,
        )

    ilib.copy_file(
        "/sched/munge.key",
        "/etc/munge/munge.key",
        owner=s.munge_user,
        group=s.munge_grp,
        mode="0600",
    )


def accounting(s: InstallSettings) -> None:

    if not s.acct_enabled:
        logging.info("slurm.accounting.enabled is false, skipping this step.")
        ilib.file(
            "/sched/accounting.conf",
            owner=s.slurm_user,
            group=s.slurm_grp,
            content="AccountingStorageType=accounting_storage/none",
        )
        return

    ilib.file(
        "/sched/accounting.conf",
        owner=s.slurm_user,
        group=s.slurm_grp,
        content="""
AccountingStorageType=accounting_storage/slurmdbd
AccountingStorageHost="localhost"
AccountingStorageTRES=gres/gpu
""",
    )
    subprocess.check_call(
        [
            "wget",
            "-O",
            "/sched/BaltimoreCyberTrustRoot.crt.pem",
            s.acct_cert_url,
        ]
    )
    ilib.chown(
        "/sched/BaltimoreCyberTrustRoot.crt.pem", owner=s.slurm_user, group=s.slurm_grp
    )
    ilib.chmod("/sched/BaltimoreCyberTrustRoot.crt.pem", mode="0600")
    ilib.link(
        "/sched/BaltimoreCyberTrustRoot.crt.pem",
        "/etc/slurm/BaltimoreCyberTrustRoot.crt.pem",
        owner=s.slurm_user,
        group=s.slurm_grp,
    )

    # Configure slurmdbd.conf
    ilib.template(
        "/sched/slurmdbd.conf",
        owner=s.slurm_user,
        group=s.slurm_grp,
        source="templates/slurmdbd.conf.template",
        mode=600,
        variables={
            "accountdb": s.acct_url or "localhost",
            "dbuser": s.acct_user or "root",
            "storagepass": f"StoragePass={s.acct_pass}" if s.acct_pass else "#StoragePass=",
            "slurmver": s.slurmver,
        },
    )
    # Link shared slurmdbd.conf to real config file location
    ilib.link(
        "/sched/slurmdbd.conf",
        "/etc/slurm/slurmdbd.conf",
        owner=s.slurm_user,
        group=s.slurm_grp,
    )

    ilib.enable_service("slurmdbd")


def complete_install(s: InstallSettings) -> None:
    ilib.template(
        "/sched/slurm.conf",
        owner=s.slurm_user,
        group=s.slurm_grp,
        mode="0644",
        source="templates/slurm.conf.template",
        variables={
            "slurmctldhost": s.hostname,
            "cluster_name": s.cluster_name,
            "max_node_count": s.max_node_count,
        },
    )

    if s.additonal_slurm_config:
        hash = md5(s.additonal_slurm_config.encode()).hexdigest()
        with open("/sched/slurm.conf", "r") as fr:
            already_written = hash in fr.read()
        if not already_written:        
            with open("/sched/slurm.conf", "a") as fa:
                fa.write("\n")
                fa.write(f"# Additional config from CycleCloud - md5 = {hash}\n")
                fa.write(s.additonal_slurm_config)

    ilib.link(
        "/sched/slurm.conf",
        "/etc/slurm/slurm.conf",
        owner=s.slurm_user,
        group=s.slurm_grp,
    )

    ilib.template(
        "/sched/cgroup.conf",
        owner=s.slurm_user,
        group=s.slurm_grp,
        source="templates/cgroup.conf.template",
        mode="0644",
    )

    ilib.link(
        "/sched/cgroup.conf",
        "/etc/slurm/cgroup.conf",
        owner=s.slurm_user,
        group=s.slurm_grp,
    )

    if os.path.exists("/sched/gres.conf"):
        ilib.link(
            "/sched/gres.conf",
            "/etc/slurm/gres.conf",
            owner=s.slurm_user,
            group=s.slurm_grp,
        )

    ilib.link(
        "/sched/azure.conf",
        "/etc/slurm/azure.conf",
        owner=s.slurm_user,
        group=s.slurm_grp,
    )

    if not os.path.exists("/sched/azure.conf"):
        ilib.file(
            "/sched/azure.conf",
            owner=s.slurm_user,
            group=s.slurm_grp,
            mode="0644",
            content="",
        )

    ilib.link(
        "/sched/keep_alive.conf",
        "/etc/slurm/keep_alive.conf",
        owner=s.slurm_user,
        group=s.slurm_grp,
    )

    if not os.path.exists("/sched/keep_alive.conf"):
        ilib.file(
            "/sched/keep_alive.conf",
            owner=s.slurm_user,
            group=s.slurm_grp,
            mode="0644",
            content="# Do not edit this file. It is managed by azslurm",
        )

    # Link the accounting.conf regardless
    ilib.link(
        "/sched/accounting.conf",
        "/etc/slurm/accounting.conf",
        owner=s.slurm_user,
        group=s.slurm_grp,
    )

    ilib.template(
        "/etc/security/limits.d/slurm-limits.conf",
        source="templates/slurm-limits.conf",
        owner="root",
        group="root",
        mode=644,
    )

    ilib.directory(
        "/etc/systemd/system/slurmctld.service.d", owner="root", group="root", mode=755
    )

    ilib.template(
        "/etc/systemd/system/slurmctld.service.d/override.conf",
        source="templates/slurmctld.override",
        owner="root",
        group="root",
        mode=644,
    )

    ilib.template(
        "/etc/slurm/job_submit.lua.azurehpc.example",
        source="templates/job_submit.lua",
        owner="root",
        group="root",
        mode=644,
    )

    ilib.create_service("munged", user=s.munge_user, exec_start="/sbin/munged")


def setup_slurmd(s: InstallSettings) -> None:
    slurmd_config = f"SLURMD_OPTIONS=-b -N {s.node_name}"
    if s.dynamic_config:
        slurmd_config = f"SLURMD_OPTIONS={s.dynamic_config} -N {s.node_name}"
    ilib.file(
        "/etc/sysconfig/slurmd" if s.platform_family == "rhel" else "/etc/default/slurmd",
        content=slurmd_config,
        owner=s.slurm_user,
        group=s.slurm_grp,
        mode="0700",
    )
    ilib.enable_service("slurmd")


def set_hostname(s: InstallSettings) -> None:
    if not s.use_nodename_as_hostname:
        return
    ilib.set_hostname(s.node_name, s.platform_family, s.ensure_waagent_monitor_hostname)


def _load_config(bootstrap_config: str) -> Dict:
    if bootstrap_config == "jetpack":
        config = json.loads(subprocess.check_output(["jetpack", "config", "--json"]))
    else:
        with open(bootstrap_config) as fr:
            config = json.load(fr)

    if "cluster_name" not in config:
        config["cluster_name"] = config["cyclecloud"]["cluster"]["name"]
        config["node_name"] = config["cyclecloud"]["node"]["name"]

    return config


def main() -> None:
    # needed to set slurmctld only
    if os.path.exists("install_logging.conf"):
        logging.config.fileConfig("install_logging.conf")
    
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--platform", default="rhel", choices=["rhel", "ubuntu", "suse", "debian"]
    )
    parser.add_argument(
        "--mode", default="scheduler", choices=["scheduler", "execute", "login"]
    )
    parser.add_argument("--bootstrap-config", default="jetpack")

    args = parser.parse_args()

    if args.platform == "debian":
        args.platform = "ubuntu"

    config = _load_config(args.bootstrap_config)
    settings = InstallSettings(config, args.platform)

    # create the users
    setup_users(settings)

    # create the munge key and/or copy it to /etc/munge/
    munge_key(settings)

    # runs either rhel.sh or ubuntu.sh to install the packages
    run_installer(settings, os.path.abspath(f"{args.platform}.sh"), args.mode)
    
    # various permissions fixes
    fix_permissions(settings)

    complete_install(settings)

    # scheduler specific - add return_to_idle script
    if args.mode == "scheduler":
        accounting(settings)
        # TODO create a rotate log
        ilib.cron(
            "return_to_idle",
            minute="*/5",
            command=f"{settings.autoscale_dir}/return_to_idle.sh 1>&2 >> {settings.autoscale_dir}/logs/return_to_idle.log",
        )

    if args.mode == "execute":
        set_hostname(settings)
        setup_slurmd(settings)


if __name__ == "__main__":
    main()
