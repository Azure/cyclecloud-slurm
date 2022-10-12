import argparse
import json
import logging
import os
import subprocess
import installlib as ilib
from typing import Dict

# TODO these need to be configurable.
slurmuser = "slurm"
mungeuser = "munge"
slurmgid = slurmuid = 11100
mungegid = mungeuid = 11101
slurmver = "22.05.3"
autoscale_dir = "/opt/azurehpc/slurm"  # node["slurm"]["autoscale_dir"]


def setup_users() -> None:
    # Set up users for Slurm and Munge
    ilib.group(slurmuser, gid=slurmgid)

    ilib.user(
        slurmuser,
        comment="User to run slurmd",
        shell="/bin/false",
        uid=slurmuid,
        gid=slurmgid,
    )

    ilib.group(mungeuser, gid=mungegid)

    ilib.user(
        mungeuser,
        comment="User to run munged",
        shell="/bin/false",
        uid=mungeuid,
        gid=mungegid,
    )


def run_installer(path: str) -> None:
    subprocess.check_call([path])


def fix_permissions() -> None:
    # Fix munge permissions and create key
    ilib.directory(
        "/var/lib/munge", owner=mungeuser, group=mungeuser, mode=711, recursive=True
    )

    ilib.directory(
        "/var/log/munge", owner="root", group="root", mode=700, recursive=True
    )

    ilib.directory(
        "/run/munge", owner=mungeuser, group=mungeuser, mode=755, recursive=True
    )

    ilib.directory("/sched/munge", owner=mungeuser, group=mungeuser, mode=700)

    # Set up slurm
    ilib.user(slurmuser, comment="User to run slurmd", shell="/bin/false")

    # add slurm to cyclecloud so it has access to jetpack / userdata
    if os.path.exists("/opt/cycle/jetpack"):
        ilib.group_members("cyclecloud", members=[slurmuser], append=True)

    ilib.directory("/var/spool/slurmd", owner=slurmuser, group=slurmuser)

    ilib.directory("/var/log/slurmd", owner=slurmuser, group=slurmuser)
    ilib.directory("/var/log/slurmctld", owner=slurmuser, group=slurmuser)


def munge_key() -> None:

    ilib.directory(
        "/etc/munge", owner=mungeuser, group=mungeuser, mode=700, recursive=True
    )

    if not os.path.exists("/sched/munge.key"):
        with open("/dev/urandom", "rb") as fr:
            buf = bytes()
            while len(buf) < 1024:
                buf = buf + fr.read(1024 - len(buf))
        ilib.file(
            "/sched/munge.key",
            content=buf,
            owner="munge",
            group="munge",
            mode=700,
        )
    ilib.copy_file(
        "/sched/munge.key",
        "/etc/munge/munge.key",
        owner="munge",
        group="munge",
        mode="0600",
    )


def accounting(bootstrap: Dict) -> None:
    ilib.link(
        "/sched/accounting.conf",
        "/etc/slurm/accounting.conf",
        owner=slurmuser,
        group=slurmuser,
    )

    if not bootstrap["slurm"]["accounting"]["enabled"]:
        logging.info("slurm.accounting.enabled is false, skipping this step.")
        ilib.file(
            "/sched/accounting.conf",
            owner=slurmuser,
            group=slurmuser,
            content="AccountingStorageType=accounting_storage/none",
        )
        return

    ilib.file(
        "/sched/accounting.conf",
        owner=slurmuser,
        group=slurmuser,
        content="""
AccountingStorageType=accounting_storage/slurmdbd
AccountingStorageHost="localhost"
""",
    )

    subprocess.check_call(["wget", "-O", "/sched/BaltimoreCyberTrustRoot.crt.pem"])
    ilib.chown(
        "/sched/BaltimoreCyberTrustRoot.crt.pem", owner=slurmuser, group=slurmuser
    )
    ilib.chown("/sched/BaltimoreCyberTrustRoot.crt.pem", mode="0600")
    ilib.link(
        "/sched/BaltimoreCyberTrustRoot.crt.pem",
        "/etc/slurm/BaltimoreCyberTrustRoot.crt.pem",
        owner=slurmuser,
        group=slurmuser,
    )

    # Configure slurmdbd.conf
    ilib.template(
        "/sched/slurmdbd.conf",
        owner=slurmuser,
        group=slurmuser,
        source="templates/slurmdbd.conf.template",
        mode=600,
        variables={
            "accountdb": bootstrap["slurm"]["accounting"]["url"],
            "dbuser": bootstrap["slurm"]["accounting"]["user"],
            "dbpass": bootstrap["slurm"]["accounting"]["password"],
            "slurmver": slurmver,
        },
    )
    # Link shared slurmdbd.conf to real config file location
    ilib.link(
        "/sched/slurmdbd.conf",
        "/etc/slurm/slurmdbd.conf",
        owner=f"{slurmuser}",
        group=f"{slurmuser}",
    )


