from scale_to_n_nodes import NodeScaler, NodeInvalidStateError
from mock import MockSlurmCommands, MockAzslurmTopology, MockClock
import scale_to_n_nodes


scale_to_n_nodes.CLOCK = MockClock()


def test_exit_early_if_powering_down():
    mock_slurm_commands = MockSlurmCommands()
    mock_slurm_commands.create_nodes(partition="gpu", count=30)
    mock_slurm_commands.run_command("scontrol update NodeName=gpu-6 State=power_down")
    mock_slurm_commands.update_states(50)
    nodescaler = NodeScaler(partition="gpu", target_count=10, overprovision=0, slurm_commands=mock_slurm_commands,azslurm_topology=None)
    try:
        nodescaler.run()
        assert False, "Expected NodeInvalidStateError"
    except NodeInvalidStateError as e:
        assert e.message == "Some nodes are in POWERING_DOWN state, cannot proceed with scaling."


def test_basic_scaling():
    mock_slurm_commands = MockSlurmCommands()
    mock_slurm_commands.create_nodes(partition="gpu", count=18)
    mock_azslurm_topology = MockAzslurmTopology(mock_slurm_commands)
    nodescaler = NodeScaler(partition="gpu", target_count=18, overprovision=0, topology_file="/tmp/topology.conf", slurm_commands=mock_slurm_commands, azslurm_topology=mock_azslurm_topology)

    # Run the scaling process
    nodescaler.run()
    
    # Validate that the scaling was successful
    assert all(node['state'] == 'IDLE' for node in mock_slurm_commands.nodes_dict.values())
    assert all(node['power_state'] == 'POWERED_UP' for node in mock_slurm_commands.nodes_dict.values())
    with open("/tmp/topology.conf", "r") as f:
        topology = f.read()
    assert "BlockName=block_001 Nodes=gpu-1,gpu-2,gpu-3,gpu-4,gpu-5,gpu-6,gpu-7,gpu-8,gpu-9,gpu-10,gpu-11,gpu-12,gpu-13,gpu-14,gpu-15,gpu-16,gpu-17,gpu-18" in topology


def test_nothing_to_do():
    mock_slurm_commands = MockSlurmCommands()
    mock_slurm_commands.create_nodes(partition="gpu", count=18)
    mock_azslurm_topology = MockAzslurmTopology(mock_slurm_commands)
    nodescaler = NodeScaler(partition="gpu", target_count=18, overprovision=0, topology_file="/tmp/topology.conf", slurm_commands=mock_slurm_commands, azslurm_topology=mock_azslurm_topology)
    for n in range(18):
        mock_slurm_commands._power_up([f"gpu-{n+1}"])
    mock_slurm_commands.update_states()
    mock_slurm_commands.update_states()
    # Run the scaling process
    nodescaler.run()
    
    # Validate that the scaling was successful
    assert all(node['state'] == 'IDLE' for node in mock_slurm_commands.nodes_dict.values())
    assert all(node['power_state'] == 'POWERED_UP' for node in mock_slurm_commands.nodes_dict.values())
    with open("/tmp/topology.conf", "r") as f:
        topology = f.read()
    assert "BlockName=block_001 Nodes=gpu-1,gpu-2,gpu-3,gpu-4,gpu-5,gpu-6,gpu-7,gpu-8,gpu-9,gpu-10,gpu-11,gpu-12,gpu-13,gpu-14,gpu-15,gpu-16,gpu-17,gpu-18" in topology


def test_basic_scaling_some_existing():
    mock_slurm_commands = MockSlurmCommands()
    mock_slurm_commands.create_nodes(partition="gpu", count=18)
    mock_azslurm_topology = MockAzslurmTopology(mock_slurm_commands)
    nodescaler = NodeScaler(partition="gpu", target_count=18, overprovision=0, topology_file="/tmp/topology.conf", slurm_commands=mock_slurm_commands, azslurm_topology=mock_azslurm_topology)
    mock_slurm_commands._power_up(["gpu-1"])
    mock_slurm_commands.update_states()
    mock_slurm_commands.update_states()
    assert mock_slurm_commands.nodes_dict["gpu-1"]["power_state"] == "POWERED_UP"
    assert scale_to_n_nodes.get_healthy_nodes("gpu", mock_slurm_commands) == ["gpu-1"]
    # Run the scaling process
    nodescaler.run()
    
    # Validate that the scaling was successful
    assert all(node['state'] == 'IDLE' for node in mock_slurm_commands.nodes_dict.values())
    assert all(node['power_state'] == 'POWERED_UP' for node in mock_slurm_commands.nodes_dict.values())
    with open("/tmp/topology.conf", "r") as f:
        topology = f.read()
    assert "BlockName=block_001 Nodes=gpu-1,gpu-2,gpu-3,gpu-4,gpu-5,gpu-6,gpu-7,gpu-8,gpu-9,gpu-10,gpu-11,gpu-12,gpu-13,gpu-14,gpu-15,gpu-16,gpu-17,gpu-18" in topology


