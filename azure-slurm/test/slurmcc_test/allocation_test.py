from typing import Dict, List, Tuple

from hpc.autoscale import util as hpcutil
from hpc.autoscale.ccbindings.mock import MockClusterBinding
from hpc.autoscale.node.node import Node
from slurmcc import allocation
from slurmcc import partition
from slurmcc import util as slutil
from slurmcc.partition import fetch_partitions

from . import testutil

import logging
import pytest
import sys
logging.basicConfig(level=logging.DEBUG, format="%(message)s", stream=sys.stderr)


class MockSyncNodes(allocation.SyncNodes):
    def __init__(self, ) -> None:
        super().__init__()

    def sync_nodes(
        self, slurm_nodes: allocation.SlurmNodes, cyclecloud_nodes: List[Node]
    ) -> Tuple[Dict, List[Node]]:
        return super().sync_nodes(slurm_nodes, cyclecloud_nodes)


@pytest.fixture
def suspend_exc_serializer(tmp_path):
    return allocation.SuspendExcNodesSerializer(str(tmp_path / "keep_alive.conf"))


def test_basic_resume(suspend_exc_serializer) -> None:
    node_mgr = testutil.make_test_node_manager()
    bindings: MockClusterBinding = node_mgr.cluster_bindings  # type: ignore
    partitions = fetch_partitions(node_mgr)
    native_cli = testutil.make_native_cli()
    node_list = ["hpc-1", "hpc-2", "htc-1"]

    bootup_result = allocation.resume(testutil.CONFIG, node_mgr, node_list, partitions)
    assert bootup_result
    assert bootup_result.nodes
    assert len(bootup_result.nodes) == 3
    assert list(node_list) == [n.name for n in bootup_result.nodes]
    assert 3 == len(bindings.get_nodes().nodes)
    by_name = hpcutil.partition_single(bindings.get_nodes().nodes, lambda n: n["Name"])
    assert by_name["hpc-1"]["PlacementGroupId"]
    assert by_name["hpc-2"]["PlacementGroupId"]
    assert not by_name["htc-1"]["PlacementGroupId"]

    def get_latest_nodes() -> List[Node]:
        new_node_mgr = testutil.refresh_test_node_manager(node_mgr)
        return new_node_mgr.get_nodes()
    
    assert 3 == len(get_latest_nodes())

    sync_nodes = MockSyncNodes()
    slurm_nodes = allocation.SlurmNodes(suspend_exc_serializer)
    states, ready = sync_nodes.sync_nodes(slurm_nodes, get_latest_nodes())
    assert len(ready) == 0

    bindings.assign_ip(["hpc-2", "htc-1"])
    states, ready = sync_nodes.sync_nodes(slurm_nodes, get_latest_nodes())
    assert len(ready) == 0
    assert native_cli.slurm_nodes["hpc-2"]["NodeAddr"] == "hpc-2"
    assert native_cli.slurm_nodes["htc-1"]["NodeAddr"] == "htc-1"

    bindings.update_state("Ready", ["hpc-2"])
    states, ready = sync_nodes.sync_nodes(slurm_nodes, get_latest_nodes())
    assert ["hpc-2"] == [n.name for n in ready]

    bindings.update_state("Ready", ["hpc-1", "htc-1"])
    states, ready = sync_nodes.sync_nodes(slurm_nodes, get_latest_nodes())
    # Readiness follows CycleCloud state, not IP assignment.
    assert node_list == [n.name for n in ready]

    bindings.assign_ip(["hpc-1"])
    states, ready = sync_nodes.sync_nodes(slurm_nodes, get_latest_nodes())
    assert list(node_list) == [n.name for n in ready]


def test_mixed_resume_names() -> None:
    node_mgr = testutil.make_test_node_manager()
    node_list = ["hpc-4", "hpc-20"]
    partitions = fetch_partitions(node_mgr)

    bootup_result = allocation.resume(testutil.CONFIG, node_mgr, node_list, partitions)
    assert bootup_result
    assert bootup_result.nodes
    assert len(bootup_result.nodes) == 2
    assert list(node_list) == [n.name for n in bootup_result.nodes]


@pytest.fixture(autouse=True)
def mock_is_slurmctld_up(monkeypatch) -> None:
    monkeypatch.setattr(slutil, "is_slurmctld_up", lambda: True)
    monkeypatch.setattr(slutil, "TEST_MODE", True)
    monkeypatch.setattr(slutil, "SLURM_CLI", testutil.MockNativeSlurmCLI())


