'''This module contains test functions for the Topology class and utility functions for running commands and handling outputs.
Classes:
    OutputContainer: A container class to hold the standard output.
    ParallelOutputContainer: A container for storing the output of a srun command.
'''
from slurmcc.topology import Topology, TopologyInput, TopologyType
from slurmcc import util as slutil
from pathlib import Path
import pytest
import io
import sys
import json
import tempfile
import os
from slurmcc.topology import output_block_nodelist

TESTDIR="test/slurmcc_test/topology_test_output"

class OutputContainer:
    """
    A container class to hold the standard output.

    Attributes:
        stdout (str): The standard output to be stored in the container.
    """
    def __init__(self,stdout):
        self.stdout=stdout
class ParallelOutputContainer:
    """
    A container for storing the output of a parallel execution.

    Attributes:
        stdout (str): The standard output from the execution.
        stderr (str): The standard error output from the execution.
        exit_code (int): The exit code of the execution.
        host (str, optional): The host where the execution took place. Defaults to None.
    """
    def __init__(self,stdout,stderr,exit_code, host=None):

        self.stdout=stdout
        self.stderr=stderr
        self.returncode=exit_code
        self.host=host

def run_parallel_cmd(hosts,cmd,shell=False, partition=None,gpus=None):
    """
    Executes a command in parallel on a list of hosts and returns the output.

    Args:
        hosts (list): A list of hostnames where the command will be executed.
        cmd (str): The command to be executed on the hosts.

    Returns:
        ParallelOutputContainer: object containing the stdout, stderr, and exit code for each host.

    Commands:
        - "grep '^ID=' /etc/os-release | cut -d'=' -f2": Returns the OS ID (e.g., "ubuntu").
        - "sharp/bin/sharp_hello": Returns "Passed".
        - "python3 -c \"import shutil; print(shutil.which('ibstatus'))\"": Returns the path to the 'ibstatus' executable.
        - 'ibstatus | grep mlx5_ib | cut -d" " -f3 | xargs -I% ibstat "%" | grep "Port GUID" | cut -d: -f2':
            Reads GUIDs from a file and returns them for each host.

    Note:
        The function simulates the srun command execution and returns predefined outputs for specific commands.
    """

    if cmd == "grep '^ID=' /etc/os-release | cut -d'=' -f2":
        stdout = "\"ubuntu\""
        stderr = ""
        exit_code = 0
        return ParallelOutputContainer(stdout,stderr,exit_code)
    elif "sharp/bin/sharp_hello" in cmd:
        stdout = "Passed"
        stderr = ""
        exit_code = 0
        return ParallelOutputContainer(stdout,stderr,exit_code)
    elif "sharp/bin/sharp_cmd topology" in cmd:
        parts = cmd.split()
        index = parts.index('--topology_file')
        topo_file = parts[index + 1]
        with open('test/slurmcc_test/topology_test_input/topology.txt','r', encoding='utf-8') as file:
            contents= file.read()
        with open(topo_file, 'w', encoding='utf-8') as file:
            file.write(contents)
        stdout="Exited Successfully"
        stderr = ""
        exit_code = 0
        return ParallelOutputContainer(stdout,stderr,exit_code)
    elif cmd =="python3 -c \"import shutil; print(shutil.which('ibstatus'))\"":
        stdout = "/usr/sbin/ibstatus"
        stderr = ""
        exit_code = 0
        return ParallelOutputContainer(stdout,stderr,exit_code)
    elif cmd == (
            'ibstatus | grep mlx5_ib | cut -d" " -f3 | '
            'xargs -I% ibstat "%" | grep "Port GUID" | cut -d: -f2 '
            '| while IFS= read -r line; do echo \"$(hostname): $line\"; done'
        ):
        with open('test/slurmcc_test/topology_test_input/nodes_guids.txt', 'r', encoding='utf-8') as file:
            stdout = file.read()
            stderr = ""
            exit_code = 0
            return ParallelOutputContainer(stdout,stderr,exit_code)

