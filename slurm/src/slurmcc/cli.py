# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
import argparse
import logging
import os
import sys
import traceback
import time
from argparse import ArgumentParser
from math import ceil, floor
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, TextIO, Union

from hpc.autoscale.cli import GenericDriver
from hpc.autoscale.clilib import (
    CommonCLI,
    ShellDict,
    disablecommand,
    main as clilibmain,
)
from hpc.autoscale.hpctypes import Memory
from hpc.autoscale import util as hpcutil
from hpc.autoscale.job.demandprinter import OutputFormat
from hpc.autoscale.job.driver import SchedulerDriver
from hpc.autoscale.node.bucket import NodeBucket

from hpc.autoscale.node.nodemanager import NodeManager
from hpc.autoscale.node.node import Node

from . import partition as partitionlib
from . import util as slutil
from . import CyclecloudSlurmError
from hpc.autoscale.results import AllocationResult

from hpc.autoscale.ccbindings import cluster_service_client as csc


def csv_list(x: str) -> List[str]:
    # used in argument parsing
    return [x.strip() for x in x.split(",")]


class SlurmDriver(GenericDriver):
    def __init__(self) -> None:
        super().__init__("slurm")
    
    def preprocess_node_mgr(self, config: Dict, node_mgr: NodeManager) -> None:
        def default_dampened_memory(node: Node) -> Memory:
            return min(node.memory - Memory.value_of("1g"), node.memory * 0.95)

        node_mgr.add_default_resource(
            selection={},
            resource_name="slurm_memory",
            default_value=default_dampened_memory,
        )

        for b in node_mgr.get_buckets():
            if "nodearrays" not in config:
                config["nodearrays"] = {}
            if b.nodearray not in config["nodearrays"]:
                config["nodearrays"][b.nodearray] = {}
            # TODO remove
            config["nodearrays"][b.nodearray]["generated_placement_group_buffer"] = 1
            if "generated_placement_group_buffer" in config["nodearrays"][b.nodearray]:
                continue
            is_hpc = (
                str(
                    b.software_configuration.get("slurm", {}).get("hpc") or "false"
                ).lower()
                == "true"
            )
            if is_hpc:
                buffer = ceil(b.limits.max_count / b.max_placement_group_size)
            else:
                buffer = 0
            config["nodearrays"][b.nodearray][
                "generated_placement_group_buffer"
            ] = buffer
        super().preprocess_node_mgr(config, node_mgr)


