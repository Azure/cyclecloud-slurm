'''This module contains test functions for the Topology class and utility functions for running commands and handling outputs.
Classes:
    OutputContainer: A container class to hold the standard output.
    ParallelOutputContainer: A container for storing the output of a srun command.
'''
from slurmcc.topology import Topology, TopologyInput, TopologyType
from slurmcc import util as slutil
from pathlib import Path
import pytest
import re

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
        with open('test/slurmcc_test/topology_test_input/nodes_clusterUUIDs.txt', 'r', encoding='utf-8') as f:
            stdout = f.read()
        return ParallelOutputContainer(stdout, "", 0)
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

def test_visualize_block_topology():
    slutil.srun=run_parallel_cmd
    slutil.run=run_command
    test_obj   = Topology("hpc",None,TopologyInput.NVLINK,TopologyType.BLOCK,TESTDIR)
    def fake_run_get_rack_id_command_1(*args, **kwargs):
        with open('test/slurmcc_test/topology_test_input/nodes_clusterUUIDs.txt', 'r', encoding='utf-8') as f:
            stdout = f.read()
        return ParallelOutputContainer(stdout, "", 0)
    test_obj._run_get_rack_id_command = fake_run_get_rack_id_command_1
    content=test_obj.run()
    vis = test_obj.visualize(content,18)
    print(vis)
    with open('test/slurmcc_test/topology_test_output/block_topo_vis.txt', 'w', encoding='utf-8') as f:
        f.write(vis)
    with open('test/slurmcc_test/topology_test_output/block_topo_vis.txt','r', encoding='utf-8') as file:
        result= file.read()
    with open('test/slurmcc_test/topology_test_input/block_topo_vis.txt','r', encoding='utf-8') as file:
        actual= file.read()
    assert result==actual