def run_command(cmd,shell=True):
    """
    Executes a given command and returns the output based on predefined conditions.

    Args:
        cmd (str): The command to be executed.
        stdout (io.TextIOWrapper, optional): A writable stream to capture standard output. Defaults to None.

    Returns:
        OutputContainer: An object containing the output of the command execution.

    The function handles the following commands:
        - If 'powered_down' is in the command, it reads from 'powered_down_hostnames.txt'.
        - If the command is 'scontrol show hostnames $(sinfo -o "%N" -h)', it reads from 'all_hostnames.txt'.
        - If 'scontrol show hostnames' is in the command and '-p' is not in the command, it reads from 'hostnames.txt'.
        - If 'scontrol show hostnames' is in the command and '-p' is in the command, it reads from 'all_hostnames.txt'.
        - If the command contains "sharp/bin/sharp_cmd topology", it reads from 'topology.txt', writes to 'topology.txt' in the output directory, and writes "Exited Successfully" to stdout.

    Note:
        The function reads from and writes to files located in 'test/slurmcc_test/topology_test_input' and 'test/slurmcc_test/topology_test_output' directories.
    """
    if 'sinfo -o %P' in cmd:
        with open('test/slurmcc_test/topology_test_input/partitions.txt', 'r', encoding='utf-8') as file:
            out= file.read()
    elif 'powered_down' in cmd:
        with open('test/slurmcc_test/topology_test_input/powered_down_hostnames.txt', 'r', encoding='utf-8') as file:
            out= file.read()
    elif cmd=='scontrol show hostnames $(sinfo -o "%N" -h)':
        with open('test/slurmcc_test/topology_test_input/all_hostnames.txt', 'r', encoding='utf-8') as file:
            out= file.read()
    elif 'scontrol show hostnames' in cmd and '-p' in cmd:
        with open('test/slurmcc_test/topology_test_input/all_hostnames.txt','r', encoding='utf-8') as file:
            out= file.read()
    else:
        out=None
    return OutputContainer(out)

def setup():
    """
    Creates the directory 'test/slurmcc_test/topology_test_output' if it does not already exist.

    This function ensures that the directory structure is created, including any necessary parent directories.
    If the directory already exists, no exception is raised.
    """
    Path("test/slurmcc_test/topology_test_output").mkdir(parents=True, exist_ok=True)
def test_get_hostnames():
    """
    Test the get_hostnames method of the Topology class.

    This test verifies that the get_hostnames method correctly retrieves and 
    sets the hostnames for the Topology object. It compares the result with 
    the expected hostnames read from a file.

    Steps:
    1. Set the run_command function for slutil.
    2. Create a Topology object with None as the initial parameter.
    3. Call get_hostnames with None and "hpc" as parameters and verify the result.
    4. Read the expected hostnames from 'test/slurmcc_test/topology_test_input/valid_hostnames.txt'.
    5. Assert that the retrieved hostnames match the expected hostnames.
    6. Call get_hostnames with "hpc" and None as parameters and verify the result.
    7. Assert that the retrieved hostnames match the expected hostnames.

    Raises:
        AssertionError: If the retrieved hostnames do not match the expected hostnames.
    """
    slutil.run=run_command
    test_obj   = Topology("hpc",None,TopologyInput.FABRIC,TopologyType.TREE,TESTDIR)
    test_obj.get_hostnames()
    result=test_obj.hosts
    with open('test/slurmcc_test/topology_test_input/valid_hostnames.txt','r', encoding='utf-8') as file:
        actual= file.read().splitlines()
    assert set(result)==set(actual)

