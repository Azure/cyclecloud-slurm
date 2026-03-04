import argparse
import json
import logging
import logging.config
import os
import re
import subprocess
import sys
import yaml
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
            config["slurm"]["accounting"] = {}

        if "user" not in config["slurm"]:
            config["slurm"]["user"] = {}

        if "munge" not in config:
            config["munge"] = {}

        if "user" not in config["munge"]:
            config["munge"]["user"] = {}

        if "slurmrestd" not in config["slurm"]:
            config["slurm"]["slurmrestd"] = {}

        if "user" not in config["slurm"]["slurmrestd"]:
            config["slurm"]["slurmrestd"]["user"] = {}

        if "monitoring" not in config["cyclecloud"]:
            config["cyclecloud"]["monitoring"] = {}

        self.autoscale_dir = (
            config["slurm"].get("autoscale_dir") or "/opt/azurehpc/slurm"
        )

        self.jwt_key_path = (
            config["slurm"].get("jwt_key_path") or "/var/spool/slurm/statesave/jwt_hs256.key"
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
        self.version = config["azure"]["metadata"]["compute"]["version"]
        # Extract major version for comparison (e.g., "8.10.2024101801" -> 8)
        self.major_version = int(self.version.split('.')[0]) if self.version else 0

        self.slurm_user: str = config["slurm"]["user"].get("name") or "slurm"
        self.slurm_grp: str = config["slurm"]["user"].get("group") or "slurm"
        self.slurm_uid: str = config["slurm"]["user"].get("uid") or "11100"
        self.slurm_gid: str = config["slurm"]["user"].get("gid") or "11100"

        self.munge_user: str = config["munge"]["user"].get("name") or "munge"
        self.munge_grp: str = config["munge"]["user"].get("group") or "munge"
        self.munge_uid: str = config["munge"]["user"].get("uid") or "11101"
        self.munge_gid: str = config["munge"]["user"].get("gid") or "11101"

        self.slurmrestd_user: str = config["slurm"]["slurmrestd"]["user"].get("name") or "slurmrestd"
        self.slurmrestd_grp: str = config["slurm"]["slurmrestd"]["user"].get("group") or "slurmrestd"
        self.slurmrestd_uid: str = config["slurm"]["slurmrestd"]["user"].get("uid") or "11102"
        self.slurmrestd_gid: str = config["slurm"]["slurmrestd"]["user"].get("gid") or "11102"

        self.monitoring_enabled: bool = config["cyclecloud"]["monitoring"].get("enabled", False)

        self.acct_enabled: bool = config["slurm"]["accounting"].get("enabled", False)
        self.acct_user: Optional[str] = config["slurm"]["accounting"].get("user")
        self.acct_pass: Optional[str] = config["slurm"]["accounting"].get("password")
        self.acct_url: Optional[str] = config["slurm"]["accounting"].get("url")
        self.acct_cert_url: Optional[str] = config["slurm"]["accounting"].get("certificate_url")
        self.acct_storageloc :Optional[str] = config["slurm"]["accounting"].get("storageloc")

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

        self.dynamic_config = config["slurm"].get("dynamic_config", None)
        self.dynamic_feature = config["slurm"].get("dynamic_feature", None)

        #TODO: Dynamic_config will be deprecated. Remove for 4.x
        if self.dynamic_config:
            self.dynamic_config = _inject_vm_size(self.dynamic_config, self.vm_size)
        elif self.dynamic_feature:
            self.dynamic_feature = f"{self.dynamic_feature},{self.vm_size}"

        self.max_node_count = int(config["slurm"].get("max_node_count", 10000))

        self.additonal_slurm_config = (
            config["slurm"].get("additional", {}).get("config")
        )
        self.launch_parameters = config["slurm"].get("launch_parameters", "")

        self.secondary_scheduler_name = config["slurm"].get("secondary_scheduler_name")
        self.is_primary_scheduler = config["slurm"].get("is_primary_scheduler", self.mode == "scheduler")
        self.config_dir = f"/sched/{self.slurm_cluster_name}"
        # Leave the ability to disable this.
        self.ubuntu22_waagent_fix = config["slurm"].get("ubuntu22_waagent_fix", True)
        self.enable_healthchecks = config["slurm"].get("enable_healthchecks", True)

        self.healthagent = config["cyclecloud"].get("healthagent", {})
        if self.healthagent.get("disabled", False) == True:
            self.enable_healthchecks = False

        if self.platform_family == "suse":
            logging.warning("Monitoring and healthchecks are not supported on SUSE platforms, disabling configuration.")
            self.enable_healthchecks = False
            self.monitoring_enabled = False


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
    # Set up users for Slurm, Munge and Slurmrestd
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
    
    if s.platform_family == "suse":
        logging.warning("slurmrestd user configuration is not supported on SUSE platforms, skipping this step.")
        return
    
    ilib.group(s.slurmrestd_grp, gid=s.slurmrestd_gid)
    
    ilib.user(
        s.slurmrestd_user,
        comment="User to run slurmrestd",
        shell="/usr/sbin/nologin",
        uid=s.slurmrestd_uid,
        gid=s.slurmrestd_gid,
    )


def run_installer(s: InstallSettings, path: str, mode: str) -> None:
    INSTALL_FILE = "/etc/azslurm-bins.installed"
    attr = {}
    if os.path.exists(INSTALL_FILE):
        try:
            with open(INSTALL_FILE, 'r') as fp:
                contents = fp.read()
                for line in contents.splitlines():
                    key, value = line.split("=")
                    attr[key] = value
            if attr.get("SLURM_VERSION") != s.slurmver:
                logging.warning(f"Slurm version installed: {attr['SLURM_VERSION']}, slurm version requested: {s.slurmver}")
            elif attr["MODE"] != "install-only" and attr["MODE"] != mode:
                logging.warning(f"Role configured {attr['MODE']} role requested: {mode}")
            elif int(attr["EXIT_CODE"]) != 0:
                logging.warning(f"Previous package install did not succeed, re-running it")
            else:
                # Everything is already installed
                logging.info(f"Required slurm version: {attr['SLURM_VERSION']} already installed.")
                return
        except Exception as e:
            logging.exception(e)
        os.remove(INSTALL_FILE)


    logging.info(f"Running script {path}, slurm version: {s.slurmver}, mode={mode}")
    out = subprocess.run([path, mode, s.slurmver], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    logging.debug(out.stdout)
    if out.returncode != 0:
        logging.error(out.stderr)
        raise Exception(f"{path} returned error")
    else:
        with open(INSTALL_FILE, 'w') as fp:
            fp.write(f"SLURM_VERSION={s.slurmver}\n")
            fp.write(f"MODE={mode}\n")
            fp.write(f"EXIT_CODE={out.returncode}\n")



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
            "auth_alt_type": "AuthAltTypes=auth/jwt" if s.monitoring_enabled else "",
            "auth_alt_parameters": f"AuthAltParameters=jwt_key={s.jwt_key_path}" 
                                if s.monitoring_enabled else ""
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

    state_save_location = f"{s.config_dir}/spool/slurmctld"

    if not os.path.exists(state_save_location):
        ilib.directory(state_save_location, owner=s.slurm_user, group=s.slurm_grp)
    
    if not os.path.exists(f"{s.config_dir}/prolog.d"):
        ilib.directory(f"{s.config_dir}/prolog.d", owner=s.slurm_user, group=s.slurm_grp)

    if not os.path.exists(f"{s.config_dir}/epilog.d"):
        ilib.directory(f"{s.config_dir}/epilog.d", owner=s.slurm_user, group=s.slurm_grp)


    # Setting health_interval to 0 disables healthchecks
    health_interval = 0
    health_program = '""'
    if s.enable_healthchecks:
        # Run background checks every 1 minute
        health_interval = 60
        health_program = f"{s.config_dir}/health.sh"
        epilog_program = f"{s.config_dir}/epilog.d/10-health_epilog.sh"
        ilib.copy_file("/etc/healthagent/health.sh.example", health_program, owner="root", group="root", mode=755)
        ilib.copy_file("/etc/healthagent/epilog.sh.example", epilog_program, owner="root", group="root", mode=755)

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
            "prolog": "/etc/slurm/prolog.d/*",
            "epilog": "/etc/slurm/epilog.d/*",
            "launch_parameters" : s.launch_parameters,
            "health_interval": health_interval,
            "health_program": health_program,
            "auth_alt_type": "AuthAltTypes=auth/jwt" if s.monitoring_enabled else "",
            "auth_alt_parameters": f"AuthAltParameters=jwt_key={s.jwt_key_path}" 
                                if s.monitoring_enabled else ""
        },
    )

    ## SLurm Prolog/Epilog guide states:
    #  When more than one prolog script is configured, they are executed in reverse alphabetical order (z-a -> Z-A -> 9-0).
    #  Therefore we should make explicit numbering choice on imex prolog/epilog. By marking them 90- - We want them to execute first
    #  but user can override that choice by putting a script that follows the ordering defined above.

    ilib.copy_file(
        "imex_prolog.sh",
        f"{s.config_dir}/prolog.d/90-imex_prolog.sh",
        owner="root",
        group="root",
        mode="0755",
        )
    
    ilib.copy_file(
        "imex_epilog.sh",
        f"{s.config_dir}/epilog.d/90-imex_epilog.sh",
        owner="root",
        group="root",
        mode="0755",
        )

    if secondary_scheduler:
        ilib.append_file(
            f"{s.config_dir}/slurm.conf",
            content=f"SlurmCtldHost={secondary_scheduler.hostname}({secondary_scheduler.private_ipv4})\n",
            comment_prefix="\n# Additional HA scheduler host -",
        )

    if not os.path.exists(f"{s.config_dir}/site_specific.conf"):
        ilib.file(
            f"{s.config_dir}/site_specific.conf",
            owner=s.slurm_user,
            group=s.slurm_grp,
            mode="0644",
            content="# site specific slurm configuration. This is preserved during upgrades",
        )

    if s.additonal_slurm_config:
        ilib.append_file(
            f"{s.config_dir}/slurm.conf",
            content=s.additonal_slurm_config,
            comment_prefix="\n# Additional config from CycleCloud cluster template-",
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
            content="# Do not edit this file. It is managed by azslurmd",
        )


    if not os.path.exists(f"{s.config_dir}/gres.conf"):
        ilib.file(
            f"{s.config_dir}/gres.conf",
            owner=s.slurm_user,
            group=s.slurm_grp,
            mode="0644",
            content="",
        )

    if not os.path.exists(f"{s.config_dir}/plugstack.conf"):
        ilib.file(
            f"{s.config_dir}/plugstack.conf",
            owner=s.slurm_user,
            group=s.slurm_grp,
            mode="0644",
            content=f"include /etc/slurm/plugstack.conf.d/*"
        )
    if not os.path.exists(f"{s.config_dir}/topology.conf"):
        ilib.file(
            f"{s.config_dir}/topology.conf",
            owner=s.slurm_user,
            group=s.slurm_grp,
            mode="0644",
            content=""
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
        f"{s.config_dir}/site_specific.conf",
        "/etc/slurm/site_specific.conf",
        owner=s.slurm_user,
        group=s.slurm_grp,
    )

    ilib.link(
        f"{s.config_dir}/keep_alive.conf",
        "/etc/slurm/keep_alive.conf",
        owner=s.slurm_user,
        group=s.slurm_grp,
    )

    ilib.link(
        f"{s.config_dir}/plugstack.conf",
        "/etc/slurm/plugstack.conf",
        owner=s.slurm_user,
        group=s.slurm_grp,
    )

    ilib.link(
        f"{s.config_dir}/topology.conf",
        "/etc/slurm/topology.conf",
        owner=s.slurm_user,
        group=s.slurm_grp,
    )

    ilib.link(
        f"{s.config_dir}/prolog.d",
        "/etc/slurm/prolog.d",
        owner=s.slurm_user,
        group=s.slurm_grp,
    )

    ilib.link(
        f"{s.config_dir}/epilog.d",
        "/etc/slurm/epilog.d",
        owner=s.slurm_user,
        group=s.slurm_grp,
    )

    if not os.path.exists("/etc/slurm/plugstack.conf.d"):
        os.makedirs("/etc/slurm/plugstack.conf.d")
        ilib.directory("/etc/slurm/plugstack.conf.d",
                       owner=s.slurm_user,
                       group=s.slurm_grp,
        )

    _configure_enroot_pyxis(s)

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

    ilib.directory(
        "/etc/systemd/system/munge.service.d", owner="root", group="root", mode=755
    )

    ilib.template(
        "/etc/systemd/system/munge.service.d/override.conf",
        source="templates/munge.override",
        owner="root",
        group="root",
        mode=644,
    )

    ilib.enable_service("munge")

    ilib.template(
        "/etc/slurm/job_submit.lua.azurehpc.example",
        source="templates/job_submit.lua",
        owner="root",
        group="root",
        mode=644,
    )
    ilib.copy_file(
        source="capture_logs.sh",
        dest="/opt/cycle/capture_logs.sh",
        owner="root",
        group="root",
        mode=755
    )

