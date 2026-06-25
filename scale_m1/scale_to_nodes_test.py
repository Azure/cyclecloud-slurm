from scale_to_n_nodes import NodeScaler, NodeInvalidStateError
from mock import MockSlurmCommands, MockAzslurmTopology, MockClock
import scale_to_n_nodes
import os
import pytest


scale_to_n_nodes.CLOCK = MockClock()


@pytest.fixture(autouse=True)
def run_around_tests():
    # just create a topology that already existed

    with open("/tmp/topology.conf", "w") as fw:
        fw.write("preexisting")
    with open("/tmp/topology.conf.pre-pruning", "w") as fw:
        fw.write("preexisting")
    yield


def test_exit_early_if_powering_down():
    mock_slurm_commands = MockSlurmCommands("/tmp/topology.conf")
    mock_slurm_commands.create_nodes(partition="gpu", count=30)
    mock_slurm_commands.run_command("scontrol update NodeName=gpu-6 State=power_down")
    mock_slurm_commands.update_states(50)

    scale_to_n_nodes.create_reservation("scale_m1", "gpu", mock_slurm_commands)
    nodescaler = NodeScaler(target_count=10, overprovision=0, slurm_commands=mock_slurm_commands,azslurm_topology=None)
    try:
        nodescaler.power_up()
        nodescaler.prune_now()
        assert False, "Expected NodeInvalidStateError"
    except NodeInvalidStateError as e:
        assert e.message == "Some nodes are in POWERING_DOWN or POWERING_UP state, cannot proceed with scaling."
    _post_test(mock_slurm_commands,
               powered_up=0,
               created_a_vm=0,
               topology="preexisting")


def test_exit_early_if_powering_up():
    mock_slurm_commands = MockSlurmCommands("/tmp/topology.conf")
    mock_slurm_commands.create_nodes(partition="gpu", count=30)
    mock_slurm_commands._power_up(["gpu-6"])
    mock_slurm_commands.update_states()

    scale_to_n_nodes.create_reservation("scale_m1", "gpu", mock_slurm_commands)
    nodescaler = NodeScaler(target_count=10, overprovision=0, slurm_commands=mock_slurm_commands,azslurm_topology=None)
    try:
        nodescaler.power_up()
        nodescaler.prune_now()
        assert False, "Expected NodeInvalidStateError"
    except NodeInvalidStateError as e:
        assert e.message == "Some nodes are in POWERING_DOWN or POWERING_UP state, cannot proceed with scaling."
    _post_test(mock_slurm_commands,
               powered_up=1,
               created_a_vm=0,
               topology="preexisting")


def _post_test(mock_slurm_commands: MockSlurmCommands,
               powered_up: int,
               created_a_vm: int,
               topology: str,
               topology_pre_pruning: str = "",
               reserved: int = -1,
               draining: int = 0,
               allocated: int = 0,
               down: int = 0) -> None:
    mock_slurm_commands.update_states(1000)
    topology_pre_pruning = topology_pre_pruning or topology
    state_counts = mock_slurm_commands.node_state_counts()
    total = state_counts.pop("total")
    powered_down = total - powered_up
    if reserved < 0:
        reserved = total - allocated
    orig_state_counts = str(state_counts)
    idle = total - draining - allocated - down
    assert state_counts.pop("draining") == draining, orig_state_counts
    assert state_counts.pop("down") == down, orig_state_counts
    assert state_counts.pop("allocated") == allocated, orig_state_counts
    assert state_counts.pop("reserved") == reserved, orig_state_counts
    assert state_counts.pop("idle") == idle, orig_state_counts
    assert state_counts.pop("powered_up") == powered_up, orig_state_counts
    assert state_counts.pop("powered_down") == powered_down, orig_state_counts
    assert state_counts.pop("created_a_vm") == created_a_vm, orig_state_counts

    assert not state_counts, f"unchecked states! {state_counts}"
    with open("/tmp/topology.conf", "r") as f:
        actual_topology = f.read()

    if topology == "preexisting":
        assert topology == actual_topology
    else:
        if not topology.startswith("# Mock topology for testing"):
            topology = "# Mock topology for testing\n" + topology
        if not topology.endswith("BlockSizes=1"):
            topology += "\nBlockSizes=1"
        assert actual_topology.strip() == topology.strip()
    
    if topology_pre_pruning:
        with open("/tmp/topology.conf.pre-pruning", "r") as f:
            actual_topology = f.read()
        if topology_pre_pruning != "preexisting":
            if not topology_pre_pruning.startswith("# Mock topology for testing"):
                topology_pre_pruning = "# Mock topology for testing\n" + topology_pre_pruning
            if not topology_pre_pruning.endswith("BlockSizes=1"):
                topology_pre_pruning += "\nBlockSizes=1"
        assert actual_topology.strip() == topology_pre_pruning.strip()


