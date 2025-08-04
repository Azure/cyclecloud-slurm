from scale_to_n_nodes import NodeScaler
from mock import MockSlurmCommands

def test_exit_early_if_powering_down():
    mock_slurm_commands = MockSlurmCommands()
    mock_slurm_commands.create_nodes(partition="gpu", count=10)
    mock_slurm_commands.run_command("scontrol update NodeName=gpu-6 State=POWER_DOWN")
    nodescaler = NodeScaler
    try:
        nodescaler.run()
        assert False, "Expected NodeInvalidStateError"
    except NodeInvalidStateError as e:
        assert str(e) == "Some nodes are in POWER_DOWN state, cannot proceed with scaling."