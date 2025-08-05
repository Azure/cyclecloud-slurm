from scale_to_n_nodes import NodeScaler, NodeInvalidStateError
from mock import MockSlurmCommands, MockAzslurmTopology

def test_exit_early_if_powering_down():
    mock_slurm_commands = MockSlurmCommands()
    mock_slurm_commands.create_nodes(partition="gpu", count=30)
    mock_slurm_commands.run_command("scontrol update NodeName=gpu-6 State=POWER_DOWN")
    nodescaler = NodeScaler(partition="gpu", target_count=10, overprovision=0, slurm_commands=mock_slurm_commands,azslurm_topology=None)
    try:
        nodescaler.run()
        #nodescaler.validate_nodes()
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
    with open("/tmp/topology.conf", "r") as f:
        topology = f.read()
    assert "BlockName=block_001 Nodes=gpu-1,gpu-2,gpu-3,gpu-4,gpu-5,gpu-6,gpu-7,gpu-8,gpu-9,gpu-10,gpu-11,gpu-12,gpu-13,gpu-14,gpu-15,gpu-16,gpu-17,gpu-18" in topology

def test_scale_not_enough_healthy_nodes():
    mock_slurm_commands = MockSlurmCommands()
    mock_slurm_commands.create_nodes(partition="gpu", count=18)
    mock_slurm_commands.simulate_failed_converge(["gpu-1", "gpu-2", "gpu-3"])  # Simulate some nodes as unhealthy
    nodescaler = NodeScaler(partition="gpu", target_count=17, overprovision=0, slurm_commands=mock_slurm_commands, azslurm_topology=None)

    try:
        nodescaler.run()
        #nodescaler.validate_nodes()
        assert False, "Expected NodeInvalidStateError"
    except NodeInvalidStateError as e:
        assert e.message == "Insufficient healthy nodes: 15 < 17"