def get_gres_count(hostname):
    count = 0
    try:
        with open("/etc/slurm/gres.conf", 'r') as file:
            for line in file:
                nodename_match = re.search(r'Nodename=([^\s]+)', line, re.IGNORECASE)
                count_match = re.search(r'count=(\d+)', line, re.IGNORECASE)
                if nodename_match and count_match:
                    nodename = nodename_match.group(1)
                    # This command is local to the node and does not send an RPC to the controller.
                    if hostname in subprocess.run(['scontrol', 'show', 'hostnames', nodename], stdout=subprocess.PIPE, universal_newlines=True).stdout:
                        count = int(count_match.group(1))

    except Exception as e:
        logging.error(f"An error occurred: {e}")

    return count


def setup_slurmd(s: InstallSettings) -> None:
    slurmd_config = f"SLURMD_OPTIONS=-b -N {s.node_name}"
    if s.dynamic_feature or s.dynamic_config:
        if s.dynamic_feature:
            override_conf = ""
            # Dynamic GPU nodes have to have their gres manually defined by the user before they can be started.
            # Check if gres is defined for this node and then add that to configuration options.
            gpu_count = get_gres_count(s.node_name)
            if gpu_count > 0:
                gres_str = f"gres=gpu:{gpu_count}"
                override_conf += f" {gres_str}"
            override_conf += f" Feature={s.dynamic_feature}"
            dynamic_config = f"-Z --conf \"{override_conf}\""
        else:
            # If user has supplied us dynamic config in the template.
            #TODO: dynamic_config will be removed for 4.x
            dynamic_config = f"{s.dynamic_config}"
        logging.debug("Dynamic config: %s" % dynamic_config)
        slurmd_config = f"SLURMD_OPTIONS={dynamic_config} -N {s.node_name}"
        if "-b" not in slurmd_config.split():
            slurmd_config = slurmd_config + " -b"

    ilib.file(
        "/etc/sysconfig/slurmd" if s.platform_family == "rhel" else "/etc/default/slurmd",
        content=slurmd_config,
        owner=s.slurm_user,
        group=s.slurm_grp,
        mode="0700",
    )

    ilib.directory(
        "/etc/systemd/system/slurmd.service.d", owner="root", group="root", mode=755
    )

    ilib.template(
        "/etc/systemd/system/slurmd.service.d/override.conf",
        source="templates/slurmd.override",
        owner="root",
        group="root",
        mode=644,
    )
    ilib.enable_service("slurmd")

