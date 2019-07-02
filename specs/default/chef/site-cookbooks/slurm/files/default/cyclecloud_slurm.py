# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#

import argparse
from collections import OrderedDict
from getpass import getpass
import json
import logging
from math import ceil, floor
import os
import sys
import time
from uuid import uuid4

from clusterwrapper import ClusterWrapper
from cyclecloud.client import Client, Record
from cyclecloud.model.NodeCreationRequestModule import NodeCreationRequest
from cyclecloud.model.NodeCreationRequestSetDefinitionModule import NodeCreationRequestSetDefinition
from cyclecloud.model.NodeCreationRequestSetModule import NodeCreationRequestSet
from slurmcc import custom_chaos_mode
import random
import traceback


class CyclecloudSlurmError(RuntimeError):
    pass


class Partition:
    
    def __init__(self, name, nodearray, machine_type, is_default, is_hpc, max_scaleset_size, vcpu_count, memory, max_vm_count):
        self.name = name
        self.nodearray = nodearray
        self.machine_type = machine_type
        self.is_default = is_default
        self.is_hpc = is_hpc
        self.max_scaleset_size = max_scaleset_size
        self.vcpu_count = vcpu_count
        self.memory = memory
        self.max_vm_count = max_vm_count
        self.node_list = None


def fetch_partitions(cluster_wrapper, subprocess_module):
    '''
    Construct a mapping of SLURM partition name -> relevant nodearray information.
    There must be a one-to-one mapping of partition name to nodearray. If not, first one wins.
    '''
    partitions = OrderedDict()
    
    _, status_response = _retry_rest(cluster_wrapper.get_cluster_status, True)
    # TODO status_response's nodes doesn't include off nodes...
    _, nodes_response = _retry_rest(cluster_wrapper.get_nodes)
            
    for nodearray_status in status_response.nodearrays:
        nodearray_name = nodearray_status.name
        if not nodearray_name:
            logging.error("Name is not defined for nodearray. Skipping")
            continue
        
        nodearray_record = nodearray_status.nodearray
        if not nodearray_record:
            logging.error("Nodearray record is not defined for nodearray status. Skipping")
            continue
            
        slurm_config = nodearray_record.get("Configuration", {}).get("slurm", {})
        is_autoscale = slurm_config.get("autoscale")
        partition_name = slurm_config.get("partition", nodearray_name)
        
        if is_autoscale is None:
            logging.warn("Nodearray %s does not define slurm.autoscale, skipping.", nodearray_name)
            continue
        
        if is_autoscale is False:
            logging.debug("Nodearray %s explicitly defined slurm.autoscale=false, skipping.", nodearray_name)
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
        
        if bucket.max_count is None:
            logging.error("No max_count defined for  machinetype=='%s'. Skipping", machine_type)
            continue
        
        if bucket.max_count <= 0:
            logging.info("Bucket has a max_count <= 0, defined for machinetype=='%s'. Skipping", machine_type)
            continue
        
        max_scaleset_size = Record(nodearray_record.get("Azure", {})).get("MaxScalesetSize", 40)
        
        is_hpc = str(slurm_config.get("hpc", True)).lower() == "true"
        
        if not is_hpc:
            max_scaleset_size = 2**31
        
        partitions[partition_name] = Partition(partition_name,
                                               nodearray_name,
                                               machine_type,
                                               slurm_config.get("default_partition", False),
                                               is_hpc,
                                               max_scaleset_size,
                                               vm.vcpu_count,
                                               vm.memory,
                                               bucket.max_count)
        
        existing_nodes = []
        
        for node in nodes_response.nodes:
            if node.get("Template") == nodearray_name:
                existing_nodes.append(node.get("Name"))
        
        if existing_nodes:
            sorted_nodes = sorted(existing_nodes, key=_get_sort_key_func(partitions[partition_name].is_hpc))
            partitions[partition_name].node_list = _to_hostlist(subprocess_module, ",".join(sorted_nodes))
    
    partitions_list = partitions.values()
    default_partitions = [p for p in partitions_list if p.is_default]
    
    if len(default_partitions) == 0:
        logging.warn("slurm.default_partition was not set on any nodearray.")
        
        # one nodearray, just assume it is the default
        if len(partitions_list) == 1:
            logging.info("Only one nodearray was defined, setting as default.")
            partitions_list[0].is_default = True
            
    elif len(default_partitions) > 1:
        # no partition is default
        logging.warn("slurm.default_partition was set on more than one nodearray!")
    
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
        cluster = client.clusters.get(cluster_name)
        _cluster_wrapper = ClusterWrapper(cluster.name, cluster._client.session, cluster._client)
        
    return _cluster_wrapper


