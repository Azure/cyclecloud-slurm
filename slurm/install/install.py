import argparse
import json
import logging
import logging.config
import os
import re
import subprocess
import sys
import installlib as ilib
from typing import Dict, Optional

# Legacy: used for connecting to Azure MariaDB, which is deprecated.
LOCAL_AZURE_CA_PEM = "AzureCA.pem"


class InstallSettings:
    def __init__(self, config: Dict, platform_family: str, mode: str) -> None:
        self.config = config

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
        self.cyclecloud_cluster_name = config["cluster_name"]
        # We use a "safe" form of the CycleCloud ClusterName
        # First we lowercase the cluster name, then replace anything
        # that is not letters, digits and '-' with a '-'
        # eg My Cluster == my-cluster.
        # This is needed because cluster names are used to create hostnames
        # hostname conventions do not allow underscores and spaces
        # https://en.wikipedia.org/wiki/Hostname#Restrictions_on_valid_host_names.
        # Since this PR: https://github.com/Azure/cyclecloud-slurm/pull/241 we now have
        # to use cluster name to create a database name if one is not provided. But database naming
        # conventions conflict witn hostname naming conventions and it cannot contain "-" hyphens.
        # For now we use a second sanitized cluster name that derives from the escaped cluster name
        # but converts all hyphens to underscores.
        self.slurm_cluster_name = _escape(self.cyclecloud_cluster_name)
        self.slurm_db_cluster_name = re.sub(r'-', '_', self.slurm_cluster_name)

        self.node_name = config["node_name"]
        self.hostname = config["hostname"]
        self.ipv4 = config["ipaddress"]
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
        self.acct_cert_url: Optional[str] = config["slurm"]["accounting"].get("certificate_url")
        self.acct_storageloc :Optional[str] = config["slurm"]["accounting"].get("storageloc")
        self.disable_pmc = config["slurm"].get("disable_pmc") or False

        self.use_nodename_as_hostname = config["slurm"].get(
            "use_nodename_as_hostname", False
        )
        self.node_name_prefix = config["slurm"].get("node_prefix")
        if self.node_name_prefix:
            self.node_name_prefix = re.sub(
                "[^a-zA-Z0-9-]", "-", self.node_name_prefix
            ).lower()

        self.ensure_waagent_monitor_hostname = config["slurm"].get(
            "ensure_waagent_monitor_hostname", True
        )

        self.platform_family = platform_family
        self.mode = mode

        self.dynamic_config = config["slurm"].get("dynamic_config")
        if self.dynamic_config:
            self.dynamic_config = _inject_vm_size(self.dynamic_config, self.vm_size)
        self.dynamic_config

        self.max_node_count = int(config["slurm"].get("max_node_count", 10000))

        self.additonal_slurm_config = (
            config["slurm"].get("additional", {}).get("config")
        )

        self.secondary_scheduler_name = config["slurm"].get("secondary_scheduler_name")
        self.is_primary_scheduler = config["slurm"].get("is_primary_scheduler", self.mode == "scheduler")
        self.config_dir = f"/sched/{self.slurm_cluster_name}"
        # Leave the ability to disable this.
        self.ubuntu22_waagent_fix = config["slurm"].get("ubuntu22_waagent_fix", True)


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

def setup_config_dir(s: InstallSettings) -> None:

    # set up config dir inside {s.config_dir} mount.
    if s.is_primary_scheduler:
        ilib.directory(s.config_dir, owner="root", group="root", mode=755)

def _escape(s: str) -> str:
    return re.sub("[^a-zA-Z0-9-]", "-", s).lower()


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
    subprocess.check_call([path, mode, s.slurmver, str(s.disable_pmc)])


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

    ilib.directory(f"{s.config_dir}/munge", owner=s.munge_user, group=s.munge_grp, mode=700)

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

    if s.mode == "scheduler" and not os.path.exists(f"{s.config_dir}/munge.key"):
        # TODO only should do this on the primary
        # we should skip this for secondary HA nodes
        with open("/dev/urandom", "rb") as fr:
            buf = bytes()
            while len(buf) < 1024:
                buf = buf + fr.read(1024 - len(buf))
        ilib.file(
            f"{s.config_dir}/munge.key",
            content=buf,
            owner=s.munge_user,
            group=s.munge_grp,
            mode=700,
        )

    ilib.copy_file(
        f"{s.config_dir}/munge.key",
        "/etc/munge/munge.key",
        owner=s.munge_user,
        group=s.munge_grp,
        mode="0600",
    )


def accounting(s: InstallSettings) -> None:
    if s.mode != "scheduler":
        return
    if s.is_primary_scheduler:
        _accounting_primary(s)
    _accounting_all(s)


