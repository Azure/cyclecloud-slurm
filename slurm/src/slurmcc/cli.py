# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
import argparse
import json
import logging
import os
import shutil
import sys
import time
import traceback
from argparse import ArgumentParser
from datetime import date, datetime, time, timedelta
from math import ceil
from subprocess import SubprocessError, check_output
from typing import Any, Callable, Dict, Iterable, List, Optional, TextIO, Union

from hpc.autoscale.cost.azurecost import azurecost
from hpc.autoscale.ccbindings import new_cluster_bindings
from hpc.autoscale.hpctypes import Memory
from hpc.autoscale import clock
from hpc.autoscale import util as hpcutil
from hpc.autoscale.cli import GenericDriver
from hpc.autoscale.clilib import CommonCLI, ShellDict, disablecommand
from hpc.autoscale.clilib import main as clilibmain
from hpc.autoscale.job.demandprinter import OutputFormat
from hpc.autoscale.job.driver import SchedulerDriver
from hpc.autoscale.node.node import Node
from hpc.autoscale.node.nodemanager import NodeManager
from hpc.autoscale.results import ShutdownResult

from slurmcc import allocation

from . import AzureSlurmError
from . import partition as partitionlib
from . import util as slutil
from .util import is_autoscale_enabled, scontrol
from . import cost


VERSION = "3.0.7"


def csv_list(x: str) -> List[str]:
    # used in argument parsing
    return [x.strip() for x in x.split(",")]


def init_power_saving_log(function: Callable) -> Callable:
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        root_logger = logging.getLogger()
        for handler in root_logger.handlers:
            if hasattr(handler, "baseFilename"):
                fname = getattr(handler, "baseFilename")
                if fname and fname.endswith(f"{function.__name__}.log"):
                    handler.setLevel(logging.INFO)
                    logging.info(f"initialized {function.__name__}.log")
        return function(*args, **kwargs)

    wrapped.__doc__ = function.__doc__
    return wrapped


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

            if "generated_placement_group_buffer" in config["nodearrays"][b.nodearray]:
                continue

            is_hpc = (
                str(
                    b.software_configuration.get("slurm", {}).get("hpc") or "false"
                ).lower()
                == "true"
            )
            if is_hpc:
                buffer = 1
                max_pgs = 1
            else:
                buffer = 0
                max_pgs = 0
            config["nodearrays"][b.nodearray][
                "generated_placement_group_buffer"
            ] = buffer
            config["nodearrays"][b.nodearray][
                "max_placement_groups"
            ] = max_pgs
        super().preprocess_node_mgr(config, node_mgr)