def setup_slurmrestd(s: InstallSettings) -> None:
    if s.mode != "scheduler":
        logging.info("Running on non-scheduler node skipping this step.")
        return
    
    if s.platform_family == "suse":
        logging.warning("slurmrestd configuration is not supported on SUSE platforms, skipping this step.")
        return
        
    # Add slurmrestd to docker group
    try:
        ilib.group("docker", gid=None)
        ilib.group_members("docker", members=[s.slurmrestd_user], append=True)
    except Exception as e:
        logging.warning(f"Could not add slurmrestd to docker group: {e}")
    openapi_flag = "" if s.acct_enabled else " -s openapi/slurmctld"
    slurmrestd_config = f"SLURMRESTD_OPTIONS=\"-u slurmrestd -g slurmrestd{openapi_flag}\"\nSLURMRESTD_LISTEN=:6820,unix:/var/spool/slurmrestd/slurmrestd.socket"
    ilib.file(
        "/etc/sysconfig/slurmrestd" if s.platform_family == "rhel" else "/etc/default/slurmrestd",
        content=slurmrestd_config,
        owner=s.slurmrestd_user,
        group=s.slurmrestd_grp,
        mode="0644",
    )
    
    ilib.directory(
        "/var/spool/slurmrestd", owner=s.slurmrestd_user, group=s.slurmrestd_grp, mode=755
    )
    ilib.file(
            "/var/spool/slurmrestd/slurmrestd.socket",
            owner=s.slurm_user,
            group=s.slurm_grp,
            mode="0755",
            content="",
    )
    ilib.directory(
        "/etc/systemd/system/slurmrestd.service.d", owner="root", group="root", mode=755
    )

    ilib.template(
        "/etc/systemd/system/slurmrestd.service.d/override.conf",
        source="templates/slurmrestd.override",
        owner="root",
        group="root",
        mode=644,
    )

    if s.monitoring_enabled:
        _configure_jwt_authentication(s)
        _add_slurm_exporter_scraper(s, "/opt/prometheus/prometheus.yml", "templates/slurm_exporter.yml")

    ilib.enable_service("slurmrestd")

