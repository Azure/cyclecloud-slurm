'''This module contains test functions for the Topology class and utility functions for running commands and handling outputs.
Classes:
    OutputContainer: A container class to hold the standard output.
    ParallelOutputContainer: A container for storing the output of a parallel execution.
Functions:
    run_parallel_cmd(hosts, cmd): Executes a command in parallel on a list of hosts and returns the output.
    run_command(cmd, stdout=None): Executes a given command and returns the output based on predefined conditions.
    test_get_hostnames(): Test the get_hostnames method of the Topology class.
    test_get_os_name(): Test the get_os_name method of the Topology class.
    test_get_sharp_cmd(): Test the get_sharp_cmd method of the Topology class.
    test_check_sharp_hello(): Test the check_sharp_hello method of the Topology class.
    test_check_ibstatus(): Test the check_ibstatus method of the Topology class.
    test_retrieve_guids(): Test the retrieve_guids method of the Topology class.
    test_generate_topo_file(): Test the generate_topo_file method of the Topology class.
    test_write_slurm_topology(): Test the write_slurm_topology method of the Topology class.
    test_run(): Test the Topology class by running a topology generation and comparing the output to the expected result.
    '''
from slurmcc.topology import Topology
from slurmcc import util as slutil
from pathlib import Path

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
    def __init__(self,stdout,stderr,exit_code,host=None):
        self.stdout=stdout
        self.stderr=stderr
        self.exit_code=exit_code
        self.host=host
def run_parallel_cmd(hosts,cmd):
    """
    Executes a command in parallel on a list of hosts and returns the output.

    Args:
        hosts (list): A list of hostnames where the command will be executed.
        cmd (str): The command to be executed on the hosts.

    Returns:
        list: A list of ParallelOutputContainer objects containing the stdout, stderr, and exit code for each host.

    Commands:
        - "grep '^ID=' /etc/os-release | cut -d'=' -f2": Returns the OS ID (e.g., "ubuntu").
        - "sharp/bin/sharp_hello": Returns "Passed".
        - "python3 -c \"import shutil; print(shutil.which('ibstatus'))\"": Returns the path to the 'ibstatus' executable.
        - 'ibstatus | grep mlx5_ib | cut -d" " -f3 | xargs -I% ibstat "%" | grep "Port GUID" | cut -d: -f2':
            Reads GUIDs from a file and returns them for each host.

    Note:
        The function simulates the command execution and returns predefined outputs for specific commands.
    """
    output=[]
    if cmd == "grep '^ID=' /etc/os-release | cut -d'=' -f2":
        stdout = "ubuntu"
        stderr = ""
        exit_code = 0
        output.append(ParallelOutputContainer(stdout,stderr,exit_code))
    elif "sharp/bin/sharp_hello" in cmd:
        stdout = "Passed"
        stderr = ""
        exit_code = 0
        output.append(ParallelOutputContainer(stdout,stderr,exit_code))
    elif cmd =="python3 -c \"import shutil; print(shutil.which('ibstatus'))\"":
        stdout = "/usr/sbin/ibstatus"
        stderr = ""
        exit_code = 0
        output.append(ParallelOutputContainer(stdout,stderr,exit_code))
    elif cmd == (
            'ibstatus | grep mlx5_ib | cut -d" " -f3 | '
            'xargs -I% ibstat "%" | grep "Port GUID" | cut -d: -f2'
        ):
        with open('test/slurmcc_test/topology_test_input/guids.txt', 'r', encoding='utf-8') as file:
            stdout_list= file.read().splitlines()
        i=0
        hosts=sorted(hosts)
        for host in hosts:
            stdout= stdout_list[i:i+8]
            i+=8
            stderr = ""
            exit_code = 0
            output.append(ParallelOutputContainer(stdout,stderr,exit_code,host))
    return output
def run_command(cmd,stdout=None):
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
    if 'powered_down' in cmd:
        with open('test/slurmcc_test/topology_test_input/powered_down_hostnames.txt', 'r', encoding='utf-8') as file:
            out= file.read()
    elif cmd=='scontrol show hostnames $(sinfo -o "%N" -h)':
        with open('test/slurmcc_test/topology_test_input/all_hostnames.txt', 'r', encoding='utf-8') as file:
            out= file.read()
    elif 'scontrol show hostnames' in cmd and '-p' not in cmd:
        with open('test/slurmcc_test/topology_test_input/hostnames.txt','r', encoding='utf-8') as file:
            out= file.read()
    elif 'scontrol show hostnames' in cmd and '-p' in cmd:
        with open('test/slurmcc_test/topology_test_input/all_hostnames.txt','r', encoding='utf-8') as file:
            out= file.read()
    elif "sharp/bin/sharp_cmd topology" in cmd:
        with open('test/slurmcc_test/topology_test_input/topology.txt','r', encoding='utf-8') as file:
            contents= file.read()
        with open('test/slurmcc_test/topology_test_output/topology.txt', 'w', encoding='utf-8') as file:
            file.write(contents)
        stdout.write("Exited Successfully")
        out=None
    else:
        out=None
    return OutputContainer(out)

