# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#

import argparse
from collections import OrderedDict
import json
import logging
from math import ceil, floor
import os
import subprocess
import sys
import time
from uuid import uuid4

from cyclecloud import autoscale_util
from cyclecloud.machine import MachineRequest
from slurmcc import SLURMDriver
from getpass import getpass
from cyclecloud.client import Client, Record
from clusterwrapper import ClusterWrapper
from cyclecloud.model.ClusterNodearrayStatusModule import ClusterNodearrayStatus
from cyclecloud.model.NodeCreationRequestModule import NodeCreationRequest
from cyclecloud.model.NodeCreationRequestSetModule import NodeCreationRequestSet
from cyclecloud.model.NodeCreationRequestSetDefinitionModule import NodeCreationRequestSetDefinition
import slurmcc


class Partition:
    
    def __init__(self, name, nodearray, machine_type, is_default, max_scaleset_size, vcpus_total, memory, quota_count):
        self.name = name
        self.nodearray = nodearray
        self.machine_type = machine_type
        self.is_default = is_default
        self.max_scaleset_size = max_scaleset_size
        self.vcpus_total = vcpus_total
        self.memory = memory
        self.quota_count = quota_count
        self.node_list = "{}-[{}-{}]".format(self.name, 1, quota_count)


def fetch_partitions(cluster_wrapper):
    '''
    Construct a mapping of SLURM partition name -> relevant nodearray information.
    There must be a one-to-one mapping of partition name to nodearray. If not, first one wins.
    '''
    partitions = OrderedDict()
    
    ClusterNodearrayStatus
    _, status_response = cluster_wrapper.get_cluster_status()
    
    for nodearray_status in status_response.nodearrays:
        nodearray_name = nodearray_status.name
        nodearray_record = nodearray_status.nodearray
        slurm_config = nodearray_record.get("Configuration", {}).get("slurm", {})
        is_autoscale = slurm_config.get("autoscale", False)
        partition_name = slurm_config.get("partition", nodearray_name)
        
        if not is_autoscale:
            logging.warn("Nodearray %s does not define slurm.autoscale, skipping.", nodearray_name)
            continue
        
        machine_types = nodearray_record.get("MachineType", "")
        if isinstance(machine_types, basestring):
            machine_types = machine_types.split(",")
        
        if len(machine_types) > 1:
            logging.warn("Ignoring multiple machine types for nodearray %s", nodearray_name)
            
        machine_type = machine_types[0]
        if not machine_type:
            logging.warn("MachineType not defined for nodearray %s. Skipping", nodearray_name)
            continue
        
        if partition_name in partitions:
            logging.warn("Same partition defined for two different nodearrays. Ignoring nodearray %s", nodearray_name)
            continue
        
        bucket = None
        for b in nodearray_status.buckets:
            if b.definition.machine_type == machine_type:
                bucket = b
                break
        
        if bucket is None:
            logging.error("Invalid status response - missing bucket with machinetype=='%s', %s", machine_type, json.dumps(status_response))
            return 1
        
        vm = bucket.virtual_machine
        if not vm:
            logging.error("Invalid status response - missing virtualMachine definition with machinetype=='%s', %s", machine_type, json.dumps(status_response))
            return 1
        
        max_scaleset_size = nodearray_record.get("Azure", {}).get("MaxScalesetSize", 40)
        partitions[partition_name] = Partition(partition_name, nodearray_name, machine_type, slurm_config.get("default_partition", False), max_scaleset_size,
                                               vm.vcpu_count, vm.memory, bucket.quota_count)
        
    return partitions


_cluster_wrapper = None


def _get_cluster_wrapper(username=None, password=None, web_server=None):
    global _cluster_wrapper
    if _cluster_wrapper is None:
        try:
            import jetpack.config as jetpack_config
        except ImportError:
            jetpack_config = {}
            
        cluster_name = jetpack_config.get("cyclecloud.cluster.name")
            
        config = {"verify_certificates": False,
                  "username": username or jetpack_config.get("cyclecloud.config.username"),
                  "password": password or jetpack_config.get("cyclecloud.config.password"),
                  "url": web_server or jetpack_config.get("cyclecloud.config.web_server"),
                  "cycleserver": {
                      "timeout": 60
                  }
        }
        
        client = Client(config)
        _cluster_wrapper = ClusterWrapper(client.clusters.get(cluster_name))
        
    return _cluster_wrapper