def test_basic_scaling_running_jobs():
    mock_slurm_commands = MockSlurmCommands()
    mock_slurm_commands.create_nodes(partition="gpu", count=18)
    mock_azslurm_topology = MockAzslurmTopology(mock_slurm_commands)
    mock_slurm_commands._power_up(["gpu-1"])
    mock_slurm_commands.update_states()
    mock_slurm_commands.update_states()
    mock_slurm_commands.alloc_nodes(["gpu-1"])
    nodescaler = NodeScaler(partition="gpu", target_count=18, overprovision=0, topology_file="/tmp/topology.conf", slurm_commands=mock_slurm_commands, azslurm_topology=mock_azslurm_topology)

    # Run the scaling process
    nodescaler.run()
    
    # Validate that the scaling was successful
    # assert all(node['state'] == 'IDLE' for node in mock_slurm_commands.nodes_dict.values())
    assert all(node['power_state'] == 'POWERED_UP' for node in mock_slurm_commands.nodes_dict.values())
    with open("/tmp/topology.conf", "r") as f:
        topology = f.read()
    assert "BlockName=block_001 Nodes=gpu-1,gpu-2,gpu-3,gpu-4,gpu-5,gpu-6,gpu-7,gpu-8,gpu-9,gpu-10,gpu-11,gpu-12,gpu-13,gpu-14,gpu-15,gpu-16,gpu-17,gpu-18" in topology


def test_basic_scaling_drained_fail():
    """
    power up a node manually, and leave it in a draining state.
    This forces the allocator to try and allocate 36 nodes instead of 18, as one that is powered up is "unhealthy"
    i.e. not in idle,allocated,or mixed.
    However - I only created 18 nodes, so we should just fail with a "not enough nodes to allocate" message.
    """
    mock_slurm_commands = MockSlurmCommands()
    mock_slurm_commands.create_nodes(partition="gpu", count=18)
    mock_azslurm_topology = MockAzslurmTopology(mock_slurm_commands)
    mock_slurm_commands._power_up(["gpu-1"])
    mock_slurm_commands.update_states()
    mock_slurm_commands.update_states()
    mock_slurm_commands.drain_nodes(["gpu-1"])
    nodescaler = NodeScaler(partition="gpu", target_count=18, overprovision=0, topology_file="/tmp/topology.conf", slurm_commands=mock_slurm_commands, azslurm_topology=mock_azslurm_topology)

    # mock_slurm_commands.run_command("")
    # Run the scaling process
    try:
        nodescaler.run()
        assert False
    except scale_to_n_nodes.SlurmM1Error as e:
        assert "There are not enough nodes in a powered down state" in str(e)


def test_basic_scaling_drained_success():
    """
    Identical as above except we pre-create 36 nodes so it can succeed.
    """
    mock_slurm_commands = MockSlurmCommands()
    mock_slurm_commands.create_nodes(partition="gpu", count=36)
    mock_azslurm_topology = MockAzslurmTopology(mock_slurm_commands)
    mock_slurm_commands._power_up(["gpu-1"])
    mock_slurm_commands.update_states()
    mock_slurm_commands.update_states()
    mock_slurm_commands.drain_nodes(["gpu-1"])
    nodescaler = NodeScaler(partition="gpu", target_count=18, overprovision=0, topology_file="/tmp/topology.conf", slurm_commands=mock_slurm_commands, azslurm_topology=mock_azslurm_topology)

    # Run the scaling process
    
    nodescaler.run()

    with open("/tmp/topology.conf", "r") as f:
        topology = f.read()
    assert """BlockName=block_002 Nodes=gpu-19,gpu-20,gpu-21,gpu-22,gpu-23,gpu-24,gpu-25,gpu-26,gpu-27,gpu-28,gpu-29,gpu-30,gpu-31,gpu-32,gpu-33,gpu-34,gpu-35,gpu-36
BlockSizes=1""" in topology


