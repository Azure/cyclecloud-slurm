#!/opt/cycle/jetpack/system/embedded/bin/python -m pytest
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#

import json
import os
import shutil
import subprocess
import tempfile

import pytest

import clusterwrapper
import jetpack
from cyclecloud.model.ClusterStatusModule import ClusterStatus


@pytest.fixture
def cyclecloud_cli():
    cli = os.path.expanduser("~/bin/cyclecloud")
    if os.path.exists(cli):
        return cli
    base_url = jetpack.config.get("cyclecloud.config.web_server")
    username = jetpack.config.get("cyclecloud.config.username")
    password = jetpack.config.get("cyclecloud.config.password")
    zip_name = "cyclecloud-cli.zip"
    url = "%s/download/tools/%s" % (base_url, zip_name)
    tempdir = tempfile.mkdtemp()
    try:
        subprocess.check_call(["curl", "-k", "-u", "%s:%s" % (username, password), "-o", zip_name, url], cwd=tempdir)
        subprocess.check_call(["unzip", "cyclecloud-cli.zip"], cwd=tempdir)
        subprocess.check_call(["cyclecloud-cli-installer/install.sh"], cwd=tempdir)
        subprocess.check_call([cli, "initialize", "--url=%s" % base_url,
                                                  "--username=%s" % username,
                                                  "--password=%s" % password,
                                                  "--verify-ssl=false",
                                                  "--batch"], cwd=tempdir)
    finally:
        shutil.rmtree(tempdir, ignore_errors=True)
    assert os.path.exists(cli)
    return cli


def get_expected_sinfo():
    cluster_wrapper = clusterwrapper.from_jetpack()
    ret = {}
    _, nodes_list = cluster_wrapper.get_nodes()
    _, cluster_status = cluster_wrapper.get_cluster_status(nodes=True)
    
    mts = {}
    for nodearray in cluster_status.nodearrays:
        for bucket in nodearray.buckets:
            name = bucket.definition.machine_type
            mts[name] = bucket.virtual_machine
            
    for node in nodes_list.nodes:
        
        if not node.get("Configuration", {}).get("slurm", {}).get("autoscale", False):
            print "skipping node %s %s" % (node.get("Name"), node.get("Configuration"))
            continue
        
        name = node.get("Name")
        vm = mts[node.get("MachineType")]
        cores = vm.vcpu_count
        memory_total = vm.memory * 1024
        memory_reduced = min(memory_total - 1024, .95 * memory_total)
        ret[name] = {"cpus": cores, "memory": memory_reduced}
    return ret


def get_version():
    for spec in jetpack.config.get("cyclecloud.cluster_init_specs"):
        if spec.get("project") == "slurm":
            return spec.get("version")
    raise RuntimeError("Could not find version")


def test_scale(cyclecloud_cli):
    cluster_name = jetpack.config.get("cyclecloud.cluster.name")
    params_raw = subprocess.check_output([cyclecloud_cli, "export_parameters", cluster_name])
    params = json.loads(params_raw)
    # make sure we are actually changing the machine type
    assert params["HPCMachineType"] != "Standard_E16_v3"
    assert params["HTCMachineType"] != "Standard_F4"
    
    params_file = cluster_name + ".params.json"
    with open(params_file, "w") as fw:
        fw.write(params_raw)
        
    def get_sinfo():
        sinfo_raw = subprocess.check_output(["sinfo", "-N", "-O", "nodelist,cpus,memory", "-h"])
        sinfo = {}
        for nodeaddr, cpus_str, memory_str in [x.split() for x in sinfo_raw.splitlines()]:
            if not nodeaddr.startswith("hpc") and not nodeaddr.startswith("htc"):
                continue
            sinfo[nodeaddr] = {"cpus": int(cpus_str), "memory": int(memory_str)}
        return sinfo
    
    sinfo_before = get_sinfo()
    assert get_expected_sinfo() == sinfo_before
    
    version = get_version()
    # TODO would be nice to have this in userdata
    template_name = "slurm_template_%s" % version
    subprocess.check_call([cyclecloud_cli, "create_cluster", template_name, cluster_name, "-p", params_file,
                           "-P", "HTCMachineType=Standard_F4", "-P", "HPCMachineType=Standard_E16_v3", "--force"])
    
    # go htc since it is a bit smaller
    any_node = "htc-1"
    subprocess.check_call([cyclecloud_cli, "start_node", cluster_name, any_node])
    try:
        subprocess.check_call(["/opt/cycle/jetpack/system/bootstrap/slurm/cyclecloud_slurm.sh", "scale"])
        raise AssertionError("Should have exited non-zero since a node is starting")
    except subprocess.CalledProcessError as e:
        assert any_node in str(e)
    
    subprocess.check_call(["/opt/cycle/jetpack/system/bootstrap/slurm/suspend.sh", any_node])
    subprocess.check_call([cyclecloud_cli, "await_target_state", cluster_name, "-n", any_node], env={"CycleCloudDevel": "1"})
    subprocess.check_call(["/opt/cycle/jetpack/system/bootstrap/slurm/cyclecloud_slurm.sh", "scale"])
    with open(params_file, "w") as fw:
        fw.write(params_raw)
        
    def get_sinfo():
        sinfo_raw = subprocess.check_output(["sinfo", "-N", "-O", "nodelist,cpus,memory", "-h"])
        sinfo = {}
        for nodeaddr, cpus_str, memory_str in [x.split() for x in sinfo_raw.splitlines()]:
            if not nodeaddr.startswith("hpc") and not nodeaddr.startswith("htc"):
                continue
            sinfo[nodeaddr] = {"cpus": int(cpus_str), "memory": int(memory_str)}
        return sinfo
    
    sinfo_before = get_sinfo()
    assert get_expected_sinfo() == sinfo_before
    
    version = get_version()
    # TODO would be nice to have this in userdata
    template_name = "slurm_template_%s" % version
    subprocess.check_call([cyclecloud_cli, "create_cluster", template_name, cluster_name, "-p", params_file,
                           "-P", "HTCMachineType=Standard_F4", "-P", "HPCMachineType=Standard_E16_v3", "--force"])
    
    # go htc since it is a bit smaller
    any_node = "htc-1"
    subprocess.check_call([cyclecloud_cli, "start_node", cluster_name, any_node])
    try:
        subprocess.check_call(["/opt/cycle/jetpack/system/bootstrap/slurm/cyclecloud_slurm.sh", "scale"])
        raise AssertionError("Should have exited non-zero since a node is starting")
    except subprocess.CalledProcessError as e:
        assert any_node in str(e)
    
    subprocess.check_call(["/opt/cycle/jetpack/system/bootstrap/slurm/suspend.sh", any_node])
    subprocess.check_call([cyclecloud_cli, "await_target_state", cluster_name, "-n", any_node], env={"CycleCloudDevel": "1"})
    subprocess.check_call(["/opt/cycle/jetpack/system/bootstrap/slurm/cyclecloud_slurm.sh", "scale"])
    sinfo_after = get_sinfo()
    assert get_expected_sinfo() == sinfo_after
    
    # restore the cluster
    subprocess.check_call([cyclecloud_cli, "create_cluster", template_name, cluster_name, "-p", params_file, "--force"])
    subprocess.check_call(["/opt/cycle/jetpack/system/bootstrap/slurm/cyclecloud_slurm.sh", "scale"])
    assert get_expected_sinfo() == get_sinfo()