class SlurmCLI(CommonCLI):
    def __init__(self) -> None:
        super().__init__(project_name="slurm")
        self.slurm_node_names = []

    @disablecommand
    def create_nodes(self, *args: Any, **kwargs: Dict) -> None:
        assert False

    @disablecommand
    def delete_nodes(
        self,
        config: Dict,
        hostnames: List[str],
        node_names: List[str],
        do_delete: bool = True,
        force: bool = False,
        permanent: bool = False,
    ) -> None:
        assert False

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

    def cost_parser(self, parser: ArgumentParser) -> None:
        parser.add_argument("-s", "--start",  type=lambda s: datetime.strptime(s, '%Y-%m-%d'),
                            default=date.today().isoformat(),
                            help="Start time period (yyyy-mm-dd), defaults to current day.")
        parser.add_argument("-e", "--end",  type=lambda s: datetime.strptime(s, '%Y-%m-%d'),
                            default=date.today().isoformat(),
                            help="End time period (yyyy-mm-dd), defaults to current day.")
        parser.add_argument("-o", "--out", required=True, help="Directory name for output CSV")
        #parser.add_argument("-p", "--partition", action='store_true', help="Show costs aggregated by partitions")
        parser.add_argument("-f", "--fmt", type=str,
                            help="Comma separated list of SLURM formatting options. Otherwise defaults are applied")

    def cost(self, config: Dict, start, end, out, fmt=None):
        """
        Cost analysis and reporting tool that maps Azure costs
        to SLURM Job Accounting data. This is an experimental
        feature.
        """

        curr = datetime.today()
        delta = timedelta(days=365)

        if (curr - start) >= delta:
            raise ValueError("Start date cannot be more than 1 year back from today")

        if start > end:
            raise ValueError("Start date cannot be after end date")
        if end > curr:
            raise ValueError("End date cannot be in the future")
        if start == end:
            end = datetime.combine(end.date(), time(hour=23,minute=59,second=59))

        azcost = azurecost(config)
        driver = cost.CostDriver(azcost, config)
        driver.run(start, end, out, fmt)

    def partitions_parser(self, parser: ArgumentParser) -> None:
        parser.add_argument("--allow-empty", action="store_true", default=False)

    def partitions(self, config: Dict, allow_empty: bool = False) -> None:
        """
        Generates partition configuration
        """
        node_mgr = self._get_node_manager(config)
        partitions = partitionlib.fetch_partitions(node_mgr, include_dynamic=True)  # type: ignore
        _partitions(
            partitions,
            sys.stdout,
            allow_empty=allow_empty,
            autoscale=is_autoscale_enabled(),
        )

    def generate_topology(self, config: Dict) -> None:
        """
        Generates topology plugin configuration
        """
        return _generate_topology(self._get_node_manager(config), sys.stdout)

    def resume_parser(self, parser: ArgumentParser) -> None:
        parser.set_defaults(read_only=False)
        parser.add_argument(
            "--node-list", type=hostlist, required=True
        ).completer = self._slurm_node_name_completer  # type: ignore
        parser.add_argument("--no-wait", action="store_true", default=False)

    @init_power_saving_log
    def resume(self, config: Dict, node_list: List[str], no_wait: bool = False) -> None:
        """
        Equivalent to ResumeProgram, starts and waits for a set of nodes.
        """
        bindings = new_cluster_bindings(config)
        allocation.wait_for_nodes_to_terminate(bindings, node_list)

        node_mgr = self._get_node_manager(config)
        partitions = partitionlib.fetch_partitions(node_mgr, include_dynamic=True)
        bootup_result = allocation.resume(config, node_mgr, node_list, partitions)
        if not bootup_result:
            raise AzureSlurmError(
                f"Failed to boot {node_list} - {bootup_result.message}"
            )
        if no_wait:
            return

        def get_latest_nodes() -> List[Node]:
            node_mgr = self._get_node_manager(config, force=True)
            return node_mgr.get_nodes()

        booted_node_list = [n.name for n in (bootup_result.nodes or [])]
        allocation.wait_for_resume(
            config, bootup_result.operation_id, booted_node_list, get_latest_nodes
        )

    def wait_for_resume_parser(self, parser: ArgumentParser) -> None:
        parser.set_defaults(read_only=False)
        parser.add_argument(
            "--node-list", type=hostlist, required=True
        ).completer = self._slurm_node_name_completer  # type: ignore

    def wait_for_resume(self, config: Dict, node_list: List[str]) -> None:
        """
        Wait for a set of nodes to converge.
        """

        def get_latest_nodes() -> List[Node]:
            node_mgr = self._get_node_manager(config, force=True)
            return node_mgr.get_nodes()

        allocation.wait_for_resume(config, "noop", node_list, get_latest_nodes)

    def _shutdown(self, config: Dict, node_list: List[str], node_mgr: NodeManager) -> None:
        by_name = hpcutil.partition_single(node_mgr.get_nodes(), lambda node: node.name)
        node_list_filtered = []
        to_keep_alive = []
        for node_name in node_list:
            if node_name in by_name:
                node = by_name[node_name]
                if node.keep_alive:
                    to_keep_alive.append(node_name)
                    logging.warning(f"{node_name} has KeepAlive=true in CycleCloud. Cannot terminate.")
                else:
                    node_list_filtered.append(node_name)
            else:
                logging.info(f"{node_name} does not exist. Skipping.")

        if to_keep_alive:
            # This will prevent the node from falsely being resume/resume_fail over and over again.
            logging.warning(f"Nodes {to_keep_alive} have KeepAlive=true in CycleCloud. Cannot terminate." +
                            " Setting state to down reason=keep_alive")
            to_keep_alive_str = slutil.to_hostlist(to_keep_alive)
            scontrol(["update", f"nodename={to_keep_alive_str}", "state=down", "reason=keep_alive"])

        if not node_list_filtered:
            logging.warning(f"No nodes out of node list {node_list} could be shutdown." +
                            " Post-processing the nodes only.")
        else:
            result = _safe_shutdown(node_list_filtered, node_mgr)
            
            if not result:
                raise AzureSlurmError(f"Failed to shutdown {node_list_filtered} - {result.message}")

        if slutil.is_autoscale_enabled():
            # undo internal DNS
            for node_name in node_list:
                _undo_internal_dns(node_name)
        else:
            # set states back to future and set NodeAddr/NodeHostName to node name
            _update_future_states(self._get_node_manager(config, force=True), node_list)

    def suspend_parser(self, parser: ArgumentParser) -> None:
        parser.set_defaults(read_only=False)
        parser.add_argument(
            "--node-list", type=hostlist, required=True
        ).completer = self._slurm_node_name_completer  # type: ignore

    @init_power_saving_log
    def suspend(self, config: Dict, node_list: List[str]) -> None:
        """
        Equivalent to SuspendProgram, shutsdown nodes
        """
        return self._shutdown(config, node_list, self._node_mgr(config))

    def resume_fail_parser(self, parser: ArgumentParser) -> None:
        self.suspend_parser(parser)

    @init_power_saving_log
    def resume_fail(
        self, config: Dict, node_list: List[str], drain_timeout: int = 300
    ) -> None:
        """
        Equivalent to SuspendFailProgram, shutsdown nodes
        """
        node_mgr = self._node_mgr(config, self._driver(config))
        self._shutdown(config, node_list=node_list, node_mgr=node_mgr)

    def return_to_idle_parser(self, parser: ArgumentParser) -> None:
        parser.set_defaults(read_only=False)
        parser.add_argument("--terminate-zombie-nodes", action="store_true", default=False)

    def return_to_idle(
        self, config: Dict, terminate_zombie_nodes: bool = False
    ) -> None:
        """
        Nodes that fail to resume in ResumeTimeout seconds will be left
        in a down~ state - i.e. down and powered_down. It is also possible
        the nodes will be in a drained~ state, if the node was drained during
        resume. This command will set those nodes to idle~.

        The one exception is for nodes that have KeepAlive set in CycleCloud.
        Those nodes will be left as down~ and will be logged. When the user
        unclicks the KeepAlive, the node can be automatically shutdown if --terminate-zombie-nodes
        is set, or config["return-to-idle"]["terminate-zombie-nodes"] is true.
        """
        if not slutil.is_autoscale_enabled():
            return

        # this is always run as root, so bump up the loglevel to info
        stream_handlers = [
            x
            for x in logging.getLogger().handlers
            if isinstance(x, logging.StreamHandler)
        ]
        for sh in stream_handlers:
            sh.setLevel(logging.INFO)

        node_mgr = self._node_mgr(config)
        ccnodes = node_mgr.get_nodes()
        ccnodes_by_name = hpcutil.partition_single(ccnodes, lambda node: node.name)

        snodes = slutil.show_nodes()
        if terminate_zombie_nodes:
            if "return_to_idle" not in config:
                config["return_to_idle"] = {}
            config["return_to_idle"]["terminate-zombie-nodes"] = True
            
        SlurmCLI._return_to_idle(config, snodes, ccnodes_by_name, scontrol, node_mgr)

    @staticmethod
    def _return_to_idle(
        config: Dict,
        snodes: List[Dict],
        ccnodes_by_name: Dict[str, Node],
        scontrol_func: Callable,
        node_mgr: NodeManager,
    ) -> None:
        to_set_to_idle = []
        to_shutdown = []

        for snode in snodes:
            slurm_states = set(snode["State"].split("+"))
            # ignore non-cloud nodes, as they aren't our responsibility
            if "CLOUD" not in slurm_states:
                continue

            power_down_states = set(["POWERED_DOWN", "POWERING_DOWN"])
            if not power_down_states.intersection(slurm_states):
                continue
            node_name = snode["NodeName"]

            if "DOWN" in slurm_states or "DRAINED" in slurm_states:
                if node_name in ccnodes_by_name:
                    ccnode = ccnodes_by_name[node_name]
                    if ccnode.keep_alive:
                        logging.warning(
                            f"{node_name} exists and has KeepAlive=true in CycleCloud. Cannot set to idle."
                        )
                    else:
                        terminate_zombie_nodes = config.get("return-to-idle", {}).get(
                                "terminate-zombie-nodes", False
                        )
                        
                        if terminate_zombie_nodes:
                            logging.warning(
                                f"Found zombie node {node_name}. Will terminate because terminate-zombie-nodes is set."
                            )
                            to_shutdown.append(node_name)
                            to_set_to_idle.append(node_name)
                        else:
                            logging.warning(
                                f"Node {node_name} is in DOWN~ state but exists in CycleCloud. To terminate the node"
                                + ", shutdown the node manually (via azslurm suspend or the UI) or, if you want the node"
                                + " to join the cluster, login to it and restart slurmd."
                            )
                else:
                    to_set_to_idle.append(node_name)

        if to_shutdown:
            result = _safe_shutdown(to_shutdown, node_mgr)
            if not result:
                logging.error(
                    f"Could not shutdown all of the nodes. Leaving {to_shutdown} in DOWN~ state."
                )
                to_set_to_idle = [x for x in to_set_to_idle if x not in to_shutdown]

        if to_set_to_idle:
            to_set_to_idle_str = slutil.to_hostlist(to_set_to_idle, scontrol_func=scontrol_func)
            logging.warning(f"Setting nodes {to_set_to_idle} to idle.")
            scontrol_func(["update", f"nodename={to_set_to_idle_str}", "state=idle"])
    

    def _get_node_manager(self, config: Dict, force: bool = False) -> NodeManager:
        return self._node_mgr(config, self._driver(config), force=force)

    def _setup_shell_locals(self, config: Dict) -> Dict:
        # TODO
        shell = {}
        partitions = partitionlib.fetch_partitions(self._get_node_manager(config))  # type: ignore
        shell["partitions"] = ShellDict(
            hpcutil.partition_single(partitions, lambda p: p.name)
        )
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
            _print(
                "nodes",
                "Current nodes according to the provider. May include nodes that have not joined yet.",
            )

        shell["slurmhelp"] = slurmhelp
        return shell

    def _driver(self, config: Dict) -> SchedulerDriver:
        return SlurmDriver()

    def _default_output_columns(
        self, config: Dict, cmd: Optional[str] = None
    ) -> List[str]:
        if hpcutil.LEGACY:
            return ["nodearray", "name", "hostname", "private_ip", "status"]
        return ["pool", "name", "hostname", "private_ip", "status"]

    def _initconfig_parser(self, parser: ArgumentParser) -> None:
        # TODO
        parser.add_argument("--accounting-tag-name", dest="accounting__tag_name")
        parser.add_argument("--accounting-tag-value", dest="accounting__tag_value")
        parser.add_argument(
            "--accounting-subscription-id", dest="accounting__subscription_id"
        )
        parser.add_argument("--cost-cache-root", dest="cost__cache_root")
        parser.add_argument("--config-dir", required=True)

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

    def scale_parser(self, parser: ArgumentParser) -> None:

        parser.add_argument("--no-restart", action="store_true", default=False, help="Don't restart slurm controller")
        return

    def scale(
        self,
        config: Dict,
        no_restart=False,
        backup_dir="/etc/slurm/.backups",
        slurm_conf_dir="/etc/slurm",
        config_only=False,
    ):
        """
        Create or update slurm partition and/or gres information
        """
        sched_dir = config.get("config_dir")
        node_mgr = self._get_node_manager(config)
        # make sure .backups exists
        now = clock.time()
        backup_dir = os.path.join(backup_dir, str(now))

        logging.debug(
            "Using backup directory %s for azure.conf and gres.conf", backup_dir
        )
        os.makedirs(backup_dir)

        azure_conf = os.path.join(sched_dir, "azure.conf")
        gres_conf = os.path.join(sched_dir, "gres.conf")
        linked_gres_conf = os.path.join(slurm_conf_dir, "gres.conf")
        if os.path.isfile(linked_gres_conf) and not os.path.islink(linked_gres_conf):
            msg = f"{linked_gres_conf} should be a symlink to {gres_conf}! Changes will not take effect locally."
            print("WARNING: " + msg, file=sys.stderr)
            logging.warning(msg)

        if not os.path.exists(linked_gres_conf):
            msg = f"please run 'ln -fs {gres_conf} {linked_gres_conf} && chown slurm:slurm {linked_gres_conf}'"
            print("WARNING: " + msg, file=sys.stderr)
            logging.warning(msg)

        if os.path.exists(azure_conf):
            shutil.copyfile(azure_conf, os.path.join(backup_dir, "azure.conf"))

        if os.path.exists(gres_conf):
            shutil.copyfile(gres_conf, os.path.join(backup_dir, "gres.conf"))

        partition_dict = partitionlib.fetch_partitions(node_mgr)
        with open(azure_conf + ".tmp", "w") as fw:
            _partitions(
                partition_dict,
                fw,
                allow_empty=False,
                autoscale=is_autoscale_enabled(),
            )
        # Issue #193 - failure to maintain ownership/permissions when
        # rewriting azure.conf and gres.conf
        _move_with_permissions(azure_conf + ".tmp", azure_conf)

        _update_future_states(node_mgr)

        with open(gres_conf + ".tmp", "w") as fw:
            _generate_gres_conf(partition_dict, fw)
        
        _move_with_permissions(gres_conf + ".tmp", gres_conf)

        if not no_restart:
            logging.info("Restarting slurmctld...")
            check_output(["systemctl", "restart", "slurmctld"])

        logging.info("")
        logging.info("Re-scaling cluster complete.")

    def keep_alive_parser(self, parser: ArgumentParser) -> None:
        parser.set_defaults(read_only=False)
        parser.add_argument(
            "--node-list", type=hostlist, required=True
        ).completer = self._slurm_node_name_completer  # type: ignore

        parser.add_argument("--remove", "-r", action="store_true", default=False)
        parser.add_argument(
            "--set", "-s", action="store_true", default=False, dest="set_nodes"
        )

    def keep_alive(
        self,
        config: Dict,
        node_list: List[str],
        remove: bool = False,
        set_nodes: bool = False,
    ) -> None:
        """
        Add, remove or set which nodes should be prevented from being shutdown.

        """

        config_dir = config.get("config_dir")
        if remove and set_nodes:
            raise AzureSlurmError("Please define only --set or --remove, not both.")

        lines = slutil.check_output(["scontrol", "show", "config"]).splitlines()
        filtered = [
            line for line in lines if line.lower().startswith("suspendexcnodes")
        ]
        current_susp_nodes = []
        if filtered:
            current_susp_nodes_expr = filtered[0].split("=")[-1].strip()
            if current_susp_nodes_expr != "(null)":
                current_susp_nodes = slutil.from_hostlist(current_susp_nodes_expr)

        if set_nodes:
            hostnames = list(set(node_list))
        elif remove:
            hostnames = list(set(current_susp_nodes) - set(node_list))
        else:
            hostnames = current_susp_nodes + node_list

        all_susp_hostnames = (
            slutil.check_output(
                [
                    "scontrol",
                    "show",
                    "hostnames",
                    ",".join(hostnames),
                ]
            )
            .strip()
            .split()
        )
        all_susp_hostnames = sorted(
            list(set(all_susp_hostnames)), key=slutil.get_sort_key_func(False)
        )
        all_susp_hostlist = slutil.check_output(
            ["scontrol", "show", "hostlist", ",".join(all_susp_hostnames)]
        ).strip()

        with open(f"{config_dir}/keep_alive.conf.tmp", "w") as fw:
            if all_susp_hostlist:
                fw.write(f"SuspendExcNodes = {all_susp_hostlist}")
            else:
                fw.write("# SuspendExcNodes = ")
        shutil.move(f"{config_dir}/keep_alive.conf.tmp", f"{config_dir}/keep_alive.conf")
        slutil.check_output(["scontrol", "reconfig"])

    def accounting_info_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--node-name", required=True)

    def accounting_info(self, config: Dict, node_name: str) -> None:
        node_mgr = self._get_node_manager(config)
        nodes = node_mgr.get_nodes()
        nodes_filtered = [n for n in nodes if n.name == node_name]
        if not nodes_filtered:
            json.dump([], sys.stdout)
            return
        assert len(nodes_filtered) == 1
        node = nodes_filtered[0]

        toks = check_output(["scontrol", "show", "node", node_name]).decode().split()
        cpus = -1
        for tok in toks:
            tok = tok.lower()
            if tok.startswith("cputot"):
                cpus = int(tok.split("=")[1])

        json.dump(
            [
                {
                    "name": node.name,
                    "location": node.location,
                    "vm_size": node.vm_size,
                    "spot": node.spot,
                    "nodearray": node.nodearray,
                    "cpus": cpus,
                    "pcpu_count": node.pcpu_count,
                    "vcpu_count": node.vcpu_count,
                    "gpu_count": node.gpu_count,
                    "memgb": node.memory.value,
                }
            ],
            sys.stdout
        )


