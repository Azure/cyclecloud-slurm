from slurmcc import azslurmd
from slurmcc import util as slutil
from slurmcc_test import testutil
from slurmcc.azslurmd import NodeSource
from hpc.autoscale.node.node import Node
from hpc.autoscale.node.nodemanager import NodeManager
from typing import Optional
import pytest


class MockNodeSource(NodeSource):
    def __init__(self, bindings: testutil.MockClusterBinding) -> None:
        self.node_mgr = testutil.make_test_node_manager_with_bindings(bindings)

    def get_nodes(self) -> list[Node]:
        return self.node_mgr.get_nodes()


class MockNode:
    def __init__(
        self,
        name: str,
        status: str,
        private_ip: Optional[str] = None,
        software_configuration: Optional[dict] = None,
    ) -> None:
        self.name = name
        self.status = status
        self.state = status
        self.target_state = "Ready"
        self.private_ip = private_ip
        self.software_configuration = software_configuration or {}


@pytest.fixture()
def bindings(setup_slurm: None) -> testutil.MockClusterBinding:
    return testutil.make_test_node_manager().cluster_bindings


@pytest.fixture()
def setup_slurm() -> None:
    testutil.make_native_cli(False)
    slutil.SLURM_CLI.create_nodes(["hpc-1", "hpc-2"], features=["CLOUD"])
    assert slutil.SLURM_CLI.slurm_nodes["hpc-1"]["State"] == "idle"
    return None


def test_noop(bindings: testutil.MockClusterBinding) -> None:
    # return an empty list of nodes - nothing to do
    azslurmd.AzslurmDaemon(MockNodeSource(bindings)).run_once()


def test_one_ready_node(bindings: testutil.MockClusterBinding) -> None:
    bindings.add_node(
        name="hpc-1", nodearray="hpc", state="Ready", target_state="Started"
    )

    azslurmd.AzslurmDaemon(MockNodeSource(bindings)).run_once()


def test_one_not_ready_node_no_ip(bindings: testutil.MockClusterBinding) -> None:
    bindings.add_node(
        name="hpc-1", nodearray="hpc", state="Allocation", target_state="Started"
    )
    azslurmd.AzslurmDaemon(MockNodeSource(bindings)).run_once()


def test_one_not_ready_node_with_ip(bindings: testutil.MockClusterBinding) -> None:
    bindings.add_node(
        name="hpc-1", nodearray="hpc", state="Allocation", target_state="Started"
    )

    bindings.assign_ip(["hpc-1"])
    azslurmd.AzslurmDaemon(MockNodeSource(bindings)).run_once()


def test_one_ready_node_with_ip(bindings: testutil.MockClusterBinding) -> None:
    bindings.add_node(
        name="hpc-1", nodearray="hpc", state="Ready", target_state="Started"
    )
    bindings.assign_ip(["hpc-1"])
    azslurmd.AzslurmDaemon(MockNodeSource(bindings)).run_once()


def test_one_ready_node_with_ip_internal_dns(
    bindings: testutil.MockClusterBinding,
) -> None:
    from slurmcc import allocation
    allocation.BEGIN_TEST = True
    node = bindings.add_node(
        name="hpc-1", nodearray="hpc", state="Ready", target_state="Started"
    )
    bindings.assign_ip(["hpc-1"])
    node.software_configuration["slurm"]["use_nodename_as_hostname"] = False
    assert not node.software_configuration["slurm"]["use_nodename_as_hostname"]
    azslurmd.AzslurmDaemon(MockNodeSource(bindings)).run_once()
    assert node.private_ip, "node should have a private IP address"
    assert (
        slutil.SLURM_CLI.slurm_nodes["hpc-1"]["NodeAddr"] == node.private_ip
    ), f"NodeAddr should be the private IP address - got {slutil.SLURM_CLI.slurm_nodes['hpc-1']['NodeAddr']}"