def _configure_jwt_authentication(s: InstallSettings) -> None:
    """
    Configure JWT authentication for Slurm.
    """
    jwt_dir = os.path.dirname(s.jwt_key_path)

    # Create the directory and key file if they don't exist
    ilib.directory(jwt_dir, owner=s.slurm_user, group=s.slurm_grp, mode=755)
    ilib.directory(os.path.dirname(jwt_dir), owner=s.slurm_user, group=s.slurm_grp, mode=755)

    if not os.path.exists(s.jwt_key_path):
        # Generate a 32-byte random key
        with open("/dev/random", "rb") as fr:
            key = fr.read(32)
        ilib.file(s.jwt_key_path, content=key, owner=s.slurm_user, group=s.slurm_grp, mode=600)
    else:
        ilib.chown(s.jwt_key_path, owner=s.slurm_user, group=s.slurm_grp)
        ilib.chmod(s.jwt_key_path, mode=600)

    ilib.chown(jwt_dir, owner=s.slurm_user, group=s.slurm_grp)
    ilib.chmod(jwt_dir, mode=755)
    ilib.chmod(os.path.dirname(jwt_dir), mode=755)

def _add_slurm_exporter_scraper(s: InstallSettings, prom_config: str, exporter_yaml: str) -> None:
    """
    Add slurm_exporter scrape config to Prometheus.
    """
    if not s.is_primary_scheduler:
        logging.info("Not primary scheduler, skipping slurm_exporter configuration.")
        return

    if not os.path.isfile(prom_config):
        logging.warning("Prometheus configuration file not found, skipping slurm_exporter configuration.")
        return
    
    with open(prom_config, "r") as f:
        prom_content = f.read()
        if "slurm_exporter" in prom_content:
            print("Slurm Exporter is already configured in Prometheus")
            return
    # Merge YAML files
    with open(prom_config, "r") as f:
        prom_yaml = yaml.safe_load(f) or {}
    with open(exporter_yaml, "r") as f:
        exporter_yaml_content = yaml.safe_load(f) or {}

    # Simple merge: add/replace scrape_configs
    def merge_scrape_configs(base, overlay):
        base_scrapes = base.get("scrape_configs", [])
        overlay_scrapes = overlay.get("scrape_configs", [])
        base["scrape_configs"] = base_scrapes + overlay_scrapes
        return base

    merged_yaml = merge_scrape_configs(prom_yaml, exporter_yaml_content)

    # Replace instance_name placeholder
    merged_str = yaml.safe_dump(merged_yaml, default_flow_style=False)
    merged_str = merged_str.replace("instance_name", s.hostname)

    # Write back to prom_config
    ilib.file(
        prom_config,
        content=merged_str,
        owner="root",
        group="root",
        mode="0644"
    )