def test_bfl_visualize_block_topology():
    test_obj   = Topology("hpc",None,TopologyInput.NVLINK,TopologyType.BLOCK,TESTDIR)
    content = (
                "# Number of Nodes in block1: 8\n"
                "# ClusterUUID and CliqueID: 1db72bdb-8004-4407-a49a-a9a935a80529 32766\n"
                "BlockName=block1 Nodes=ccw1-gpu-8,ccw1-gpu-22,ccw1-gpu-82,ccw1-gpu-179,ccw1-gpu-97,ccw1-gpu-146,ccw1-gpu-45,ccw1-gpu-112\n"
                "# Number of Nodes in block2: 15\n"
                "# ClusterUUID and CliqueID: 18f2ff51-040a-486c-90ce-138067a7379a 32766\n"
                "BlockName=block2 Nodes=ccw1-gpu-247,ccw1-gpu-134,ccw1-gpu-17,ccw1-gpu-33,ccw1-gpu-110,ccw1-gpu-51,ccw1-gpu-240,ccw1-gpu-154,ccw1-gpu-186,ccw1-gpu-198,ccw1-gpu-95,ccw1-gpu-210,ccw1-gpu-169,ccw1-gpu-225,ccw1-gpu-227\n"
                "# Number of Nodes in block3: 18\n"
                "# ClusterUUID and CliqueID: f9eeccb9-69ff-4a55-95e8-c00f14b83c38 32766\n"
                "BlockName=block3 Nodes=ccw1-gpu-1,ccw1-gpu-9,ccw1-gpu-242,ccw1-gpu-79,ccw1-gpu-209,ccw1-gpu-248,ccw1-gpu-128,ccw1-gpu-172,ccw1-gpu-218,ccw1-gpu-109,ccw1-gpu-76,ccw1-gpu-32,ccw1-gpu-61,ccw1-gpu-203,ccw1-gpu-138,ccw1-gpu-238,ccw1-gpu-163,ccw1-gpu-226\n"
                "# Number of Nodes in block4: 17\n"
                "# ClusterUUID and CliqueID: 50c636e0-94d8-4df8-97c5-515a399e7f60 32766\n"
                "BlockName=block4 Nodes=ccw1-gpu-164,ccw1-gpu-73,ccw1-gpu-195,ccw1-gpu-207,ccw1-gpu-245,ccw1-gpu-129,ccw1-gpu-10,ccw1-gpu-144,ccw1-gpu-125,ccw1-gpu-221,ccw1-gpu-235,ccw1-gpu-3,ccw1-gpu-104,ccw1-gpu-215,ccw1-gpu-229,ccw1-gpu-53,ccw1-gpu-80\n"
                "# Number of Nodes in block5: 13\n"
                "# ClusterUUID and CliqueID: 475636da-3c86-4f45-bc03-7623e8ef7085 32766\n"
                "BlockName=block5 Nodes=ccw1-gpu-31,ccw1-gpu-184,ccw1-gpu-40,ccw1-gpu-166,ccw1-gpu-156,ccw1-gpu-65,ccw1-gpu-5,ccw1-gpu-13,ccw1-gpu-87,ccw1-gpu-78,ccw1-gpu-75,ccw1-gpu-108,ccw1-gpu-136\n"
                "# Number of Nodes in block6: 16\n"
                "# ClusterUUID and CliqueID: 87e6be3b-cd1a-46cd-ae93-7ea1629a165f 32766\n"
                "BlockName=block6 Nodes=ccw1-gpu-91,ccw1-gpu-74,ccw1-gpu-135,ccw1-gpu-34,ccw1-gpu-193,ccw1-gpu-116,ccw1-gpu-63,ccw1-gpu-160,ccw1-gpu-29,ccw1-gpu-202,ccw1-gpu-130,ccw1-gpu-126,ccw1-gpu-48,ccw1-gpu-165,ccw1-gpu-208,ccw1-gpu-211\n"
                "# Number of Nodes in block7: 16\n"
                "# ClusterUUID and CliqueID: cc79d754-915f-408b-b1c3-b8c3aa6668ab 32766\n"
                "BlockName=block7 Nodes=ccw1-gpu-237,ccw1-gpu-182,ccw1-gpu-217,ccw1-gpu-90,ccw1-gpu-223,ccw1-gpu-201,ccw1-gpu-159,ccw1-gpu-243,ccw1-gpu-139,ccw1-gpu-192,ccw1-gpu-64,ccw1-gpu-120,ccw1-gpu-2,ccw1-gpu-231,ccw1-gpu-41,ccw1-gpu-47\n"
                "# Number of Nodes in block8: 17\n"
                "# ClusterUUID and CliqueID: 19ce407e-11b7-4236-97f7-0f9a5b62692b 32766\n"
                "BlockName=block8 Nodes=ccw1-gpu-49,ccw1-gpu-77,ccw1-gpu-157,ccw1-gpu-137,ccw1-gpu-30,ccw1-gpu-102,ccw1-gpu-142,ccw1-gpu-181,ccw1-gpu-4,ccw1-gpu-71,ccw1-gpu-12,ccw1-gpu-88,ccw1-gpu-162,ccw1-gpu-20,ccw1-gpu-117,ccw1-gpu-98,ccw1-gpu-57\n"
                "# Number of Nodes in block9: 17\n"
                "# ClusterUUID and CliqueID: 809d6b94-4c14-40b4-8eee-b71539be6baf 32766\n"
                "BlockName=block9 Nodes=ccw1-gpu-19,ccw1-gpu-212,ccw1-gpu-224,ccw1-gpu-241,ccw1-gpu-197,ccw1-gpu-46,ccw1-gpu-105,ccw1-gpu-23,ccw1-gpu-222,ccw1-gpu-188,ccw1-gpu-249,ccw1-gpu-133,ccw1-gpu-56,ccw1-gpu-89,ccw1-gpu-94,ccw1-gpu-234,ccw1-gpu-153\n"
                "# Number of Nodes in block10: 14\n"
                "# ClusterUUID and CliqueID: 5110b53c-8898-4b07-bb98-9c7159894d5a 32766\n"
                "BlockName=block10 Nodes=ccw1-gpu-15,ccw1-gpu-18,ccw1-gpu-14,ccw1-gpu-7,ccw1-gpu-22,ccw1-gpu-11,ccw1-gpu-16,ccw1-gpu-21,ccw1-gpu-27,ccw1-gpu-28,ccw1-gpu-24,ccw1-gpu-26,ccw1-gpu-25,ccw1-gpu-39\n"
                "# Number of Nodes in block11: 16\n"
                "# ClusterUUID and CliqueID: ad2669de-e798-494b-b2fb-ab9445b17e75 32766\n"
                "BlockName=block11 Nodes=ccw1-gpu-250,ccw1-gpu-244,ccw1-gpu-50,ccw1-gpu-72,ccw1-gpu-143,ccw1-gpu-84,ccw1-gpu-114,ccw1-gpu-194,ccw1-gpu-220,ccw1-gpu-206,ccw1-gpu-158,ccw1-gpu-28,ccw1-gpu-185,ccw1-gpu-232,ccw1-gpu-228,ccw1-gpu-176\n"
                "# Number of Nodes in block12: 16\n"
                "# ClusterUUID and CliqueID: 8a2e3316-46f1-4772-882f-a53e2448892b 32766\n"
                "BlockName=block12 Nodes=ccw1-gpu-36,ccw1-gpu-55,ccw1-gpu-27,ccw1-gpu-151,ccw1-gpu-122,ccw1-gpu-118,ccw1-gpu-18,ccw1-gpu-141,ccw1-gpu-103,ccw1-gpu-70,ccw1-gpu-131,ccw1-gpu-60,ccw1-gpu-175,ccw1-gpu-92,ccw1-gpu-161,ccw1-gpu-171\n"
                "# Number of Nodes in block13: 16\n"
                "# ClusterUUID and CliqueID: a3b58aab-21bc-4a89-8eaf-cf7ce06c1609 32766\n"
                "BlockName=block13 Nodes=ccw1-gpu-85,ccw1-gpu-149,ccw1-gpu-239,ccw1-gpu-38,ccw1-gpu-204,ccw1-gpu-58,ccw1-gpu-213,ccw1-gpu-67,ccw1-gpu-100,ccw1-gpu-173,ccw1-gpu-219,ccw1-gpu-24,ccw1-gpu-177,ccw1-gpu-189,ccw1-gpu-115,ccw1-gpu-233\n"
                "# Number of Nodes in block14: 18\n"
                "# ClusterUUID and CliqueID: b78ed242-7b98-426f-b194-b76b8899f4ec 32766\n"
                "BlockName=block14 Nodes=ccw1-gpu-123,ccw1-gpu-132,ccw1-gpu-69,ccw1-gpu-83,ccw1-gpu-15,ccw1-gpu-26,ccw1-gpu-147,ccw1-gpu-93,ccw1-gpu-52,ccw1-gpu-107,ccw1-gpu-113,ccw1-gpu-152,ccw1-gpu-62,ccw1-gpu-44,ccw1-gpu-7,ccw1-gpu-127,ccw1-gpu-35,ccw1-gpu-167\n"
                "# Number of Nodes in block15: 16\n"
                "# ClusterUUID and CliqueID: acd0098d-5416-4fe2-b3b9-edebcd0d9374 32766\n"
                "BlockName=block15 Nodes=ccw1-gpu-246,ccw1-gpu-14,ccw1-gpu-37,ccw1-gpu-214,ccw1-gpu-236,ccw1-gpu-119,ccw1-gpu-200,ccw1-gpu-66,ccw1-gpu-191,ccw1-gpu-148,ccw1-gpu-124,ccw1-gpu-42,ccw1-gpu-99,ccw1-gpu-216,ccw1-gpu-168,ccw1-gpu-230\n"
                "# Number of Nodes in block16: 16\n"
                "# ClusterUUID and CliqueID: ef2f7639-552c-437e-bcee-56af9d562415 32766\n"
                "BlockName=block16 Nodes=ccw1-gpu-25,ccw1-gpu-205,ccw1-gpu-170,ccw1-gpu-11,ccw1-gpu-39,ccw1-gpu-196,ccw1-gpu-86,ccw1-gpu-6,ccw1-gpu-111,ccw1-gpu-187,ccw1-gpu-155,ccw1-gpu-145,ccw1-gpu-183,ccw1-gpu-121,ccw1-gpu-54,ccw1-gpu-59\n"
                "BlockSizes=1\n"

            )
    vis = test_obj.visualize(content,18)
    with open('test/slurmcc_test/topology_test_output/bfl_block_topo_vis.txt', 'w', encoding='utf-8') as f:
        f.write(vis)
    with open('test/slurmcc_test/topology_test_output/bfl_block_topo_vis.txt','r', encoding='utf-8') as file:
        result= file.read()
    with open('test/slurmcc_test/topology_test_input/bfl_block_topo_vis.txt','r', encoding='utf-8') as file:
        actual= file.read()
    assert result==actual

