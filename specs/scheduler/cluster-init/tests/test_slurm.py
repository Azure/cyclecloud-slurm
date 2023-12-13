#!/opt/cycle/jetpack/system/embedded/bin/python -m pytest
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
import grp
import json
import os
import pwd
import random
import subprocess
from typing import List, Tuple
import time
import uuid

WHOAMI = subprocess.check_output(["whoami"]).decode().strip()
FAIL_FAST = int(os.getenv("FAIL_FAST", "1")) == 1


def test_simple_autoscale():
    if not is_autoscale():
        return

    script_path = "/tmp/hello_world.sh"
    job_name = str(uuid.uuid4())
    with open(script_path, "w") as fw:
        fw.write(
            """#!/bin/bash
#
#SBATCH --job-name={job_name}
#SBATCH --output=test_hello_world.{job_name}.txt
#
#SBATCH --ntasks=1
srun hostname""".format(
                job_name=job_name
            )
        )

    check_output("sudo", "-u", "cyclecloud", "sbatch", script_path)
    wait_for_job(job_name)
    wait_for_scale_down()


def test_manual_scale():
    if is_autoscale():
        return
    nodes = _get_future_nodes()
    check_output("azslurm", "resume", "--nodes", nodes[-1])
    wait_for_scale_up()
    check_output("azslurm", "suspend", "--nodes", nodes[-1])


def test_get_acct_info():
    """
    Low level cost reporting test, just to ensure our get_acct_info script is working.
    """
    offline_node = _get_powered_down_nodes()[0]
    check_output("scontrol", "update", "NodeName=%s" % offline_node, "State=power_up")
    time.sleep(15)
    response = json.loads(
        check_output("/opt/azurehpc/slurm/get_acct_info.sh", offline_node)
    )
    assert 1 == len(response)
    info = response[0]
    assert info.pop("name") == offline_node
    assert info.pop("location")
    assert info.pop("vm_size")
    assert info.pop("spot") is not None
    assert info.pop("nodearray")
    assert info.pop("cpus")
    assert info.pop("pcpu_count")
    assert info.pop("vcpu_count")
    assert info.pop("gpu_count") is not None
    assert info.pop("memgb")
    assert not info, "Unexpected keys: %s" % info.keys()


def test_multi_node_start() -> None:
    """
    Slurm has changed how it passes in the node_list to the suspend/resume scripts.
    This test ensures that we can handle both the old and new formats.
    """
    if not is_autoscale():
        return

    nodes = _get_powered_down_nodes()
    random.shuffle(nodes)
    nodes_to_start = []
    for line in nodes[0:10]:
        node_name = line.split()[0]
        nodes_to_start.append(node_name)

    nodes_before = json.loads(
        check_output("azslurm", "nodes", "--output-format", "json")
    )
    assert not nodes_before, "Expected 0 nodes already started!"
    hostlist = check_output("scontrol", "show", "hostlist", ",".join(nodes_to_start))
    check_output("scontrol", "update", "NodeName=" + hostlist, "State=power_up")
    time.sleep(10)
    nodes_after = json.loads(
        check_output("azslurm", "nodes", "--output-format", "json")
    )

    assert len(nodes_after) == 10
    assert set([n["name"] for n in nodes_after]) == set(nodes_to_start)

    check_output("scontrol", "update", "NodeName=" + hostlist, "State=power_down_force")
    time.sleep(10)
    nodes_final = json.loads(
        check_output("azslurm", "nodes", "--output-format", "json")
    )

    assert 0 == len(nodes_final)


def wait_for_ip(node: str) -> bool:

    for _ in range(60):
        records = json.loads(
            check_output("azslurm", "nodes", "--output-format", "json")
        )
        for record in records:
            if record.get("name") == node and record.get("private_ip"):
                return True
        time.sleep(5)
    return False


def test_resume_suspend_repeat() -> None:
    """
    Ensures that we can resume and suspend a node multiple times even if
    it is still in the process of shutting down / starting.
    """
    node = _get_powered_down_nodes()[0]
    check_output("azslurm", "resume", "--node-list", node, "--no-wait")
    assert wait_for_ip(node)
    check_output("azslurm", "suspend", "--node-list", node)

    check_output("azslurm", "resume", "--node-list", node, "--no-wait")
    assert wait_for_ip(node)

    check_output("azslurm", "suspend", "--node-list", node)


def test_create_dyn_node() -> None:
    cluster_name = check_output("jetpack", "config", "cyclecloud.cluster.name")
    cluster_name = cluster_name.replace("_", "-").replace(".", "-")
    node = f"{cluster_name}-dyn-node-test"
    if is_autoscale():
        check_output(
            "scontrol", "create", f"nodename={node}", "state=CLOUD", "Feature=dyn"
        )
        check_output("scontrol", "update", f"nodename={node}", "state=power_up")
    else:
        check_output(
            "scontrol", "create", f"nodename={node}", "state=FUTURE", "Feature=dyn"
        )
        check_output("azslurm", "resume", "--node-list", node, "--no-wait")
    wait_for_scale_up()
    wait_for_scale_down()