def _configure_enroot_pyxis(s: InstallSettings) -> None:
    if s.platform_family == "suse" or (s.platform_family == "rhel" and s.major_version != 8):
        logging.warning("Enroot is only supported on Ubuntu and RHEL/AlmaLinux 8. Skipping enroot configuration.")
        return

    def _get_enroot_scratch_base_dir() -> str:
        if os.path.exists("/nvme") and ilib.is_mount_point("/nvme"):
            logging.info("Using /nvme for enroot scratch directory (nvme mount detected)")
            return "/nvme"
        elif os.path.exists("/mnt") and ilib.is_mount_point("/mnt"):
            logging.info("Using /mnt for enroot scratch directory (mnt mount detected)")
            return "/mnt"
        else:
            logging.info("Using /tmp for enroot scratch directory (no suitable mounts found)")
            return "/tmp"

    # Determine scratch directory based on available mounts
    scratch_base_dir = _get_enroot_scratch_base_dir()
    enroot_scratch_dir = f"{scratch_base_dir}/enroot"
    
    # Create the enroot directory
    ilib.directory(enroot_scratch_dir, owner="root", group="root", mode=755)

    # Create enroot subdirectories
    subdirs = ["enroot-cache", "enroot-data", "enroot-temp", "enroot-runtime", "enroot-run"]
    for subdir in subdirs:
        full_path = f"{enroot_scratch_dir}/{subdir}"
        ilib.directory(full_path, owner="root", group="root", mode=777)
    
    ilib.template(
        f"/etc/enroot/enroot.conf",
        owner=s.slurm_user,
        group=s.slurm_grp,
        mode="0644",
        source="templates/enroot.conf.template",
        variables={
            "ENROOT_SCRATCH_DIR": enroot_scratch_dir
        },
    )
    # Install extra hooks for PMIx on compute nodes
    if s.mode == "execute":
        # Ensure hooks directory exists
        ilib.directory("/etc/enroot/hooks.d", owner="root", group="root", mode=755)
        
        # Copy hook files
        hook_files = ["50-slurm-pmi.sh", "50-slurm-pytorch.sh"]
        for hook_file in hook_files:
            source_path = f"/usr/share/enroot/hooks.d/{hook_file}"
            dest_path = f"/etc/enroot/hooks.d/{hook_file}"
            
            if os.path.exists(source_path):
                ilib.copy_file(
                    source_path,
                    dest_path,
                    owner="root",
                    group="root",
                    mode="0755"
                )
            else:
                logging.warning(f"Hook file {source_path} not found, skipping")
    
    # Create the pyxis.conf file with the required plugin configuration
    pyxis_config = f'required /opt/pyxis/spank_pyxis.so runtime_path={enroot_scratch_dir}/enroot-runtime'
    ilib.file(
        "/etc/slurm/plugstack.conf.d/pyxis.conf",
        content=pyxis_config,
        owner=s.slurm_user,
        group=s.slurm_grp,
        mode="0644"
    )