def test_basic_scaling_og():
    mock_slurm_commands = MockSlurmCommands("/tmp/topology.conf")
    mock_slurm_commands.create_nodes(partition="gpu", count=18)
    mock_azslurm_topology = MockAzslurmTopology(mock_slurm_commands)

    scale_to_n_nodes.create_reservation("scale_m1", "gpu", mock_slurm_commands)
    nodescaler = NodeScaler(target_count=18, overprovision=0, topology_file="/tmp/topology.conf", slurm_commands=mock_slurm_commands, azslurm_topology=mock_azslurm_topology)

    # Run the scaling process
    nodescaler.power_up()
    nodescaler.prune_now()

    _post_test(mock_slurm_commands,
               powered_up=18,
               created_a_vm=18,
               topology="""BlockName=block_001 Nodes=gpu-1,gpu-2,gpu-3,gpu-4,gpu-5,gpu-6,gpu-7,gpu-8,gpu-9,gpu-10,gpu-11,gpu-12,gpu-13,gpu-14,gpu-15,gpu-16,gpu-17,gpu-18""")

def test_nothing_to_do_og():
    mock_slurm_commands = MockSlurmCommands("/tmp/topology.conf")
    mock_slurm_commands.create_nodes(partition="gpu", count=18)
    mock_azslurm_topology = MockAzslurmTopology(mock_slurm_commands)

    scale_to_n_nodes.create_reservation("scale_m1", "gpu", mock_slurm_commands)
    nodescaler = NodeScaler(target_count=18, overprovision=0, topology_file="/tmp/topology.conf", slurm_commands=mock_slurm_commands, azslurm_topology=mock_azslurm_topology)
    for n in range(18):
        mock_slurm_commands._power_up([f"gpu-{n+1}"])
    mock_slurm_commands.update_states(100)
    mock_slurm_commands.update_states(100)
    assert mock_slurm_commands.node_state_counts()["powered_up"] == 18
    # Run the scaling process
    nodescaler.power_up()
    nodescaler.prune_now()
    
    # there is no need to even create a reservation: all idle
    _post_test(mock_slurm_commands,
               powered_up=18,
               created_a_vm=0,
               topology="""# Mock topology for testing
BlockName=block_001 Nodes=gpu-1,gpu-2,gpu-3,gpu-4,gpu-5,gpu-6,gpu-7,gpu-8,gpu-9,gpu-10,gpu-11,gpu-12,gpu-13,gpu-14,gpu-15,gpu-16,gpu-17,gpu-18
BlockSizes=1""")


