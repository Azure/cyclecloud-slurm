# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
import logging
from typing import Callable, Dict, Iterator, List, Set, Tuple

from hpc.autoscale import util as hpcutil
from hpc.autoscale import clock
from hpc.autoscale.ccbindings import ClusterBindingInterface
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
    for partition in partitions:
        for name in partition.all_nodes():
            name_to_partition[name] = partition
    
    existing_nodes_by_name = hpcutil.partition(node_mgr.get_nodes(), lambda n: n.name)

    nodes = []
    unknown_node_names = []
    for name in node_list:
        if name not in name_to_partition:
            unknown_node_names.append(name)

    if unknown_node_names:
        raise AzureSlurmError("Unknown node name(s): %s" % ",".join(unknown_node_names))
    
    for name in node_list:
        if name in existing_nodes_by_name:
            node = existing_nodes_by_name[name][0]
            if node.state != "Deallocated":
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


def wait_for_nodes_to_terminate(
    bindings: ClusterBindingInterface, node_list: List[str]
) -> None:
    attempts = 1800 / 5
    waiting_for_nodes = []
    while attempts > 0:
        attempts -= 1
        waiting_for_nodes = []
        cc_by_name = hpcutil.partition_single(bindings.get_nodes().nodes, lambda n: n["Name"])

        for name in node_list:
            if name in cc_by_name:
                cc_node = cc_by_name[name]
                target_state = cc_node.get("TargetState") or "undefined"
                status = cc_node.get("Status") or "undefined"
                is_booting = target_state == "Started"
                reached_final_state = target_state == status
                if is_booting or reached_final_state:
                    continue
                waiting_for_nodes.append(name)
        if not waiting_for_nodes:
            logging.info("All nodes are available to be started.")
            return
        logging.info(f"Waiting for nodes to terminate: {waiting_for_nodes}")
        clock.sleep(5)
    raise AzureSlurmError(f"Timed out waiting for nodes to terminate: {waiting_for_nodes}")


class SlurmNodes:
    def __init__(self, node_list: List[str]) -> None:
        self.__nodes = hpcutil.partition_single(
            slutil.show_nodes(node_list), lambda node: node["NodeName"]
        )

    def __iter__(self) -> Iterator[str]:
        return iter(self.__nodes.keys())
    
    def states(self, name: str) -> Set[str]:
        return set(self.__nodes[name]["State"].lower().split("+"))

    def is_idle(self, name: str) -> bool:
        return "idle" in self.states(name)
    
    def is_powered_down(self, name: str) -> bool:
        return "powered_down" in self.states(name)
    
    def is_down(self, name: str) -> bool:
        return "down" in self.states(name)
    
    def is_powering_up(self, name: str) -> bool:
        return bool(self.states(name).intersection(set(["powering_up"])))

    def reason(self, name: str) -> str:
        return self.__nodes[name].get("Reason", "").strip()

    def unset_reason(self, name: str) -> None:
        if try_scontrol(["update", f"NodeName={name}", "Reason=(null)"]):
            # update internally
            self.__nodes[name]["Reason"] = ""

    def is_down_by_cyclecloud(self, name: str) -> bool:
        return (
            self.is_down(name)
            and self.__nodes[name].get("Reason") in ["cyclecloud_node_failure", "cyclecloud_zombie_node"]
        )
    
    def is_joined(self, name: str) -> bool:
        return not bool(self.states(name).intersection(set(["powered_down", "powering_down", "powering_up"])))

    def mark_down_as_zombie(self, name: str) -> None:
        if try_scontrol(
            [
                "update",
                f"NodeName={name}",
                f"NodeAddr={name}",
                f"NodeHostName={name}",
                "State=down",
                "Reason=cyclecloud_zombie_node",
            ]
        ):
            # update internally
            self.__nodes[name]["State"] = "down"
            self.__nodes[name]["Reason"] = "cyclecloud_zombie_node"
            self.__nodes[name]["NodeAddr"] = name
            self.__nodes[name]["NodeHostName"] = name

    def mark_down_by_cyclecloud(self, name: str) -> None:
        if try_scontrol(
            [
                "update",
                f"NodeName={name}",
                f"NodeAddr={name}",
                f"NodeHostName={name}",
                "State=down",
                "Reason=cyclecloud_node_failure",
            ]
        ):
            # update internally
            self.__nodes[name]["State"] = "down"
            self.__nodes[name]["Reason"] = "cyclecloud_node_failure"
            self.__nodes[name]["NodeAddr"] = name
            self.__nodes[name]["NodeHostName"] = name

    def recover_node(self, name: str) -> None:
        assert self.is_down_by_cyclecloud(name)
        cmd = [
            "update",
            f"NodeName={name}",
            "State=idle",
            "Reason=(null)",
        ]
        if try_scontrol(cmd):
            # update internally
            self.__nodes[name]["State"] = "idle"
            self.__nodes[name]["Reason"] = ""

    def has_ip(self, name: str) -> bool:
        return (
            self.__nodes[name]["NodeAddr"] != name
            and self.__nodes[name]["NodeHostName"] != name
        )

    def set_ip(self, name: str, ip: str) -> None:
        if ip == name:
            return
        if self.__nodes[name]["NodeAddr"] == ip:
            if self.__nodes[name]["NodeHostName"] == ip:
                return

        if try_scontrol(
            ["update", f"NodeName={name}", f"NodeAddr={ip}", f"NodeHostName={ip}"]
        ):
            # update internally
            self.__nodes[name]["NodeAddr"] = ip
            self.__nodes[name]["NodeHostName"] = ip


