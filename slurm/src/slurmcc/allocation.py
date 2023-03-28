# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
import logging
from typing import Callable, Dict, List, Set, Tuple

from hpc.autoscale import util as hpcutil
from hpc.autoscale import clock
from hpc.autoscale.node.bucket import NodeBucket
from hpc.autoscale.node.node import Node
from hpc.autoscale.node.nodemanager import NodeManager
from hpc.autoscale.results import AllocationResult, BootupResult

from . import AzureSlurmError
from . import partition as partitionlib
from . import util as slutil


def resume(
    config: Dict,
    node_mgr: NodeManager,
    node_list: List[str],
    partitions: List[partitionlib.Partition],
) -> BootupResult:
    name_to_partition = {}
    feature_to_partition = {}
    for partition in partitions:
        for name in partition.all_nodes():
            name_to_partition[name] = partition

        if partition.dynamic_config:
            feature_key = tuple(sorted([x.lower() for x in partition.features]))
            if feature_key in feature_to_partition:
                logging.warning(
                    f"Duplicate feature key: {feature_key}: {partition}, using the first definition."
                )
            else:
                feature_to_partition[feature_key] = partition
            feature_key_w_vm_size = feature_key + (partition.machine_type.lower(),)
            if feature_key_w_vm_size in feature_to_partition:
                logging.warning(
                    f"Duplicate feature key: {feature_key_w_vm_size}: {partition}, using the first definition."
                )
            else:
                feature_to_partition[feature_key_w_vm_size] = partition

    existing_nodes_by_name = hpcutil.partition(node_mgr.get_nodes(), lambda n: n.name)

    nodes = []
    find_by_feature = []
    for name in node_list:
        if name not in name_to_partition:
            find_by_feature.append(name)
    
    if find_by_feature and not feature_to_partition:
        raise AzureSlurmError(f"Could not find static nodes {find_by_feature} and there were no dynamic patitions either!")

    if find_by_feature:
        response = slutil.show_nodes(find_by_feature)
        for slurm_node in response:
            name = slurm_node["NodeName"]
            find_by_feature.remove(name)
            features = [x.strip() for x in slurm_node.get("AvailableFeatures", "").lower().split(",") if x.strip()]
            if not features:
                raise AzureSlurmError(f"The node {name} is not a static node and does not define any Features. This is required for dynamic nodes. {slurm_node}")
            feature_key = tuple(sorted(features))
            if feature_key not in feature_to_partition:
                # assert False, f"{feature_key} not in {list(feature_to_partition.keys())}"
                raise AzureSlurmError(
                    f"Could not map feature set to a nodearray/VM_Size combination: {feature_key}: {list(feature_to_partition.keys())}"
                )
                continue
            partition = feature_to_partition[feature_key]
            partition.add_dynamic_node(name)
            logging.info(f"Resuming {name} in {partition.name}")
            name_to_partition[name] = partition
    
    for name in node_list:
        if name in existing_nodes_by_name:
            logging.info(f"{name} already exists.")
            continue

        if name not in name_to_partition:    
            raise AzureSlurmError(
                f"Unknown node name: {name}: {list(name_to_partition.keys())}"
            )
        partition = name_to_partition[name]
        bucket = partition.bucket_for_node(name)

        def name_hook(bucket: NodeBucket, index: int) -> str:
            if index != 1:
                raise RuntimeError(f"Could not create node with name {name}. Perhaps the node already exists in a terminating state?")
            return name

        node_mgr.set_node_name_hook(name_hook)
        constraints = {"node.bucket_id": bucket.bucket_id, "exclusive": True}
        if partition.is_hpc:
            constraints["node.colocated"] = True
        result: AllocationResult = node_mgr.allocate(
            constraints, node_count=1, allow_existing=False
        )
        if len(result.nodes) != 1:
            raise RuntimeError()
        result.nodes[0].name_format = name
        nodes.extend(result.nodes)

    boot_result = node_mgr.bootup(nodes)

    return boot_result