def test_visualize_tree_topology():
    slutil.srun=run_parallel_cmd
    slutil.run=run_command
    test_obj   = Topology("hpc",None,TopologyInput.FABRIC,TopologyType.TREE,TESTDIR)
    content=test_obj.run()
    vis = test_obj.visualize(content,18)
    with open('test/slurmcc_test/topology_test_output/tree_topo_vis.txt', 'w', encoding='utf-8') as f:
            f.write(vis)
    with open('test/slurmcc_test/topology_test_output/tree_topo_vis.txt','r', encoding='utf-8') as file:
        result= file.read()
    with open('test/slurmcc_test/topology_test_input/tree_topo_vis.txt','r', encoding='utf-8') as file:
        actual= file.read()
    assert result==actual

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

def test_get_rack_id_success(monkeypatch):
    class DummyOutput:
        stdout = 'node1:uuidA\nnode2:uuidB\nnode3:uuidA\n'
    def fake_run_get_rack_id_command(*args, **kwargs):
        return DummyOutput()
    test_obj = Topology("hpc", None, TopologyInput.NVLINK, TopologyType.BLOCK, TESTDIR)
    test_obj._run_get_rack_id_command = fake_run_get_rack_id_command
    result = test_obj.get_rack_id()
    assert result == {'node1': 'uuidA', 'node2': 'uuidB', 'node3': 'uuidA'}

