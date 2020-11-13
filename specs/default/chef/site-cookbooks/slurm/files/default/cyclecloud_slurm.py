# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
import argparse
from collections import OrderedDict
import json
import logging
from math import ceil, floor
import os
import random
import shutil
import sys
import time
import traceback
import csv
from uuid import uuid4

from clusterwrapper import ClusterWrapper
from cyclecloud.client import Client, Record
from cyclecloud.model.NodeCreationRequestModule import NodeCreationRequest
from cyclecloud.model.NodeCreationRequestSetDefinitionModule import NodeCreationRequestSetDefinition
from cyclecloud.model.NodeCreationRequestSetModule import NodeCreationRequestSet
from slurmcc import custom_chaos_mode


class CyclecloudSlurmError(RuntimeError):
    pass


class Partition:
    
    def __init__(self, name, nodearray, machine_type, is_default, is_hpc, max_scaleset_size, vm, max_vm_count, dampen_memory=.05):
        self.name = name
        self.nodearray = nodearray
        self.machine_type = machine_type
        self.is_default = is_default
        self.is_hpc = is_hpc
        self.max_scaleset_size = max_scaleset_size
        self.vcpu_count = vm.vcpu_count
        self.memory = vm.memory
        self.max_vm_count = max_vm_count
        self.node_list = None
        self.dampen_memory = dampen_memory
        self.vm = vm

    @property
    def pcpu_count(self):
        if hasattr(self.vm, "pcpu_count"):
            return self.vm.pcpu_count
        return self.vcpu_count

    @property
    def gpu_count(self):
        if hasattr(self.vm, "gpu_count"):
            return self.vm.gpu_count
        return 0


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
        if not isinstance(machine_types, list):
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
            logging.error("Invalid status response - missing bucket with machinetype=='%s', %s", machine_type, _dump_response(status_response))
            sys.exit(1)
        
        vm = bucket.virtual_machine
        if not vm:
            logging.error("Invalid status response - missing virtualMachine definition with machinetype=='%s', %s", machine_type, _dump_response(status_response))
            sys.exit(1)
        
        if bucket.max_count is None:
            logging.error("No max_count defined for  machinetype=='%s'. Skipping", machine_type)
            continue
        
        if bucket.max_count <= 0:
            logging.info("Bucket has a max_count <= 0, defined for machinetype=='%s'. Skipping", machine_type)
            continue
        
        max_scaleset_size = Record(nodearray_record.get("Azure", {})).get("MaxScalesetSize", 40)
        
        dampen_memory = float(slurm_config.get("dampen_memory") or 5) / 100
        
        is_hpc = str(slurm_config.get("hpc", True)).lower() == "true"
        
        if not is_hpc:
            max_scaleset_size = 2**31
        
        partitions[partition_name] = Partition(partition_name,
                                               nodearray_name,
                                               machine_type,
                                               slurm_config.get("default_partition", False),
                                               is_hpc,
                                               max_scaleset_size,
                                               vm,
                                               bucket.max_count,
                                               dampen_memory=dampen_memory)
        
        existing_nodes = []
        
        for node in nodes_response.nodes:
            if node.get("Template") == nodearray_name:
                existing_nodes.append(node.get("Name"))
        
        if existing_nodes:
            sorted_nodes = sorted(existing_nodes, key=_get_sort_key_func(partitions[partition_name].is_hpc))
            partitions[partition_name].node_list = _to_hostlist(subprocess_module, ",".join(sorted_nodes))
    
    partitions_list = list(partitions.values())
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