def test_one_failed_node_with_ip(bindings: testutil.MockClusterBinding) -> None:
    hpc1 = bindings.add_node(
        name="hpc-1", nodearray="hpc", state="Allocation", target_state="Started"
    )
    bindings.assign_ip(["hpc-1"])
    hpc1.software_configuration["slurm"]["use_nodename_as_hostname"] = False
    
    azslurmd.AzslurmDaemon(MockNodeSource(bindings)).run_once()
    assert slutil.SLURM_CLI.slurm_nodes["hpc-1"]["State"] == "idle"
    assert slutil.SLURM_CLI.slurm_nodes["hpc-1"]["NodeAddr"] == hpc1.private_ip, "NodeAddr should be the private IP address"

    bindings.update_state("Failed", ["hpc-1"])
    azslurmd.AzslurmDaemon(MockNodeSource(bindings)).run_once()

    assert slutil.SLURM_CLI.slurm_nodes["hpc-1"]["State"] == "down", "Should be marked down because it failed"
    assert slutil.SLURM_CLI.slurm_nodes["hpc-1"]["Reason"] == "cyclecloud_node_failure"

    bindings.update_state("Ready", ["hpc-1"])
    azslurmd.AzslurmDaemon(MockNodeSource(bindings)).run_once()
    assert slutil.SLURM_CLI.slurm_nodes["hpc-1"]["State"] == "idle", "node should be recovered %s" % SLURM_CLI.slurm_nodes["hpc-1"]
    assert slutil.SLURM_CLI.slurm_nodes["hpc-1"]["Reason"] == "cyclecloud_node_recovery"


def test_node_goes_missing(bindings: testutil.MockClusterBinding) -> None:
    bindings.add_node(
        name="hpc-1", nodearray="hpc", state="Ready", target_state="Started"
    )
    bindings.assign_ip(["hpc-1"])
    azslurmd.AzslurmDaemon(MockNodeSource(bindings)).run_once()

    # remove the node from the cluster
    bindings.shutdown_nodes(names=["hpc-1"])
    azslurmd.AzslurmDaemon(MockNodeSource(bindings)).run_once()

    assert slutil.SLURM_CLI.slurm_nodes["hpc-1"]["State"] == "down"
    assert slutil.SLURM_CLI.slurm_nodes["hpc-1"]["Reason"] == "cyclecloud_node_failure"


def test_node_goes_missing_with_ip(bindings: testutil.MockClusterBinding) -> None:
    node = bindings.add_node(
        name="hpc-1", nodearray="hpc", state="Ready", target_state="Started"
    )
    bindings.assign_ip(["hpc-1"])
    node.software_configuration["slurm"]["use_nodename_as_hostname"] = False
    azslurmd.AzslurmDaemon(MockNodeSource(bindings)).run_once()
    assert slutil.SLURM_CLI.slurm_nodes["hpc-1"]["NodeAddr"] == node.private_ip, "NodeAddr should be the private IP address"
    # remove the node from cyclecloud
    bindings.shutdown_nodes(names=["hpc-1"])
    azslurmd.AzslurmDaemon(MockNodeSource(bindings)).run_once()

    assert slutil.SLURM_CLI.slurm_nodes["hpc-1"]["State"] == "down"
    assert slutil.SLURM_CLI.slurm_nodes["hpc-1"]["Reason"] == "cyclecloud_node_failure"
    assert slutil.SLURM_CLI.slurm_nodes["hpc-1"]["NodeAddr"] == "hpc-1"


def test_zombie_node(bindings: testutil.MockClusterBinding) -> None:
    bindings.add_node(
        name="hpc-1", nodearray="hpc", state="Ready", target_state="Started"
    )
    azslurmd.AzslurmDaemon(MockNodeSource(bindings)).run_once()

    # change the node state in slurm to powered / powering_down
    slutil.SLURM_CLI.scontrol(["update", "NodeName=hpc-1", "State=powered_down"])
    azslurmd.AzslurmDaemon(MockNodeSource(bindings)).run_once()

    assert slutil.SLURM_CLI.slurm_nodes["hpc-1"]["State"] == "down"
    assert slutil.SLURM_CLI.slurm_nodes["hpc-1"]["Reason"] == "cyclecloud_zombie_node"
    assert slutil.SLURM_CLI.slurm_nodes["hpc-1"]["NodeAddr"] == "hpc-1"