def test_get_os_name():
    """
    Test the get_os_name method of the Topology class.

    This test sets up a Topology object with a single host 'node1' and 
    verifies that the get_os_name method returns 'ubuntu'.

    Steps:
    1. Assign the run_parallel_cmd function to slutil.run_parallel_cmd.
    2. Create a Topology object with None as its parameter.
    3. Set the hosts attribute of the Topology object to ['node1'].
    4. Call the get_os_name method of the Topology object.
    5. Assert that the result is 'ubuntu'.
    """
    slutil.srun=run_parallel_cmd
    test_obj   = Topology("hpc",None,TopologyInput.FABRIC,TopologyType.TREE,TESTDIR)
    test_obj.hosts=['node1']
    result=test_obj.get_os_name()
    assert result=='ubuntu'
def test_get_sharp_cmd():
    """
    Test the get_sharp_cmd method of the Topology class.

    This test initializes a Topology object with a single host 'node1' and 
    verifies that the get_sharp_cmd method returns the expected command string.

    Assertions:
        - The result of get_sharp_cmd() should be "/opt/hpcx-v2.18-gcc-mlnx_ofed-ubuntu22.04-cuda12-x86_64/"
    """
    test_obj   = Topology("hpc",None,TopologyInput.FABRIC,TopologyType.TREE,TESTDIR)
    test_obj.hosts=['node1']
    result=test_obj.get_sharp_cmd()
    assert result=="/opt/hpcx-v2.18-gcc-mlnx_ofed-ubuntu22.04-cuda12-x86_64/"
def test_check_sharp_hello():
    """
    Test the check_sharp_hello method of the Topology class.

    This test sets up a Topology object with a single host and a specified
    sharp command path. It then calls the check_sharp_hello method and asserts
    that the result is 0, indicating success.

    Steps:
    1. Assign the srun function to slutil.run_parallel_cmd.
    2. Create a Topology object with no initial parameters.
    3. Set the hosts attribute of the Topology object to a list containing 'node1'.
    4. Set the sharp_cmd_path attribute of the Topology object to the specified path.
    5. Call the check_sharp_hello method of the Topology object.
    6. Assert that the result of the check_sharp_hello method is 0.

    Returns:
        None
    """
    slutil.srun=run_parallel_cmd
    test_obj   = Topology("hpc",None,TopologyInput.FABRIC,TopologyType.TREE,TESTDIR)
    test_obj.hosts=['node1']
    test_obj.sharp_cmd_path="/opt/hpcx-v2.18-gcc-mlnx_ofed-ubuntu22.04-cuda12-x86_64/"
    result=test_obj.check_sharp_hello()
    assert result==0
def test_check_ibstatus():
    """
    Test the check_ibstatus method of the Topology class.

    This test sets up a Topology object with a single host ('node1') and 
    checks the InfiniBand status using the check_ibstatus method. It 
    asserts that the result of the check_ibstatus method is 0, indicating 
    that the InfiniBand status check passed.

    Steps:
    1. Assign the srun function to slutil.run_parallel_cmd.
    2. Create a Topology object with no initial parameters.
    3. Set the hosts attribute of the Topology object to ['node1'].
    4. Call the check_ibstatus method on the Topology object.
    5. Assert that the result of check_ibstatus is 0.

    Returns:
        None
    """
    slutil.srun=run_parallel_cmd
    test_obj   = Topology("hpc",None,TopologyInput.FABRIC,TopologyType.TREE,TESTDIR)
    test_obj.hosts=['node1']
    result=test_obj.check_ibstatus()
    assert result==0