def try_scontrol(args: List[str]) -> bool:
    try:
        slutil.scontrol(args)
        return True
    except Exception as e:
        logging.error("Failed to run scontrol %s: %s", args, e)
        return False


class SyncNodes:

    def sync_nodes(
        self, slurm_nodes: SlurmNodes, cyclecloud_nodes: List[Node]
    ) -> Tuple[Dict, List[Node]]:
        states = {}
        cc_nodes = hpcutil.partition_single(cyclecloud_nodes, lambda node: node.name)

        ready_nodes = []

        logging.info("Converging the following node names %s", list(slurm_nodes))

        for name in slurm_nodes:
            if slurm_nodes.reason(name) in ["cyclecloud_node_failure", "cyclecloud_zombie_node"]:
                if slurm_nodes.is_idle(name) and slurm_nodes.is_powered_down(name):
                    logging.info("Unsetting old reason", name)
                    slurm_nodes.unset_reason(name)
                    continue
            node = cc_nodes.get(name)

            if not node:
                if slurm_nodes.is_joined(name):
                    logging.warning("Node %s not found in CycleCloud, but slurm thinks it does exist.", name)
                    logging.warning("Marking node %s down in slurm.", name)
                    slurm_nodes.mark_down_by_cyclecloud(name)
                    continue
                else:
                    # typical case - node is in neither CC or slurm
                    continue

            if node.state == "Ready" and not slurm_nodes.is_joined(name):
                if not slurm_nodes.is_powering_up(name) and not slurm_nodes.is_down_by_cyclecloud(name):
                    logging.warning("Node %s is off in slurm, but cyclecloud does have a node.", name)
                    logging.warning("Marking node %s down (zombie) in slurm. To fix this, please try one of the following:", name)
                    logging.warning("    - scontrol update nodename=%s state=power_down - to tell slurm to power this node down again", name)
                    logging.warning("    - azslurm suspend --node-list %s", name)
                    logging.warning("    - Or simply terminate the node %s from the CycleCloud UI", name)
                    slurm_nodes.mark_down_as_zombie(name)

                continue

            state = node.state or "UNKNOWN"

            if state.lower() == "failed":
                if not slurm_nodes.is_down(name):
                    slurm_nodes.mark_down_by_cyclecloud(name)
                continue

            use_nodename_as_hostname = node.software_configuration.get("slurm", {}).get(
                "use_nodename_as_hostname", False
            )

            if not use_nodename_as_hostname:
                if node.private_ip:
                    slurm_nodes.set_ip(name, node.private_ip)

            if slurm_nodes.is_down_by_cyclecloud(name):
                slurm_nodes.recover_node(name)

            if state == "Ready":
                if not node.private_ip:
                    state = "WaitingOnIPAddress"
                else:
                    ready_nodes.append(node)

            states[state] = states.get(state, 0) + 1

        return (states, ready_nodes)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )
    logging.info("Starting azslurmd in the foreground")
    # azslurmd()
    import sys

    if "-h" in sys.argv or "--help" in sys.argv:
        print("Usage: azslurm.py <command> <node>")
        print("Commands:")
        print("  is_down <node>+")
        print("  reason <node>+")
        print("  is_down_by_cyclecloud <node>+")
        print("  is_joined <node>+")
        print("  mark_down_by_cyclecloud <node>+")
        print("  recover_node <node>+")
        print("  has_ip <node>+")
        sys.exit(0)

    nodes = SlurmNodes(sys.argv[2:])
    for node in nodes:
        print(node, getattr(nodes, sys.argv[1])(node))

if __name__ == "__main__":
    main()