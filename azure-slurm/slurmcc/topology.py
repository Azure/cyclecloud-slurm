"""Module providing slurm topology.conf"""
import os
import sys
import logging
from pathlib import Path
import subprocess as subprocesslib
import datetime
from . import util as slutil
from enum import Enum

log=logging.getLogger('topology')

class TopologyType(Enum):
    """
    Enum class representing the type of topology.
    """
    BLOCK = "block"
    TREE = "tree"
    def __str__(self):
        return self.value

class TopologyInput(Enum):
    """
    Enum class representing the type of topology input.
    """
    NVLINK = "nvlink"
    FABRIC = "fabric"
    def __str__(self):
        return self.value

class Topology:
    """
    A class to represent and manage the topology of a Slurm cluster.
    Attributes:
    """

    def __init__(self, partition, output, topo_input, topo_type, directory, block_size=1):
        if not isinstance(topo_type, TopologyType):
            raise ValueError("topo_type must be an instance of TopologyType Enum")
        if not isinstance(topo_input, TopologyInput):
            raise ValueError("topo_input must be an instance of TopologyInput Enum")
        self.timestamp= datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = f"{directory}/.topology/topology_ouput_{self.timestamp}"
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        self.guid_to_host_map = {}
        self.device_guids_per_switch = []
        self.host_to_torset_map = {}
        self.torsets = {}
        self.partition=partition
        self.hosts=[]
        self.sharp_cmd_path = None
        self.guids_file = f"{self.output_dir}/guids.txt"
        self.topo_file = f"{self.output_dir}/topology.txt"
        self.slurm_top_file= output
        self.topo_input = topo_input
        self.topo_type = topo_type
        self.block_size = block_size

    def get_hostnames(self) -> None:
        """
        Validates partition and retrieves a list of hostnames from the SLURM scheduler based on the provided parition.
        It also checks for hosts that are not idle and powered on and filters them out.
            None
        Raises:
            SystemExit: If the number of valid and powered-on hosts is less than 2.
        Logs:
            Warnings for invalid or powered-down nodes.
            Debug information for the list of hosts and the filtered valid hosts.
            Error if the number of valid and powered-on hosts is less than 2.
        """
        def validate_partition(partition) -> None:
            try:
                output=slutil.run("sinfo -o %P | tr -d '*'", shell=True)
            except subprocesslib.CalledProcessError:
                sys.exit(1)
            except subprocesslib.TimeoutExpired:
                sys.exit(1)
            partitions=set(output.stdout.strip('*').split('\n')[1:-1])
            log.debug("Valid Partitions: %s", partitions)
            if partition not in partitions:
                log.error("Partition %s does not exist", partition)
                sys.exit(1)
            else:
                log.debug("Partition %s exists", partition)
        def get_hostlist(cmd) -> list:
            try:
                output=slutil.run(cmd, shell=True)
            except subprocesslib.CalledProcessError:
                sys.exit(1)
            except subprocesslib.TimeoutExpired:
                sys.exit(1)
            return set(output.stdout.split('\n')[:-1])
        validate_partition(self.partition)
        partition_cmd = f'-p {self.partition} '
        host_cmd = f'scontrol show hostnames $(sinfo -p {self.partition} -o "%N" -h)'
        partition_states = "powered_down,powering_up,powering_down,power_down,drain,drained,draining,unknown,down,no_respond,fail,reboot"
        sinfo_cmd = f'sinfo {partition_cmd}-t {partition_states} -o "%N" -h'
        down_cmd = f'scontrol show hostnames $({sinfo_cmd})'
        hosts=get_hostlist(host_cmd)
        down_hosts=get_hostlist(down_cmd)
        self.hosts = list(hosts-down_hosts)
        if len(self.hosts)<len(hosts):
            log.warning(
                "Some nodes were not fully powered up and idle, "
                "running on a subset of nodes that are powered on and idle"
            )
            log.warning("Excluded Nodes: %s",
                                down_hosts)
        log.debug("Original hosts: %s", hosts)
        log.debug("Powered On and Idle Hosts: %s", self.hosts)
        if len(self.hosts)<2:
            log.error(
                "Need more than 2 nodes to create slurm topology, "
                "less than 2 nodes were powered up and idle. "
            )
            sys.exit(1)

    def get_os_name(self):
        """
        Retrieves the operating system name from the first host in self.hosts.

        This method runs a command on the first host to extract the OS ID from the
        /etc/os-release file. It uses the `grep` command to find the line starting
        with 'ID=' and then cuts the value after the '=' character.

        Returns:
            str: The operating system ID if the command is successful.

        Raises:
            SystemExit: If the command fails, logs the error and exits the program.
        """
        cmd = "grep '^ID=' /etc/os-release | cut -d'=' -f2"
        try:
            output = slutil.srun([self.hosts[0]],cmd,shell=True, partition=self.partition)
            exit_code=output.returncode
            stdout=output.stdout
        except slutil.SrunExitCodeException as e:
            log.error("Error running get_os_id command on host %s",self.hosts[0])
            if e.stderr_content:
                log.error(e.stderr_content)
            log.error(e.stderr)
            sys.exit(e.returncode)
        except subprocesslib.TimeoutExpired:
            sys.exit(1)
        if exit_code==0:
            os_id = stdout.strip().strip('"')
            log.debug(f"OS ID for host {self.hosts[0]}: {os_id}")
            return os_id

    def _run_get_rack_id_command(self) -> str:
        """
        Runs a command to retrieve the rack ID (ClusterUUID) for each host.

        This method executes a shell command on the specified hosts to query the NVIDIA GPU ClusterUUID
        using `nvidia-smi`. The output is processed to extract the hostname and ClusterUUID, which are
        then stored in the `rack_to_host_map` attribute.
        
        Args:
            cmd (str): The command to execute on the hosts.

        Returns:
            str: The output of the command execution.
        """
        cmd = "echo \"$(nvidia-smi -q | grep 'ClusterUUID' | head -n 1 | cut -d: -f2)$(nvidia-smi -q | grep 'CliqueId' | head -n 1 | cut -d: -f2)\" | while IFS= read -r line; do echo \"$(hostname): $line\"; done"
        return slutil.srun(self.hosts, cmd, shell=True, partition=self.partition, gpus=len(self.hosts))
    
    def get_rack_id(self):
        """
        Retrieves a mapping of node names to their corresponding rack (cluster UUID + CliqueId) identifiers.

        Executes an external command to obtain rack information for hosts. Handles errors related to command execution,
        including specific exceptions for command failure and timeouts. Parses the command output, which is expected to be
        a list of lines in the format "node:cluster_uuid", and constructs a dictionary mapping each node to its rack ID.

        Returns:
            dict: A dictionary where keys are node names (str) and values are rack (cluster UUID) identifiers (str).

        Raises:
            SystemExit: If the external command fails or times out, the process exits with the appropriate return code.
        """
        try:
            output = self._run_get_rack_id_command()
        except slutil.SrunExitCodeException as e:
            log.error("Error running get_rack_id command on hosts")
            if e.stderr_content:
                log.error(e.stderr_content)
            log.error(e.stderr)
            sys.exit(e.returncode)
        except subprocesslib.TimeoutExpired:
            sys.exit(1)
        lines = output.stdout.split('\n')[:-1]
        rack_to_host_map = {}
        for line in lines:
            line = line.strip('"')
            node, cluster_uuid = line.split(':')
            rack_to_host_map[node.strip()] = cluster_uuid.strip()
        return rack_to_host_map
    
    def group_hosts_per_rack(self) -> dict:
        """
        Groups hosts by their rack identifiers.
        Returns:
            dict: A dictionary where each key is a rack identifier and the value is a list of hostnames belonging to that rack.
        """

        racks = {}
        rack_to_host_map = self.get_rack_id()
        for host, rack in rack_to_host_map.items():
            if rack not in racks:
                racks[rack] = [host]
            else:
                racks[rack].append(host)
        return racks

    def get_sharp_cmd(self):
        """
        Determines the appropriate SHARP command based on the operating system.

        Returns:
            str: The path to the SHARP command for the detected operating system.

        Raises:
            SystemExit: If the operating system is not supported.
        """
        os_id=self.get_os_name()
        if os_id == "ubuntu":
            log.debug("sharp_cmd_path: /opt/hpcx-v2.18-gcc-mlnx_ofed-ubuntu22.04-cuda12-x86_64/")
            return "/opt/hpcx-v2.18-gcc-mlnx_ofed-ubuntu22.04-cuda12-x86_64/"
        if os_id=="almalinux":
            log.debug("sharp_cmd_path: /opt/hpcx-v2.18-gcc-mlnx_ofed-redhat8-cuda12-x86_64/")
            return "/opt/hpcx-v2.18-gcc-mlnx_ofed-redhat8-cuda12-x86_64/"
        log.error("OS Not supported, exiting")
        sys.exit(1)


    def check_sharp_hello(self):
        """
        Executes the sharp_hello command on the first host in self.hosts and logs the output.

        This method constructs a command to run the `sharp_hello` executable located in the 
        `sharp_cmd_path` directory on the first host in self.hosts. It then executes 
        this command in parallel using `slutil.srun`.

        The standard output of the command is logged at the debug level. If the command 
        fails (i.e., the exit code is not 0), the standard error output is logged at the 
        error level, and the program exits with the same exit code. If the command succeeds, 
        a debug message is logged indicating success, and the method returns 0.

        Returns:
            int: 0 if the sharp_hello command passes successfully.

        Raises:
            SystemExit: If the sharp_hello command fails, the program exits with the 
                        corresponding exit code.
        """
        cmd = f"{self.sharp_cmd_path}sharp/bin/sharp_hello"
        try:
            output = slutil.srun([self.hosts[0]],cmd, partition=self.partition)
            log.debug(output.stdout)
        except slutil.SrunExitCodeException as e:
            log.error("SHARP is disabled on cluster")
            if e.stderr_content:
                log.error(e.stderr_content)
            log.error(e.stderr)
            sys.exit(e.returncode)
        except subprocesslib.TimeoutExpired:
            sys.exit(1)
        if output.returncode==0:
            log.debug("sharp_hello command passed")
            return 0


    def check_ibstatus(self) -> None:
        """
        Checks the availability of the 'ibstatus' command on the first host in self.hosts.

        This method runs a Python command to check if 'ibstatus' is available on the first host.
        If 'ibstatus' is not found, it logs an error message and exits the program.
        If 'ibstatus' is found, it logs a debug message indicating its availability.

        Returns:
            None

        Raises:
            SystemExit: If 'ibstatus' is not available on the first host.
        """
        cmd ="python3 -c \"import shutil; print(shutil.which('ibstatus'))\""
        try:
            output = slutil.srun([self.hosts[0]],cmd, partition=self.partition)
            path=output.stdout.strip()
            log.debug(path)
        except slutil.SrunExitCodeException as e:
            log.error("Error running check_ibstatus command on host %s",self.hosts[0])
            if e.stderr_content:
                log.error(e.stderr_content)
            log.error(e.stderr)
            sys.exit(e.returncode)
        except subprocesslib.TimeoutExpired:
            sys.exit(1)
        if path=="None":
            log.error("The 'ibstatus' command is not available")
            sys.exit(1)
        else:
            log.debug("The 'ibstatus' command is available.")
            return 0

    def retrieve_guids(self) -> None:
        """
        Retrieve GUIDs (Globally Unique Identifiers) from the hosts.
        This method runs a command on self.hosts to retrieve the Port GUIDs
        from the InfiniBand status. The command extracts the GUIDs using a series
        of shell commands and processes the output to map each GUID to its
        corresponding host.
        The GUIDs are stored in the `guid_to_host_map` attribute.
        """
        cmd = (
            'ibstatus | grep mlx5_ib | cut -d" " -f3 | '
            'xargs -I% ibstat "%" | grep "Port GUID" | cut -d: -f2 | '
            'while IFS= read -r line; do echo \"$(hostname): $line\"; done'
        )
        try:
            output = slutil.srun(self.hosts, cmd, shell=True, partition=self.partition)
        except slutil.SrunExitCodeException as e:
            log.error("Error running retrieve_guids command on hosts")
            if e.stderr_content:
                log.error(e.stderr_content)
            log.error(e.stderr)
            sys.exit(e.returncode)
        except subprocesslib.TimeoutExpired:
            sys.exit(1)
        lines=output.stdout.split('\n')[:-1]
        for line in lines:
                # Querying GUIDs from ibstat will have pattern 0x0099999999999999,
                # but Sharp will return 0x99999999999999
                # - So we need to remove the leading 00 after 0x
            node,guid = line.split(':')
            self.guid_to_host_map[guid.replace('0x00', '0x').strip()]=node.strip()

    def write_guids_to_file(self) -> None:
        """
        Writes the GUIDs from the guid_to_host_map to a file.

        This method opens the file specified by self.guids_file in write mode
        with UTF-8 encoding and writes each GUID from the guid_to_host_map
        to the file, each on a new line.
        """
        with open(self.guids_file, 'w', encoding="utf-8") as f:
            for guid in self.guid_to_host_map:
                f.write(f"{guid}\n")

    def generate_topo_file(self) -> None:
        """
        Generates the topology file for SHARP (Scalable Hierarchical Aggregation and Reduction Protocol).

        This method sets up the environment variables and constructs the command to generate the topology file
        using the SHARP command-line tool. The command is executed, and the output is logged to a file.

        Environment Variables:
            SHARP_SMX_UC_INTERFACE: Set to "mlx5_ib0:1".
            SHARP_CMD: Optional. If set, it is used as the base path for the SHARP command.

        Attributes:
            sharp_cmd_path (str): The base path for the SHARP command if SHARP_CMD is not set in the environment.
            guids_file (str): The path to the GUIDs file.
            topo_file (str): The path to the output topology file.
            output_dir (str): The directory where the log file will be saved.

        Raises:
            Any exceptions raised by `slutil.run_command` will propagate.
        """
        env=os.environ.copy()
        if 'SHARP_CMD' not in env:
            command = (
                f"SHARP_SMX_UCX_INTERFACE=mlx5_ib0:1 "
                f"{self.sharp_cmd_path}sharp/bin/sharp_cmd topology "
                f"--ib-dev mlx5_ib0:1 "
                f"--guids_file {self.guids_file} "
                f"--topology_file {self.topo_file}"
            )
        else:
            command = (
                f"SHARP_SMX_UCX_INTERFACE=mlx5_ib0:1 "
                f"{env['SHARP_CMD']}sharp/bin/sharp_cmd topology "
                f"--ib-dev mlx5_ib0:1 "
                f"--guids_file {self.guids_file} "
                f"--topology_file {self.topo_file}"
            )

        try:
            output = slutil.srun([self.hosts[0]], command, shell = True, partition=self.partition)
            log.debug(output.stdout)
        except slutil.SrunExitCodeException as e:
            log.error("Error running sharp_command on host %s",self.hosts[0])
            if e.stderr_content:
                log.error(e.stderr_content)
            log.error(e.stderr)
            sys.exit(e.returncode)
        except subprocesslib.TimeoutExpired:
            sys.exit(1)

    def group_guids_per_switch(self) -> list:
        """
        Parses the topology file and groups GUIDs per switch.

        This method reads the topology file specified by `self.topo_file`, 
        extracts lines containing 'Nodes=', and retrieves the GUIDs associated 
        with each switch. The GUIDs are then grouped and returned as a list.

        Returns:
            list: A list of GUIDs grouped per switch.
        """
        guids_per_switch = []
        with open(self.topo_file, 'r', encoding="utf-8") as f:
            for line in f:
                if 'Nodes=' not in line:
                    continue
                # 'SwitchName=ibsw2 Nodes=0x155dfffd341acb,0x155dfffd341b0b'
                guids_per_switch.append(line.strip().split(' ')[1].split('=')[1])
        return guids_per_switch

    def identify_torsets(self) -> dict:
        """
        Identify and map hosts to torsets based on device GUIDs per switch.

        This method processes the device GUIDs for each switch, assigns a torset index
        to each unique set of hosts, and maps each host to a torset identifier in the
        format "torset-XX", where XX is a zero-padded index.

        Returns:
            dict: A dictionary mapping each host to its corresponding torset identifier.
        """
        host_to_torset_map = {}
        for device_guids_one_switch in self.device_guids_per_switch:
            device_guids = device_guids_one_switch.strip().split(",")
            # increment torset index for each new torset
            torset_index = len(set(host_to_torset_map.values()))
            for guid in device_guids:
                host = self.guid_to_host_map[guid]
                if host in host_to_torset_map:
                    continue
                host_to_torset_map[host] = f"torset-{torset_index:02}"
        return host_to_torset_map

    def group_hosts_by_torset(self) -> dict:
        """
        Groups hosts by their torset.

        This method iterates over the `host_to_torset_map` dictionary and groups
        hosts based on their associated torset. It returns a dictionary where the
        keys are torset identifiers and the values are lists of hosts that belong
        to each torset.

        Returns:
            dict: A dictionary with torset identifiers as keys and lists of hosts
                  as values.
        """
        torsets = {}
        for host, torset in self.host_to_torset_map.items():
            if torset not in torsets:
                torsets[torset] = [host]
            else:
                torsets[torset].append(host)
        return torsets

    def write_block_topology(self, host_dict) -> str:
        """
        Generates a block topology configuration string from a dictionary of host groups.
        Args:
            host_dict (dict): A dictionary where each key is a group identifier (e.g., ClusterUUID and CliqueID)
                              and each value is a list of hostnames belonging to that group.
        Returns:
            str: A formatted string representing the block topology, including comments with the number of nodes
                 and group identifiers, and block definitions listing the nodes in each block.
        """
        if not host_dict:
            log.error("Host dictionary is empty, cannot generate block topology")
            sys.exit(1)
        lines = []
        block_index = 0
        for group_id, hosts in host_dict.items():
            block_index += 1
            num_nodes = len(hosts)
            lines.append(f"# Number of Nodes in block{block_index}: {num_nodes}")
            lines.append(f"# ClusterUUID and CliqueID: {group_id}")
            if "N/A" in group_id:
                lines.append(f"# Warning: Block {block_index} has unknown ClusterUUID and CliqueID")
            if len(hosts) < self.block_size:
                lines.append(f"# Warning: Block {block_index} has less than {self.block_size} nodes, commenting out")
                lines.append(f"#BlockName=block{block_index} Nodes={','.join(hosts)}")
            else:
                lines.append(f"BlockName=block{block_index} Nodes={','.join(hosts)}")
        lines.append(f"BlockSizes={self.block_size}")
        content = "\n".join(lines) + "\n"
        return content

    def write_tree_topology(self) -> str:
        """
        Generates the SLURM tree topology configuration as a string.

        This method constructs the SLURM topology configuration based on the `torsets` attribute,
        where each torset represents a set of hosts connected to a switch. For each torset, it adds
        a configuration line specifying the switch name and associated nodes. If there are multiple
        torsets, it also adds a parent switch connecting all the individual switches.

        Returns:
            str: The generated SLURM topology configuration as a string.
        """
        switches = []
        lines = []
        for torset, hosts in self.torsets.items():
            torset_index = torset[-2:]
            num_nodes = len(hosts)
            lines.append(f"# Number of Nodes in sw{torset_index}: {num_nodes}")
            lines.append(f"SwitchName=sw{torset_index} Nodes={','.join(hosts)}")
            switches.append(f"sw{torset_index}")
        if len(self.torsets) > 1:
            switch_name = int(torset_index) + 1
            lines.append(f"SwitchName=sw{switch_name:02} Switches={','.join(switches)}")
        content = "\n".join(lines) + "\n"
        return content

    def run_nvlink(self) -> dict:
        """
        Executes the NVLink topology discovery process for the cluster.

        This method performs the following steps:
            1. Retrieves the list of hostnames in the cluster.
            2. Obtains rack IDs for each host.
            3. Groups hosts by their respective racks and stores the result.
        Returns:
            dict: A dictionary where keys are rack identifiers and values are lists of hostnames in each rack.

        """
        self.get_hostnames()
        racks = self.group_hosts_per_rack()
        log.debug("Grouped hosts by racks")
        return racks
    
    def run_fabric(self):
        """
        Executes the full workflow to collect InfiniBand topology information and generate topology files.

        The method performs the following steps:
            1. Retrieves the list of hostnames.
            2. Locates the directory containing the SHARP command-line tools.
            3. Verifies that the SHARP hello command works on all hosts.
            4. Checks that the 'ibstat' command can be executed on all hosts.
            5. Collects InfiniBand device GUIDs from all hosts.
            6. Writes the collected GUIDs to a file.
            7. Generates the topology file based on the collected data.
            8. Groups device GUIDs by InfiniBand switch.
            9. Identifies torsets (groups of hosts connected to the same switch).
            10. Groups hosts by their corresponding torsets.

        """
        self.get_hostnames()
        self.sharp_cmd_path=self.get_sharp_cmd()
        self.check_sharp_hello()
        self.check_ibstatus()
        self.retrieve_guids()
        self.write_guids_to_file()
        self.generate_topo_file()
        log.debug("Topology file generated at %s", self.topo_file)
        self.device_guids_per_switch =  self.group_guids_per_switch()
        self.host_to_torset_map = self.identify_torsets()
        self.torsets = self.group_hosts_by_torset()
        log.debug("Finished grouping hosts by torsets")

    def run(self):
        """
        Executes the topology generation process based on the specified input and topology type.

        - Runs NVLINK or fabric topology generation depending on the `topo_input`.
        - Writes the topology in either block or tree format based on `topo_type`.
        - Logs the completion of topology writing, indicating the output file if specified.

        Raises:
            Any exceptions raised by the called methods are propagated.
        """
        if self.topo_input == TopologyInput.FABRIC:
            self.run_fabric()
            host_dict = None
        else:
            host_dict = self.run_nvlink()
        content = self.write_tree_topology() if self.topo_type == TopologyType.TREE else self.write_block_topology(host_dict)
        if self.slurm_top_file:
            with open(self.slurm_top_file, 'w', encoding="utf-8") as file:
                file.write(content)
            log.info("Finished writing slurm topology to %s", self.slurm_top_file)
        else:
            print(content, end='')
            log.info("Printed slurm topology")
            