def _accounting_primary(s: InstallSettings) -> None:
    """
    Only the primary scheduler should be creating files under
    {s.config_dir} for accounting.
    """

    if s.secondary_scheduler_name:
        secondary_scheduler = ilib.await_node_hostname(
            s.config, s.secondary_scheduler_name
        )
    if not s.acct_enabled:
        logging.info("slurm.accounting.enabled is false, skipping this step.")
        ilib.file(
            f"{s.config_dir}/accounting.conf",
            owner=s.slurm_user,
            group=s.slurm_grp,
            content="AccountingStorageType=accounting_storage/none",
        )
        return

    ilib.file(
        f"{s.config_dir}/accounting.conf",
        owner=s.slurm_user,
        group=s.slurm_grp,
        content=f"""
AccountingStorageType=accounting_storage/slurmdbd
AccountingStorageHost={s.hostname}
AccountingStorageTRES=gres/gpu
""",
    )

    # Previously this was required when connecting to any Azure MariaDB instance.
    # Which is why we shipped with LOCAL_AZURE_CA_PEM.
    if s.acct_cert_url and s.acct_cert_url != LOCAL_AZURE_CA_PEM:
        logging.info(f"Downloading {s.acct_cert_url} to {s.config_dir}/AzureCA.pem")
        subprocess.check_call(
            [
                "wget",
                "-O",
                f"{s.config_dir}/AzureCA.pem",
                s.acct_cert_url,
            ]
        )
        ilib.chown(
            f"{s.config_dir}/AzureCA.pem", owner=s.slurm_user, group=s.slurm_grp
        )
        ilib.chmod(f"{s.config_dir}/AzureCA.pem", mode="0600")
    elif s.acct_cert_url and s.acct_cert_url == LOCAL_AZURE_CA_PEM:
        ilib.copy_file(
            LOCAL_AZURE_CA_PEM,
            f"{s.config_dir}/AzureCA.pem",
            owner=s.slurm_user,
            group=s.slurm_grp,
            mode="0600",
        )

    # Configure slurmdbd.conf
    ilib.template(
        f"{s.config_dir}/slurmdbd.conf",
        owner=s.slurm_user,
        group=s.slurm_grp,
        source="templates/slurmdbd.conf.template",
        mode=600,
        variables={
            "accountdb": s.acct_url or "localhost",
            "dbuser": s.acct_user or "root",
            "dbdhost": s.hostname,
            "storagepass": f"StoragePass={s.acct_pass}" if s.acct_pass else "#StoragePass=",
            "storage_parameters": "StorageParameters=SSL_CA=/etc/slurm/AzureCA.pem"
                                  if s.acct_cert_url
                                  else "#StorageParameters=",
            "slurmver": s.slurmver,
            "storageloc": s.acct_storageloc or f"{s.slurm_db_cluster_name}_acct_db",
        },
    )

    if s.secondary_scheduler_name:
        ilib.append_file(
            f"{s.config_dir}/accounting.conf",
            content=f"AccountingStorageBackupHost={secondary_scheduler.hostname}\n",
            comment_prefix="\n# Additional HA Storage Backup host -"
        )
        ilib.append_file(
            f"{s.config_dir}/slurmdbd.conf",
            content=f"DbdBackupHost={secondary_scheduler.hostname}\n",
            comment_prefix="\n# Additional HA dbd host -"
        )


def _accounting_all(s: InstallSettings) -> None:
    """
    Perform linking and enabling of slurmdbd
    """
    # This used to be required for all installations, but it is
    # now optional, so only create the link if required.
    original_azure_ca_pem = f"{s.config_dir}/AzureCA.pem"
    if os.path.exists(original_azure_ca_pem):
        ilib.link(
            f"{s.config_dir}/AzureCA.pem",
            "/etc/slurm/AzureCA.pem",
            owner=s.slurm_user,
            group=s.slurm_grp,
        )

    # Link shared slurmdbd.conf to real config file location
    ilib.link(
        f"{s.config_dir}/slurmdbd.conf",
        "/etc/slurm/slurmdbd.conf",
        owner=s.slurm_user,
        group=s.slurm_grp,
    )

    ilib.enable_service("slurmdbd")


def complete_install(s: InstallSettings) -> None:
    if s.mode == "scheduler":
        if s.is_primary_scheduler:
            _complete_install_primary(s)
        _complete_install_all(s)
    else:
        _complete_install_all(s)