class SlurmCLI(CommonCLI):
    def __init__(self) -> None:
        super().__init__(project_name="slurm")
        self.slurm_node_names = []

    def _add_completion_data(self, completion_json: Dict) -> None:
        node_names = slutil.check_output(["sinfo", "-N", "-h", "-o", "%N"]).splitlines(
            keepends=False
        )
        node_lists = slutil.check_output(["sinfo", "-h", "-o", "%N"]).strip().split(",")
        completion_json["slurm_node_names"] = node_names + node_lists

    def _read_completion_data(self, completion_json: Dict) -> None:
        self.slurm_node_names = completion_json.get("slurm_node_names", [])

    def _slurm_node_name_completer(
        self,
        prefix: str,
        action: argparse.Action,
        parser: ArgumentParser,
        parsed_args: argparse.Namespace,
    ) -> List[str]:
        self._get_example_nodes(parsed_args.config)
        output_prefix = ""
        if prefix.endswith(","):
            output_prefix = prefix
        return [output_prefix + x + "," for x in self.slurm_node_names]

    def _pool_parser(self, parser: ArgumentParser) -> None:
        parser.add_argument("-n", "--name", type=str, required=True)
        parser.add_argument("-P", "--partition", type=str, required=False)
        parser.add_argument(  # type: ignore
            "-v", "--vm-size", required=False
        ).completer = self._all_vm_size_completer  # type: ignore
        parser.add_argument("-N", "--max-nodes", type=int, required=False, default=-1)
        parser.add_argument("-C", "--max-cores", type=int, required=False, default=-1)
        parser.add_argument(
            "-A", "--autoscale", type=bool, required=False, default=True
        )
        parser.add_argument(
            "-S", "--spot", action="store_true", required=False, default=False
        )
        parser.add_argument(
            "-K", "--keep-alive", type=bool, required=False, default=False,
        )
        parser.add_argument(
            "--vmss-definition", type=str, required=False, default="default"
        )
        parser.add_argument("-R", "--region", required=True)
        parser.add_argument("--base-name", required=True)

    def add_pool_parser(self, parser: ArgumentParser) -> None:
        self._pool_parser(parser)

    def add_pool(
        self,
        config: Dict,
        name: str,
        region: str,
        partition: str,
        vm_size: str,
        base_name: str = "",
        max_nodes: int = -1,
        max_cores: int = -1,
        autoscale: bool = True,
        spot: bool = False,
        keep_alive: bool = False,
        vmss_definition: str = "default",
    ):
        """
        azslurm add_pool --name name --vm-sizes
        """
        from hpc.autoscale.node import vm_sizes as vmlib
        partition = partition or name
        aux_info = vmlib.get_aux_vm_size_info(region, vm_size)
    
        vm = csc.VirtualMachine(
            vm_size=vm_size,
            vcpu_count=aux_info.vcpu_count,
            pcpu_count=aux_info.pcpu_count,
            gpu_count=aux_info.gpu_count,
            infiniband=aux_info.infiniband,
            memory_gb=aux_info.memory.value,
        )
        configuration = csc.PoolConfiguration(
            base_name=base_name,
            max_count=max_nodes,
            virtual_machine=vm,
            max_core_count=max_cores,
            placement_group="pg0",
            placement_group_attribute="placement_group",
            max_placement_group_size=100,
            spot=spot,
            autoscale=autoscale,
            keep_alive=keep_alive,
            vmss_definition="",
            user_data={},
        )

        self._get_node_manager(config).add_pool(name, configuration)

    def delete_pool_parser(self, parser: ArgumentParser) -> None:
        parser.add_argument("-n", "--name", type=str, required=True)

    def delete_pool(self, config: Dict, name: str) -> None:
        properties = csc.RemovePoolRequestMessage(
            cluster_id=config["cluster_name"],
            pool_name=name,
        )

        self._get_node_manager(config).delete_pool(properties)
    
    def update_pool_parser(self, parser: ArgumentParser) -> None:
        self._pool_parser(parser)
        # parser.add_argument(  # type: ignore
        #     "-V", "--add-vm-sizes", type=csv_list, required=False
        # ).completer = self._all_vm_size_completer  # type: ignore
        # parser.add_argument(  # type: ignore
        #     "-R", "--remove-vm-sizes", type=csv_list, required=False
        # ).completer = self._all_vm_size_completer  # type: ignore

    def update_pool(
        self,
        config: Dict,
        name: str,
        vm_sizes: List[str],
        add_vm_sizes: List[str],
        remove_vm_sizes: List[str],
        max_nodes: int = -1,
        max_cores: int = -1,
        autoscale: bool = True,
    ):
        print(
            f"Updating {name} in {config['cluster_name']}"
        )
        
        if vm_sizes and (add_vm_sizes or remove_vm_sizes):
            raise RuntimeError("You may only pick --vm-sizes OR --add-vm-sizes/--remove-vm-sizes!")

        if add_vm_sizes:
            print(f"Adding VM Size(s) {','.join(add_vm_sizes)}")

        if remove_vm_sizes:
            print(f"Removing VM Size(s) {','.join(add_vm_sizes)}")
        if vm_sizes:
            print(f"Setting VM Size(s) to {','.join(add_vm_sizes)}")

        if max_cores > 0:
            print(f"Maximum cores set to {max_cores}")
        elif max_nodes > 0:
            print(f"Maximum nodes set to {max_cores}")
        
        if autoscale:
            print(f"Setting autoscale to {autoscale}")

    def generate_slurm_conf_parser(self, parser: ArgumentParser) -> None:
        parser.add_argument("--allow-empty", action="store_true", default=False)

    def generate_slurm_conf(self, config: Dict, allow_empty: bool = False) -> None:
        node_mgr = self._get_node_manager(config)
        partitions = partitionlib.fetch_partitions(node_mgr)  # type: ignore
        _generate_slurm_conf(
            partitions,
            sys.stdout,
            allow_empty=allow_empty,
            autoscale=config.get("autoscale", True),
        )

    def generate_topology(self, config: Dict) -> None:
        return _generate_topology(self._get_node_manager(config), sys.stdout)

    def resume_parser(self, parser: ArgumentParser) -> None:
        parser.set_defaults(read_only=False)
        parser.add_argument(
            "--node-list", type=hostlist, required=True
        ).completer = self._slurm_node_name_completer  # type: ignore
        parser.add_argument("--no-wait", action="store_true", default=False)

    def resume(self, config: Dict, node_list: List[str], no_wait: bool = False) -> None:
        node_mgr = self._get_node_manager(config)
        partitions = partitionlib.fetch_partitions(node_mgr)
        return self._resume(config, node_mgr, node_list, partitions, no_wait)

    def _resume(
        self,
        config: Dict,
        node_mgr: NodeManager,
        node_list: List[str],
        partitions: Dict[str, partitionlib.Partition],
        no_wait: bool = False,
    ) -> None:
        name_to_partition = {}
        for partition in partitions.values():
            for name in partition.all_nodes():
                name_to_partition[name] = partition

        nodes = []
        for name in node_list:
            if name not in name_to_partition:
                raise CyclecloudSlurmError(
                    f"Unknown node name: {name}: {list(name_to_partition.keys())}"
                )
            partition = name_to_partition[name]
            bucket = partition.bucket_for_node(name)

            def name_hook(bucket: NodeBucket, index: int) -> str:
                if index != 1:
                    raise RuntimeError(f"Unexpected index: {index}")
                return name

            node_mgr.set_node_name_hook(name_hook)
            result: AllocationResult = node_mgr.allocate(
                {"node.bucket_id": bucket.bucket_id, "exclusive": True}, node_count=1
            )
            if len(result.nodes) != 1:
                raise RuntimeError()
            result.nodes[0].name_format = name
            nodes.extend(result.nodes)
        boot_result = node_mgr.bootup(nodes)

        if not no_wait:
            self._wait_for_resume(config, boot_result.operation_id, node_list)

    def wait_for_resume_parser(self, parser: ArgumentParser) -> None:
        parser.set_defaults(read_only=False)
        parser.add_argument(
            "--node-list", type=hostlist, required=True
        ).completer = self._slurm_node_name_completer  # type: ignore

    def wait_for_resume(self, config: Dict, node_list: List[str]) -> None:
        self._wait_for_resume(config, "noop", node_list)

    def _shutdown(self, node_list: List[str], node_mgr: NodeManager) -> None:
        nodes = _as_nodes(node_list, node_mgr)
        _retry_rest(lambda: node_mgr.shutdown_nodes(nodes))

    def shutdown_parser(self, parser: ArgumentParser) -> None:
        parser.set_defaults(read_only=False)
        parser.add_argument(
            "--node-list", type=hostlist, required=True
        ).completer = self._slurm_node_name_completer  # type: ignore

    def shutdown(self, config: Dict, node_list: List[str], drain_timeout: int = 300):
        for node in node_list:
            cmd = [
                "scontrol",
                "update",
                "NodeName=%s" % node,
                "State=Drain",
                "Reason=cyclecloud: shutting down",
            ]
            logging.info("Running %s", " ".join(cmd))
            _retry_subprocess(lambda: slutil.check_output(cmd))

        def get_drained_nodes() -> List[str]:
            args = ["sinfo", "-h", "-t", "DRAINED", "-O", "nodelist"]
            return _retry_subprocess(lambda: slutil.check_output(args)).split()

        start_time = time.time()

        def is_timedout() -> bool:
            if drain_timeout < 0:
                return False
            omega = start_time + drain_timeout
            return time.time() > omega

        expected = set(node_list)
        while not is_timedout():
            actual = set(get_drained_nodes())
            still_draining = expected - actual
            if not still_draining:
                break
            time.sleep(1)

        for node in node_list:
            cmd = [
                "scontrol",
                "update",
                "NodeName=%s" % node,
                "NodeAddr=%s" % node,
                "NodeHostName=%s" % node,
            ]
            if not config.get("autoscale", True):
                cmd += ["State=FUTURE"]
            logging.info("Running %s", " ".join(cmd))
            _retry_subprocess(lambda: slutil.check_output(cmd))
        return self._shutdown(node_list, self._node_mgr(config))

    def _get_node_manager(self, config: Dict, force: bool = False) -> NodeManager:
        return self._node_mgr(config, self._driver(config), force=force)

    def _setup_shell_locals(self, config: Dict) -> Dict:
        # TODO
        shell = {}
        partitions = partitionlib.fetch_partitions(self._get_node_manager(config))  # type: ignore
        shell["partitions"] = ShellDict(partitions)
        shell["node_mgr"] = node_mgr = self._get_node_manager(config)
        nodes = {}
        
        for node in node_mgr.get_nodes():
            node.shellify()
            nodes[node.name] = node
            if node.hostname:
                nodes[node.hostname] = node
        shell["nodes"] = ShellDict(nodes)

        def slurmhelp() -> None:
            def _print(key: str, desc: str) -> None:
                print("%-20s %s" % (key, desc))

            _print("partitions", "partition information")
            _print("node_mgr", "NodeManager")
            _print("nodes", "Current nodes according to the provider. May include nodes that have not joined yet.")

        shell["slurmhelp"] = slurmhelp
        return shell

    def _driver(self, config: Dict) -> SchedulerDriver:
        return SlurmDriver()

    def _default_output_columns(
        self, config: Dict, cmd: Optional[str] = None
    ) -> List[str]:
        # TODO
        return ["name", "status"]

    def _initconfig_parser(self, parser: ArgumentParser) -> None:
        # TODO
        ...

    def _initconfig(self, config: Dict) -> None:
        # TODO
        ...

    @disablecommand
    def analyze(self, config: Dict, job_id: str, long: bool = False) -> None:
        ...

    @disablecommand
    def validate_constraint(
        self,
        config: Dict,
        constraint_expr: List[str],
        writer: TextIO = sys.stdout,
        quiet: bool = False,
    ) -> Union[List, Dict]:
        return super().validate_constraint(
            config, constraint_expr, writer=writer, quiet=quiet
        )

    @disablecommand
    def join_nodes(
        self, config: Dict, hostnames: List[str], node_names: List[str]
    ) -> None:
        return super().join_nodes(config, hostnames, node_names)

    @disablecommand
    def jobs(self, config: Dict) -> None:
        return super().jobs(config)

    @disablecommand
    def demand(
        self,
        config: Dict,
        output_columns: Optional[List[str]],
        output_format: OutputFormat,
        long: bool = False,
    ) -> None:
        return super().demand(config, output_columns, output_format, long=long)

    @disablecommand
    def autoscale(
        self,
        config: Dict,
        output_columns: Optional[List[str]],
        output_format: OutputFormat,
        dry_run: bool = False,
        long: bool = False,
    ) -> None:
        return super().autoscale(
            config, output_columns, output_format, dry_run=dry_run, long=long
        )

    def _wait_for_resume(
        self,
        config: Dict,
        operation_id: str,
        node_list: List[str],
    ) -> None:
        previous_states = {}

        nodes_str = ",".join(node_list[:5])
        omega = time.time() + 3600

        failed_node_names: Set[str] = set()

        ready_nodes: List[Node] = []

        while time.time() < omega:
            ready_nodes = []
            states = {}

            node_mgr = self._get_node_manager(config, force=True)
            nodes = _retry_rest(lambda: node_mgr.get_nodes())

            by_name = hpcutil.partition_single(nodes, lambda node: node.name)

            relevant_nodes: List[Node] = []

            recovered_node_names: Set[str] = set()

            newly_failed_node_names: List[str] = []

            deleted_nodes = []

            for name in node_list:
                node = by_name.get(name)
                if not node:
                    deleted_nodes.append(node)
                    continue

                relevant_nodes.append(node)

                state = node.state

                if state and state.lower() == "failed":
                    states["Failed"] = states.get("Failed", 0) + 1
                    if name not in failed_node_names:
                        newly_failed_node_names.append(name)
                        failed_node_names.add(name)

                    continue

                if name in failed_node_names:
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
                failed_node_names_str = ",".join(failed_node_names)
                try:
                    logging.error(
                        "The following nodes failed to start: %s", failed_node_names_str
                    )
                    for failed_name in failed_node_names:
                        cmd = [
                            "scontrol",
                            "update",
                            "NodeName=%s" % failed_name,
                            "State=down",
                            "Reason=cyclecloud_node_failure",
                        ]
                        logging.info("Running %s", " ".join(cmd))
                        slutil.check_output(cmd)
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
                        cmd = [
                            "scontrol",
                            "update",
                            "NodeName=%s" % recovered_name,
                            "State=idle",
                            "Reason=cyclecloud_node_recovery",
                        ]
                        logging.info("Running %s", " ".join(cmd))
                        slutil.check_output(cmd)
                        if recovered_name in failed_node_names:
                            failed_node_names.pop(recovered_name)
                except Exception:
                    logging.exception(
                        "Failed to mark the following nodes as recovered: %s. Will re-attempt next iteration.",
                        recovered_node_names_str,
                    )

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

            if terminal_states == len(relevant_nodes):
                break

            previous_states = states

            time.sleep(5)

        logging.info(
            "The following nodes reached Ready state: %s",
            ",".join([x.name for x in ready_nodes]),
        )
        for node in ready_nodes:
            use_nodename_as_hostname = node.software_configuration.get("slurm", {}).get(
                "use_nodename_as_hostname", False
            )
            # backwards compatibility - set NodeAddr=private ip address
            if not use_nodename_as_hostname:

                if not node.private_ip:
                    logging.error("Could not find PrivateIp for node %s.", node.name)
                else:
                    cmd = [
                        "scontrol",
                        "update",
                        "NodeName=%s" % node.name,
                        "NodeAddr=%s" % node.private_ip,
                        "NodeHostName=%s" % node.private_ip,
                    ]
                    logging.info("Running %s", " ".join(cmd))
                    slutil.check_output(cmd)

        logging.info(
            "OperationId=%s NodeList=%s: all nodes updated with the proper IP address. Exiting",
            operation_id,
            nodes_str,
        )