def test_retrieve_guids():
    """
    Test the `retrieve_guids` method of the `Topology` class.

    This test performs the following steps:
    1. Sets up the `run_parallel_cmd` function.
    2. Initializes a `Topology` object with no arguments.
    3. Reads hostnames from 'test/slurmcc_test/topology_test_input/guid_hostnames.txt' and assigns them to the `hosts` attribute of the `Topology` object.
    4. Calls the `retrieve_guids` method on the `Topology` object.
    5. Sets the `guids_file` attribute of the `Topology` object to 'test/slurmcc_test/topology_test_output/guids.txt'.
    6. Writes the retrieved GUIDs to the file specified by `guids_file`.
    7. Reads the contents of the output GUIDs file.
    8. Reads the expected GUIDs from 'test/slurmcc_test/topology_test_input/guids.txt'.
    9. Asserts that the contents of the output GUIDs file match the expected GUIDs.

    Raises:
        AssertionError: If the contents of the output GUIDs file do not match the expected GUIDs.
    """
    slutil.srun=run_parallel_cmd
    test_obj   = Topology("hpc",None,TopologyInput.FABRIC,TopologyType.TREE,TESTDIR)
    with open('test/slurmcc_test/topology_test_input/guid_hostnames.txt','r', encoding='utf-8') as file:
        test_obj.hosts= file.read().splitlines()
    test_obj.retrieve_guids()
    test_obj.write_guids_to_file()
    with open(test_obj.guids_file,'r', encoding='utf-8') as file:
        result= file.read()
    with open('test/slurmcc_test/topology_test_input/guids.txt','r', encoding='utf-8') as file:
        actual= file.read()
    assert result==actual
def test_generate_topo_file():
    """
    Test the generate_topo_file method of the Topology class.

    This test sets up a Topology object and calls its generate_topo_file method.
    It then reads the generated topology file and compares its content with the
    expected content from a predefined input file.

    The test asserts that the generated topology file content matches the expected
    content.

    Raises:
        AssertionError: If the generated topology file content does not match the
                        expected content.
    """
    slutil.srun=run_parallel_cmd
    test_obj   = Topology("hpc",None,TopologyInput.FABRIC,TopologyType.TREE,TESTDIR)
    test_obj.hosts=['node1']
    test_obj.generate_topo_file()
    with open(test_obj.topo_file,'r', encoding='utf-8') as file:
        result= file.read()
    with open('test/slurmcc_test/topology_test_input/topology.txt','r', encoding='utf-8') as file:
        actual= file.read()
    assert result==actual
    
def test_run_fabric():
    """
    Test the Topology class by running a topology generation and comparing the output to the expected result.

    This function performs the following steps:
    1. Creates an instance of the Topology class with the specified output file.
    2. Sets the topology input file for the Topology instance.
    3. Runs the topology generation process.
    4. Reads the generated output file.
    5. Reads the expected output file.
    6. Asserts that the generated output matches the expected output.

    Raises:
        AssertionError: If the generated output does not match the expected output.
    """
    slutil.srun=run_parallel_cmd
    slutil.run=run_command
    output= 'test/slurmcc_test/topology_test_output/slurm_topology_2.txt'
    test_obj   = Topology("hpc",output,TopologyInput.FABRIC,TopologyType.TREE,TESTDIR)
    test_obj.run()
    with open('test/slurmcc_test/topology_test_output/slurm_topology_2.txt','r', encoding='utf-8') as file:
        result= file.read()
    with open('test/slurmcc_test/topology_test_input/slurm_topology.txt','r', encoding='utf-8') as file:
        actual= file.read()
    assert result==actual

def test_run_nvlink():
    """
    Test the run method of the Topology class.

    This test performs the following steps:
    1. Creates an instance of the Topology class with a specified output file.
    2. Sets the topology input file for the Topology instance.
    3. Runs the topology generation process.
    4. Reads the generated output file.
    5. Reads the expected output file.
    6. Asserts that the generated output matches the expected output.

    Raises:
        AssertionError: If the generated output does not match the expected output.
    """
    slutil.srun=run_parallel_cmd
    slutil.run=run_command
    output= 'test/slurmcc_test/topology_test_output/slurm_block_topology.txt'
    test_obj   = Topology("hpc",output,TopologyInput.NVLINK,TopologyType.BLOCK,TESTDIR)
    def fake_run_get_rack_id_command_1(*args, **kwargs):
        output=[]
        with open('test/slurmcc_test/topology_test_input/nodes_clusterUUIDs.txt', 'r', encoding='utf-8') as f:
            lines= f.readlines()
            for line in lines:
                host= line.split(':')[0]
                uuid= line.split(':')[1].strip()
                output.append(ParallelOutputContainer([uuid],"",0,host))
        return output
    test_obj._run_get_rack_id_command = fake_run_get_rack_id_command_1
    test_obj.run()
    racks=test_obj.run_nvlink()
    content = test_obj.write_block_topology(racks)
    with open('test/slurmcc_test/topology_test_output/slurm_block_topology.txt','r', encoding='utf-8') as file:
        result= file.read()
    with open('test/slurmcc_test/topology_test_input/block_topology.txt','r', encoding='utf-8') as file:
        actual= file.read()
    assert result==actual
    assert content==actual
    assert len(racks)==4