def _get_cluster_wrapper(config_path=None):
    global _cluster_wrapper
    if _cluster_wrapper is None:
        assert config_path
        if not os.path.exists(config_path):
            raise CyclecloudSlurmError("{} does not exist! Please see 'cyclecloud_slurm.sh initialize'")
        
        with open(config_path) as fr:
            autoscale_config = json.load(fr)
        
        def _get(k):
            if not autoscale_config.get(k):
                raise CyclecloudSlurmError("Please define {} in {}".format(k, config_path))
            return autoscale_config.get(k)
            
        cluster_name = _get("cluster_name")
        
        connection_config = {"verify_certificates": autoscale_config.get("verify_certificates", False),
                  "username": _get("username"),
                  "password": _get("password"),
                  "url": _get("url"),
                  "cycleserver": {
                      "timeout": autoscale_config.get("timeout", 60)
                  }
        }
        
        client = Client(connection_config)
        cluster = client.clusters.get(cluster_name)
        _cluster_wrapper = ClusterWrapper(cluster.name, cluster._client.session, cluster._client)
        
    return _cluster_wrapper


def _generate_slurm_conf(partitions, writer, subprocess_module):
    for partition in partitions.values():
        if partition.node_list is None:
            raise RuntimeError("No nodes found for nodearray %s. Please run 'cyclecloud_slurm.sh create_nodes' first!" % partition.nodearray)
        
        num_placement_groups = int(ceil(float(partition.max_vm_count) / partition.max_scaleset_size))
        default_yn = "YES" if partition.is_default else "NO"
        
        memory_to_reduce = max(1, partition.memory * partition.dampen_memory)
        memory = max(1024, int(floor((partition.memory - memory_to_reduce) * 1024)))
        def_mem_per_cpu = memory // partition.pcpu_count
        cores_per_socket = max(1, partition.pcpu_count // partition.vcpu_count)

        writer.write("# Note: CycleCloud reported a RealMemory of %d but we reduced it by %d (i.e. max(1gb, %d%%)) to account for OS/VM overhead which\n"
                     % (int(partition.memory * 1024), int(memory_to_reduce * 1024), int(partition.dampen_memory * 100)))
        writer.write("# would result in the nodes being rejected by Slurm if they report a number less than defined here.\n")
        writer.write("# To pick a different percentage to dampen, set slurm.dampen_memory=X in the nodearray's Configuration where X is percentage (5 = 5%).\n")
        writer.write("PartitionName={} Nodes={} Default={} DefMemPerCPU={} MaxTime=INFINITE State=UP\n".format(partition.name, partition.node_list, default_yn, def_mem_per_cpu))
        
        all_nodes = sorted(_from_hostlist(subprocess_module, partition.node_list), key=_get_sort_key_func(partition.is_hpc)) 
        
        for pg_index in range(num_placement_groups):
            start = pg_index * partition.max_scaleset_size
            end = min(partition.max_vm_count, (pg_index + 1) * partition.max_scaleset_size)
            subset_of_nodes = all_nodes[start:end]
            node_list = _to_hostlist(subprocess_module, ",".join((subset_of_nodes)))
            # cut out 1gb so that the node reports at least this amount of memory. - recommended by schedmd
            
            writer.write("Nodename={} Feature=cloud STATE=CLOUD CPUs={} CoresPerSocket={} RealMemory={}".format(
                         node_list, partition.pcpu_count, cores_per_socket, memory))
            
            if partition.gpu_count:
                writer.write(" Gres=gpu:{}".format(partition.gpu_count))

            writer.write("\n")


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
            

def generate_slurm_conf(writer=sys.stdout):
    subprocess = _subprocess_module()
    partitions = fetch_partitions(_get_cluster_wrapper(), subprocess)
    _generate_slurm_conf(partitions, writer, subprocess)
            

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


def generate_topology(writer=sys.stdout):
    subprocess = _subprocess_module()
    return _generate_topology(_get_cluster_wrapper(), subprocess, writer)

def _generate_gres_conf(partitions, writer, subprocess_module):
    for partition in partitions.values():
        if partition.node_list is None:
            raise RuntimeError("No nodes found for nodearray %s. Please run 'cyclecloud_slurm.sh create_nodes' first!" % partition.nodearray)

        num_placement_groups = int(ceil(float(partition.max_vm_count) / partition.max_scaleset_size))
        all_nodes = sorted(_from_hostlist(subprocess_module, partition.node_list), key=_get_sort_key_func(partition.is_hpc)) 

        for pg_index in range(num_placement_groups):
            start = pg_index * partition.max_scaleset_size
            end = min(partition.max_vm_count, (pg_index + 1) * partition.max_scaleset_size)
            subset_of_nodes = all_nodes[start:end]
            node_list = _to_hostlist(subprocess_module, ",".join((subset_of_nodes)))
            # cut out 1gb so that the node reports at least this amount of memory. - recommended by schedmd
            
            if partition.gpu_count:
                if partition.gpu_count > 1:
                    nvidia_devices = "/dev/nvidia[0-{}]".format(partition.gpu_count-1)
                else:
                    nvidia_devices = "/dev/nvidia0"
                writer.write("Nodename={} Name=gpu Count={} File={}".format(node_list, partition.gpu_count, nvidia_devices))

            writer.write("\n")
        
def generate_gres_conf(writer=sys.stdout):
    subprocess = _subprocess_module()
    partitions = fetch_partitions(_get_cluster_wrapper(), subprocess)
    _generate_gres_conf(partitions, writer, subprocess)

        
def _shutdown(node_list, cluster_wrapper):
    _retry_rest(lambda: cluster_wrapper.shutdown_nodes(names=node_list))


def shutdown(node_list):
    for node in node_list:
        subprocess_module = _subprocess_module()
        cmd = ["scontrol", "update", "NodeName=%s" % node, "NodeAddr=%s" % node, "NodeHostname=%s" % node]
        logging.info("Running %s", " ".join(cmd))
        _retry_subprocess(lambda: subprocess_module.check_call(cmd))
    return _shutdown(node_list, _get_cluster_wrapper())


def _terminate_nodes(node_list, cluster_wrapper):
    _retry_rest(lambda: cluster_wrapper.terminate_nodes(names=node_list))

def terminate_nodes(node_list):
    # Forces termination even if autoscale ShutdownPolicy is Deallocate
    return _terminate_nodes(node_list, _get_cluster_wrapper())


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
                
        terminal_states = states.get("Started", 0) + sum(states.get("UNKNOWN", {}).values()) + states.get("Failed", 0)
        
        if states != previous_states:
            states_messages = []
            for key in sorted(states.keys()):
                if key != "UNKNOWN":
                    states_messages.append("{}={}".format(key, states[key]))
                else:
                    for ukey in sorted(states["UNKNOWN"].keys()):
                        states_messages.append("{}={}".format(ukey, states["UNKNOWN"][ukey]))
                        
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
    

class UnreferencedNodePolicy:
    RemoveSafely = "RemoveSafely"
    

def _create_nodes(partitions, cluster_wrapper, subprocess_module, existing_policy=ExistingNodePolicy.Error, unreferenced_policy=UnreferencedNodePolicy.RemoveSafely):
    request = NodeCreationRequest()
    request.request_id = str(uuid4())
    request.sets = []
    
    nodearray_counts = {}
     
    for partition in partitions.values():
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
        
        valid_node_names = set()
        
        for index in range(partition.max_vm_count):
            placement_group_index = index // partition.max_scaleset_size
            placement_group = placement_group_base + str(placement_group_index)
            
            if current_pg_index != placement_group_index:
                current_name_offset = 1
                current_pg_index = placement_group_index
                
            name_index = (index % partition.max_scaleset_size) + 1
            node_name = name_format.format(partition.nodearray, placement_group_index) % (name_index)
            
            valid_node_names.add(node_name)
            
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
            
        unreferenced_nodes = sorted(list(set(expanded_node_list) - valid_node_names))
        if unreferenced_nodes and unreferenced_policy == UnreferencedNodePolicy.RemoveSafely:
            _remove_nodes(cluster_wrapper, subprocess_module, unreferenced_nodes)
            
    for key, instance_count in sorted(nodearray_counts.items(), key=lambda x: x[0]):
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
        
        logging.info("No new nodes are required.")
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

    for n, set_result in enumerate(result.sets):
        request_set = request.sets[n]
        if set_result.added == 0:
            logging.warn("No nodes were created for nodearray %s using name format %s and offset %s: %s", request_set.nodearray, request_set.name_format,
                                                                                                          request_set.name_offset, set_result.message)
        else:
        
            message = "Added %s nodes to %s using name format %s and offset %s." % (set_result.added, request_set.nodearray, request_set.name_format, request_set.name_offset)
            if set_result.message:
                message += " Note: %s" % set_result.message
            logging.info(message)
        

def create_nodes(existing_policy):
    cluster_wrapper = _get_cluster_wrapper()
    subprocess_module = _subprocess_module()
    partitions = fetch_partitions(cluster_wrapper, subprocess_module)
    _create_nodes(partitions, cluster_wrapper, subprocess_module, existing_policy)
    
    
def _remove_nodes(cluster_wrapper, subprocess_module, names_to_remove):
    # this is just used for logging purposes, so fall back on a simple comma delimited list.
    try:
        to_remove_hostlist = _to_hostlist(subprocess_module, ",".join(names_to_remove))
    except:
        logging.warn(traceback.format_exc())
        to_remove_hostlist = ",".join(names_to_remove)
        
    logging.info("Attempting to remove the following nodes: %s", to_remove_hostlist)
    
    node_filter = 'ClusterName == "%s" && Name in {"%s"} && (State=="Terminated" || State is undefined)' % (cluster_wrapper.cluster_name, '","'.join(names_to_remove))
    _, mgmt_result = _retry_rest(lambda: cluster_wrapper.remove_nodes(custom_filter=node_filter))
    removed_nodes = [n.name for n in mgmt_result.nodes]
    unremoved_nodes = set(names_to_remove) - set(removed_nodes)
    if unremoved_nodes:
        logging.warn("Warning: The following nodes could not be removed because they were not terminated - %s.", ",".join(unremoved_nodes))
        logging.warn("Please terminate them and rerun this command or remove them manually via the cli or user interface.",)


def remove_nodes(names_to_remove=None):
    cluster_wrapper = _get_cluster_wrapper()
    subprocess_module = _subprocess_module()
    if not names_to_remove:
        names_to_remove = []
        _, node_list = _retry_rest(cluster_wrapper.get_nodes)
        for node in node_list.nodes:
            name = node.get("Name")
            is_autoscale = node.get("Configuration", {}).get("slurm", {}).get("autoscale", False)
            if is_autoscale:
                names_to_remove.append(name)
    else:
        if isinstance(names_to_remove, basestring):
            names_to_remove = [x.strip() for x in names_to_remove.split(",")]
    _remove_nodes(cluster_wrapper, subprocess_module, names_to_remove)
    
    
def delete_nodes_if_out_of_date(subprocess_module=None, cluster_wrapper=None):
    subprocess_module = subprocess_module or _subprocess_module()
    cluster_wrapper = cluster_wrapper or _get_cluster_wrapper()
    _, node_list = cluster_wrapper.get_nodes()
    nodes_by_name = {}
    for node in node_list.nodes:
        nodes_by_name[node["Name"]] = node
        
    partitions = fetch_partitions(cluster_wrapper, subprocess_module)
    to_remove = []
    can_not_remove = []
    
    for partition in partitions.values():
        if not partition.node_list:
            continue
        node_list = _from_hostlist(subprocess_module, partition.node_list)

        for node_name in node_list:
            node = nodes_by_name[node_name]
            mt = str(node.get("MachineType"))
            if str(partition.machine_type).lower() != mt.lower():
                if node.get("State") not in [None, "Terminated"]:
                    can_not_remove.append(node)
                    continue
                to_remove.append(node_name)
    
    if can_not_remove:
        any_node = can_not_remove[0]
        node_name = any_node.get("Name")
        node_list_expr = ",".join(sorted([x.get("Name") for x in can_not_remove]))
        to_shutdown = _to_hostlist(subprocess_module, node_list_expr)
        raise CyclecloudSlurmError(("Machine type is now %s for %s nodes but at least one node is not terminated that has the old machine type - %s in state %s with machine type %s.\n" +
                                   "Please terminate these via the UI or 'terminate_nodes.sh %s' then rerun the scale command.")
                                               % (partition.machine_type, partition.name, node_name, node.get("State"), mt, to_shutdown))
    
    if to_remove:
        to_remove = sorted(to_remove)
        to_remove_hostlist = _from_hostlist(subprocess_module, ",".join(to_remove))
        logging.info("Deleting %s nodes because their machine type changed - %s" % (len(to_remove), to_remove_hostlist))
        cluster_wrapper.remove_nodes(names=to_remove)
        
        
def upgrade_conf(slurm_conf=None, sched_dir="/sched", backup_dir="/etc/slurm/.backups"):
    '''
    Handle upgrades - we used to use slurm.conf.base and then append to it.
    1) make sure we include cyclecloud.conf
    2) Ignore partition / nodename definitions we used to append to slurm.conf
    3) Remove deprecated ControlMachine
    '''
    
    slurm_conf = slurm_conf or os.path.join(sched_dir, "slurm.conf")
    
    if os.getenv("CYCLECLOUD_SLURM_DISABLE_CONF_UPGRADE", ""):
        logging.warn("CYCLECLOUD_SLURM_DISABLE_CONF_UPGRADE is defined, skipping upgrade.")
        return
        
    base_slurm_conf = slurm_conf
    
    if not os.path.exists(base_slurm_conf):
        base_slurm_conf = os.path.join(sched_dir, "slurm.conf.base")
        if not os.path.exists(base_slurm_conf):
            raise CyclecloudSlurmError("Slurm conf does not exist at %s" % slurm_conf)
        shutil.copyfile(base_slurm_conf, slurm_conf)
    
    deprecated = ["partitionname", "nodename", "controlmachine"]
    
    requires_upgrade = False
    found_include = False
    with open(slurm_conf) as fr:
        for line in fr:
            for prefix in deprecated:
                if line.lower().startswith(prefix):
                    logging.warn("Found line starting with %s. Will upgrade old slurm.conf. To disable, define CYCLECLOUD_SLURM_DISABLE_CONF_UPGRADE=1" % prefix)
                    requires_upgrade = True
                    continue
                if line.lower().strip().split() == ["include", "cyclecloud.conf"]:
                    found_include = True
                    
    if not found_include and not requires_upgrade:
        logging.warn("Did not find include cyclecloud.conf, so will upgrade slurm.conf. To disable, define CYCLECLOUD_SLURM_DISABLE_CONF_UPGRADE=1")
        requires_upgrade = True
        
    if not requires_upgrade:
        logging.info("Upgrade not required!")
        return
    
    # make sure .backups exists
    now = time.time()
    backup_dir = os.path.join(backup_dir, str(now))
    
    logging.info("Using backup directory %s for slurm.conf", backup_dir)
    os.makedirs(backup_dir)
    
    shutil.copyfile(slurm_conf, os.path.join(backup_dir, "slurm.conf"))
    
    logging.warn("Upgrading slurm.conf by removing ControlHost, PartitionName and NodeName definitions. To disable, define CYCLECLOUD_SLURM_DISABLE_CONF_UPGRADE=1")
    # backwards compat - if a slurm.conf does not include cyclecloud.conf, include it
    with open(slurm_conf) as fr:
        with open(slurm_conf + ".tmp", "w") as fw:
            skip_entries = (deprecated + ["include cyclecloud.conf"])
            for line in fr:
                line_lower = line.lower()
                
                skip_this_line = False
                
                for prefix in skip_entries:
                    if line_lower.startswith(prefix):
                        skip_this_line = True
                
                if not skip_this_line:
                    fw.write(line)
            fw.write("\ninclude cyclecloud.conf")
            
    shutil.move(slurm_conf + ".tmp", slurm_conf)
    logging.info("Upgrade success! Please restart slurmctld")
    
    
def rescale(subprocess_module=None, backup_dir="/etc/slurm/.backups", slurm_conf_dir="/etc/slurm", sched_dir="/sched", cluster_wrapper=None):
    slurm_conf = os.path.join(sched_dir, "slurm.conf")
    
    subprocess_module = subprocess_module or _subprocess_module()
    cluster_wrapper = cluster_wrapper or _get_cluster_wrapper()
    
    delete_nodes_if_out_of_date(subprocess_module, cluster_wrapper)
    
    create_nodes(ExistingNodePolicy.AllowExisting)
    
    # make sure .backups exists
    now = time.time()
    backup_dir = os.path.join(backup_dir, str(now))
    
    logging.debug("Using backup directory %s for topology.conf and slurm.conf", backup_dir)
    os.makedirs(backup_dir)
    
    topology_conf = os.path.join(sched_dir, "topology.conf")
    cyclecloud_slurm_conf = os.path.join(sched_dir, "cyclecloud.conf")
    
    backup_cyclecloud_conf = os.path.join(backup_dir, "slurm.conf")
    backup_topology_conf = os.path.join(backup_dir, "topology.conf")
    
    if os.path.exists(topology_conf):
        shutil.copyfile(topology_conf, backup_topology_conf)
    else:
        logging.warn("No topology file exists at %s", topology_conf)
        
    shutil.copyfile(slurm_conf, backup_cyclecloud_conf)
    shutil.copyfile(topology_conf, backup_topology_conf)
        
    with open(cyclecloud_slurm_conf + ".tmp", "w") as fw:
        generate_slurm_conf(fw)
                
    logging.debug("Moving %s to %s", cyclecloud_slurm_conf + ".tmp", cyclecloud_slurm_conf)
    shutil.move(cyclecloud_slurm_conf + ".tmp", cyclecloud_slurm_conf)
    
    logging.debug("Writing new topology to %s", topology_conf + ".tmp")
    with open(topology_conf + ".tmp", "w") as fw:
        generate_topology(fw)
    
    logging.debug("Moving %s to %s", topology_conf + ".tmp", topology_conf)    
    shutil.move(topology_conf + ".tmp", topology_conf)
    
    logging.info("Restarting slurmctld...")
    subprocess_module.check_call(["slurmctld", "restart"])
    
    new_topology = _retry_subprocess(lambda: _check_output(subprocess_module, ["scontrol", "show", "topology"]))
    logging.info("New topology:\n%s", new_topology)
    
    logging.info("")
    logging.info("Re-scaling cluster complete.")
    
    
def _nodeaddrs(cluster_wrapper, writer):
    logging.debug("Nodeaddrs: querying current nodes, filtering out those without ip addresses and where slurm.autoscale is undefined or false.")
    _, node_list = _retry_rest(cluster_wrapper.get_nodes)
    num_wrote = 0
    for node in node_list.nodes:
        name = node.get("Name")
        ip = node.get("PrivateIp")
        is_autoscale = node.get("Configuration", {}).get("slurm", {}).get("autoscale", False)
        if is_autoscale and ip:
            num_wrote += 1
            writer.write("%s %s\n" % (ip, name))
            
    logging.debug("Nodeaddrs: wrote %d nodes", num_wrote)


def nodeaddrs():
    cluster_wrapper = _get_cluster_wrapper()
    _nodeaddrs(cluster_wrapper, sys.stdout)

def _nodeinfo_sinfo(subprocess_module, nodelist=None):
    cmd = ["sinfo", "-N", "-h", "-o", '"%N %T"']
    
    if nodelist is not None:
        cmd.extend(["--nodes", ",".join(nodelist)])
 
    return _retry_subprocess(lambda: subprocess_module.check_output(cmd)).decode("utf-8").replace('"','').splitlines()
    

def _nodeinfo(cluster_wrapper, nodelist, subprocess_module, writer, show_all=False, list_nodes=False):

    writer.writerow(["Node-Name", "Slurm-State", "IpAddr", "Hostname",  "CC-Node-State", "CC-Node-Status", "Azure-VM-SKU" ])

    _, cluster_node_list = _retry_rest(cluster_wrapper.get_nodes)
    
    nodes_by_name = {}
    for node in cluster_node_list.nodes:
        nodes_by_name[node["Name"]] = node
    
    aggregated_node_status = {}
    for [node_name, slurm_status] in  [x.split(" ") for x in _nodeinfo_sinfo(subprocess_module, nodelist)]:
        node = nodes_by_name[node_name]
        ip = node.get("PrivateIp","-")
        hostname = node.get("Hostname","-")
        vmsku = node.get("MachineType","-")
        node_state = node.get("State","-")
        node_status = node.get("Status","-")
        target_state = node.get("TargetState","-")

        show = True

        if (node_status == "Off"):
            if ((node_state != '-') and (node_state != 'Terminated')) or (show_all): 
                # cyclecloud caches info nodes that have not been removed 
                # Clear out these values if node is in the "Off" state
                ip = "-"
                hostname = "-"
                show = True
            else:
                show = False
        
        if show:
            if list_nodes:
                writer.writerow([node_name, slurm_status, ip, hostname,  node_state, node_status, vmsku ])
            else:
                if aggregated_node_status.get((slurm_status, ip, hostname,  node_state, node_status, vmsku)):
                    aggregated_node_status[(slurm_status, ip, hostname,  node_state, node_status, vmsku)].append(node_name)
                else:
                    aggregated_node_status[(slurm_status, ip, hostname,  node_state, node_status, vmsku)]=[node_name]    
    
    if not list_nodes:
        for (slurm_status, ip, hostname,  node_state, node_status, vmsku) in aggregated_node_status:
            node_name_list = ",".join(aggregated_node_status[(slurm_status, ip, hostname,  node_state, node_status, vmsku)])
            hostlist = _to_hostlist(subprocess_module,node_name_list)
            writer.writerow([hostlist, slurm_status, ip, hostname,  node_state, node_status, vmsku ])


def nodeinfo(node_list, show_all, list_nodes):
    cluster_wrapper = _get_cluster_wrapper()
    subprocess = _subprocess_module()
    _nodeinfo(cluster_wrapper, node_list, subprocess, csv.writer(sys.stdout, delimiter="\t"), show_all, list_nodes)


        
def _init_logging(logfile):
    import logging.handlers
    
    # other libs will call logging.basicConfig which adds a duplicate streamHandler to the root logger.
    # filter them out here so we can add our own.
    logging.getLogger().handlers = [x for x in logging.getLogger().handlers if not isinstance(x, logging.StreamHandler)]
    
    log_level_name = os.getenv('AUTOSTART_LOG_LEVEL', "INFO")
    log_file_level_name = os.getenv('AUTOSTART_LOG_FILE_LEVEL', "DEBUG")
    actual_log_file = os.getenv('AUTOSTART_LOG_FILE', logfile)
    
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
    
    log_file = logging.handlers.RotatingFileHandler(actual_log_file, maxBytes=1024 * 1024 * 5, backupCount=5)
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
    last_exception = None
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except Exception as e:
            last_exception = e
            logging.debug(traceback.format_exc())
            
            time.sleep(attempt * attempt)
    
    raise CyclecloudSlurmError(str(last_exception))


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
    return _retry_subprocess(lambda: _check_output(subprocess_module, ["scontrol", "show", "hostlist", nodes])).strip()


def _from_hostlist(subprocess_module, hostlist_expr):
    '''
        convert name-1,name-2,name-3,name-4,name-5 into name-[1-5]
    '''
    stdout = _retry_subprocess(lambda: _check_output(subprocess_module, ["scontrol", "show", "hostnames", hostlist_expr]))
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


def initialize_config(path, cluster_name, username, password, url, force=False):
    if os.path.exists(path) and not force:
        raise CyclecloudSlurmError("{} already exists. To force reinitialization, please pass in --force".format(path))
    
    with open(path + ".tmp", "w") as fw:
        json.dump({
            "cluster_name": cluster_name,
            "username": username,
            "password": password,
            "url": url.rstrip("/")
        }, fw, indent=2)
    shutil.move(path + ".tmp", path)
    logging.info("Initialized config ({})".format(path))

    
def main(argv=None):
    
    def hostlist(hostlist_expr):
        import subprocess
        return _from_hostlist(subprocess, hostlist_expr)
    
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    
    def add_parser(name, func):
        new_parser = subparsers.add_parser(name)
        new_parser.set_defaults(func=func, logfile="{}.log".format(name))
        autoscale_path = os.path.join(os.getenv("CYCLECLOUD_HOME", "/opt/cycle/jetpack"), "config", "autoscale.json")
        new_parser.add_argument("-c", "--config", default=autoscale_path)
        return new_parser
    
    add_parser("slurm_conf", generate_slurm_conf)
    add_parser("gres_conf", generate_gres_conf)
    
    add_parser("topology", generate_topology)
    
    create_nodes_parser = add_parser("create_nodes", create_nodes)
    create_nodes_parser.add_argument("--policy", dest="existing_policy", default=ExistingNodePolicy.Error)
    
    add_parser("remove_nodes", remove_nodes)
    
    terminate_parser = add_parser("terminate_nodes", terminate_nodes)
    terminate_parser.add_argument("--node-list", type=hostlist, required=True)
    
    resume_parser = add_parser("resume", resume)
    resume_parser.add_argument("--node-list", type=hostlist, required=True)
    
    add_parser("upgrade_conf", upgrade_conf)
    
    resume_fail_parser = add_parser("resume_fail", shutdown)
    resume_fail_parser.add_argument("--node-list", type=hostlist, required=True)
    
    suspend_parser = add_parser("suspend", shutdown)
    suspend_parser.add_argument("--node-list", type=hostlist, required=True)
    
    add_parser("scale", rescale)
    
    add_parser("nodeaddrs", nodeaddrs)
    
    nodeinfo_parser = add_parser("nodeinfo", nodeinfo)
    nodeinfo_parser.add_argument("--node-list", type=hostlist, required=False)
    nodeinfo_parser.add_argument("-a","--all", dest="show_all", action='store_true', required=False)
    nodeinfo_parser.add_argument("-N", dest="list_nodes", action='store_true', required=False)

    init_parser = add_parser("initialize", initialize_config)
    init_parser.add_argument("--cluster-name", required=True)
    init_parser.add_argument("--username", required=True)
    init_parser.add_argument("--password", required=True)
    init_parser.add_argument("--url", required=True)
    init_parser.add_argument("--force", action="store_true", default=False, required=False)
    
    args = parser.parse_args(argv)
    if hasattr(args, "logfile"):
        _init_logging(args.logfile)
    
    if args.func != initialize_config:
        if not os.path.exists(args.config):
            raise CyclecloudSlurmError("Please run cyclecloud_slurm.sh initialize")
        else:
            _get_cluster_wrapper(args.config)
        kwargs = {}
        for argname in dir(args):
            if argname[0].islower() and argname not in ["config", "logfile", "func"]:
                kwargs[argname] = getattr(args, argname)
        
        args.func(**kwargs)
    else:
        initialize_config(args.config, args.cluster_name, args.username, args.password, args.url, args.force)


def _check_output(subprocess_module, *args, **kwargs):
    ret = subprocess_module.check_output(*args, **kwargs)
    if not isinstance(ret, str):
        ret = ret.decode()
    return ret


def _dump_response(status_response):

    def default_to_json(r):
        if hasattr(r, "to_dict"):
            return r.to_dict()
        return str(x)

    return json.dumps(status_response, default=default_to_json)

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
