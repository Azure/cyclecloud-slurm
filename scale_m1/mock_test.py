from mock import MockAzslurmTopology, MockSlurmCommands
def test_generate_single_block():
    mock_slurm_commands = MockSlurmCommands()
    mock_slurm_commands.create_nodes(partition="gpu", count=18)
    mock_topology = MockAzslurmTopology(mock_slurm_commands)
    result = mock_topology.generate_topology("gpu", "topology.txt")
    with open("topology.txt", "r") as f:
        content = f.read()
    assert "BlockName=block_001 Nodes=gpu-1,gpu-2,gpu-3,gpu-4,gpu-5,gpu-6,gpu-7,gpu-8,gpu-9,gpu-10,gpu-11,gpu-12,gpu-13,gpu-14,gpu-15,gpu-16,gpu-17,gpu-18" in content