def test_group_hosts_per_rack_single_rack(monkeypatch):
    """
    Test group_hosts_per_rack when all hosts belong to the same rack.
    """
    test_obj = Topology("hpc", None, TopologyInput.NVLINK, TopologyType.BLOCK, TESTDIR)
    test_obj.hosts = ['node1', 'node2', 'node3']

    # Mock get_rack_id to return all hosts mapped to the same rack
    def fake_get_rack_id():
        return {'node1': 'rackA', 'node2': 'rackA', 'node3': 'rackA'}
    test_obj.get_rack_id = fake_get_rack_id

    racks = test_obj.group_hosts_per_rack()
    assert racks == {'rackA': ['node1', 'node2', 'node3']}

def test_group_hosts_per_rack_multiple_racks(monkeypatch):
    """
    Test group_hosts_per_rack when hosts are distributed across multiple racks.
    """
    test_obj = Topology("hpc", None, TopologyInput.NVLINK, TopologyType.BLOCK, TESTDIR)
    test_obj.hosts = ['node1', 'node2', 'node3', 'node4']

    # Mock get_rack_id to return hosts mapped to different racks
    def fake_get_rack_id():
        return {'node1': 'rackA', 'node2': 'rackB', 'node3': 'rackA', 'node4': 'rackC'}
    test_obj.get_rack_id = fake_get_rack_id
    racks = test_obj.group_hosts_per_rack()
    assert racks == {
        'rackA': ['node1', 'node3'],
        'rackB': ['node2'],
        'rackC': ['node4']
    }

def test_group_hosts_per_rack_empty(monkeypatch):
    """
    Test group_hosts_per_rack when there are no hosts.
    """
    test_obj = Topology("hpc", None, TopologyInput.NVLINK, TopologyType.BLOCK, TESTDIR)
    test_obj.hosts = []

    # Mock get_rack_id to return empty dict
    def fake_get_rack_id():
        return {}
    test_obj.get_rack_id = fake_get_rack_id

    racks = test_obj.group_hosts_per_rack()
    assert racks == {}

def test_group_hosts_per_rack_duplicate_hosts(monkeypatch):
    """
    Test group_hosts_per_rack when the same host appears multiple times in get_rack_id.
    """
    test_obj = Topology("hpc", None, TopologyInput.NVLINK, TopologyType.BLOCK, TESTDIR)
    test_obj.hosts = ['node1', 'node2']

    # Mock get_rack_id to return duplicate hosts (should not happen, but test for robustness)
    def fake_get_rack_id():
        return {'node1': 'rackA', 'node1': 'rackA', 'node2': 'rackB'}
    test_obj.get_rack_id = fake_get_rack_id

    racks = test_obj.group_hosts_per_rack()
    assert racks == {'rackA': ['node1'], 'rackB': ['node2']}
class DummyHostOut:
    def __init__(self, host, stdout):
        self.host = host
        self.stdout = stdout

def make_host_out(host, lines):
    return DummyHostOut(host, lines)

def test_get_rack_id_success(monkeypatch):
    # Simulate _run_get_rack_id_command returning host outputs with rack IDs
    outputs = [
        make_host_out("node1", ["uuidA"]),
        make_host_out("node2", ["uuidB"]),
        make_host_out("node3", ["uuidA"]),
    ]
    topo = Topology("hpc", None, TopologyInput.NVLINK, TopologyType.BLOCK, "testdir")
    monkeypatch.setattr(topo, "_run_get_rack_id_command", lambda: outputs)
    result = topo.get_rack_id()
    assert result == {"node1": "uuidA", "node2": "uuidB", "node3": "uuidA"}