def test_basic_scaling_some_existing():
    mock_slurm_commands = MockSlurmCommands("/tmp/topology.conf")
    mock_slurm_commands.create_nodes(partition="gpu", count=18)
    mock_azslurm_topology = MockAzslurmTopology(mock_slurm_commands)

    scale_to_n_nodes.create_reservation("scale_m1", "gpu", mock_slurm_commands)
    nodescaler = NodeScaler(target_count=18, overprovision=0, topology_file="/tmp/topology.conf", slurm_commands=mock_slurm_commands, azslurm_topology=mock_azslurm_topology)
    mock_slurm_commands._power_up(["gpu-1"])
    mock_slurm_commands.update_states()
    mock_slurm_commands.update_states()
    assert mock_slurm_commands.nodes_dict["gpu-1"]["power_state"] == "POWERED_UP"
    assert scale_to_n_nodes.get_healthy_nodes("gpu", mock_slurm_commands) == ["gpu-1"]
    # Run the scaling process
    nodescaler.power_up()
    nodescaler.prune_now()
    _post_test(mock_slurm_commands,
            powered_up=18,
            created_a_vm=17,
            topology="BlockName=block_001 Nodes=gpu-1,gpu-2,gpu-3,gpu-4,gpu-5,gpu-6,gpu-7,gpu-8,gpu-9,gpu-10,gpu-11,gpu-12,gpu-13,gpu-14,gpu-15,gpu-16,gpu-17,gpu-18")


def test_basic_scaling_running_jobs():
    mock_slurm_commands = MockSlurmCommands("/tmp/topology.conf")
    mock_slurm_commands.create_nodes(partition="gpu", count=18)
    mock_azslurm_topology = MockAzslurmTopology(mock_slurm_commands)
    mock_slurm_commands._power_up(["gpu-1"])
    mock_slurm_commands.update_states()
    mock_slurm_commands.update_states()
    mock_slurm_commands.alloc_nodes(["gpu-1"])

    scale_to_n_nodes.create_reservation("scale_m1", "gpu", mock_slurm_commands)
    nodescaler = NodeScaler(target_count=18, overprovision=0, topology_file="/tmp/topology.conf", slurm_commands=mock_slurm_commands, azslurm_topology=mock_azslurm_topology)

    # Run the scaling process
    nodescaler.power_up()
    nodescaler.prune_now()
    _post_test(mock_slurm_commands,
        powered_up=18,
        created_a_vm=17,
        allocated=1,
        topology="BlockName=block_001 Nodes=gpu-1,gpu-2,gpu-3,gpu-4,gpu-5,gpu-6,gpu-7,gpu-8,gpu-9,gpu-10,gpu-11,gpu-12,gpu-13,gpu-14,gpu-15,gpu-16,gpu-17,gpu-18")


def test_basic_scaling_drained_fail():
    """
    power up a node manually, and leave it in a draining state.
    This forces the allocator to try and allocate 36 nodes instead of 18, as one that is powered up is "unhealthy"
    i.e. not in idle,allocated,or mixed.
    However - I only created 18 nodes, so we should just fail with a "not enough nodes to allocate" message.
    """
    mock_slurm_commands = MockSlurmCommands("/tmp/topology.conf")
    mock_slurm_commands.create_nodes(partition="gpu", count=18)
    mock_azslurm_topology = MockAzslurmTopology(mock_slurm_commands)
    mock_slurm_commands._power_up(["gpu-1"])
    mock_slurm_commands.update_states()
    mock_slurm_commands.update_states()
    mock_slurm_commands.drain_nodes(["gpu-1"])

    scale_to_n_nodes.create_reservation("scale_m1", "gpu", mock_slurm_commands)
    nodescaler = NodeScaler(target_count=18, overprovision=0, topology_file="/tmp/topology.conf", slurm_commands=mock_slurm_commands, azslurm_topology=mock_azslurm_topology)

    # mock_slurm_commands.run_command("")
    # Run the scaling process
    try:
        nodescaler.power_up()
        nodescaler.prune_now()
        assert False
    except scale_to_n_nodes.SlurmM1Error as e:
        assert "There are not enough nodes in a powered down state" in str(e)
    _post_test(mock_slurm_commands,
            powered_up=1,
            draining=1,
            created_a_vm=0,
            topology="preexisting")