def _generate_slurm_conf(partitions, writer):
    partitions_list = partitions.values()
    default_partitions = [p for p in partitions_list if p.is_default]
    if len(default_partitions) == 0:
        logging.warn("slurm.default_partition was not set on any nodearray.")
        if len(partitions_list) == 1:
            logging.info("Only one nodearray was defined, setting as default.")
            partitions_list[0].is_default = True
    elif len(default_partitions) > 1:
        logging.warn("slurm.default_partition was set on more than one nodearray!")
    
    for partition in partitions_list:
        num_placement_groups = int(ceil(float(partition.quota_count) / partition.max_scaleset_size))
        default_yn = "YES" if partition.is_default else "NO"
        writer.write("PartitionName={} Nodes={} Default={} MaxTime=INFINITE State=UP\n".format(partition.name, partition.node_list, default_yn))
        for pg_index in range(num_placement_groups):
            start = pg_index * partition.max_scaleset_size + 1
            end = min(partition.quota_count, (pg_index + 1) * partition.max_scaleset_size)
            node_list = "{}-[{}-{}]".format(partition.name, start, end)
            writer.write("Nodename={} Feature=cloud STATE=CLOUD CPUs={} RealMemory={}\n".format(node_list, partition.vcpus_total, int(floor(partition.memory * 1024))))


def generate_slurm_conf():
    partitions = fetch_partitions(_get_cluster_wrapper())
    _generate_slurm_conf(partitions, sys.stdout)
            

def _generate_switches(partitions):
    switches = OrderedDict()
    
    for partition in partitions.itervalues():
        num_placement_groups = int(ceil(float(partition.quota_count) / partition.max_scaleset_size))
        placement_group_base = "{}-{}-{}-pg".format(partition.name, partition.nodearray, partition.machine_type)
        pg_list = "{}[0-{}]".format(placement_group_base, num_placement_groups - 1)
        for pg_index in range(num_placement_groups): 
            start = pg_index * partition.max_scaleset_size + 1
            end = min(partition.quota_count, (pg_index + 1) * partition.max_scaleset_size)
            node_list = "{}-[{}-{}]".format(partition.name, start, end)
            
            placement_group_id = placement_group_base + str(pg_index)
            parent_switch = "{}-{}".format(partition.name, partition.nodearray)
            switches[parent_switch] = switches.get(parent_switch, OrderedDict({"pg_list": pg_list,
                                                                   "children": OrderedDict()}))
            switches[parent_switch]["children"][placement_group_id] = node_list
            
    return switches
        

def _store_topology(switches, fw):
    for parent_switch, parent_switch_dict in switches.iteritems():
        
        fw.write("SwitchName={} Switches={}\n".format(parent_switch, parent_switch_dict["pg_list"]))
        for placement_group_id, node_list in parent_switch_dict["children"].iteritems():
            fw.write("SwitchName={} Nodes={}\n".format(placement_group_id, node_list))


def _generate_topology(partitions, writer):
    logging.info("Checking for topology updates")
    new_switches = _generate_switches(partitions)
    _store_topology(new_switches, writer)


def generate_topology():
    return _generate_topology(fetch_partitions(_get_cluster_wrapper()), sys.stdout)
        
        
def _shutdown(node_list, cluster_wrapper):
    for _ in range(30):
        try:
            cluster_wrapper.shutdown_nodes(names=node_list)
            return
        except Exception:
            logging.exception("Retrying...")
            time.sleep(60)
    return 1


def shutdown(node_list):
    return _shutdown(node_list, _get_cluster_wrapper())


def _resume(node_list, cluster_wrapper):
    _, start_response = cluster_wrapper.start_nodes(names=node_list)
    _wait_for_resume(cluster_wrapper, start_response.operation_id)


def _wait_for_resume(cluster_wrapper, operation_id):
    updated_node_addrs = set()
    
    while True:
        states = {}
        _, nodes_response = cluster_wrapper.get_nodes(operation_id=operation_id)
        for node in nodes_response.nodes:
            name = node.get("Name")
            states[node.get("State")] = states.get(node.get("State"), 0) + 1
            private_ip = node.get("Hostname")
            
            if private_ip and name not in updated_node_addrs:
                subprocess.check_call(["scontrol", "update", "NodeName=%s" % name, "NodeAddr=%s" % private_ip, "State=Power_Up"])
            
        num_with_ip = len([x for x in nodes_response.nodes if x.get("PrivateIp")])
        if num_with_ip == len(nodes_response.nodes):
            break
        
        logging.info("Number of nodes in each state: %s", str(states))
        time.sleep(5)
        
        