def test_get_rack_id_strip_and_multiple_lines(monkeypatch):
    # Simulate multiple lines per host
    outputs = [
        make_host_out("node1", ["uuidA", "uuidA2"]),
        make_host_out("node2", ["uuidB"]),
    ]
    topo = Topology("hpc", None, TopologyInput.NVLINK, TopologyType.BLOCK, "testdir")
    monkeypatch.setattr(topo, "_run_get_rack_id_command", lambda: outputs)
    result = topo.get_rack_id()
    # Only the last line for each host will be kept due to overwrite
    assert result == {"node1": "uuidA2", "node2": "uuidB"}

def test_get_rack_id_empty(monkeypatch):
    outputs = []
    topo = Topology("hpc", None, TopologyInput.NVLINK, TopologyType.BLOCK, "testdir")
    monkeypatch.setattr(topo, "_run_get_rack_id_command", lambda: outputs)
    result = topo.get_rack_id()
    assert result == {}

def test_get_rack_id_exception(monkeypatch):
    topo = Topology("hpc", None, TopologyInput.NVLINK, TopologyType.BLOCK, "testdir")
    def raise_exc():
        raise Exception("fail")
    monkeypatch.setattr(topo, "_run_get_rack_id_command", raise_exc)
    with pytest.raises(SystemExit):
        topo.get_rack_id()

def test_get_rack_id_timeout(monkeypatch):
    topo = Topology("hpc", None, TopologyInput.NVLINK, TopologyType.BLOCK, "testdir")
    def raise_timeout():
        raise TimeoutError("timeout")
    monkeypatch.setattr(topo, "_run_get_rack_id_command", raise_timeout)
    with pytest.raises(SystemExit):
        topo.get_rack_id()

TESTDIR = "test/slurmcc_test/topology_test_output"

@pytest.mark.parametrize(
    "block_size,host_dict,expected_lines,should_exit",
    [
        # Normal case: all blocks have enough nodes
        (
            2,
            {
                "rackA": ["node1", "node2"],
                "rackB": ["node3", "node4"],
            },
            [
                "# Number of Nodes in Block 1: 2",
                "# ClusterUUID and CliqueID: rackA",
                "BlockName=block_rackA Nodes=node1,node2",
                "# Number of Nodes in Block 2: 2",
                "# ClusterUUID and CliqueID: rackB",
                "BlockName=block_rackB Nodes=node3,node4",
                "BlockSizes=2",
            ],
            False,
        ),
        # One block too small
        (
            3,
            {
                "rackA": ["node1", "node2"],
                "rackB": ["node3", "node4", "node5"],
            },
            [
                "# Warning: Block 1 has less than 3 nodes, commenting out",
                "#BlockName=block_rackA Nodes=node1,node2",
                "BlockName=block_rackB Nodes=node3,node4,node5",
                "BlockSizes=3",
            ],
            False,
        ),
        # All blocks too small
        (
            5,
            {
                "rackA": ["node1"],
                "rackB": ["node2", "node3"],
            },
            [
                "# Warning: Block 1 has less than 5 nodes, commenting out",
                "#BlockName=block_rackA Nodes=node1",
                "# Warning: Block 2 has less than 5 nodes, commenting out",
                "#BlockName=block_rackB Nodes=node2,node3",
                "BlockSizes=5",
            ],
            False,
        ),
        # Empty host_dict triggers sys.exit
        (
            2,
            {},
            [],
            True,
        ),
    ]
)
def test_write_block_topology_cases(monkeypatch, block_size, host_dict, expected_lines, should_exit):
    test_obj = Topology("hpc", None, TopologyInput.NVLINK, TopologyType.BLOCK, TESTDIR, block_size=block_size)
    if should_exit:
        with pytest.raises(SystemExit):
            test_obj.write_block_topology(host_dict)
    else:
        result = test_obj.write_block_topology(host_dict)
        for line in expected_lines:
            assert line in result
        assert result.strip().endswith(f"BlockSizes={block_size}")

