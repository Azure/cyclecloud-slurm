from . import testutil


def test_mock_scontrol() -> None:
    """
    Test the mock scontrol maintains state correctly between update calls, as well as avoids typos.
    """
    cli = testutil.MockNativeSlurmCLI()
    cli.create_nodes(["hpc-1", "hpc-2"])
    assert cli.slurm_nodes["hpc-1"]["NodeAddr"] == "hpc-1" == cli.slurm_nodes["hpc-1"]["NodeHostName"]
    assert cli.slurm_nodes["hpc-2"]["NodeAddr"] == "hpc-2" == cli.slurm_nodes["hpc-2"]["NodeHostName"]
    cli.scontrol(["update", "NodeName=hpc-1", "NodeAddr=1.2.3.4", "NodeHostName=1.2.3.4"])
    assert cli.slurm_nodes["hpc-1"]["NodeAddr"] == "1.2.3.4" == cli.slurm_nodes["hpc-1"]["NodeHostName"]

    try:
        cli.scontrol(["update", "NodeName=hpc-1", "MadeUpThing=1"])
        assert False, "Expected KeyError"
    except KeyError:
        pass