def test_reproduce_scale_to_19():
    """
    Identical as above except we pre-create 36 nodes so it can succeed.
    10 drained
    4 allocated
    14 idle
    goal -> 36 in powered up.
    i.e. only starting 8
    """
    mock_slurm_commands = MockSlurmCommands()
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
    # 4 allocated
    assert 4 == len(scale_to_n_nodes.get_healthy_but_not_idle_nodes("gpu", mock_slurm_commands))
    assert 10 == len(scale_to_n_nodes.get_unhealthy_nodes("gpu", mock_slurm_commands))

    nodescaler = NodeScaler(partition="gpu", target_count=19, overprovision=0, topology_file="/tmp/topology.conf", slurm_commands=mock_slurm_commands, azslurm_topology=mock_azslurm_topology)

    # Run the scaling process
    
    nodescaler.run()

    with open("/tmp/topology.conf", "r") as f:
        topology = f.read()
    assert """# Mock topology for testing
BlockName=block_001 Nodes=gpu-11,gpu-12,gpu-13,gpu-14
BlockName=block_002 Nodes=gpu-22,gpu-23,gpu-24,gpu-25,gpu-26,gpu-27,gpu-28,gpu-29,gpu-30,gpu-31,gpu-32,gpu-33,gpu-34,gpu-35,gpu-36
BlockSizes=1""" in topology


def test_scale_not_enough_healthy_nodes():
    mock_slurm_commands = MockSlurmCommands()
    mock_slurm_commands.create_nodes(partition="gpu", count=18)
    mock_slurm_commands.simulate_failed_converge(["gpu-1", "gpu-2", "gpu-3"])  # Simulate some nodes as unhealthy
    nodescaler = NodeScaler(partition="gpu", target_count=17, overprovision=0, slurm_commands=mock_slurm_commands, azslurm_topology=None)

    try:
        nodescaler.run()
        assert False, "Expected NodeInvalidStateError"
    except NodeInvalidStateError as e:
        assert e.message == "Insufficient healthy nodes: 15 < 17"


def test_scale_not_enough_healthy_nodes_fail_all():
    mock_slurm_commands = MockSlurmCommands()
    mock_slurm_commands.create_nodes(partition="gpu", count=18)
    node_list = [f"gpu-{i}" for i in range(1, 19)]
    mock_slurm_commands.simulate_failed_converge(node_list)  # Simulate some nodes as unhealthy
    nodescaler = NodeScaler(partition="gpu", target_count=17, overprovision=0, slurm_commands=mock_slurm_commands, azslurm_topology=None)

    try:
        nodescaler.run()
        assert False, "Expected NodeInvalidStateError"
    except NodeInvalidStateError as e:
        assert e.message == "Insufficient healthy nodes: 0 < 17"


def test_successful_over_alloc():
    mock_slurm_commands = MockSlurmCommands()
    mock_slurm_commands.create_nodes(partition="gpu", count=40)
    node_list = [f"gpu-{i}" for i in range(1, 6)] + [f"gpu-{i}" for i in range(20, 26)] 
    mock_slurm_commands.simulate_failed_converge(node_list)  # Simulate some nodes as unhealthy
    mock_azslurm_topology = MockAzslurmTopology(mock_slurm_commands)
    nodescaler = NodeScaler(partition="gpu", target_count=17, overprovision=18, topology_file="/tmp/topology.conf", slurm_commands=mock_slurm_commands, azslurm_topology=mock_azslurm_topology)

    nodescaler.run()

    with open("/tmp/topology.conf", "r") as f:
        topology = f.read()
    assert """# Mock topology for testing
BlockName=block_001 Nodes=gpu-6,gpu-7,gpu-8,gpu-9,gpu-10,gpu-11,gpu-12,gpu-13,gpu-14,gpu-15,gpu-16,gpu-17,gpu-18
BlockName=block_002 Nodes=gpu-33,gpu-34,gpu-35,gpu-36
BlockSizes=1""" in topology
    

def test_termination_with_running_jobs():
    mock_slurm_commands = MockSlurmCommands()
    mock_slurm_commands.create_nodes(partition="gpu", count=18)
    for n in range(18):
        mock_slurm_commands._power_up([f"gpu-{n + 1}"])
    mock_slurm_commands.update_states(50)
    mock_slurm_commands.update_states(50)

    for n in range(18):
        mock_slurm_commands.alloc_nodes([f"gpu-{n + 1}"])

    mock_azslurm_topology = MockAzslurmTopology(mock_slurm_commands)
    nodescaler = NodeScaler(partition="gpu", target_count=1, overprovision=0, topology_file="/tmp/topology.conf", slurm_commands=mock_slurm_commands, azslurm_topology=mock_azslurm_topology)

    nodescaler.run()

    assert 18 == len(scale_to_n_nodes.get_powered_up_nodes("gpu", mock_slurm_commands))

    # topology is not generated in this case