def test_resume_dynamic_by_feature() -> None:

    
    node_mgr = testutil.make_test_node_manager()
    bindings: MockClusterBinding = node_mgr.cluster_bindings  # type: ignore
    native_cli = testutil.make_native_cli()
    native_cli.create_nodes(["mydynamic-1"], features=["dyn"])
    
    partitions = partition.fetch_partitions(node_mgr, include_dynamic=True)
    assert 3 == len(partitions)

    result = allocation.resume(testutil.CONFIG, node_mgr, ["mydynamic-1"], partitions)
    assert result
    assert result.nodes
    assert len(result.nodes) == 1
    assert result.nodes[0].name == "mydynamic-1"

    assert 1 == len(bindings.get_nodes().nodes)

    bindings.add_bucket(
        nodearray_name="dynamic",
        vm_size="Standard_F4",
        max_count=100,
        available_count=100,
    )

    node_mgr = testutil.refresh_test_node_manager(node_mgr)
    assert 4 == len(partition.fetch_partitions(node_mgr, include_dynamic=True))

    native_cli.create_nodes(["f2-1"], features=["dyn", "Standard_F2"])
    native_cli.create_nodes(["f4-1"], features=["dyn", "Standard_F4"])

    result = allocation.resume(testutil.CONFIG, node_mgr, ["f2-1", "f4-1"], fetch_partitions(node_mgr))
    assert result
    assert result.nodes
    assert 2 == len(result.nodes)


def test_failure_mode(suspend_exc_serializer) -> None:
    node_mgr = testutil.make_test_node_manager()
    bindings: MockClusterBinding = node_mgr.cluster_bindings  # type: ignore
    node_list = ["hpc-1", "hpc-2", "htc-1"]
    partitions = fetch_partitions(node_mgr)
    native_cli = testutil.make_native_cli()

    bootup_result = allocation.resume(testutil.CONFIG, node_mgr, node_list, partitions)
    assert bootup_result
    assert bootup_result.nodes
    assert len(bootup_result.nodes) == 3
    assert list(node_list) == [n.name for n in bootup_result.nodes]

    def get_latest_nodes() -> List[Node]:
        new_node_mgr = testutil.refresh_test_node_manager(node_mgr)
        return new_node_mgr.get_nodes()

    sync_nodes = MockSyncNodes()
    slurm_nodes = allocation.SlurmNodes(suspend_exc_serializer)
    states, ready = sync_nodes.sync_nodes(slurm_nodes, get_latest_nodes())
    assert len(ready) == 0

    bindings.assign_ip(node_list)
    states, ready = sync_nodes.sync_nodes(slurm_nodes, get_latest_nodes())

    assert native_cli.slurm_nodes["htc-1"]["NodeAddr"] == "htc-1"

    # IP changes are left to node registration, not daemon convergence.
    bindings.assign_ip(["htc-1"])
    states, ready = sync_nodes.sync_nodes(slurm_nodes, get_latest_nodes())
    assert native_cli.slurm_nodes["htc-1"]["NodeAddr"] == "htc-1"

    # A CycleCloud health failure must not take a joined Slurm node down.
    bindings.update_state("Failed", ["htc-1"])
    states, ready = sync_nodes.sync_nodes(slurm_nodes, get_latest_nodes())
    assert native_cli.slurm_nodes["htc-1"]["NodeAddr"] == "htc-1", states
    assert native_cli.slurm_nodes["htc-1"]["State"] == "idle"
    assert not ready


def test_keep_alive(suspend_exc_serializer) -> None:
    native_cli = testutil.make_native_cli()
    # add the node outside of azslurmd
    native_cli.scontrol(["update", "suspendexcnodes+=htc-1"])
    sn = allocation.SlurmNodes(suspend_exc_serializer)
    
    # node is in suspend_exc and remains there, even if we try to remove it
    assert sn.is_suspend_exc("htc-1")
    sn.unsuspend_exc_node("htc-1")
    assert sn.is_suspend_exc("htc-1")

    # now _we_ have suspended this node (i.e. KeepAlive=true was seen)
    sn.suspend_exc_node("htc-1")
    assert sn.is_suspend_exc("htc-1")
    # so now we can remove it - and it is NOT suspended
    sn.unsuspend_exc_node("htc-1")
    assert not sn.is_suspend_exc("htc-1")