def _generate_slurm_conf(partitions, writer, subprocess_module):
    for partition in partitions.values():
        if partition.node_list is None:
            raise RuntimeError("No nodes found for nodearray %s. Please run 'cyclecloud_slurm.sh create_nodes' first!" % partition.nodearray)
        
        num_placement_groups = int(ceil(float(partition.max_vm_count) / partition.max_scaleset_size))
        default_yn = "YES" if partition.is_default else "NO"
        writer.write("PartitionName={} Nodes={} Default={} MaxTime=INFINITE State=UP\n".format(partition.name, partition.node_list, default_yn))
        
        all_nodes = sorted(_from_hostlist(subprocess_module, partition.node_list), key=_get_sort_key_func(partition.is_hpc)) 
        
        for pg_index in range(num_placement_groups):
            start = pg_index * partition.max_scaleset_size
            end = min(partition.max_vm_count, (pg_index + 1) * partition.max_scaleset_size)
            subset_of_nodes = all_nodes[start:end]
            node_list = _to_hostlist(subprocess_module, ",".join((subset_of_nodes)))
            
            writer.write("Nodename={} Feature=cloud STATE=CLOUD CPUs={} RealMemory={}\n".format(node_list, partition.vcpu_count, int(floor(partition.memory * 1024))))


def _get_sort_key_func(is_hpc):
    return _node_index_and_pg_as_sort_key if is_hpc else _node_index_as_sort_key


def _node_index_as_sort_key(nodename):
    '''
    Used to get the key to sort names that don't have name-pg#-# format
    '''
    try:
        return int(nodename.split("-")[-1])
    except Exception:
        return nodename
    

def _node_index_and_pg_as_sort_key(nodename):
    '''
        Used to get the key to sort names that have name-pg#-# format
    '''
    try:
        node_index = int(nodename.split("-")[-1])
        pg = int(nodename.split("-")[-2].replace("pg", "")) * 100000
        return pg + node_index
    except Exception:
        return nodename
            

def generate_slurm_conf():
    subprocess = _subprocess_module()
    partitions = fetch_partitions(_get_cluster_wrapper(), subprocess)
    _generate_slurm_conf(partitions, sys.stdout, subprocess)
            

def _generate_topology(cluster_wrapper, subprocess_module, writer):
    _, node_list = _retry_rest(cluster_wrapper.get_nodes)
    
    nodes_by_pg = {}
    for node in node_list.nodes:
        is_autoscale = node.get("Configuration", {}).get("slurm", {}).get("autoscale", False)
        if not is_autoscale:
            continue
        
        pg = node.get("PlacementGroupId") or "htc"

        if pg not in nodes_by_pg:
            nodes_by_pg[pg] = []
        
        nodes_by_pg[pg].append(node.get("Name"))
    
    if not nodes_by_pg:
        raise CyclecloudSlurmError("No nodes found to create topology! Do you need to run create_nodes first?")
        
    for pg in sorted(nodes_by_pg.keys()):
        nodes = nodes_by_pg[pg]
        nodes = sorted(nodes, key=_get_sort_key_func(pg != "htc"))
        slurm_node_expr = _to_hostlist(subprocess_module, ",".join(nodes))
        writer.write("SwitchName={} Nodes={}\n".format(pg, slurm_node_expr))


def generate_topology():
    subprocess = _subprocess_module()
    return _generate_topology(_get_cluster_wrapper(), subprocess, sys.stdout)
        
        
def _shutdown(node_list, cluster_wrapper):
    _retry_rest(lambda: cluster_wrapper.shutdown_nodes(names=node_list))