def _update_prom_config(s: InstallSettings, prom_config: str, host_name: str) -> None:
    """
    Update hostnames in Prometheus config targets to be new_hostname
    """
    if not s.monitoring_enabled or not os.path.isfile(prom_config):
        logging.info("Monitoring is not enabled or prometheus config is not found, skipping Prometheus configuration update.")
        return
    
    with open(prom_config, "r") as f:
        prom_content = f.read()

    # Replace hostnames in targets arrays, keeping the port
    # Matches: "hostname:port" and replaces hostname with new host_name
    prom_content = re.sub(r'"([^":]+):(\d+)"', f'"{host_name}:\\2"', prom_content)

    # Also replace the global instance label
    prom_content = re.sub(r'instance:\s*([^\s\n]+)', f'instance: {host_name}', prom_content)

    # Write back to prom_config
    ilib.file(
        prom_config,
        content=prom_content,
        owner="root",
        group="root",
        mode="0644"
    )
    
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
    
    #Update prom config with new hostname
    _update_prom_config(s, "/opt/prometheus/prometheus.yml", new_hostname)
    
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

def detect_platform() -> str:
    """
    Detects Os Platform
    """
    id_val = ""
    id_like_val = ""
    platform_map = {
        "ubuntu": "ubuntu",
        "debian": "ubuntu",
        "almalinux": "rhel",
        "centos": "rhel",
        "fedora": "rhel",
        "rhel": "rhel",
        "suse": "suse",
        "sles": "suse",
        "sle_hpc": "suse"
    }
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("ID="):
                    id_val = line.strip().split("=", 1)[1].strip('"').lower()
                elif line.startswith("ID_LIKE="):
                    id_like_val = line.strip().split("=", 1)[1].strip('"').lower()
    except Exception:
        return "unknown"

    for key, val in platform_map.items():
        if key in id_val or key in id_like_val:
            return val
    return "unknown"