def _complete_install_primary(s: InstallSettings) -> None:
    """
    Only the primary scheduler should be creating files under {s.config_dir}.
    """
    assert s.is_primary_scheduler
    secondary_scheduler = None
    if s.secondary_scheduler_name:
        secondary_scheduler = ilib.await_node_hostname(
            s.config, s.secondary_scheduler_name
        )
    state_save_location = "/var/spool/slurmctld"
    if secondary_scheduler:
        state_save_location = f"{s.config_dir}/spool/slurmctld"

    if not os.path.exists(state_save_location):
        ilib.directory(state_save_location, owner=s.slurm_user, group=s.slurm_grp)

    ilib.template(
        f"{s.config_dir}/slurm.conf",
        owner=s.slurm_user,
        group=s.slurm_grp,
        mode="0644",
        source="templates/slurm.conf.template",
        variables={
            "slurmctldhost": f"{s.hostname}({s.ipv4})",
            "cluster_name": s.slurm_cluster_name,
            "max_node_count": s.max_node_count,
            "state_save_location": state_save_location,
        },
    )

    if secondary_scheduler:
        ilib.append_file(
            f"{s.config_dir}/slurm.conf",
            content=f"SlurmCtldHost={secondary_scheduler.hostname}({secondary_scheduler.private_ipv4})\n",
            comment_prefix="\n# Additional HA scheduler host -",
        )

    if s.additonal_slurm_config:
        ilib.append_file(
            f"{s.config_dir}/slurm.conf",
            content=s.additonal_slurm_config,
            comment_prefix="\n# Additional config from CycleCloud -",
        )

    ilib.template(
        f"{s.config_dir}/cgroup.conf",
        owner=s.slurm_user,
        group=s.slurm_grp,
        source=f"templates/cgroup.conf.template",
        mode="0644",
    )

    if not os.path.exists(f"{s.config_dir}/azure.conf"):
        ilib.file(
            f"{s.config_dir}/azure.conf",
            owner=s.slurm_user,
            group=s.slurm_grp,
            mode="0644",
            content="",
        )

    if not os.path.exists(f"{s.config_dir}/keep_alive.conf"):
        ilib.file(
            f"{s.config_dir}/keep_alive.conf",
            owner=s.slurm_user,
            group=s.slurm_grp,
            mode="0644",
            content="# Do not edit this file. It is managed by azslurm",
        )

    if not os.path.exists(f"{s.config_dir}/gres.conf"):
        ilib.file(
            f"{s.config_dir}/gres.conf",
            owner=s.slurm_user,
            group=s.slurm_grp,
            mode="0644",
            content="",
        )

def _complete_install_all(s: InstallSettings) -> None:
    ilib.link(
        f"{s.config_dir}/gres.conf",
        "/etc/slurm/gres.conf",
        owner=s.slurm_user,
        group=s.slurm_grp,
    )

    ilib.link(
        f"{s.config_dir}/slurm.conf",
        "/etc/slurm/slurm.conf",
        owner=s.slurm_user,
        group=s.slurm_grp,
    )

    ilib.link(
        f"{s.config_dir}/cgroup.conf",
        "/etc/slurm/cgroup.conf",
        owner=s.slurm_user,
        group=s.slurm_grp,
    )

    ilib.link(
        f"{s.config_dir}/azure.conf",
        "/etc/slurm/azure.conf",
        owner=s.slurm_user,
        group=s.slurm_grp,
    )

    ilib.link(
        f"{s.config_dir}/keep_alive.conf",
        "/etc/slurm/keep_alive.conf",
        owner=s.slurm_user,
        group=s.slurm_grp,
    )

    # Link the accounting.conf regardless
    ilib.link(
        f"{s.config_dir}/accounting.conf",
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
        if "-b" not in slurmd_config.split():
            slurmd_config = slurmd_config + " -b"

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

    if s.is_primary_scheduler:
        return

    new_hostname = s.node_name.lower()
    if s.mode != "execute" and not new_hostname.startswith(s.node_name_prefix):
        new_hostname = f"{s.node_name_prefix}{new_hostname}"

    ilib.set_hostname(
        new_hostname, s.platform_family, s.ensure_waagent_monitor_hostname
    )
    if _is_at_least_ubuntu22() and s.ubuntu22_waagent_fix:
        logging.warning("Restarting systemd-networkd to fix waagent/hostname issue on Ubuntu 22.04." +
                        " To disable this, set slurm.ubuntu22_waagent_fix=false under this" +
                        " node/nodearray's [[[configuration]]] section")
        subprocess.check_call(["systemctl", "restart", "systemd-networkd"])


def _is_at_least_ubuntu22() -> bool:
    if not os.path.exists("/etc/os-release"):
        return False
    lsb_rel = {}
    with open("/etc/os-release") as fr:
        for line in fr:
            line = line.strip()
            if not line:
                continue
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            lsb_rel[key.strip().upper()] = val.strip('"').strip().lower()

    if lsb_rel.get("ID") == "ubuntu" and lsb_rel.get("VERSION_ID", "") >= "22.04":
        return True
    
    return False


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
    settings = InstallSettings(config, args.platform, args.mode)

    #create config dir
    setup_config_dir(settings)

    # create the users
    setup_users(settings)

    # create the munge key and/or copy it to /etc/munge/
    munge_key(settings)

    # runs either rhel.sh or ubuntu.sh to install the packages
    run_installer(settings, os.path.abspath(f"{args.platform}.sh"), args.mode)

    # various permissions fixes
    fix_permissions(settings)

    complete_install(settings)

    if settings.mode == "scheduler":
        accounting(settings)
        # TODO create a rotate log
        ilib.cron(
            "return_to_idle",
            minute="*/5",
            command=f"{settings.autoscale_dir}/return_to_idle.sh 1>&2 >> {settings.autoscale_dir}/logs/return_to_idle.log",
        )

    set_hostname(settings)

    if settings.mode == "execute":
        setup_slurmd(settings)


if __name__ == "__main__":
    try:
        main()
    except:
        print(
            "An error occured during installation. See log file /var/log/azure-slurm-install.log for details.",
            file=sys.stderr,
        )
        logging.exception("An error occured during installation.")
        sys.exit(1)