def shutdown(node_list):
    return _shutdown(node_list, _get_cluster_wrapper())


def _resume(node_list, cluster_wrapper, subprocess_module):
    _, start_response = _retry_rest(lambda: cluster_wrapper.start_nodes(names=node_list))
    _wait_for_resume(cluster_wrapper, start_response.operation_id, node_list, subprocess_module)


def _wait_for_resume(cluster_wrapper, operation_id, node_list, subprocess_module):
    updated_node_addrs = set()
    
    previous_states = {}
    
    nodes_str = ",".join(node_list[:5])
    omega = time.time() + 3600 
    
    while time.time() < omega:
        states = {}
        _, nodes_response = _retry_rest(lambda: cluster_wrapper.get_nodes(operation_id=operation_id))
        for node in nodes_response.nodes:
            name = node.get("Name")
            state = node.get("State")
            
            if node.get("TargetState") != "Started":
                states["UNKNOWN"] = states.get("UNKNOWN", {})
                states["UNKNOWN"][state] = states["UNKNOWN"].get(state, 0) + 1
                continue
            
            private_ip = node.get("PrivateIp")
            if state == "Started" and not private_ip:
                state = "WaitingOnIPAddress"
            
            states[state] = states.get(state, 0) + 1
            
            if private_ip and name not in updated_node_addrs:
                cmd = ["scontrol", "update", "NodeName=%s" % name, "NodeAddr=%s" % private_ip, "NodeHostname=%s" % private_ip]
                logging.info("Running %s", " ".join(cmd))
                _retry_subprocess(lambda: subprocess_module.check_call(cmd))
                updated_node_addrs.add(name)
                
        terminal_states = states.get("Started", 0) + sum(states.get("UNKNOWN", {}).itervalues()) + states.get("Failed", 0)
        
        if states != previous_states:
            states_messages = []
            for key in sorted(states.keys()):
                if key != "UNKNOWN":
                    states_messages.append("{}={}".format(key, states[key]))
                else:
                    for ukey in sorted(states["UNKNOWN"].keys()):
                        states_messages.append("{}={}".format(ukey, states["UNKNOWN"][key]))
                        
            states_message = " , ".join(states_messages)
            logging.info("OperationId=%s NodeList=%s: Number of nodes in each state: %s", operation_id, nodes_str, states_message)
            
        if terminal_states == len(nodes_response.nodes):
            break
        
        previous_states = states
        
        time.sleep(5)
        
    logging.info("OperationId=%s NodeList=%s: all nodes updated with the proper IP address. Exiting", operation_id, nodes_str)
        
        
def resume(node_list):
    cluster_wrapper = _get_cluster_wrapper()
    subprocess_module = _subprocess_module()
    return _resume(node_list, cluster_wrapper, subprocess_module)


class ExistingNodePolicy:
    Error = "Error"
    AllowExisting = "AllowExisting"
    # TODO need a Recreate - shutdown, remove and recreate...
    