def test_basic_scaling_drained_success():
    """
    Identical as above except we pre-create 36 nodes so it can succeed.
    """
    mock_slurm_commands = MockSlurmCommands("/tmp/topology.conf")
    mock_slurm_commands.create_nodes(partition="gpu", count=36)
    mock_azslurm_topology = MockAzslurmTopology(mock_slurm_commands)
    mock_slurm_commands._power_up(["gpu-1"])
    mock_slurm_commands.update_states()
    mock_slurm_commands.update_states()
    mock_slurm_commands.drain_nodes(["gpu-1"])

    scale_to_n_nodes.create_reservation("scale_m1", "gpu", mock_slurm_commands)
    nodescaler = NodeScaler(target_count=18, overprovision=0, topology_file="/tmp/topology.conf", slurm_commands=mock_slurm_commands, azslurm_topology=mock_azslurm_topology)

    # Run the scaling process
    
    nodescaler.power_up()
    nodescaler.prune_now()

    _post_test(mock_slurm_commands,
               powered_up=19,
               created_a_vm=35, # need 19, which means we need 36 - but less 1 drained
               draining=1,
               topology="""BlockName=block_002 Nodes=gpu-19,gpu-20,gpu-21,gpu-22,gpu-23,gpu-24,gpu-25,gpu-26,gpu-27,gpu-28,gpu-29,gpu-30,gpu-31,gpu-32,gpu-33,gpu-34,gpu-35,gpu-36
BlockSizes=1""",
               topology_pre_pruning="""# Mock topology for testing
BlockName=block_001 Nodes=gpu-2,gpu-3,gpu-4,gpu-5,gpu-6,gpu-7,gpu-8,gpu-9,gpu-10,gpu-11,gpu-12,gpu-13,gpu-14,gpu-15,gpu-16,gpu-17,gpu-18
BlockName=block_002 Nodes=gpu-19,gpu-20,gpu-21,gpu-22,gpu-23,gpu-24,gpu-25,gpu-26,gpu-27,gpu-28,gpu-29,gpu-30,gpu-31,gpu-32,gpu-33,gpu-34,gpu-35,gpu-36
BlockSizes=1""")


def test_reproduce_scale_to_19():
    """
    Identical as above except we pre-create 36 nodes so it can succeed.
    10 drained
    4 allocated
    14 idle
    goal -> 36 in powered up.
    i.e. only starting 8
    """
    mock_slurm_commands = MockSlurmCommands("/tmp/topology.conf")
    mock_slurm_commands.create_nodes(partition="gpu", count=50)
    mock_azslurm_topology = MockAzslurmTopology(mock_slurm_commands)
    for i in range(28):
        mock_slurm_commands._power_up([f"gpu-{i+1}"])
    mock_slurm_commands.update_states(50)
    mock_slurm_commands.update_states(50)

    for i in range(10):
        mock_slurm_commands.drain_nodes([f"gpu-{i+1}"])

    mock_slurm_commands.alloc_nodes([f"gpu-11", "gpu-12", "gpu-13", "gpu-14"])

    assert 18 == len(scale_to_n_nodes.get_healthy_nodes("gpu", mock_slurm_commands))
    assert mock_slurm_commands.nodes_dict["gpu-20"]["state"] == "IDLE"
    assert mock_slurm_commands.nodes_dict["gpu-20"]["power_state"] == "POWERED_UP"

    scale_to_n_nodes.create_reservation("scale_m1", "gpu", mock_slurm_commands)
    nodescaler = NodeScaler(target_count=19, overprovision=0, topology_file="/tmp/topology.conf", slurm_commands=mock_slurm_commands, azslurm_topology=mock_azslurm_topology)

    # Run the scaling process
    
    nodescaler.power_up()
    nodescaler.prune_now()

    _post_test(mock_slurm_commands,
            powered_up=19 + 10,  # targe=19 + 10 draining
            created_a_vm=8,
            draining=10,
            allocated=4,
            topology="""# Mock topology for testing
BlockName=block_001 Nodes=gpu-11,gpu-12,gpu-13,gpu-14
BlockName=block_002 Nodes=gpu-22,gpu-23,gpu-24,gpu-25,gpu-26,gpu-27,gpu-28,gpu-29,gpu-30,gpu-31,gpu-32,gpu-33,gpu-34,gpu-35,gpu-36
BlockSizes=1""",
            topology_pre_pruning="""# Mock topology for testing
BlockName=block_001 Nodes=gpu-11,gpu-12,gpu-13,gpu-14,gpu-15,gpu-16,gpu-17,gpu-18
BlockName=block_002 Nodes=gpu-19,gpu-20,gpu-21,gpu-22,gpu-23,gpu-24,gpu-25,gpu-26,gpu-27,gpu-28,gpu-29,gpu-30,gpu-31,gpu-32,gpu-33,gpu-34,gpu-35,gpu-36
BlockSizes=1""")