def test_write_block_topology_order_and_indexing():
    # Ensure block indices increment in insertion order
    host_dict = {"rackA": ["n1"], "rackB": ["n2"], "rackC": ["n3"]}
    test_obj = Topology("hpc", None, TopologyInput.NVLINK, TopologyType.BLOCK, TESTDIR, block_size=2)
    result = test_obj.write_block_topology(host_dict)
    assert "# Number of Nodes in Block 1: 1" in result
    assert "# Number of Nodes in Block 2: 1" in result
    assert "# Number of Nodes in Block 3: 1" in result
    assert result.count("BlockSizes=2") == 1

def test_write_block_topology_single_block_enough_nodes():
    host_dict = {"rackA": ["node1", "node2"]}
    test_obj = Topology("hpc", None, TopologyInput.NVLINK, TopologyType.BLOCK, TESTDIR, block_size=2)
    result = test_obj.write_block_topology(host_dict)
    assert "BlockName=block_rackA Nodes=node1,node2" in result
    assert "# Warning:" not in result

def test_write_block_topology_single_block_too_few_nodes():
    host_dict = {"rackA": ["node1"]}
    test_obj = Topology("hpc", None, TopologyInput.NVLINK, TopologyType.BLOCK, TESTDIR, block_size=3)
    result = test_obj.write_block_topology(host_dict)
    assert "# Warning: Block 1 has less than 3 nodes, commenting out" in result
    assert "#BlockName=block_rackA Nodes=node1" in result
    # The uncommented version should not appear anywhere in the result
    assert "\nBlockName=block_rackA Nodes=node1\n" not in f"\n{result}\n"

def test_write_block_topology_multiple_blocks_mixed_sizes():
    host_dict = {
        "rackA": ["node1", "node2", "node3"],
        "rackB": ["node4"],
        "rackC": ["node5", "node6", "node7"],
    }
    test_obj = Topology("hpc", None, TopologyInput.NVLINK, TopologyType.BLOCK, TESTDIR, block_size=3)
    result = test_obj.write_block_topology(host_dict)
    assert "BlockName=block_rackA Nodes=node1,node2,node3" in result
    assert "# Warning: Block 2 has less than 3 nodes, commenting out" in result
    assert "#BlockName=block_rackB Nodes=node4" in result
    assert "BlockName=block_rackC Nodes=node5,node6,node7" in result

def test_run_nvlink_calls_methods(monkeypatch):
    """
    Test that run_nvlink calls get_hostnames and group_hosts_per_rack, and returns the correct racks dict.
    """
    test_obj = Topology("hpc", None, TopologyInput.NVLINK, TopologyType.BLOCK, TESTDIR)
    called = {"get_hostnames": False, "group_hosts_per_rack": False}

    def fake_get_hostnames():
        called["get_hostnames"] = True

    expected_racks = {"rackA": ["node1", "node2"], "rackB": ["node3"]}
    def fake_group_hosts_per_rack():
        called["group_hosts_per_rack"] = True
        return expected_racks

    test_obj.get_hostnames = fake_get_hostnames
    test_obj.group_hosts_per_rack = fake_group_hosts_per_rack

    result = test_obj.run_nvlink()
    assert called["get_hostnames"]
    assert called["group_hosts_per_rack"]
    assert result == expected_racks

def test_run_nvlink_empty_hosts(monkeypatch):
    """
    Test run_nvlink returns empty dict when group_hosts_per_rack returns empty.
    """
    test_obj = Topology("hpc", None, TopologyInput.NVLINK, TopologyType.BLOCK, TESTDIR)
    test_obj.get_hostnames = lambda: None
    test_obj.group_hosts_per_rack = lambda: {}
    result = test_obj.run_nvlink()
    assert result == {}