def resume(node_list):
    cluster_wrapper = _get_cluster_wrapper()
    return _resume(node_list, cluster_wrapper)


def _create_nodes(node_list, partitions, cluster_wrapper):
    if len(node_list) == 1 and node_list[0] == "all":
        node_list = []
        for partition in partitions.itervalues():
            node_list.extend(parse_nodelist(partition.node_list))
    
    print "creating node_list", node_list
    request = NodeCreationRequest()
    request.request_id = str(uuid4())
    nodearray_counts = {}
     
    for node in node_list:
        if "-" not in node:
            logging.error("Invalid node name - expected 'nodearrayname-index', i.e. execute-100. Got %s", node)
            return 1
         
        partition_name, index = node.rsplit("-", 2)
        if partition_name not in partitions:
            logging.error("Unknown partition %s. Maybe the same partition was used for multiple arrays?", partition_name)
            return 1
         
        try:
            index = int(index)
        except Exception:
            logging.exception("Could not convert index in node name to an integer - %s", node)
            return 1
         
        partition = partitions[partition_name]
        machine_type = partition.machine_type
 
        placement_group_index = (index - 1) / partition.max_scaleset_size
        placement_group = "%s-%s-pg%d" % (partition_name, machine_type, placement_group_index)
        key = (partition_name, placement_group)
        nodearray_counts[key] = nodearray_counts.get(key, 0) + 1
        
    request.sets = []
     
    for key, instance_count in nodearray_counts.iteritems():
        partition_name, pg = key
        partition = partitions[partition_name]
        
        request_set = NodeCreationRequestSet()
        
        request_set.nodearray = partition.nodearray
        
        request_set.placement_group_id = pg
        
        request_set.count = instance_count
        
        request_set.definition = NodeCreationRequestSetDefinition()
        request_set.definition.machine_type = partition.machine_type
        
        request_set.node_attributes = Record()
        request_set.node_attributes["Name"] = node_list[0]
        request_set.node_attributes["StartAutomatically"] = False
        request_set.node_attributes["State"] = "Off"
        request_set.node_attributes["TargetState"] = "Terminated"
        
        request.sets.append(request_set)
    
    cluster_wrapper.create_nodes(request)
        

def create_nodes(node_list):
    cluster_wrapper = _get_cluster_wrapper()
    partitions = fetch_partitions(cluster_wrapper)
    _create_nodes(node_list, partitions, cluster_wrapper)
        
        
def _init_logging(logfile):
    import logging.handlers
    
    log_level_name = os.getenv('AUTOSTART_LOG_LEVEL', "DEBUG")
    log_file_level_name = os.getenv('AUTOSTART_LOG_FILE_LEVEL', "DEBUG")
    log_file = os.getenv('AUTOSTART_LOG_FILE', logfile)
    
    if log_file_level_name.lower() not in ["debug", "info", "warn", "error", "critical"]:
        log_file_level = logging.DEBUG
    else:
        log_file_level = getattr(logging, log_level_name.upper())
    
    logging.getLogger("requests.packages.urllib3.connectionpool").setLevel(logging.WARN)
    logging.getLogger("urllib3.connectionpool").setLevel(logging.WARN)
    
    log_file = logging.handlers.RotatingFileHandler(log_file, maxBytes=1024 * 1024 * 5, backupCount=5)
    log_file.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    log_file.setLevel(log_file_level)
    
    logging.getLogger().addHandler(log_file)
    logging.getLogger().setLevel(logging.DEBUG)
    
    
def _submit_prolog(driver, slurm_job_id):
    if not slurm_job_id:
        logging.error("SLURM_JOB_ID is not defined!")
        return 1
    
    jobs = driver.get_jobs([slurm_job_id])
    
    if not jobs:
        logging.error("Unknown SLURM_JOB_ID %s", slurm_job_id)
        return 1
    
    assert len(jobs) == 1
    job = jobs[0]
    print json.dumps(job, indent=2, default=str)
    
    if job.get("reqswitch", 0) > 0:
        logging.debug("User specified --switches, skipping.")
        return 0
    else:
        network = slurmcc.parse_network(job.get("network", slurmcc.SLURM_NULL))
        if network.sn_single:
            logging.debug("User specified --network=SN_Single, skipping.")
            return 0
                     
        logging.info("Job does not declare SN_Single or --switches. Setting Switches=1.")
        driver.update_job(slurm_job_id, "Switches", "1")
        