def test_azslurm_cost() -> None:
    """
    Ensures that the azslurm cost command works.
    """
    check_output("azslurm", "cost", "-o", "/tmp")
    assert os.path.exists("/tmp/jobs.csv")
    assert os.path.exists("/tmp/partition.csv")
    assert os.path.exists("/tmp/partition_hourly.csv")


def test_azslurm_scale() -> None:
    def stat(path: str) -> Tuple[int, int, int]:
        st = os.stat(path)
        return st.st_mode, st.st_uid, st.st_gid
    
    azure_conf = os.path.realpath("/etc/slurm/azure.conf")
    gres_conf = os.path.realpath("/etc/slurm/gres.conf")
    original = stat(azure_conf), stat(gres_conf)
    try:
        subprocess.call(["sudo", "chown", f"cyclecloud:cyclecloud", azure_conf])
        subprocess.call(["sudo", "chmod", "400", azure_conf])
        subprocess.call(["sudo", "chown", f"cyclecloud:cyclecloud", gres_conf])
        subprocess.call(["sudo", "chmod", "400", gres_conf])
        before_scale = stat(azure_conf), stat(gres_conf)
        assert before_scale != original
        subprocess.call(["sudo", "azslurm", "scale"])
        after_scale = stat(azure_conf), stat(gres_conf)
        
        # assert we have actually maintained perms and ownership
        # See issue #193 for more information
        assert after_scale == before_scale
        
    finally:
        # restore back to original permissions
        azconf_owner = pwd.getpwuid(original[0][1]).pw_name
        azconf_grp = grp.getgrgid(original[0][2]).gr_name
        gres_owner = pwd.getpwuid(original[1][1]).pw_name
        gres_grp = grp.getgrgid(original[1][2]).gr_name
        subprocess.call(["sudo", "chown", f"{azconf_owner}:{azconf_grp}", azure_conf])
        subprocess.call(["sudo", "chown", f"{gres_owner}:{gres_grp}", gres_conf])
        subprocess.call(["sudo", "chmod", oct(original[0][0])[-4:], azure_conf])
        subprocess.call(["sudo", "chmod", oct(original[1][0])[-4:], gres_conf])
    

def _get_powered_down_nodes() -> List[str]:
    ret = []
    lines = check_output(
        "scontrol", "show", "nodes", "--future"
    ).splitlines()
    for line in lines:
        line = line.strip()
        if line.startswith("NodeName"):
            name = line.split()[0].split("=")[1].strip()
            ret.append(name)
    return ret

def _get_future_nodes() -> List[str]:
    return check_output(
        "scontrol", "-N", "-h", "-t", "powered_down", "--format=%N"
    ).splitlines()


def teardown() -> None:
    subprocess.call(["scancel", "-u", WHOAMI])
    lines = check_output(
        "sinfo", "-N", "-h", "-Onodelist:100,StateComplete:100"
    ).splitlines()
    nodes = []
    for line in lines:
        name, states = line.strip().split()
        if "powered_down" in states or "powering_down" in states:
            continue
        nodes.append(name)

    if nodes:
        hostlist = check_output("scontrol", "show", "hostlist", ",".join(nodes))
        check_output(
            "scontrol", "update", "NodeName=" + hostlist, "State=power_down_force"
        )
        if not FAIL_FAST:
            time.sleep(75)

    cc_nodes = json.loads(check_output("azslurm", "nodes", "--output-format", "json"))
    if cc_nodes:
        check_output(
            "azslurm",
            "suspend",
            "--node-list",
            ",".join([n["name"] for n in cc_nodes]),
        )
        if not FAIL_FAST:
            time.sleep(10)


def check_output(*args, **kwargs):
    print("Running:", " ".join(args))
    return subprocess.check_output(list(args), **kwargs).decode().strip()


def is_autoscale() -> bool:
    with open("/etc/slurm/azure.conf") as fr:
        if "FUTURE" not in fr.read().upper():
            # an autoscale cluster, ignore
            return True
    return False


def wait_for_job(job_name):
    deadline = time.time() + 20 * 60
    while time.time() < deadline:
        time.sleep(1)
        stdout = check_output("squeue", "--format", "%j", "-h")
        if job_name not in stdout:
            return
    raise AssertionError("Timed out waiting for job %s to finish" % job_name)


def wait_for_scale_up():
    deadline = time.time() + 20 * 60
    while time.time() < deadline:
        time.sleep(1)
        stdout = check_output("sinfo", "--format", "%T", "-h")
        if "idle" in stdout:
            return
    raise AssertionError("Timed out waiting for scale up")


def wait_for_scale_down():
    deadline = time.time() + 20 * 60
    while time.time() < deadline:
        time.sleep(1)
        stdout = check_output("sinfo", "--format", "%T", "-h")
        if "~idle" != stdout:
            return
    raise AssertionError("Timed out waiting for scale down")