def _generate_slurm_conf(
    partitions: Dict[str, partitionlib.Partition],
    writer: TextIO,
    allow_empty: bool = False,
    autoscale: bool = True,
) -> None:
    for partition in partitions.values():
        node_list = partition.node_list or []
        
        max_count = min(partition.max_vm_count, partition.max_scaleset_size)
        default_yn = "YES" if partition.is_default else "NO"

        memory = max(1024, partition.memory)
        def_mem_per_cpu = memory // partition.pcpu_count

        if partition.use_pcpu:
            cpus = partition.pcpu_count
            # cores_per_socket = 1
        else:
            cpus = partition.vcpu_count
            # cores_per_socket = max(1, partition.vcpu_count // partition.pcpu_count)

        writer.write(
            "# TODO RDH Note: CycleCloud reported a RealMemory of %d but we reduced it by %d (i.e. max(1gb, %d%%)) to account for OS/VM overhead which\n"
            % (
                int(partition.memory * 1024),
                -1,
                -1,
                # int(partition.dampen_memory * 100),
            )
        )
        writer.write(
            "# would result in the nodes being rejected by Slurm if they report a number less than defined here.\n"
        )
        writer.write(
            "# To pick a different percentage to dampen, set slurm.dampen_memory=X in the nodearray's Configuration where X is percentage (5 = 5%).\n"
        )
        writer.write(
            "PartitionName={} Nodes={} Default={} DefMemPerCPU={} MaxTime=INFINITE State=UP\n".format(
                partition.name, partition.node_list, default_yn, def_mem_per_cpu
            )
        )

        # all_nodes = sorted(
        #     slutil.from_hostlist(partition.node_list),  # type: ignore
        #     key=slutil.get_sort_key_func(partition.is_hpc),
        # )

        #node_list = f"{partition.nodename_prefix}{partition.name}-[1-{max_count}]"
        # node_list = slutil.to_hostlist(",".join((subset_of_nodes)))  # type: ignore
        # cut out 1gb so that the node reports at least this amount of memory. - recommended by schedmd

        if partition.use_pcpu:
            cpus = partition.pcpu_count
            threads = max(1, partition.vcpu_count // partition.pcpu_count)
        else:
            cpus = partition.vcpu_count
            threads = 1
        state = "CLOUD" if autoscale else "FUTURE"
        writer.write(
            "Nodename={} Feature=cloud STATE={} CPUs={} ThreadsPerCore={} RealMemory={}".format(
                partition.node_list, state, cpus, threads, memory
            )
        )

        if partition.gpu_count:
            writer.write(" Gres=gpu:{}".format(partition.gpu_count))

        writer.write("\n")


def _generate_topology(node_mgr: NodeManager, writer: TextIO) -> None:
    partitions = partitionlib.fetch_partitions(node_mgr)

    nodes_by_pg = {}
    for partition in partitions.values():
        for pg, node_list in partition.node_list_by_pg.items():
            if pg not in nodes_by_pg:
                nodes_by_pg[pg] = []
            nodes_by_pg[pg].extend(node_list)

    if not nodes_by_pg:
        raise CyclecloudSlurmError(
            "No nodes found to create topology! Do you need to run create_nodes first?"
        )

    for pg in sorted(nodes_by_pg.keys(), key=lambda x: x if x is not None else ""):
        nodes = nodes_by_pg[pg]
        if not nodes:
            continue
        nodes = sorted(nodes, key=slutil.get_sort_key_func(bool(pg)))
        slurm_node_expr = ",".join(nodes)  #slutil.to_hostlist(",".join(nodes))
        writer.write("SwitchName={} Nodes={}\n".format(pg or "htc", slurm_node_expr))


def _retry_rest(func: Callable, attempts: int = 5) -> Any:
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


def _retry_subprocess(func: Callable, attempts: int = 5) -> Any:
    attempts = max(1, attempts)
    last_exception: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except Exception as e:
            last_exception = e
            logging.debug(traceback.format_exc())
            logging.warning("Command failed, retrying: %s", str(e))
            time.sleep(attempt * attempt)

    raise CyclecloudSlurmError(str(last_exception))


def hostlist(hostlist_expr: str) -> List[str]:
    if hostlist_expr == "*":

        all_node_names = slutil.check_output(
            ["sinfo", "-O", "nodelist", "-h", "-N"]
        ).split()
        return all_node_names
    return slutil.from_hostlist(hostlist_expr)


def hostlist_null_star(hostlist_expr) -> Optional[List[str]]:
    if hostlist_expr == "*":
        return None
    return slutil.from_hostlist(hostlist_expr)


def _as_nodes(node_list: List[str], node_mgr: NodeManager) -> List[Node]:
    nodes: List[Node] = []
    by_name = hpcutil.partition_single(node_mgr.get_nodes(), lambda node: node.name)
    for node_name in node_list:
        # TODO error handling on missing node names
        if node_name not in by_name:
            raise CyclecloudSlurmError(f"Unknown node - {node_name}")
        nodes.append(by_name[node_name])
    return nodes


def main(argv: Optional[Iterable[str]] = None) -> None:
    clilibmain(argv or sys.argv[1:], "slurm", SlurmCLI())


if __name__ == "__main__":
    main()