def submit_prolog(slurm_job_id):
    _submit_prolog(SLURMDriver({}), slurm_job_id)
    
    
def _sync_nodes(cluster_wrapper, subprocess_module, partitions):
    nodes = cluster_wrapper.get_nodes()["nodes"]
    existing_nodes = subprocess_module.check_output(["sinfo", "-N", "-O", "NODELIST", "--noheader"]).splitlines()
    existing_nodes = set([x.strip() for x in existing_nodes])
    
    cyclecloud_nodes = {}
    for node in nodes:
        if node["Template"] not in partitions:
            continue
        
        cyclecloud_nodes[node["Name"]] = node
        
    manual_nodes = set(cyclecloud_nodes.keys()) - existing_nodes
    _resume(manual_nodes, cluster_wrapper)
    

def sync_nodes():
    cluster_wrapper = _get_cluster_wrapper()
    partitions = fetch_partitions(cluster_wrapper)
    return _sync_nodes(cluster_wrapper, subprocess, partitions)
    
    
def parse_nodelist(nodelist_expr):
    nodes = []
    for e in nodelist_expr.split(","):
        def expand(expr):
            if "[" not in expr:
                nodes.append(expr)
                return
            
            leftb = expr.rindex("[") 
            rightb = expr.rindex("]") 
            range_expr = expr[leftb + 1: rightb]
            start, stop = range_expr.split("-")
            
            while int(start) <= int(stop):
                node = expr[0: leftb] + start + expr[rightb + 1:]
                expand(node)
                formatexpr = "%0" + str(len(start)) + "d"
                start = formatexpr % (int(start) + 1)
                
        expand(e)
    return nodes

    
def main(argv=None):
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    
    slurm_conf_parser = subparsers.add_parser("slurm_conf")
    slurm_conf_parser.set_defaults(func=generate_slurm_conf, logfile="slurm_conf.log")
    
    topology_parser = subparsers.add_parser("topology")
    topology_parser.set_defaults(func=generate_topology, logfile="topology.log")
    
    create_nodes_parser = subparsers.add_parser("create_nodes")
    create_nodes_parser.set_defaults(func=create_nodes, logfile="create_nodes.log")
    create_nodes_parser.add_argument("--node-list", type=parse_nodelist, default=["all"])
    
    resume_parser = subparsers.add_parser("resume")
    resume_parser.set_defaults(func=resume, logfile="resume.log")
    resume_parser.add_argument("--node-list", type=parse_nodelist, required=True)
    
    resume_fail_parser = subparsers.add_parser("resume_fail")
    resume_fail_parser.set_defaults(func=shutdown, logfile="resume_fail.log")
    resume_fail_parser.add_argument("--node-list", type=parse_nodelist, required=True)
    
    suspend_parser = subparsers.add_parser("suspend")
    suspend_parser.set_defaults(func=shutdown, logfile="suspend.log")
    suspend_parser.add_argument("--node-list", type=parse_nodelist, required=True)
    
    submit_prolog_parser = subparsers.add_parser("submit_prolog")
    submit_prolog_parser.set_defaults(func=submit_prolog, logfile="submit_prolog.log")
    submit_prolog_parser.add_argument("--slurm-job-id", required=True)
    
    sync_nodes_parser = subparsers.add_parser("sync_nodes")
    sync_nodes_parser.set_defaults(func=sync_nodes, logfile="sync_nodes.log")
    
    for conn_parser in [sync_nodes_parser, create_nodes_parser, topology_parser, slurm_conf_parser]:
        conn_parser.add_argument("--web-server")
        conn_parser.add_argument("--username")
        
    args = parser.parse_args(argv)
    _init_logging(args.logfile)
    
    if hasattr(args, "username"):
        password = None
        if args.username:
            password = getpass()
            
        _get_cluster_wrapper(args.username, password, args.web_server)
    
    kwargs = {}
    for argname in dir(args):
        if argname[0].islower() and argname not in ["logfile", "func", "username", "password", "web_server"]:
            kwargs[argname] = getattr(args, argname)
    
    args.func(**kwargs)


if __name__ == "__main__":
    main()