def _create_nodes(partitions, cluster_wrapper, subprocess_module, existing_policy=ExistingNodePolicy.Error):
    request = NodeCreationRequest()
    request.request_id = str(uuid4())
    request.sets = []
    
    nodearray_counts = {}
     
    for partition in partitions.itervalues():
        placement_group_base = "{}-{}-pg".format(partition.nodearray, partition.machine_type)
        if partition.is_hpc:
            name_format = "{}-pg{}-%d"
        else:
            name_format = "{}-%d"
        
        current_name_offset = None
        current_pg_index = None
        
        expanded_node_list = []
        if partition.node_list:
            expanded_node_list = _from_hostlist(subprocess_module, partition.node_list)
        
        for index in range(partition.max_vm_count):
            placement_group_index = index / partition.max_scaleset_size
            placement_group = placement_group_base + str(placement_group_index)
            
            if current_pg_index != placement_group_index:
                current_name_offset = 1
                current_pg_index = placement_group_index
                
            name_index = (index % partition.max_scaleset_size) + 1
            node_name = name_format.format(partition.nodearray, placement_group_index) % (name_index)
            if node_name in expanded_node_list:
                # Don't allow recreation of nodes
                if existing_policy == ExistingNodePolicy.Error:
                    raise CyclecloudSlurmError("Node %s already exists. Please pass in --policy AllowExisting if you want to go ahead and create the nodes anyways." % node_name)
                current_name_offset = name_index + 1
                continue
            
            # we are grouping these by their name offset
            name_offset = current_name_offset
            
            key = (partition.name, placement_group, placement_group_index, name_offset)
            nodearray_counts[key] = nodearray_counts.get(key, 0) + 1
            
    for key, instance_count in sorted(nodearray_counts.iteritems(), key=lambda x: x[0]):
        partition_name, pg, pg_index, name_offset = key
        partition = partitions[partition_name]
        
        request_set = NodeCreationRequestSet()
        
        request_set.nodearray = partition.nodearray
        
        if partition.is_hpc:
            request_set.placement_group_id = pg
        
        request_set.count = instance_count
        
        request_set.definition = NodeCreationRequestSetDefinition()
        request_set.definition.machine_type = partition.machine_type
        
        # TODO should probably make this a util function
        if partition.is_hpc:
            request_set.name_format = "{}-pg{}-%d".format(partition.nodearray, pg_index)
        else:
            request_set.name_format = "{}-%d".format(partition.nodearray)
            
        request_set.name_offset = name_offset
        request_set.node_attributes = Record()
        request_set.node_attributes["StartAutomatically"] = False
        request_set.node_attributes["Fixed"] = True
        
        request.sets.append(request_set)
    
    if not request.sets:
        # they must have been attempting to create at least one node.
        if existing_policy == ExistingNodePolicy.Error:
            raise CyclecloudSlurmError("No nodes were created!")
        
        logging.info("No new nodes to create with policy %s", existing_policy)
        return
    
    # one shot, don't retry as this is not monotonic.
    logging.debug("Creation request: %s", json.dumps(json.loads(request.json_encode()), indent=2))
    try:
        _, result = cluster_wrapper.create_nodes(request)
    except Exception as e:
        logging.debug(traceback.format_exc())
        try:
            # attempt to parse the json response from cyclecloud to give a better message
            response = json.loads(str(e))
            message = "%s: %s" % (response["Message"], response["Detail"])
        except:
            logging.debug(traceback.format_exc())
            message = str(e)
            
        raise CyclecloudSlurmError("Creation of nodes failed: %s" % message)
    
    num_created = sum([s.added for s in result.sets])
    
    if num_created == 0 and existing_policy == ExistingNodePolicy.Error:
        raise CyclecloudSlurmError("Did not create a single node!")
    
    for set_result in result.sets:
        logging.info("Added %s nodes. %s", set_result.added, set_result.message)
        

def create_nodes(existing_policy):
    cluster_wrapper = _get_cluster_wrapper()
    subprocess_module = _subprocess_module()
    partitions = fetch_partitions(cluster_wrapper, subprocess_module)
    _create_nodes(partitions, cluster_wrapper, subprocess_module, existing_policy)
        
        
def _init_logging(logfile):
    import logging.handlers
    
    log_level_name = os.getenv('AUTOSTART_LOG_LEVEL', "INFO")
    log_file_level_name = os.getenv('AUTOSTART_LOG_FILE_LEVEL', "DEBUG")
    log_file = os.getenv('AUTOSTART_LOG_FILE', logfile)
    
    if log_file_level_name.lower() not in ["debug", "info", "warn", "error", "critical"]:
        log_file_level = logging.DEBUG
    else:
        log_file_level = getattr(logging, log_file_level_name.upper())
        
    if log_level_name.lower() not in ["debug", "info", "warn", "error", "critical"]:
        stderr_level = logging.DEBUG
    else:
        stderr_level = getattr(logging, log_level_name.upper())
    
    logging.getLogger("requests.packages.urllib3.connectionpool").setLevel(logging.WARN)
    logging.getLogger("urllib3.connectionpool").setLevel(logging.WARN)
    
    log_file = logging.handlers.RotatingFileHandler(log_file, maxBytes=1024 * 1024 * 5, backupCount=5)
    log_file.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    log_file.setLevel(log_file_level)
    
    stderr = logging.StreamHandler(sys.stderr)
    stderr.setFormatter(logging.Formatter("%(message)s"))
    stderr.setLevel(stderr_level)
    
    logging.getLogger().addHandler(log_file)
    logging.getLogger().addHandler(stderr)
    logging.getLogger().setLevel(logging.DEBUG)
    

