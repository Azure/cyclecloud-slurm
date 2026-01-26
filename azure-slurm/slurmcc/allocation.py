# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
import logging
import shutil
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
        raise AzureSlurmError(f"Unknown node name(s): {','.join(unknown_node_names)}")
    
    for name in node_list:
        if name in existing_nodes_by_name:
            node = existing_nodes_by_name[name][0]
            if node.state != "Deallocated":
                logging.info("%s already exists.", name)
                continue

        if name not in name_to_partition:    
            raise AzureSlurmError(
                f"Unknown node name: {name}: {list(name_to_partition.keys())}"
            )
        partition = name_to_partition[name]
        bucket = partition.bucket_for_node(name)

        def make_name_hook(name: str) -> Callable[[NodeBucket, int], str]:
            def name_hook(bucket: NodeBucket, index: int) -> str:
                if index != 1:
                    raise RuntimeError(f"Could not create node with name {name}. Perhaps the node already exists in a terminating state?")
                return name
            return name_hook

        node_mgr.set_node_name_hook(make_name_hook(name))
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
    waiting_for_nodes: List[str] = []
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
        logging.info("Waiting for nodes to terminate: %s", waiting_for_nodes)
        clock.sleep(5)
    raise AzureSlurmError(f"Timed out waiting for nodes to terminate: {waiting_for_nodes}")


class SuspendExcNodesSerializer:
    def __init__(self, keep_alive_conf_path: str) -> None:
        self.keep_alive_conf_path = keep_alive_conf_path
        self.last_suspend_exc_nodes: Tuple[str, Set[str]] = ("", set())

    def serialize_keep_alive(self) -> Set[str]:
        # parse existing SuspendExcNodes and serialize it out to keep_alive.conf
        # note: this should not be required, but slurm's ReconfigFlags are not respecting
        # this.
        # Only write this out if we are out of date. For simplicity, we will always write this out 
        # on first startup of azslurmd.
        for raw_line in slutil.scontrol(["show", "config"]).splitlines():
            if raw_line.startswith("SuspendExcNodes"):
                if "(null)" in raw_line:
                    raw_line = "# SuspendExcNodes ="
                if raw_line != self.last_suspend_exc_nodes[0]:
                    logging.info("KeepAlive: Updating %s:", self.keep_alive_conf_path)
                    logging.info("KeepAlive: Old: %s", self.last_suspend_exc_nodes[0])
                    logging.info("KeepAlive: New: %s", raw_line)
                    # safe write then move, to avoid partial writes
                    with open(self.keep_alive_conf_path + ".tmp", "w") as fw:
                        fw.write("# Managed by azslurmd\n")
                        fw.write(raw_line)
                    shutil.move(self.keep_alive_conf_path + ".tmp", self.keep_alive_conf_path)
                    _, value = raw_line.split("=")
                    node_list = set(slutil.from_hostlist(value))
                    # save the last raw_line and the parsed node_list
                    self.last_suspend_exc_nodes = (raw_line, node_list)
        return self.last_suspend_exc_nodes[1]


class SlurmNodes:
    def __init__(self, suspend_exc_nodes_slzr: SuspendExcNodesSerializer) -> None:
        self.__nodes: Dict[str, Dict] = []
        self.suspend_exc_nodes_slzr = suspend_exc_nodes_slzr
        self.__suspend_exc_nodes: Set[str] = set()
        self.__active_suspend_exc_nodes: Set[str] = set()
        self.refresh()

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
            and self.__nodes[name].get("Reason") in ["cyclecloud_no_node", "cyclecloud_zombie_node"]
        )
    
    def has_zombie_reason(self, name: str) -> bool:
        return self.__nodes[name].get("Reason") in ["cyclecloud_zombie_node"]
    
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

    def mark_missing_in_cyclecloud(self, name: str) -> None:
        if try_scontrol(
            [
                "update",
                f"NodeName={name}",
                f"NodeAddr={name}",
                f"NodeHostName={name}",
                "State=down",
                "Reason=cyclecloud_no_node",
            ]
        ):
            # update internally
            self.__nodes[name]["State"] = "down"
            self.__nodes[name]["Reason"] = "cyclecloud_no_node"
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

    def _mark_active_suspend(self, name: str) -> None:
        if name not in self.__active_suspend_exc_nodes:
            logging.info("Node %s has KeepAlive", name)
            self.__active_suspend_exc_nodes.add(name)
        
    def _unmark_active_suspend(self, name: str) -> None:
        if name in self.__active_suspend_exc_nodes:
            logging.info("Node %s no longer has KeepAlive", name)
            self.__active_suspend_exc_nodes.remove(name)

    def _is_active_suspend(self, name: str) -> bool:
        """ Returns true if we have seen KeepAlive=true on this node"""
        return name in self.__active_suspend_exc_nodes
    
    def is_suspend_exc(self, name: str) -> bool:
        return name in self.__suspend_exc_nodes
    
    def suspend_exc_node(self, name: str) -> None:
        if not self.is_suspend_exc(name):
            logging.info("Adding %s to SuspendExcNodes", name)
            slutil.update_suspend_exc_nodes("add", name)
            self.__suspend_exc_nodes.add(name)
        self._mark_active_suspend(name)

    def unsuspend_exc_node(self, name: str) -> None:
        if self.is_suspend_exc(name):
            if self._is_active_suspend(name):
                logging.info("Removing %s from SuspendExcNodes", name)
                slutil.update_suspend_exc_nodes("remove", name)
                self.__suspend_exc_nodes.remove(name)
                self._unmark_active_suspend(name)
            else:
                logging.info("Node %s will remain in SuspendExcNodes, as no history of KeepAlive in CycleCloud found.", name)

    def refresh(self) -> None:
        self.__nodes = hpcutil.partition_single(
            slutil.show_nodes([]), lambda node: node["NodeName"]
        )
        self.__suspend_exc_nodes = self.suspend_exc_nodes_slzr.serialize_keep_alive()