class WaitForResume:
    def __init__(self) -> None:
        self.failed_node_names: Set[str] = set()
        self.ip_already_set: Set[Tuple[str, str]] = set()

    def check_nodes(
        self, node_list: List[str], latest_nodes: List[Node]
    ) -> Tuple[Dict, List[Node]]:
        ready_nodes = []
        states = {}

        by_name = hpcutil.partition_single(latest_nodes, lambda node: node.name)

        relevant_nodes: List[Node] = []

        recovered_node_names: Set[str] = set()

        newly_failed_node_names: List[str] = []

        deleted_nodes = []

        for name in node_list:
            node = by_name.get(name)
            
            if not node:
                deleted_nodes.append(node)
                continue
            is_dynamic = node.software_configuration.get("slurm", {}).get("dynamic_config")

            relevant_nodes.append(node)

            state = node.state

            if state and state.lower() == "failed":
                states["Failed"] = states.get("Failed", 0) + 1
                if name not in self.failed_node_names:
                    newly_failed_node_names.append(name)
                    if not is_dynamic:
                        slutil.scontrol(["update", f"NodeName={name}", f"NodeAddr={name}", f"NodeHostName={name}"])
                    self.failed_node_names.add(name)

                continue

            use_nodename_as_hostname = node.software_configuration.get("slurm", {}).get(
                "use_nodename_as_hostname", False
            )
            if not use_nodename_as_hostname and not is_dynamic:
                ip_already_set_key = (name, node.private_ip)
                if node.private_ip and ip_already_set_key not in self.ip_already_set:
                    slutil.scontrol(
                        [
                            "update",
                            "NodeName=%s" % name,
                            "NodeAddr=%s" % node.private_ip,
                            "NodeHostName=%s" % node.private_ip,
                        ]
                    )
                    self.ip_already_set.add(ip_already_set_key)

            if name in self.failed_node_names:
                recovered_node_names.add(name)

            if node.target_state != "Started":
                states["UNKNOWN"] = states.get("UNKNOWN", {})
                states["UNKNOWN"][node.state] = states["UNKNOWN"].get(state, 0) + 1
                continue

            if node.state == "Ready":
                if not node.private_ip:
                    state = "WaitingOnIPAddress"
                else:
                    ready_nodes.append(node)

            states[state] = states.get(state, 0) + 1

        if newly_failed_node_names:
            failed_node_names_str = ",".join(self.failed_node_names)
            try:
                logging.error(
                    "The following nodes failed to start: %s", failed_node_names_str
                )
                for failed_name in self.failed_node_names:
                    slutil.scontrol(
                        [
                            "update",
                            "NodeName=%s" % failed_name,
                            "State=down",
                            "Reason=cyclecloud_node_failure",
                        ]
                    )
            except Exception:
                logging.exception(
                    "Failed to mark the following nodes as down: %s. Will re-attempt next iteration.",
                    failed_node_names_str,
                )

        if recovered_node_names:
            recovered_node_names_str = ",".join(recovered_node_names)
            try:
                for recovered_name in recovered_node_names:
                    logging.error(
                        "The following nodes have recovered from failure: %s",
                        recovered_node_names_str,
                    )
                    if not is_dynamic:
                        slutil.scontrol(
                            [
                                "update",
                                "NodeName=%s" % recovered_name,
                                "State=idle",
                                "Reason=cyclecloud_node_recovery",
                            ]
                        )
                    if recovered_name in self.failed_node_names:
                        self.failed_node_names.remove(recovered_name)
            except Exception:
                logging.exception(
                    "Failed to mark the following nodes as recovered: %s. Will re-attempt next iteration.",
                    recovered_node_names_str,
                )

        return (states, ready_nodes)


def wait_for_resume(
    config: Dict,
    operation_id: str,
    node_list: List[str],
    get_latest_nodes: Callable[[], List[Node]],
    waiter: "WaitForResume" = WaitForResume(),
) -> None:
    previous_states = {}

    nodes_str = ",".join(node_list[:5])
    omega = clock.time() + 3600

    ready_nodes: List[Node] = []

    while clock.time() < omega:
        states, ready_nodes = waiter.check_nodes(node_list, get_latest_nodes())
        terminal_states = (
            states.get("Ready", 0)
            + sum(states.get("UNKNOWN", {}).values())
            + states.get("Failed", 0)
        )

        if states != previous_states:
            states_messages = []
            for key in sorted(states.keys()):
                if key != "UNKNOWN":
                    states_messages.append("{}={}".format(key, states[key]))
                else:
                    for ukey in sorted(states["UNKNOWN"].keys()):
                        states_messages.append(
                            "{}={}".format(ukey, states["UNKNOWN"][ukey])
                        )

            states_message = " , ".join(states_messages)
            logging.info(
                "OperationId=%s NodeList=%s: Number of nodes in each state: %s",
                operation_id,
                nodes_str,
                states_message,
            )

        if terminal_states == len(node_list):
            break

        previous_states = states
        clock.sleep(5)

    logging.info(
        "The following nodes reached Ready state: %s",
        ",".join([x.name for x in ready_nodes]),
    )
    for node in ready_nodes:
        if not hpcutil.is_valid_hostname(config, node):
            continue
        is_dynamic = node.software_configuration.get("slurm", {}).get("dynamic_config")
        if is_dynamic:
            continue
        slutil.scontrol(
            [
                "update",
                "NodeName=%s" % node.name,
                "NodeAddr=%s" % node.private_ip,
                "NodeHostName=%s" % node.hostname,
            ]
        )

    logging.info(
        "OperationId=%s NodeList=%s: all nodes updated with the proper IP address. Exiting",
        operation_id,
        nodes_str,
    )
    