def _move_with_permissions(src: str, dst: str) -> None:
    if os.path.exists(dst):
        st = os.stat(dst)
        os.chmod(src, st.st_mode)
        os.chown(src, st.st_uid, st.st_gid)
    logging.debug("Moving %s to %s", src, dst)
    shutil.move(src, dst)

    if not slutil.is_autoscale_enabled():
        def sync_future_states_parser(self, parser: ArgumentParser) -> None:
            parser.add_argument(
                "--node-list", type=hostlist_null_star, help="Optional subset of nodes to sync. Default is all."
            )

        def sync_future_states(self, config: Dict, node_list: Optional[List[str]] = None) -> None:
            _update_future_states(self._get_node_manager(config), node_list)


def _dynamic_partition(partition: partitionlib.Partition, writer: TextIO) -> None:
    assert partition.dynamic_config

    writer.write(
        "# Creating dynamic nodeset and partition using slurm.dynamic_config=%s\n"
        % partition.dynamic_config
    )
    if not partition.features:
        logging.error(
            f"slurm.dynamic_config was set for {partition.name}"
            + "but it did not include a feature declaration. Slurm requires this! Skipping for now.ß"
        )
        return

    writer.write(f"Nodeset={partition.name}ns Feature={','.join(partition.features)}\n")
    writer.write(f"PartitionName={partition.name} Nodes={partition.name}ns")
    if partition.is_default:
        writer.write(" Default=YES")
    writer.write("\n")