def test_run_nvlink_multiple_racks(monkeypatch):
    """
    Test run_nvlink returns correct mapping for multiple racks.
    """
    test_obj = Topology("hpc", None, TopologyInput.NVLINK, TopologyType.BLOCK, TESTDIR)
    test_obj.get_hostnames = lambda: None
    racks = {
        "rack1": ["host1", "host2"],
        "rack2": ["host3"],
        "rack3": ["host4", "host5", "host6"]
    }
    test_obj.group_hosts_per_rack = lambda: racks
    result = test_obj.run_nvlink()
    assert result == racks
@pytest.fixture
def block_topology_str():
    return (
        "# Comment line\n"
        "BlockName=block1 Nodes=node1,node2,node3\n"
        "BlockName=block2 Nodes=node4,node5\n"
        "# Another comment\n"
        "BlockName=block3 Nodes=node6\n"
    )

@pytest.fixture
def block_topology_file(block_topology_str):
    with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as f:
        f.write(block_topology_str)
        f.flush()
        yield f.name
    os.remove(f.name)

def test_output_block_nodelist_json_string(block_topology_str):
    result = output_block_nodelist(block_topology_str, table=False)
    blocks = json.loads(result)
    assert isinstance(blocks, list)
    assert len(blocks) == 3
    # Sorted by size (smallest to largest)
    assert blocks[0]['blockname'] == 'block3'
    assert blocks[0]['size'] == 1
    assert blocks[1]['blockname'] == 'block2'
    assert blocks[1]['size'] == 2
    assert blocks[2]['blockname'] == 'block1'
    assert blocks[2]['size'] == 3
    assert blocks[2]['nodelist'] == ['node1', 'node2', 'node3']

def test_output_block_nodelist_json_file(block_topology_file):
    result = output_block_nodelist(block_topology_file, table=False)
    blocks = json.loads(result)
    assert isinstance(blocks, list)
    assert len(blocks) == 3
    assert any(b['blockname'] == 'block1' for b in blocks)

def test_output_block_nodelist_table_output(block_topology_str, capsys):
    """
    Test that output_block_nodelist prints the correct table output to stdout.
    """
    output_block_nodelist(block_topology_str, table=True)
    captured = capsys.readouterr()
    out = captured[0] if isinstance(captured, tuple) else captured.out
    assert "Block Name" in out
    assert "block1" in out
    assert "node1" in out
    assert "Total blocks: 3" in out
    assert "Total nodes: 6" in out

def test_output_block_nodelist_table_output_file(block_topology_file, capsys):
    output_block_nodelist(block_topology_file, table=True)
    captured = capsys.readouterr()
    out = captured[0] if isinstance(captured, tuple) else captured.out
    assert "Block Name" in out
    assert "block2" in out
    assert "node4" in out
    assert "Total blocks: 3" in out

def test_output_block_nodelist_empty_blocks(capsys):
    content = "# Only comments\n#BlockName=block1 Nodes=node1"
    output_block_nodelist(content, table=True)
    captured = capsys.readouterr()
    out = captured[0] if isinstance(captured, tuple) else captured.out
    assert "No blocks found in topology" in out

def test_output_block_nodelist_invalid_format():
    with pytest.raises(ValueError):
        output_block_nodelist("This is not a block topology", table=False)

def test_output_block_nodelist_long_nodes_truncation(capsys):
    long_nodes = ",".join([f"node{i}" for i in range(20)])
    content = f"BlockName=blockX Nodes={long_nodes}"
    output_block_nodelist(content, table=True)
    captured = capsys.readouterr()
    out = captured[0] if isinstance(captured, tuple) else captured.out
    # Should be truncated with "..."
    assert "..." in out

def test_output_block_nodelist_handles_spaces():
    content = "  BlockName=blockA   Nodes= n1 , n2 , n3  "
    result = output_block_nodelist(content, table=False)
    blocks = json.loads(result)
    assert blocks[0]['nodelist'] == ['n1', 'n2', 'n3']


