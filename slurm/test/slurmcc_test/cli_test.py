from io import StringIO
from typing import List, Optional

from hpc.autoscale.hpctypes import Memory
from hpc.autoscale.node.bucket import NodeBucket, NodeDefinition
from hpc.autoscale.results import ShutdownResult

from slurmcc import cli, util
from slurmcc.partition import Partition

from slurmcc_test import testutil


class SimpleMockLimits:
    def __init__(self, max_count: int) -> None:
        self.max_count = max_count


def setup() -> None:
    util.TEST_MODE = True
    util.SLURM_CLI = testutil.MockNativeSlurmCLI()

def teardown() -> None:
    util.TEST_MODE = False
    util.SLURM_CLI = testutil.MockNativeSlurmCLI()


def make_partition(
    name: str,
    is_default: bool,
    is_hpc: bool,
    use_pcpu: bool = True,
    slurm_memory: str = "",
    dampen_memory: Optional[float] = None,
    dynamic_config: str = "",
) -> Partition:
    resources = {"slurm_memory": Memory.value_of(slurm_memory)} if slurm_memory else {}
    node_def = NodeDefinition(
        name,
        f"b-id-{name}",
        "Standard_F4",
        "southcentralus",
        False,
        "subnet",
        4,
        0,
        Memory.value_of("16g"),
        f"pg-{name}" if is_hpc else None,
        resources,
        {},
    )

    limits = SimpleMockLimits(100)

    bucket = NodeBucket(node_def, limits, 100, [])
    return Partition(
        name,
        name,
        f"pre-",
        "Standard_F4",
        is_default,
        is_hpc,
        100,
        [bucket],
        100,
        use_pcpu,
        dynamic_config,
        {},
        ["Standard_f4"],
        dampen_memory,
    )


def test_partitions() -> None:

    partitions = [
        make_partition("htc", False, False),
        make_partition("hpc", True, True),
        make_partition("dynamic", False, False, dynamic_config="-Z Feature=dyn"),
    ]

    # Define neither slurm_memory nor dampen_memory, autoscale=true
    # Expect full 16g to be applied.
    writer = StringIO()

    cli._partitions(partitions, writer, autoscale=True)
    actual = "\n".join(
        [x for x in writer.getvalue().splitlines() if not x.startswith("#")]
    )
    with open("/tmp/partitions.txt", "w") as f:
        f.write(actual)
    assert (
        actual
        == """PartitionName=htc Nodes=pre-[1-100] Default=NO DefMemPerCPU=3840 MaxTime=INFINITE State=UP
Nodename=pre-[1-100] Feature=cloud STATE=CLOUD CPUs=4 ThreadsPerCore=1 RealMemory=15360
PartitionName=hpc Nodes=pre-[1-100] Default=YES DefMemPerCPU=3840 MaxTime=INFINITE State=UP
Nodename=pre-[1-100] Feature=cloud STATE=CLOUD CPUs=4 ThreadsPerCore=1 RealMemory=15360
Nodeset=dynamicns Feature=dyn
PartitionName=dynamic Nodes=dynamicns"""
    )

    # Define neither slurm_memory nor dampen_memory, autoscale=true
    # Expect default of 16g - 1gb to be applied.
    # Exoect state=FUTURE instead of CLOUD
    writer = StringIO()
    cli._partitions(partitions, writer, autoscale=False)
    actual = "\n".join(
        [x for x in writer.getvalue().splitlines() if not x.startswith("#")]
    )
    assert (
        actual
        == """PartitionName=htc Nodes=pre-[1-100] Default=NO DefMemPerCPU=3840 MaxTime=INFINITE State=UP
Nodename=pre-[1-100] Feature=cloud STATE=FUTURE CPUs=4 ThreadsPerCore=1 RealMemory=15360
PartitionName=hpc Nodes=pre-[1-100] Default=YES DefMemPerCPU=3840 MaxTime=INFINITE State=UP
Nodename=pre-[1-100] Feature=cloud STATE=FUTURE CPUs=4 ThreadsPerCore=1 RealMemory=15360
Nodeset=dynamicns Feature=dyn
PartitionName=dynamic Nodes=dynamicns"""
    )

    # Define only slurm_memory resource, autoscale=true
    # Expect slurm_memory (15g, 14g) will be applied.
    partitions = [
        make_partition("htc", False, False, slurm_memory="15g"),
        make_partition("hpc", True, True, slurm_memory="14g"),
        make_partition(
            "dynamic", False, False, dynamic_config="-Z Feature=dyn", slurm_memory="13g"
        ),
    ]
    # No slurm.dampen_memory or slurm_memory resource, autoscale=FALSE
    writer = StringIO()
    cli._partitions(partitions, writer, autoscale=True)
    actual = "\n".join(
        [x for x in writer.getvalue().splitlines() if not x.startswith("#")]
    )
    assert (
        actual
        == """PartitionName=htc Nodes=pre-[1-100] Default=NO DefMemPerCPU=3840 MaxTime=INFINITE State=UP
Nodename=pre-[1-100] Feature=cloud STATE=CLOUD CPUs=4 ThreadsPerCore=1 RealMemory=15360
PartitionName=hpc Nodes=pre-[1-100] Default=YES DefMemPerCPU=3584 MaxTime=INFINITE State=UP
Nodename=pre-[1-100] Feature=cloud STATE=CLOUD CPUs=4 ThreadsPerCore=1 RealMemory=14336
Nodeset=dynamicns Feature=dyn
PartitionName=dynamic Nodes=dynamicns"""
    )

    # Define both slurm_memory resource and slurm.dampen_memory, autoscale=true
    # Expect dampen_memory (25%, 50%) will be applied
    partitions = [
        make_partition("htc", False, False, slurm_memory="15g", dampen_memory=0.25),
        make_partition("hpc", True, True, slurm_memory="14g", dampen_memory=0.5),
        make_partition(
            "dynamic",
            False,
            False,
            dynamic_config="-Z Feature=dyn",
            slurm_memory="13g",
            dampen_memory=0.75,
        ),
    ]

    writer = StringIO()
    cli._partitions(partitions, writer, autoscale=True)
    actual = "\n".join(
        [x for x in writer.getvalue().splitlines() if not x.startswith("#")]
    )
    assert (
        actual
        == """PartitionName=htc Nodes=pre-[1-100] Default=NO DefMemPerCPU=3072 MaxTime=INFINITE State=UP
Nodename=pre-[1-100] Feature=cloud STATE=CLOUD CPUs=4 ThreadsPerCore=1 RealMemory=12288
PartitionName=hpc Nodes=pre-[1-100] Default=YES DefMemPerCPU=2048 MaxTime=INFINITE State=UP
Nodename=pre-[1-100] Feature=cloud STATE=CLOUD CPUs=4 ThreadsPerCore=1 RealMemory=8192
Nodeset=dynamicns Feature=dyn
PartitionName=dynamic Nodes=dynamicns"""
    )
    
    # Define both slurm_memory resource and slurm.dampen_memory, autoscale=true
    # Expect dampen_memory (use 1G as 1% is too small) will be applied
    partitions = [
        make_partition("htc", False, False, slurm_memory="15g", dampen_memory=0.001),
        make_partition("hpc", True, True, slurm_memory="14g", dampen_memory=0.001),
        make_partition(
            "dynamic",
            False,
            False,
            dynamic_config="-Z Feature=dyn",
            slurm_memory="13g",
            dampen_memory=0.75,
        ),
    ]

    writer = StringIO()
    cli._partitions(partitions, writer, autoscale=True)
    actual = "\n".join(
        [x for x in writer.getvalue().splitlines() if not x.startswith("#")]
    )
    assert (
        actual
        == """PartitionName=htc Nodes=pre-[1-100] Default=NO DefMemPerCPU=3840 MaxTime=INFINITE State=UP
Nodename=pre-[1-100] Feature=cloud STATE=CLOUD CPUs=4 ThreadsPerCore=1 RealMemory=15360
PartitionName=hpc Nodes=pre-[1-100] Default=YES DefMemPerCPU=3840 MaxTime=INFINITE State=UP
Nodename=pre-[1-100] Feature=cloud STATE=CLOUD CPUs=4 ThreadsPerCore=1 RealMemory=15360
Nodeset=dynamicns Feature=dyn
PartitionName=dynamic Nodes=dynamicns"""
    )