def _partitions(
    partitions: List[partitionlib.Partition],
    writer: TextIO,
    allow_empty: bool = False,
    autoscale: bool = True,
) -> None:

    written_dynamic_partitions = set()

    writer.write(
        f"# Note: To account for OS/VM overhead, by default we reduce the reported memory from CycleCloud by 5%.\n"
    )
    writer.write(
        "# We do this because Slurm will reject a node that reports less than what is defined in this config.\n"
    )
    writer.write(
        "# There are two ways to change this:\n" +
        "#  1) edit slurm.dampen_memory=X in the nodearray's Configuration where X is percentage (5 = 5%).\n"
        "#  2) Edit the slurm_memory value defined in /opt/azurehpc/slurm/autosacle.json.\n" + 
        "# Note that slurm.dampen_memory will take precedence.\n"
    )

    for partition in partitions:
        if partition.dynamic_config:
            if partition.name in written_dynamic_partitions:
                logging.warning("Duplicate partition found mapped to the same name." +
                                " Using first Feature= declaration and ignoring the rest!")
                continue
            _dynamic_partition(partition, writer)
            written_dynamic_partitions.add(partition.name)
            continue

        node_list = partition.node_list or []

        max_count = min(partition.max_vm_count, partition.max_scaleset_size)
        default_yn = "YES" if partition.is_default else "NO"

        memory = max(1024, partition.memory)

        if partition.use_pcpu:
            cpus = partition.pcpu_count
            threads = max(1, partition.vcpu_count // partition.pcpu_count)
        else:
            cpus = partition.vcpu_count
            threads = 1
        def_mem_per_cpu = memory // cpus


        writer.write(
            "PartitionName={} Nodes={} Default={} DefMemPerCPU={} MaxTime=INFINITE State=UP\n".format(
                partition.name, partition.node_list, default_yn, def_mem_per_cpu
            )
        )

        state = "CLOUD" if autoscale else "FUTURE"
        writer.write(
            "Nodename={} Feature=cloud STATE={} CPUs={} ThreadsPerCore={} RealMemory={}".format(
                node_list, state, cpus, threads, memory
            )
        )

        if partition.gpu_count:
            writer.write(" Gres=gpu:{}".format(partition.gpu_count))

        writer.write("\n")


def _generate_topology(node_mgr: NodeManager, writer: TextIO) -> None:
    partitions = partitionlib.fetch_partitions(node_mgr)

    nodes_by_pg = {}
    for partition in partitions:
        for pg, node_list in partition.node_list_by_pg.items():
            if pg not in nodes_by_pg:
                nodes_by_pg[pg] = []
            nodes_by_pg[pg].extend(node_list)

    if not nodes_by_pg:
        raise AzureSlurmError(
            "No nodes found to create topology! Do you need to run create_nodes first?"
        )

    for pg in sorted(nodes_by_pg.keys(), key=lambda x: x if x is not None else ""):
        nodes = nodes_by_pg[pg]
        if not nodes:
            continue
        nodes = sorted(nodes, key=slutil.get_sort_key_func(bool(pg)))
        slurm_node_expr = ",".join(nodes)  # slutil.to_hostlist(",".join(nodes))
        writer.write("SwitchName={} Nodes={}\n".format(pg or "htc", slurm_node_expr))


def _generate_gres_conf(partitions: List[partitionlib.Partition], writer: TextIO):
    for partition in partitions:
        if partition.node_list is None:
            raise RuntimeError(
                "No nodes found for nodearray %s. Please run 'azslurm create_nodes' first!"
                % partition.nodearray
            )

        num_placement_groups = int(
            ceil(float(partition.max_vm_count) / partition.max_scaleset_size)
        )
        all_nodes = sorted(
            slutil.from_hostlist(partition.node_list),
            key=slutil.get_sort_key_func(partition.is_hpc),
        )

        for pg_index in range(num_placement_groups):
            start = pg_index * partition.max_scaleset_size
            end = min(
                partition.max_vm_count, (pg_index + 1) * partition.max_scaleset_size
            )
            subset_of_nodes = all_nodes[start:end]
            node_list = slutil.to_hostlist(",".join((subset_of_nodes)))
            # cut out 1gb so that the node reports at least this amount of memory. - recommended by schedmd

            if partition.gpu_count:
                if partition.gpu_count > 1:
                    nvidia_devices = "/dev/nvidia[0-{}]".format(partition.gpu_count - 1)
                else:
                    nvidia_devices = "/dev/nvidia0"
                writer.write(
                    "Nodename={} Name=gpu Count={} File={}".format(
                        node_list, partition.gpu_count, nvidia_devices
                    )
                )

            writer.write("\n")


def _update_future_states(node_mgr: NodeManager, node_list: Optional[List[str]] = None) -> None:
    autoscale_enabled = is_autoscale_enabled()
    if autoscale_enabled:
        return
    nodes = node_mgr.get_nodes()

    for node in nodes:
        if node_list and node.name not in node_list:
            continue

        if node.target_state != "Started":
            name = node.name
            try:
                cmd = [
                    "scontrol",
                    "update",
                    f"NodeName={name}",
                    f"NodeAddr={name}",
                    f"NodeHostName={name}",
                    "state=FUTURE",
                ]
                check_output(cmd)
            except SubprocessError:
                logging.warning(f"Could not set {node.get('Name')} state=FUTURE")


def _undo_internal_dns(node_name: str) -> None:
    try:
        cmd = [
            "scontrol",
            "update",
            f"NodeName={node_name}",
            f"NodeAddr={node_name}",
            f"NodeHostName={node_name}",
        ]
        check_output(cmd)
    except SubprocessError:
        logging.warning(f"Could not set {node_name}'s nodeaddr/nodehostname!")


def _retry_rest(func: Callable, attempts: int = 5) -> Any:
    attempts = max(1, attempts)
    last_exception = None
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except Exception as e:
            last_exception = e
            logging.debug(traceback.format_exc())

            clock.sleep(attempt * attempt)

    raise AzureSlurmError(str(last_exception))


def hostlist(hostlist_expr: str) -> List[str]:
    if hostlist_expr == "*":

        all_node_names = slutil.check_output(
            ["sinfo", "-O", "nodelist", "-h", "-N"]
        ).split()
        return all_node_names
    return slutil.from_hostlist(hostlist_expr)


def hostlist_null_star(hostlist_expr: str) -> Optional[List[str]]:
    if hostlist_expr == "*":
        return None
    return slutil.from_hostlist(hostlist_expr)


def _safe_shutdown(node_list: List[str], node_mgr: NodeManager) -> ShutdownResult:
    assert node_list
    logging.info(f"Shutting down nodes {node_list}")
    nodes = _as_nodes(node_list, node_mgr)
    ret = _retry_rest(lambda: node_mgr.shutdown_nodes(nodes))
    if ret:
        logging.info(str(ret))
    else:
        logging.error(str(ret))
    return ret


def _as_nodes(node_list: List[str], node_mgr: NodeManager) -> List[Node]:
    nodes: List[Node] = []
    by_name = hpcutil.partition_single(node_mgr.get_nodes(), lambda node: node.name)
    for node_name in node_list:
        # TODO error handling on missing node names
        if node_name not in by_name:
            raise AzureSlurmError(f"Unknown node - {node_name}")
        nodes.append(by_name[node_name])
    return nodes


def main(argv: Optional[Iterable[str]] = None) -> None:
    try:
        clilibmain(argv or sys.argv[1:], "slurm", SlurmCLI())
    except AzureSlurmError as e:
        logging.error(e.message)
        sys.exit(1)
    except Exception:
        log_files = [x.baseFileName for x in logging.getLogger().handlers if hasattr(x, "baseFilename")]
        logging.exception(f"Unexpected error. See {','.join(log_files)} for more information.")
        raise


if __name__ == "__main__":
    main()