def test_scale_not_enough_healthy_nodes():
    mock_slurm_commands = MockSlurmCommands("/tmp/topology.conf")
    mock_slurm_commands.create_nodes(partition="gpu", count=18)
    mock_slurm_commands.simulate_failed_converge(["gpu-1", "gpu-2", "gpu-3"])  # Simulate some nodes as unhealthy

    scale_to_n_nodes.create_reservation("scale_m1", "gpu", mock_slurm_commands)
    nodescaler = NodeScaler(target_count=17, overprovision=0, slurm_commands=mock_slurm_commands, azslurm_topology="preexisting")

    try:
        nodescaler.power_up()
        nodescaler.prune_now()
        assert False, "Expected NodeInvalidStateError"
    except NodeInvalidStateError as e:
        assert e.message == "Insufficient healthy nodes: 15 < 17"
    _post_test(mock_slurm_commands,
            powered_up=15,
            created_a_vm=18,
            topology="preexisting")


def test_scale_not_enough_healthy_nodes_fail_all():
    mock_slurm_commands = MockSlurmCommands("/tmp/topology.conf")
    mock_slurm_commands.create_nodes(partition="gpu", count=18)
    node_list = [f"gpu-{i}" for i in range(1, 19)]
    mock_slurm_commands.simulate_failed_converge(node_list)  # Simulate some nodes as unhealthy

    scale_to_n_nodes.create_reservation("scale_m1", "gpu", mock_slurm_commands)
    nodescaler = NodeScaler(target_count=17, overprovision=0, slurm_commands=mock_slurm_commands, azslurm_topology="preexisting")

    try:
        nodescaler.power_up()
        nodescaler.prune_now()
        assert False, "Expected NodeInvalidStateError"
    except NodeInvalidStateError as e:
        assert e.message == "Insufficient healthy nodes: 0 < 17"
    
    _post_test(mock_slurm_commands,
               powered_up=0,
               created_a_vm=18,
               topology="preexisting")


def test_successful_over_alloc():
    mock_slurm_commands = MockSlurmCommands("/tmp/topology.conf")
    mock_slurm_commands.create_nodes(partition="gpu", count=40)
    node_list = [f"gpu-{i}" for i in range(1, 6)] + [f"gpu-{i}" for i in range(20, 26)] 
    mock_slurm_commands.simulate_failed_converge(node_list)  # Simulate some nodes as unhealthy
    mock_azslurm_topology = MockAzslurmTopology(mock_slurm_commands)

    scale_to_n_nodes.create_reservation("scale_m1", "gpu", mock_slurm_commands)
    nodescaler = NodeScaler(target_count=17, overprovision=18, topology_file="/tmp/topology.conf", slurm_commands=mock_slurm_commands, azslurm_topology=mock_azslurm_topology)

    nodescaler.power_up()
    nodescaler.prune_now()

    _post_test(mock_slurm_commands,
                powered_up=17,
                created_a_vm=36,
                topology="""# Mock topology for testing
BlockName=block_001 Nodes=gpu-6,gpu-7,gpu-8,gpu-9,gpu-10,gpu-11,gpu-12,gpu-13,gpu-14,gpu-15,gpu-16,gpu-17,gpu-18
BlockName=block_002 Nodes=gpu-33,gpu-34,gpu-35,gpu-36
BlockSizes=1""",
                topology_pre_pruning="""# Mock topology for testing
BlockName=block_001 Nodes=gpu-6,gpu-7,gpu-8,gpu-9,gpu-10,gpu-11,gpu-12,gpu-13,gpu-14,gpu-15,gpu-16,gpu-17,gpu-18
BlockName=block_002 Nodes=gpu-19,gpu-26,gpu-27,gpu-28,gpu-29,gpu-30,gpu-31,gpu-32,gpu-33,gpu-34,gpu-35,gpu-36
BlockSizes=1""")
    