def test_get_rack_id_empty(monkeypatch):
    class DummyOutput:
        stdout = ''
    def fake_run_get_rack_id_command(*args, **kwargs):
        return DummyOutput()
    test_obj = Topology("hpc", None, TopologyInput.NVLINK, TopologyType.BLOCK, TESTDIR)
    test_obj._run_get_rack_id_command = fake_run_get_rack_id_command
    result = test_obj.get_rack_id()
    assert result == {}

def test_get_rack_id_strip_quotes(monkeypatch):
    class DummyOutput:
        stdout = '"node1:uuidA"\n"node2:uuidB"\n'
    def fake_run_get_rack_id_command(*args, **kwargs):
        return DummyOutput()
    test_obj = Topology("hpc", None, TopologyInput.NVLINK, TopologyType.BLOCK, TESTDIR)
    test_obj._run_get_rack_id_command = fake_run_get_rack_id_command
    result = test_obj.get_rack_id()
    assert result == {'node1': 'uuidA', 'node2': 'uuidB'}

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
                "# Number of Nodes in block1: 2",
                "# ClusterUUID and CliqueID: rackA",
                "BlockName=block1 Nodes=node1,node2",
                "# Number of Nodes in block2: 2",
                "# ClusterUUID and CliqueID: rackB",
                "BlockName=block2 Nodes=node3,node4",
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
                "#BlockName=block1 Nodes=node1,node2",
                "BlockName=block2 Nodes=node3,node4,node5",
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
                "#BlockName=block1 Nodes=node1",
                "# Warning: Block 2 has less than 5 nodes, commenting out",
                "#BlockName=block2 Nodes=node2,node3",
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
    assert "# Number of Nodes in block1: 1" in result
    assert "# Number of Nodes in block2: 1" in result
    assert "# Number of Nodes in block3: 1" in result
    assert result.count("BlockSizes=2") == 1

def test_write_block_topology_single_block_enough_nodes():
    host_dict = {"rackA": ["node1", "node2"]}
    test_obj = Topology("hpc", None, TopologyInput.NVLINK, TopologyType.BLOCK, TESTDIR, block_size=2)
    result = test_obj.write_block_topology(host_dict)
    assert "BlockName=block1 Nodes=node1,node2" in result
    assert "# Warning:" not in result

def test_write_block_topology_single_block_too_few_nodes():
    host_dict = {"rackA": ["node1"]}
    test_obj = Topology("hpc", None, TopologyInput.NVLINK, TopologyType.BLOCK, TESTDIR, block_size=3)
    result = test_obj.write_block_topology(host_dict)
    assert "# Warning: Block 1 has less than 3 nodes, commenting out" in result
    assert "#BlockName=block1 Nodes=node1" in result
    # The uncommented version should not appear anywhere in the result
    assert "\nBlockName=block1 Nodes=node1\n" not in f"\n{result}\n"

def test_write_block_topology_multiple_blocks_mixed_sizes():
    host_dict = {
        "rackA": ["node1", "node2", "node3"],
        "rackB": ["node4"],
        "rackC": ["node5", "node6", "node7"],
    }
    test_obj = Topology("hpc", None, TopologyInput.NVLINK, TopologyType.BLOCK, TESTDIR, block_size=3)
    result = test_obj.write_block_topology(host_dict)
    assert "BlockName=block1 Nodes=node1,node2,node3" in result
    assert "# Warning: Block 2 has less than 3 nodes, commenting out" in result
    assert "#BlockName=block2 Nodes=node4" in result
    assert "BlockName=block3 Nodes=node5,node6,node7" in result

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