def test_basic_scaling_large_delete():
    mock_slurm_commands = MockSlurmCommands()
    mock_slurm_commands.create_nodes(partition="gpu", count=54)
    mock_azslurm_topology = MockAzslurmTopology(mock_slurm_commands)
    nodescaler = NodeScaler(partition="gpu", target_count=18, overprovision=36, topology_file="/tmp/topology.conf", slurm_commands=mock_slurm_commands, azslurm_topology=mock_azslurm_topology)

    # Run the scaling process
    nodescaler.run()
    
    # Validate that the scaling was successful
    assert all(node['state'] == 'IDLE' for node in mock_slurm_commands.nodes_dict.values())
    # assert all(node['power_state'] == 'POWERED_UP' for node in mock_slurm_commands.nodes_dict.values())
    with open("/tmp/topology.conf", "r") as f:
        topology = f.read()
    assert """# Mock topology for testing
BlockName=block_003 Nodes=gpu-37,gpu-38,gpu-39,gpu-40,gpu-41,gpu-42,gpu-43,gpu-44,gpu-45,gpu-46,gpu-47,gpu-48,gpu-49,gpu-50,gpu-51,gpu-52,gpu-53,gpu-54
BlockSizes=1""" in topology
    

def test_basic_scaling_with_reserved_noop():
    """
    leave gpu-[19-36] as still reserved - it should be a no-op
    """
    mock_slurm_commands = MockSlurmCommands()
    mock_slurm_commands.create_nodes(partition="gpu", count=54)
    mock_azslurm_topology = MockAzslurmTopology(mock_slurm_commands)
    for n in range(18, 36):
        mock_slurm_commands._power_up([f"gpu-{n+1}"])
    mock_slurm_commands.update_states(30)
    mock_slurm_commands.update_states(30)
    for n in range(18, 36):
        mock_slurm_commands.reserve_nodes([f"gpu-{n+1}"])

    nodescaler = NodeScaler(partition="gpu", target_count=18, overprovision=36, topology_file="/tmp/topology.conf", slurm_commands=mock_slurm_commands, azslurm_topology=mock_azslurm_topology)

    # Run the scaling process
    nodescaler.run()
    
    # assert all(node['power_state'] == 'POWERED_UP' for node in mock_slurm_commands.nodes_dict.values())
    with open("/tmp/topology.conf", "r") as f:
        topology = f.read()
    assert """# Mock topology for testing
BlockName=block_002 Nodes=gpu-19,gpu-20,gpu-21,gpu-22,gpu-23,gpu-24,gpu-25,gpu-26,gpu-27,gpu-28,gpu-29,gpu-30,gpu-31,gpu-32,gpu-33,gpu-34,gpu-35,gpu-36
BlockSizes=1""" in topology
    

def test_basic_scaling_with_reserved():
    """
    leave gpu-[19-30] as still reserved - it should include 19-30 and others
    """
    mock_slurm_commands = MockSlurmCommands()
    mock_slurm_commands.create_nodes(partition="gpu", count=54)
    mock_azslurm_topology = MockAzslurmTopology(mock_slurm_commands)
    for n in range(18, 30):
        mock_slurm_commands._power_up([f"gpu-{n+1}"])
    mock_slurm_commands.update_states(30)
    mock_slurm_commands.update_states(30)
    for n in range(18, 30):
        mock_slurm_commands.reserve_nodes([f"gpu-{n+1}"])

    nodescaler = NodeScaler(partition="gpu", target_count=18, overprovision=36, topology_file="/tmp/topology.conf", slurm_commands=mock_slurm_commands, azslurm_topology=mock_azslurm_topology)

    # Run the scaling process
    nodescaler.run()
    
    # assert all(node['power_state'] == 'POWERED_UP' for node in mock_slurm_commands.nodes_dict.values())
    with open("/tmp/topology.conf", "r") as f:
        topology = f.read()
    assert """# Mock topology for testing
BlockName=block_002 Nodes=gpu-19,gpu-20,gpu-21,gpu-22,gpu-23,gpu-24,gpu-25,gpu-26,gpu-27,gpu-28,gpu-29,gpu-30
BlockName=block_003 Nodes=gpu-49,gpu-50,gpu-51,gpu-52,gpu-53,gpu-54
BlockSizes=1""" in topology