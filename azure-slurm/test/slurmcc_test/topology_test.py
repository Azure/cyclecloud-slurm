'''This module contains test functions for the Topology class and utility functions for running commands and handling outputs.
Classes:
    OutputContainer: A container class to hold the standard output.
    ParallelOutputContainer: A container for storing the output of a srun command.
'''
from slurmcc.topology import Topology
from slurmcc import util as slutil
from pathlib import Path

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
    def __init__(self,stdout,stderr,exit_code):
        self.stdout=stdout
        self.stderr=stderr
        self.returncode=exit_code
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
    elif cmd == "echo \"$(nvidia-smi -q | grep 'ClusterUUID' | head -n 1 | cut -d: -f2)$(nvidia-smi -q | grep 'CliqueId' | head -n 1 | cut -d: -f2)\" | while IFS= read -r line; do echo \"$(hostname): $line\"; done":
        with open('test/slurmcc_test/topology_test_input/nodes_clusterUUIDs.txt', 'r', encoding='utf-8') as file:
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
    test_obj   = Topology("hpc",None,"fabric","tree",TESTDIR)
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
    test_obj   = Topology("hpc",None,"fabric","tree",TESTDIR)
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
    test_obj   = Topology("hpc",None,"fabric","tree",TESTDIR)
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
    test_obj   = Topology("hpc",None,"fabric","tree",TESTDIR)
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
    test_obj   = Topology("hpc",None,"fabric","tree",TESTDIR)
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
    test_obj   = Topology("hpc",None,"fabric","tree",TESTDIR)
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
    test_obj   = Topology("hpc",None,"fabric","tree",TESTDIR)
    test_obj.hosts=['node1']
    test_obj.generate_topo_file()
    with open(test_obj.topo_file,'r', encoding='utf-8') as file:
        result= file.read()
    with open('test/slurmcc_test/topology_test_input/topology.txt','r', encoding='utf-8') as file:
        actual= file.read()
    assert result==actual

def test_write_tree_topology():
    """
    Test the write_tree_topology method of the Topology class.

    This test performs the following steps:
    1. Creates an instance of the Topology class with a specified output file.
    2. Sets the topo_file attribute to a predefined input topology file.
    3. Groups device GUIDs per switch using the group_guids_per_switch method.
    4. Identifies torsets using the identify_torsets method.
    5. Groups hosts by torset using the group_hosts_by_torset method.
    6. Writes the slurm topology to the output file using the write_tree_topology method.
    7. Reads the generated output file and compares it with an expected output file.
    
    The test asserts that the content of the generated output file matches the expected output file.
    """
    slutil.srun=run_parallel_cmd
    slutil.run=run_command
    output= 'test/slurmcc_test/topology_test_output/slurm_topology_1.txt'
    test_obj   = Topology("hpc",output,"fabric","tree",TESTDIR)
    test_obj.get_hostnames()
    test_obj.retrieve_guids()
    test_obj.topo_file = 'test/slurmcc_test/topology_test_input/topology.txt'
    test_obj.device_guids_per_switch =  test_obj.group_guids_per_switch()
    test_obj.host_to_torset_map = test_obj.identify_torsets()
    test_obj.torsets = test_obj.group_hosts_by_torset()
    test_obj.write_tree_topology()
    with open('test/slurmcc_test/topology_test_output/slurm_topology_1.txt','r', encoding='utf-8') as file:
        result= file.read()
    with open('test/slurmcc_test/topology_test_input/slurm_topology.txt','r', encoding='utf-8') as file:
        actual= file.read()
    assert result==actual

def test_run_block():
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
    test_obj   = Topology("hpc",output,"nvlink","block",TESTDIR)
    test_obj.run()
    #test_obj.topo_file = 'test/slurmcc_test/topology_test_input/topology.txt'
    with open('test/slurmcc_test/topology_test_output/slurm_block_topology.txt','r', encoding='utf-8') as file:
        result= file.read()
    with open('test/slurmcc_test/topology_test_input/block_topology.txt','r', encoding='utf-8') as file:
        actual= file.read()
    assert result==actual
    
def test_run_tree():
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
    test_obj   = Topology("hpc",output,"fabric","tree",TESTDIR)
    test_obj.run()
    with open('test/slurmcc_test/topology_test_output/slurm_topology_2.txt','r', encoding='utf-8') as file:
        result= file.read()
    with open('test/slurmcc_test/topology_test_input/slurm_topology.txt','r', encoding='utf-8') as file:
        actual= file.read()
    assert result==actual