def _retry_rest(func, attempts=5):
    attempts = max(1, attempts)
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except Exception as e:
            logging.debug(traceback.format_exc())
            
            time.sleep(attempt * attempt)
    
    raise CyclecloudSlurmError(str(e))


def _retry_subprocess(func, attempts=5):
    attempts = max(1, attempts)
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except Exception as e:
            logging.debug(traceback.format_exc())
            logging.warn("Command failed, retrying: %s", str(e))
            time.sleep(attempt * attempt)
    
    raise CyclecloudSlurmError(str(e))


def _to_hostlist(subprocess_module, nodes):
    '''
        convert name-[1-5] into name-1 name-2 name-3 name-4 name-5
    '''
    return _retry_subprocess(lambda: subprocess_module.check_output(["scontrol", "show", "hostlist", nodes])).strip()


def _from_hostlist(subprocess_module, hostlist_expr):
    '''
        convert name-1,name-2,name-3,name-4,name-5 into name-[1-5]
    '''
    stdout = _retry_subprocess(lambda: subprocess_module.check_output(["scontrol", "show", "hostnames", hostlist_expr]))
    return [x.strip() for x in stdout.split()]


def _subprocess_module():
    '''
    Wrapper so we can attach chaos mode to the subprocess module
    '''
    import subprocess
    
    def raise_exception():
        def called_proc_exception(msg):
            raise subprocess.CalledProcessError(1, msg)
        raise random.choice([OSError, called_proc_exception])("Random failure")
    
    class SubprocessModuleWithChaosMode:
        @custom_chaos_mode(raise_exception)
        def check_call(self, *args, **kwargs):
            return subprocess.check_call(*args, **kwargs)
        
        @custom_chaos_mode(raise_exception)
        def check_output(self, *args, **kwargs):
            return subprocess.check_output(*args, **kwargs)
        
    return SubprocessModuleWithChaosMode()

    
def main(argv=None):
    
    def hostlist(hostlist_expr):
        import subprocess
        return _from_hostlist(subprocess, hostlist_expr)
    
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    
    slurm_conf_parser = subparsers.add_parser("slurm_conf")
    slurm_conf_parser.set_defaults(func=generate_slurm_conf, logfile="slurm_conf.log")
    
    topology_parser = subparsers.add_parser("topology")
    topology_parser.set_defaults(func=generate_topology, logfile="topology.log")
    
    create_nodes_parser = subparsers.add_parser("create_nodes")
    create_nodes_parser.add_argument("--policy", dest="existing_policy", default=ExistingNodePolicy.Error)
    create_nodes_parser.set_defaults(func=create_nodes, logfile="create_nodes.log")
    
    resume_parser = subparsers.add_parser("resume")
    resume_parser.set_defaults(func=resume, logfile="resume.log")
    resume_parser.add_argument("--node-list", type=hostlist, required=True)
    
    resume_fail_parser = subparsers.add_parser("resume_fail")
    resume_fail_parser.set_defaults(func=shutdown, logfile="resume_fail.log")
    resume_fail_parser.add_argument("--node-list", type=hostlist, required=True)
    
    suspend_parser = subparsers.add_parser("suspend")
    suspend_parser.set_defaults(func=shutdown, logfile="suspend.log")
    suspend_parser.add_argument("--node-list", type=hostlist, required=True)
    
    for conn_parser in [create_nodes_parser, topology_parser, slurm_conf_parser]:
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
    try:
        main()
    except CyclecloudSlurmError as e:
        logging.error(str(e))
        logging.debug(traceback.format_exc())
        sys.exit(1)
    except Exception:
        logging.exception("Unhandled failure.")
        raise