def test_termination_with_running_jobs():
    mock_slurm_commands = MockSlurmCommands("/tmp/topology.conf")
    mock_slurm_commands.create_nodes(partition="gpu", count=19)
    for n in range(18):
        mock_slurm_commands._power_up([f"gpu-{n + 1}"])
    mock_slurm_commands.update_states(50)
    mock_slurm_commands.update_states(50)

    for n in range(18):
        mock_slurm_commands.alloc_nodes([f"gpu-{n + 1}"])

    mock_azslurm_topology = MockAzslurmTopology(mock_slurm_commands)

    scale_to_n_nodes.create_reservation("scale_m1", "gpu", mock_slurm_commands)
    nodescaler = NodeScaler(target_count=1, overprovision=0, topology_file="/tmp/topology.conf", slurm_commands=mock_slurm_commands, azslurm_topology=mock_azslurm_topology)
    nodescaler.power_up()
    nodescaler.prune_now()

    _post_test(mock_slurm_commands,
               powered_up=18,
               created_a_vm=0,
               allocated=18,
               reserved=1,
               topology="""# Mock topology for testing
BlockName=block_001 Nodes=gpu-1,gpu-2,gpu-3,gpu-4,gpu-5,gpu-6,gpu-7,gpu-8,gpu-9,gpu-10,gpu-11,gpu-12,gpu-13,gpu-14,gpu-15,gpu-16,gpu-17,gpu-18
BlockSizes=1""")


def test_basic_scaling_large_delete():
    mock_slurm_commands = MockSlurmCommands("/tmp/topology.conf")
    mock_slurm_commands.create_nodes(partition="gpu", count=54)
    mock_azslurm_topology = MockAzslurmTopology(mock_slurm_commands)

    scale_to_n_nodes.create_reservation("scale_m1", "gpu", mock_slurm_commands)
    nodescaler = NodeScaler(target_count=18, overprovision=36, topology_file="/tmp/topology.conf", slurm_commands=mock_slurm_commands, azslurm_topology=mock_azslurm_topology)

    # Run the scaling process
    nodescaler.power_up()
    nodescaler.prune_now()
    
    _post_test(mock_slurm_commands,
            powered_up=18,
            created_a_vm=54,
            topology="""# Mock topology for testing
BlockName=block_003 Nodes=gpu-37,gpu-38,gpu-39,gpu-40,gpu-41,gpu-42,gpu-43,gpu-44,gpu-45,gpu-46,gpu-47,gpu-48,gpu-49,gpu-50,gpu-51,gpu-52,gpu-53,gpu-54
BlockSizes=1""",
            topology_pre_pruning="""# Mock topology for testing
BlockName=block_001 Nodes=gpu-1,gpu-2,gpu-3,gpu-4,gpu-5,gpu-6,gpu-7,gpu-8,gpu-9,gpu-10,gpu-11,gpu-12,gpu-13,gpu-14,gpu-15,gpu-16,gpu-17,gpu-18
BlockName=block_002 Nodes=gpu-19,gpu-20,gpu-21,gpu-22,gpu-23,gpu-24,gpu-25,gpu-26,gpu-27,gpu-28,gpu-29,gpu-30,gpu-31,gpu-32,gpu-33,gpu-34,gpu-35,gpu-36
BlockName=block_003 Nodes=gpu-37,gpu-38,gpu-39,gpu-40,gpu-41,gpu-42,gpu-43,gpu-44,gpu-45,gpu-46,gpu-47,gpu-48,gpu-49,gpu-50,gpu-51,gpu-52,gpu-53,gpu-54
BlockSizes=1""")
    