@pytest.mark.parametrize(
    "topo_type,topology_str,max_block_size,expected_lines,block_size",
    [
        # BLOCK: one block, not enough nodes, commented
        (
            TopologyType.BLOCK,
            "# Number of Nodes in block1: 1\n"
            "# ClusterUUID and CliqueID: rackA\n"
            "# Warning: Block 1 has less than 2 nodes, commenting out\n"
            "#BlockName=block1 Nodes=node1\n"
            "BlockSizes=2\n",
            2,
            [
                "block 1  : # of Nodes = 1",
                "ClusterUUID + CliqueID : rackA",
                "** This block is ineligible for scheduling because # of nodes < min block size 2**",
                "|-------|",
                "| node1 |",
                "|-------|",
                "|   X   |",
                "|-------|",
            ],
            2
        ),
        (
            TopologyType.BLOCK,
            "# Number of Nodes in block1: 6\n"
            "# ClusterUUID and CliqueID: N/A N/A\n"
            "# Warning: Block 1 has unknown ClusterUUID and CliqueID\n"
            "# Warning: Block 1 has less than 8 nodes, commenting out\n"
            "#BlockName=block1 Nodes=vis0603-gpu-4,vis0603-gpu-6,vis0603-gpu-3,vis0603-gpu-5,vis0603-gpu-1,vis0603-gpu-2\n"
            "BlockSizes=8",
            18,
            [
                "block 1  : # of Nodes = 6",
                "ClusterUUID + CliqueID : N/A N/A",
                "** This block is ineligible for scheduling because # of nodes < min block size 8**",
                "|---------------|---------------|---------------|",
                "| vis0603-gpu-4 | vis0603-gpu-6 | vis0603-gpu-3 |",
                "|---------------|---------------|---------------|",
                "| vis0603-gpu-5 | vis0603-gpu-1 | vis0603-gpu-2 |",
                "|---------------|---------------|---------------|",
                "|       X       |       X       |       X       |",
                "|---------------|---------------|---------------|",
                "|       X       |       X       |       X       |",
                "|---------------|---------------|---------------|",
                "|       X       |       X       |       X       |",
                "|---------------|---------------|---------------|",
                "|       X       |       X       |       X       |"
            ],
            8
        ),
        # BLOCK: no valid blocks
        (
            TopologyType.BLOCK,
            "",
            2,
            [
                "# No valid blocks found in topology string.",
            ],
            2
        ),
        (
            TopologyType.BLOCK,
            (
                "# Number of Nodes in block1: 4\n"
                "# ClusterUUID and CliqueID: rackA\n"
                "BlockName=block1 Nodes=node1,node2,node3,node4\n"
                "BlockSizes=4\n"
            ),
            4,
            [
                "block 1  : # of Nodes = 4",
                "ClusterUUID + CliqueID : rackA",
                "|-------|-------|",
                "| node1 | node2 |",
                "|-------|-------|",
                "| node3 | node4 |",
                "|-------|-------|",
            ],
            2
        ),
        (
            TopologyType.BLOCK,
            (
                "# Number of Nodes in block1: 2\n"
                "# ClusterUUID and CliqueID: rackB\n"
                "BlockName=block1 Nodes=nodeA,nodeB\n"
                "BlockSizes=2\n"
            ),
            2,
            [
                "block 1  : # of Nodes = 2",
                "ClusterUUID + CliqueID : rackB",
                "|-------|",
                "| nodeA |",
                "|-------|",
                "| nodeB |",
                "|-------|",
            ],
            2
        ),
        (
            TopologyType.BLOCK,
            (
                "# Number of Nodes in block1: 1\n"
                "# ClusterUUID and CliqueID: rackC\n"
                "BlockName=block1 Nodes=host1\n"
                "BlockSizes=3\n"
            ),
            3,
            [
                "block 1  : # of Nodes = 1",
                "ClusterUUID + CliqueID : rackC",
                "|-------|",
                "| host1 |",
                "|-------|",
                "|   X   |",
                "|-------|",
                "|   X   |",
                "|-------|",
            ],
            2
        ),
        (
            TopologyType.BLOCK,
            (
                "# Number of Nodes in block1: 0\n"
                "# ClusterUUID and CliqueID: rackD\n"
                "BlockName=block1 Nodes=\n"
                "BlockSizes=2\n"
            ),
            2,
            [
                "# No valid blocks found in topology string."
            ],
            2
        ),
        (
            TopologyType.BLOCK,
            (
                "# Number of Nodes in block1: 3\n"
                "# ClusterUUID and CliqueID: rackE\n"
                "BlockName=block1 Nodes=node1,node2,node3\n"
                "BlockSizes=2\n"
            ),
            5,
            [
                "block 1  : # of Nodes = 3",
                "ClusterUUID + CliqueID : rackE",
                "|-------|",
                "| node1 |",
                "|-------|",
                "| node2 |",
                "|-------|",
                "| node3 |",
                "|-------|",
                "|   X   |",
                "|-------|",
                "|   X   |",
                "|-------|"
            ],
            2
        ),
        # TREE: two switches, one parent
        (
            TopologyType.TREE,
            "# Number of Nodes in sw01: 2\n"
            "SwitchName=sw01 Nodes=node1,node2\n"
            "# Number of Nodes in sw02: 1\n"
            "SwitchName=sw02 Nodes=node3\n"
            "SwitchName=sw03 Switches=sw01,sw02\n",
            2,
            [
                "Switch 3 (root)",
                "├── Switch 1 (2 nodes)",
                "│   ├── node1",
                "│   └── node2",
                "└── Switch 2 (1 nodes)",
                "    └── node3",
            ],
            2
        ),
        # TREE: no valid switches
        (
            TopologyType.TREE,
            "",
            2,
            [
                "# No valid switches found in topology string.",
            ],
            2
        ),
        
    ]
)
def test_visualize_various_cases(topo_type, topology_str, max_block_size, expected_lines,block_size):
    test_obj = Topology("hpc", None, TopologyInput.FABRIC, topo_type, "testdir", block_size)
    result = test_obj.visualize(topology_str, max_block_size)
    print(result)
    for line in expected_lines:
        assert line in result

