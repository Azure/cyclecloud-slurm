from mock import MockAzslurmTopology, MockSlurmCommands

import scale_to_n_nodes


def test_scontrol_power_down():
    mock_slurm_commands = MockSlurmCommands(topology_file="/tmp/topology.txt")
    mock_slurm_commands.create_nodes(partition="gpu", count=18)
    mock_slurm_commands.run_command("scontrol update NodeName=gpu-6 State=POWER_DOWN")
    result = mock_slurm_commands.run_command("sinfo -p gpu -t powering_down -o '%N'")
    assert result.stdout.strip() == ""
    mock_slurm_commands.update_states(50)
    result = mock_slurm_commands.run_command("sinfo -p gpu -t powering_down -o '%N'")
    assert result.stdout.strip() == "gpu-6"


def test_reservation():
    mock_slurm_commands = MockSlurmCommands(topology_file="/tmp/topology.txt")
    mock_slurm_commands.create_nodes(partition="gpu", count=18)
    mock_slurm_commands.run_command("scontrol create reservation PartitionName=gpu ReservationName=test_resv Nodes=gpu-1,gpu-2 Duration=60")
    result = mock_slurm_commands.run_command("scontrol show reservation test_resv")
    assert "ReservationName=test_resv" in result.stdout
    assert "Nodes=gpu-1,gpu-2" in result.stdout


def test_generate_single_block():
    mock_slurm_commands = MockSlurmCommands(topology_file="/tmp/topology.txt")
    mock_slurm_commands.create_nodes(partition="gpu", count=18)
    mock_topology = MockAzslurmTopology(mock_slurm_commands)
    mock_slurm_commands.run_command("scontrol update NodeName=gpu-1,gpu-2,gpu-3,gpu-4,gpu-5,gpu-6,gpu-7,gpu-8,gpu-9,gpu-10,gpu-11,gpu-12,gpu-13,gpu-14,gpu-15,gpu-16,gpu-17,gpu-18 State=POWER_UP")
    mock_slurm_commands.update_states(50)
    mock_slurm_commands.update_states(50)
    result =  mock_slurm_commands.run_command('sinfo -p gpu -t powered_down,powering_up,powering_down,power_down,drain,drained,draining,unknown,down,no_respond,fail,reboot -o "%N" -h -N')
    assert result.stdout.strip() == ''
    mock_topology.generate_topology("gpu", "/tmp/topology.txt")
    with open("/tmp/topology.txt", "r") as f:
        content = f.read()
    assert "# Mock topology for testing\nBlockName=block_001 Nodes=gpu-1,gpu-2,gpu-3,gpu-4,gpu-5,gpu-6,gpu-7,gpu-8,gpu-9,gpu-10,gpu-11,gpu-12,gpu-13,gpu-14,gpu-15,gpu-16,gpu-17,gpu-18\nBlockSizes=1" in content


def test_sinfo():
    sc = MockSlurmCommands(topology_file="/tmp/topology.txt")
    sc.create_nodes(partition="gpu", count=18)
    sc._power_up(["gpu-1", "gpu-2", "gpu-3", "gpu-4"])
    sc.update_states(4)
    sc.update_states(4)
    powered_down = [f"gpu-{n+1}" for n in range(4, 18)]
    assert scale_to_n_nodes.get_healthy_nodes("gpu", sc) == ["gpu-1", "gpu-2", "gpu-3", "gpu-4"]
    assert scale_to_n_nodes.get_powered_up_nodes("gpu", sc) == ["gpu-1", "gpu-2", "gpu-3", "gpu-4"]
    assert scale_to_n_nodes.get_powered_down("gpu", sc) == powered_down
    assert scale_to_n_nodes.get_reservable_nodes("gpu", sc) == ["gpu-1", "gpu-2", "gpu-3", "gpu-4"] + powered_down

    sc.drain_nodes(["gpu-1"])
    sc.reserve_nodes(["gpu-2"])
    sc.alloc_nodes(["gpu-3"])
    sc.down_nodes(["gpu-4"])

    assert scale_to_n_nodes.get_healthy_nodes("gpu", sc) == ["gpu-2", "gpu-3"]
    assert scale_to_n_nodes.get_powered_up_nodes("gpu", sc) == ["gpu-1", "gpu-2", "gpu-3", "gpu-4"]
    assert scale_to_n_nodes.get_powered_down("gpu", sc) == powered_down
    # remove gpu-2 (reserved) and gpu-3 (allocated)
    assert scale_to_n_nodes.get_reservable_nodes("gpu", sc) == ["gpu-1", "gpu-4"] + powered_down