def test_return_to_idle() -> None:
    class MockNode:
        def __init__(self, name: str, keep_alive: bool) -> None:
            self.name = name
            self.keep_alive = keep_alive
    class MockNodeMgr:
        def __init__(self) -> None:
            self._expect = []

        def expect(self, *names: str):
            self._expect.append(set(names))

        def shutdown_nodes(self, nodes: List[MockNode]) -> ShutdownResult:
            actual = set()
            for node in nodes:
                assert not node.keep_alive
                actual.add(node.name)
            assert actual == self._expect[-1]
            self._expect.pop()

    class MockScontrol:
        def __init__(self) -> None:
            self._expect = []

        def expect(self, *args: str, **kwargs) -> None:
            self._expect.append((list(args), kwargs.get("return_value", "")))

        def __call__(self, args: List[str]) -> str:
            if args[0] == "show" and args[1] == "hostlist":
                return args[2]
            assert self._expect, f"Unexpected call to scontrol: {args}"
            expected_args, return_value = self._expect.pop()
            assert args == expected_args
            return return_value


    ccnodes_by_name = {"htc-1": MockNode("htc-1", True), "htc-2": MockNode("htc-2", False)}
    config = {}
    node_mgr = MockNodeMgr()
    scontrol_func = MockScontrol()
    snodes = [
        {"NodeName": "htc-1", "State": "POWERING_DOWN+DOWN+CLOUD"},
        {"NodeName": "htc-2", "State": "POWERED_DOWN+DOWN+CLOUD"},
        {"NodeName": "unmanaged", "State": "POWERED_DOWN+DOWN"},
    ]

    def run_test():
        cli.SlurmCLI._return_to_idle(config=config,
                                     snodes=snodes,
                                     ccnodes_by_name=ccnodes_by_name, 
                                     node_mgr=node_mgr,
                                     scontrol_func=scontrol_func,
                                    )
    node_mgr.expect("htc-2")
    scontrol_func.expect("update", "nodename=htc-2", "state=idle")
    run_test()
    ccnodes_by_name.pop("htc-2")
    snodes[1]["State"] = "POWERED_DOWN+IDLE+CLOUD"
    run_test()
    ccnodes_by_name["htc-1"].keep_alive = False
    run_test()
    config["slurm"] = {"return_to_idle": True}
    node_mgr.expect("htc-2")
    run_test()