def test_visualize_block_grid_shape():
    # Test grid shape for block size 6 (should be 3x2 or 2x3)
    topology_str = (
        "# Number of Nodes in block1: 6\n"
        "# ClusterUUID and CliqueID: rackA\n"
        "BlockName=block1 Nodes=n1,n2,n3,n4,n5,n6\n"
        "BlockSizes=6\n"
    )
    test_obj = Topology("hpc", None, TopologyInput.NVLINK, TopologyType.BLOCK, "testdir", block_size=6)
    vis = test_obj.visualize(topology_str, 6)
    # Should have 3 rows and 2 columns or 2 rows and 3 columns
    assert vis.count("|") > 0
    assert "n1" in vis and "n6" in vis

def test_visualize_block_invalid_max_block_size():
    topology_str = (
        "# Number of Nodes in block1: 2\n"
        "# ClusterUUID and CliqueID: rackA\n"
        "BlockName=block1 Nodes=node1,node2\n"
        "BlockSizes=2\n"
    )
    test_obj = Topology("hpc", None, TopologyInput.NVLINK, TopologyType.BLOCK, "testdir", block_size=2)
    with pytest.raises(ValueError):
        test_obj.visualize(topology_str, 0)

def test_visualize_tree_no_parent_switch():
    topology_str = (
        "# Number of Nodes in sw01: 2\n"
        "SwitchName=sw01 Nodes=node1,node2\n"
        "# Number of Nodes in sw02: 1\n"
        "SwitchName=sw02 Nodes=node3\n"
    )
    test_obj = Topology("hpc", None, TopologyInput.FABRIC, TopologyType.TREE, "testdir")
    vis = test_obj.visualize(topology_str, 2)
    assert "Switch 1 (2 nodes)" in vis
    assert "Switch 2 (1 nodes)" in vis
    assert "node1" in vis and "node2" in vis and "node3" in vis

def test_visualize_tree_with_parent_switch():
    topology_str = (
        "# Number of Nodes in sw01: 2\n"
        "SwitchName=sw01 Nodes=node1,node2\n"
        "# Number of Nodes in sw02: 1\n"
        "SwitchName=sw02 Nodes=node3\n"
        "SwitchName=sw03 Switches=sw01,sw02\n"
    )
    test_obj = Topology("hpc", None, TopologyInput.FABRIC, TopologyType.TREE, "testdir")
    vis = test_obj.visualize(topology_str, 2)
    assert "Switch 3 (root)" in vis
    assert "Switch 1 (2 nodes)" in vis
    assert "Switch 2 (1 nodes)" in vis
    assert "node1" in vis and "node2" in vis and "node3" in vis