def main() -> None:
    # needed to set slurmctld only
    if os.path.exists("install_logging.conf"):
        logging.config.fileConfig("install_logging.conf")

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--platform", default=detect_platform(), choices=["rhel", "ubuntu", "suse", "debian"], required=False
    )
    parser.add_argument(
        "--mode", default="scheduler", choices=["scheduler", "execute", "login"]
    )
    parser.add_argument("--bootstrap-config", default="jetpack")

    args = parser.parse_args()

    config = _load_config(args.bootstrap_config)
    settings = InstallSettings(config, args.platform, args.mode)

    #create config dir
    setup_config_dir(settings)

    # create the users
    setup_users(settings)

    set_hostname(settings)
    # create the munge key and/or copy it to /etc/munge/
    munge_key(settings)

    # runs either rhel.sh or ubuntu.sh to install the packages
    run_installer(settings, os.path.abspath(f"{args.platform}.sh"), args.mode)

    # various permissions fixes
    fix_permissions(settings)

    complete_install(settings)

    if settings.mode == "scheduler":
        accounting(settings)
        setup_slurmrestd(settings)
        # TODO create a rotate log
        ilib.cron(
            "return_to_idle",
            minute="*/5",
            command=f"{settings.autoscale_dir}/return_to_idle.sh 1>&2 >> {settings.autoscale_dir}/logs/return_to_idle.log",
        )
        if settings.is_primary_scheduler == False:
            # This is the HA node.
            logging.info(f"Secondary Scheduler {settings.secondary_scheduler_name} starting wait on primary to finish converging.")
            ilib.await_node_converge(settings.config, "scheduler", timeout=600)

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