def try_scontrol(args: List[str]) -> bool:
    try:
        logging.info(" ".join(args))
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

        unexpected_nodes = cc_nodes.keys() - set(list(slurm_nodes))
        if unexpected_nodes:
            logging.warning("Unexpected nodes found in CycleCloud - will these be joining as dynamic nodes? %s", ",".join(list(unexpected_nodes)))

        ready_nodes = []

        by_status = hpcutil.partition(cyclecloud_nodes, lambda node: node.state)
        states_message = []
        for state, nodes in sorted(by_status.items(), key=lambda key: key[0]):
            if state != "Ready":
                states_message.append(f"{state}={len(nodes)}:{','.join(x.name for x in nodes)}")
            else:
                states_message.append(f"Ready={len(nodes)}")
        logging.info("Converging nodes with the following states: %s", ", ".join(states_message))

        for name in slurm_nodes:
            if slurm_nodes.reason(name) in ["cyclecloud_no_node", "cyclecloud_zombie_node"]:
                if slurm_nodes.is_idle(name) and slurm_nodes.is_powered_down(name):
                    logging.info("Unsetting old reason for node=%s", name)
                    slurm_nodes.unset_reason(name)
                    continue
            node = cc_nodes.get(name)

            if not node:
                if slurm_nodes.is_joined(name):
                    logging.warning("Node %s not found in CycleCloud, but slurm thinks it does exist.", name)
                    logging.warning("Marking node %s down in slurm.", name)
                    slurm_nodes.mark_missing_in_cyclecloud(name)
                    continue
                else:
                    # typical case - node is in neither CC or slurm
                    # just make sure we clean up zombie reason codes here.
                    # TODO should we unset all reason codes here?
                    if slurm_nodes.has_zombie_reason(name):
                        logging.info("Removing Reason=cyclecloud_zombie_node from %s. Node no longer exists in CycleCloud", name)
                        slurm_nodes.unset_reason(name)
                    continue
            
            # slurm node has an internal cache of this information, so this is only called once.
            if node.keep_alive:
                slurm_nodes.suspend_exc_node(name)
            else:
                slurm_nodes.unsuspend_exc_node(name)

            if node.state == "Ready" and not slurm_nodes.is_joined(name):
                if not slurm_nodes.is_powering_up(name) and not slurm_nodes.is_down_by_cyclecloud(name):
                    logging.warning("Node %s is off in slurm, but cyclecloud does have a node.", name)
                    logging.warning("Marking node %s down (zombie) in slurm. To fix this, please try one of the following:", name)
                    logging.warning("    - scontrol update nodename=%s state=power_down - to tell slurm to power this node down again", name)
                    logging.warning("    - azslurm suspend --node-list %s", name)
                    logging.warning("    - Or simply terminate the node %s from the CycleCloud UI", name)
                    slurm_nodes.mark_down_as_zombie(name)
                # Bail out here. Either the node is still powering up, or the node is a zombie.
                continue

            # the above continue means that all nodes from here on out should never be in a zombie state.
            if slurm_nodes.has_zombie_reason(name):
                logging.info("Removing Reason=cyclecloud_zombie_node from %s. CycleCloud State=%s Slurm State=%s", 
                             name, node.state, "+".join(list(slurm_nodes.states(name))))
                slurm_nodes.unset_reason(name)

            state = node.state or "UNKNOWN"

            if state.lower() == "failed":
                # don't mark nodes down that have already joined, as health events will cause nodes to 
                # be in a failed state, but should handle putting them in drain.
                # if not slurm_nodes.is_joined(name) and not slurm_nodes.is_down(name):
                #     slurm_nodes.mark_down_by_cyclecloud(name)
                logging.warning("Node %s is in a failed state. Ignoring", name)
                continue

            use_nodename_as_hostname = node.software_configuration.get("slurm", {}).get(
                "use_nodename_as_hostname", False
            )

            if slurm_nodes.is_down_by_cyclecloud(name):
                slurm_nodes.recover_node(name)

            if state == "Ready":
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
        sys.exit(0)

    nodes = SlurmNodes(sys.argv[2:], [])
    for node in nodes:
        print(node, getattr(nodes, sys.argv[1])(node))

if __name__ == "__main__":
    main()