def setup():
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
    slutil.run_command=run_command
    test_obj   = Topology(None)
    test_obj.get_hostnames(None,"hpc")
    result=test_obj.hosts
    with open('test/slurmcc_test/topology_test_input/valid_hostnames.txt','r', encoding='utf-8') as file:
        actual= file.read().splitlines()
    assert set(result)==set(actual)
    test_obj.get_hostnames("hpc",None)
    result=test_obj.hosts
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
    slutil.run_parallel_cmd=run_parallel_cmd
    test_obj   = Topology(None)
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
    test_obj   = Topology(None)
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
    1. Assign the run_parallel_cmd function to slutil.run_parallel_cmd.
    2. Create a Topology object with no initial parameters.
    3. Set the hosts attribute of the Topology object to a list containing 'node1'.
    4. Set the sharp_cmd_path attribute of the Topology object to the specified path.
    5. Call the check_sharp_hello method of the Topology object.
    6. Assert that the result of the check_sharp_hello method is 0.

    Returns:
        None
    """
    slutil.run_parallel_cmd=run_parallel_cmd
    test_obj   = Topology(None)
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
    1. Assign the run_parallel_cmd function to slutil.run_parallel_cmd.
    2. Create a Topology object with no initial parameters.
    3. Set the hosts attribute of the Topology object to ['node1'].
    4. Call the check_ibstatus method on the Topology object.
    5. Assert that the result of check_ibstatus is 0.

    Returns:
        None
    """
    slutil.run_parallel_cmd=run_parallel_cmd
    test_obj   = Topology(None)
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
    slutil.run_parallel_cmd=run_parallel_cmd
    test_obj   = Topology(None)
    with open('test/slurmcc_test/topology_test_input/guid_hostnames.txt','r', encoding='utf-8') as file:
        test_obj.hosts= file.read().splitlines()
    test_obj.retrieve_guids()
    test_obj.guids_file='test/slurmcc_test/topology_test_output/guids.txt'
    test_obj.write_guids_to_file()
    with open('test/slurmcc_test/topology_test_output/guids.txt','r', encoding='utf-8') as file:
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
    slutil.run_command=run_command
    test_obj   = Topology(None)
    test_obj.generate_topo_file()
    with open('test/slurmcc_test/topology_test_output/topology.txt','r', encoding='utf-8') as file:
        result= file.read()
    with open('test/slurmcc_test/topology_test_input/topology.txt','r', encoding='utf-8') as file:
        actual= file.read()
    assert result==actual
    
def test_write_slurm_topology():
    """
    Test the write_slurm_topology method of the Topology class.

    This test performs the following steps:
    1. Creates an instance of the Topology class with a specified output file.
    2. Sets the topo_file attribute to a predefined input topology file.
    3. Groups device GUIDs per switch using the group_guids_per_switch method.
    4. Identifies torsets using the identify_torsets method.
    5. Groups hosts by torset using the group_hosts_by_torset method.
    6. Writes the slurm topology to the output file using the write_slurm_topology method.
    7. Reads the generated output file and compares it with an expected output file.
    
    The test asserts that the content of the generated output file matches the expected output file.
    """
    output= 'test/slurmcc_test/topology_test_output/slurm_topology_1.txt'
    test_obj   = Topology(output)
    test_obj.topo_file = 'test/slurmcc_test/topology_test_input/topology.txt'
    test_obj.device_guids_per_switch =  test_obj.group_guids_per_switch()
    test_obj.host_to_torset_map = test_obj.identify_torsets()
    test_obj.torsets = test_obj.group_hosts_by_torset()
    test_obj.write_slurm_topology(output)
    with open('test/slurmcc_test/topology_test_output/slurm_topology_1.txt','r', encoding='utf-8') as file:
        result= file.read()
    with open('test/slurmcc_test/topology_test_input/slurm_topology.txt','r', encoding='utf-8') as file:
        actual= file.read()
    assert result==actual

def test_run():
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
    output= 'test/slurmcc_test/topology_test_output/slurm_topology_2.txt'
    test_obj   = Topology(output)
    test_obj.topo_file = 'test/slurmcc_test/topology_test_input/topology.txt'
    test_obj.run("hpc",None,output)
    with open('test/slurmcc_test/topology_test_output/slurm_topology_2.txt','r', encoding='utf-8') as file:
        result= file.read()
    with open('test/slurmcc_test/topology_test_input/slurm_topology.txt','r', encoding='utf-8') as file:
        actual= file.read()
    assert result==actual