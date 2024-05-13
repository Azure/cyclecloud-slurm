from typing import Dict, List

from hpc.autoscale import util as hpcutil
from hpc.autoscale.ccbindings.mock import MockClusterBinding
from hpc.autoscale.clock import use_mock_clock
from hpc.autoscale.node import nodemanager
from hpc.autoscale.node.nodemanager import NodeManager
from slurmcc import partition
from slurmcc.cli import SlurmDriver
from slurmcc.util import NativeSlurmCLI, set_slurm_cli

use_mock_clock()


CONFIG: Dict = {}


def _show_hostnames(expr: str) -> List[str]:
    """
    Purely used to mimic scontrol
    """
    assert isinstance(expr, str)
    ret = []
    if "," in expr:
        for sub_expr in expr.split(","):
            ret.extend(_show_hostnames(sub_expr))
        return ret

    if "[" in expr:
        left, right = expr.rindex("["), expr.rindex("]")
        range_expr = expr[left + 1 : right].strip()
        if "-" in range_expr:
            start, stop = range_expr.split("-")
            for i in range(int(start), int(stop) + 1):
                new_expr = expr[:left] + str(i) + expr[right + 1 :]
                ret.extend(_show_hostnames(new_expr))
        return ret
    else:
        return [expr]


def _show_hostlist(node_list: List[str]) -> str:
    if len(node_list) == 1:
        return node_list[0]
    by_prefix = hpcutil.partition(node_list, lambda n: n.split("-")[0])
    ret = []
    for prefix, names in by_prefix.items():
        if len(names) == 1:
            ret.append(names[0])
            continue
        nums = []
        for name in names:
            try:
                nums.append(int(name.split("-")[-1]))
            except ValueError:
                raise RuntimeError(f"Bad name - {name} from list {node_list}")
        nums = sorted(nums)
        min_num = nums[0]
        last_num = min_num
        for n, num in enumerate(nums[1:]):

            if num > last_num + 1 or n == len(nums) - 2:
                if n == len(nums) - 2:
                    last_num = num
                ret.append(f"{prefix}-[{min_num}-{last_num}]")
                last_num = min_num = num
            else:
                last_num = num
    if node_list:
        assert ret, node_list
    return ",".join(ret)


class MockNativeSlurmCLI(NativeSlurmCLI):
    def __init__(self) -> None:
        self.slurm_nodes: Dict[str, Dict] = {}

    def scontrol(self, args: List[str], retry: bool = True) -> str:
        clear_caches()
        if args[0:2] == ["show", "hostnames"]:
            assert len(args) == 3
            assert isinstance(args[-1], str)
            ret = _show_hostnames(args[-1])
            assert ret
            assert isinstance(ret[0], str), ret[0]
            return "\n".join(ret)
        
        if args[0:2] == ["show", "hostlist"]:
            assert len(args) == 3
            assert args[-1]
            return _show_hostlist(args[-1].split(","))

        if args[0:2] == ["show", "nodes"]:
            if len(args) == 3:
                return self.show_nodes(args[2].split(","))
            return self.show_nodes([])

        if args[0] == "update":
            entity, value = args[1].split("=")
            if entity == "NodeName":
                slurm_node = self.slurm_nodes[value]
                for expr in args[2:]:
                    key, value = expr.split("=")
                    slurm_node[key] = value
            else:
                raise RuntimeError(f"Unknown args {args}")
            return ""
        raise RuntimeError(f"Unexpected command - {args}")

    def show_nodes(self, node_names: List[str]) -> str:
        ret = []
        node_names = node_names or list(self.slurm_nodes.keys())
        for node_name in node_names:
            assert (
                node_name in self.slurm_nodes
            ), f"Unknown slurm node_name {node_name}. Try calling .create_nodes first"
            snode = self.slurm_nodes[node_name]
            ret.append(
                """
NodeName=%(NodeName)s
    NodeAddr=%(NodeAddr)s NodeHostName=%(NodeHostName)s AvailableFeatures=%(AvailableFeatures)s Partitions=%(Partitions)s"""
                % snode
            )

        return "\n".join(ret)

    def create_nodes(self, node_names: List[str], features: List[str] = [], partitions: List[str] = []) -> None:
        for node_name in node_names:
            self.slurm_nodes[node_name] = {
                "NodeName": node_name,
                "NodeAddr": node_name,
                "NodeHostName": node_name,
                "AvailableFeatures": ",".join(features),
                "Partitions": "dynamic" if "dyn" in features else node_name.split("-")[0]
            }
        clear_caches()


set_slurm_cli(MockNativeSlurmCLI())


def make_native_cli(create_default_nodes: bool = True) -> MockNativeSlurmCLI:
    ret = MockNativeSlurmCLI()
    set_slurm_cli(ret)
    if create_default_nodes:
        ret.create_nodes(_show_hostnames("hpc-[1-100]"))
        ret.create_nodes(_show_hostnames("htc-[1-100]"))
    return ret


def refresh_test_node_manager(old_node_mgr: NodeManager) -> NodeManager:
    config = dict(CONFIG)

    config["_mock_bindings"] = old_node_mgr.cluster_bindings

    driver = SlurmDriver()
    config = driver.preprocess_config(config)

    node_mgr = nodemanager.new_node_manager(config)
    driver.preprocess_node_mgr(config, node_mgr)
    assert config["nodearrays"]["hpc"]
    return node_mgr


def make_test_node_manager(cluster_name: str = "c1") -> NodeManager:
    bindings = MockClusterBinding(cluster_name)
    config = dict(CONFIG)
    config["_mock_bindings"] = bindings

    bindings.add_nodearray(
        name="hpc",
        resources={},
        software_configuration=dict(
            slurm=dict(is_default=True, hpc=True, use_nodename_as_hostname=True)
        ),
    )
    # uses simple nodeaddr=ipaddress
    bindings.add_nodearray(
        name="htc",
        resources={},
        software_configuration=dict(
            slurm=dict(is_default=False, hpc=False, use_nodename_as_hostname=False)
        ),
    )
    bindings.add_nodearray(
        name="dynamic",
        resources={},
        software_configuration=dict(slurm=dict(is_default=False, hpc=False, dynamic_config="-Z Feature=dyn")),
    )
    bindings.add_bucket(
        nodearray_name="hpc", vm_size="Standard_F4", max_count=100, available_count=100, placement_groups=["Standard_F4_pg0"]
    )
    
    bindings.add_bucket(
        nodearray_name="htc", vm_size="Standard_F2", max_count=100, available_count=100
    )
    bindings.add_bucket(
        nodearray_name="dynamic",
        vm_size="Standard_F2",
        max_count=100,
        available_count=100,
    )

    driver = SlurmDriver()
    config = driver.preprocess_config(config)

    node_mgr = nodemanager.new_node_manager(config)
    driver.preprocess_node_mgr(config, node_mgr)
    assert config["nodearrays"]["hpc"]
    return node_mgr


def clear_caches() -> None:
    partition.Partition._SLURM_NODES_CACHE = None