def test_basic_scaling_with_reserved_noop():
    """
    leave gpu-[19-36] as still reserved - it should be a no-op
    """
    mock_slurm_commands = MockSlurmCommands("/tmp/topology.conf")
    mock_slurm_commands.create_nodes(partition="gpu", count=54)
    mock_azslurm_topology = MockAzslurmTopology(mock_slurm_commands)
    for n in range(18, 36):
        mock_slurm_commands._power_up([f"gpu-{n+1}"])
    mock_slurm_commands.update_states(30)
    mock_slurm_commands.update_states(30)
    for n in range(18, 36):
        mock_slurm_commands.reserve_nodes([f"gpu-{n+1}"])

    scale_to_n_nodes.create_reservation("scale_m1", "gpu", mock_slurm_commands)
    nodescaler = NodeScaler(target_count=18, overprovision=36, topology_file="/tmp/topology.conf", slurm_commands=mock_slurm_commands, azslurm_topology=mock_azslurm_topology)

    # Run the scaling process
    nodescaler.power_up()
    nodescaler.prune_now()
    
    _post_test(mock_slurm_commands,
            powered_up=18,
            created_a_vm=0,  # 18 were already started, it is a noop
            topology="""# Mock topology for testing
BlockName=block_002 Nodes=gpu-19,gpu-20,gpu-21,gpu-22,gpu-23,gpu-24,gpu-25,gpu-26,gpu-27,gpu-28,gpu-29,gpu-30,gpu-31,gpu-32,gpu-33,gpu-34,gpu-35,gpu-36
BlockSizes=1""")
    

def test_basic_scaling_with_reserved_og():
    """
    leave gpu-[19-30] as still reserved - it should include 19-30 and others
    """
    mock_slurm_commands = MockSlurmCommands("/tmp/topology.conf")
    mock_slurm_commands.create_nodes(partition="gpu", count=54)
    mock_azslurm_topology = MockAzslurmTopology(mock_slurm_commands)
    for n in range(18, 30):
        mock_slurm_commands._power_up([f"gpu-{n+1}"])
    mock_slurm_commands.update_states(30)
    mock_slurm_commands.update_states(30)
    for n in range(18, 30):
        mock_slurm_commands.reserve_nodes([f"gpu-{n+1}"])

    scale_to_n_nodes.create_reservation("scale_m1", "gpu", mock_slurm_commands)
    nodescaler = NodeScaler(target_count=18, overprovision=36, topology_file="/tmp/topology.conf", slurm_commands=mock_slurm_commands, azslurm_topology=mock_azslurm_topology)

    # Run the scaling process
    nodescaler.power_up()
    nodescaler.prune_now()
    _post_test(mock_slurm_commands,
               powered_up=18,
               created_a_vm=42,  # 12 were already started
               topology="""# Mock topology for testing
BlockName=block_002 Nodes=gpu-19,gpu-20,gpu-21,gpu-22,gpu-23,gpu-24,gpu-25,gpu-26,gpu-27,gpu-28,gpu-29,gpu-30
BlockName=block_003 Nodes=gpu-49,gpu-50,gpu-51,gpu-52,gpu-53,gpu-54
BlockSizes=1""",
                topology_pre_pruning="""# Mock topology for testing
BlockName=block_001 Nodes=gpu-1,gpu-2,gpu-3,gpu-4,gpu-5,gpu-6,gpu-7,gpu-8,gpu-9,gpu-10,gpu-11,gpu-12,gpu-13,gpu-14,gpu-15,gpu-16,gpu-17,gpu-18
BlockName=block_002 Nodes=gpu-19,gpu-20,gpu-21,gpu-22,gpu-23,gpu-24,gpu-25,gpu-26,gpu-27,gpu-28,gpu-29,gpu-30,gpu-31,gpu-32,gpu-33,gpu-34,gpu-35,gpu-36
BlockName=block_003 Nodes=gpu-37,gpu-38,gpu-39,gpu-40,gpu-41,gpu-42,gpu-43,gpu-44,gpu-45,gpu-46,gpu-47,gpu-48,gpu-49,gpu-50,gpu-51,gpu-52,gpu-53,gpu-54
BlockSizes=1""")