def complete_install(node: Dict) -> None:
    ilib.template(
        "/sched/slurm.conf",
        owner=slurmuser,
        group=slurmuser,
        mode="0644",
        source="templates/slurm.conf.template",
        variables={
            "slurmctldhost": node["hostname"],
            "cluster_name": node["cluster_name"]
            # "slurmver": node["slurm"]["slurmver"],
            # "nodename": node["internal"]["node_name"],
            # "autoscale_dir": node["slurm"].get("autoscale_dir", "/opt/azurehpc/slurm"),
            # "resume_timeout": node["slurm"].get("resume_timeout", 1800),
            # "suspend_time": node["slurm"].get("suspend_time", 300),
            # "accountingenabled": node["slurm"].get("accounting", {}).get("enabled", False),
        },
    )

    ilib.link(
        "/sched/slurm.conf",
        "/etc/slurm/slurm.conf",
        owner=f"{slurmuser}",
        group=f"{slurmuser}",
    )

    ilib.template(
        "/sched/cgroup.conf",
        owner=slurmuser,
        group=slurmuser,
        source="templates/cgroup.conf.template",
        mode="0644",
    )

    ilib.link(
        "/sched/cgroup.conf",
        "/etc/slurm/cgroup.conf",
        owner=f"{slurmuser}",
        group=f"{slurmuser}",
    )

    if os.path.exists("/sched/gres.conf"):
        ilib.link(
            "/sched/gres.conf",
            "/etc/slurm/gres.conf",
            owner=f"{slurmuser}",
            group=f"{slurmuser}",
        )

    ilib.link(
        "/sched/azure.conf",
        "/etc/slurm/azure.conf",
        owner=f"{slurmuser}",
        group=f"{slurmuser}",
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
        "/etc/slurm/job_submit.lua",
        source="templates/job_submit.lua",
        owner="root",
        group="root",
        mode=644,
    )

    # TODO need to update this
    # host=$(hostname -s)
    #     grep -q "SlurmctldHost=$host" /sched/slurm.conf && exit 0
    #     grep -v SlurmctldHost /sched/slurm.conf > /sched/slurm.conf.tmp
    #     printf "\nSlurmctldHost=$host\n" >> /sched/slurm.conf.tmp
    #     mv /sched/slurm.conf.tmp /sched/slurm.conf

    accounting(node)

    # ilib.create_service("slurmctld")
    ilib.create_service("munged", user=mungeuser, exec_start="/sbin/munged")

    # v19 does this for us automatically BUT only for nodes that were susped
    # nodes that hit ResumeTimeout, however, remain in down~

    ilib.start_service("munge")


def _load_config(bootstrap_config: str) -> Dict:
    if bootstrap_config == "jetpack":
        config = json.loads(subprocess.check_output(["jetpack", "config", "--json"]))
        config["cluster_name"] = config["cyclecloud"]["cluster"]["name"]
        return config
    else:
        with open(bootstrap_config) as fr:
            return json.load(fr)


def main() -> None:
    # needed to set slurmctld only
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", default="rhel", choices=["rhel", "ubuntu"])
    parser.add_argument(
        "--mode", default="scheduler", choices=["scheduler", "execute", "login"]
    )
    parser.add_argument("--bootstrap-config", default="jetpack")

    args = parser.parse_args()

    config = _load_config(args.bootstrap_config)

    # create the users
    setup_users()

    # create the munge key and/or copy it to /etc/munge/
    munge_key()

    # runs either rhel.sh or ubuntu.sh to install the packages
    run_installer(os.path.abspath(f"{args.platform}.sh"))

    # various permissions fixes
    fix_permissions()

    complete_install(config)

    # scheduler specific - add return_to_idle script
    if args.mode == "scheduler":
        # TODO create a rotate log
        ilib.cron(
            "return_to_idle",
            minute="*/5",
            command=f"{autoscale_dir}/return_to_idle.sh 1>&2 >> {autoscale_dir}/logs/return_to_idle.log",
        )


if __name__ == "__main__":
    main()
