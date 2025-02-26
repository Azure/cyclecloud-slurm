"""Module providing slurm topology.conf for IB SHARP-enabled Cluster"""
import os
import sys
import logging
from pathlib import Path
import subprocess as subprocesslib
import datetime
from . import util as slutil

log=logging.getLogger('topology')

class Topology:
    """
    A class to represent and manage the topology of a Slurm cluster.
    Attributes:
    """

    def __init__(self,partition, output,directory):
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

    def get_hostnames(self) -> None:
        """
        Retrieves and validates the list of hostnames for a given partition.
        This method fetches the list of hostnames from the SLURM scheduler based on the provided
        partition or string of nodes and validates them against the list of all available hostnames. It also checks
        for hosts that are powered down and filters them out.
            None
        Raises:
            SystemExit: If the number of valid and powered-on hosts is less than 2.
        Logs:
            Warnings for invalid or powered-down nodes.
            Debug information for the list of hosts and the filtered valid hosts.
            Error if the number of valid and powered-on hosts is less than 2.
        """
        def get_hostlist(cmd) -> list:
            try:
                output=slutil.run(cmd, shell=True)
            except subprocesslib.CalledProcessError:
                sys.exit(1)
            except subprocesslib.TimeoutExpired:
                sys.exit(1)
            return set(output.stdout.split('\n')[:-1])
        partition_cmd = f'-p {self.partition} '
        host_cmd = f'scontrol show hostnames $(sinfo -p {self.partition} -o "%N" -h)'
        partition_states = "powered_down,powering_up,powering_down,power_down,drain,drained,draining,unknown,down,no_respond,fail,reboot"
        sinfo_cmd = f'sinfo {partition_cmd}-t {partition_states} -o "%N" -h'
        down_cmd = f'scontrol show hostnames $({sinfo_cmd})'
        hosts=get_hostlist(host_cmd)
        down_hosts=get_hostlist(down_cmd)
        #powered_down_hosts = hosts&down_hosts
        self.hosts = list(hosts-down_hosts)
        if len(self.hosts)<len(hosts):
            log.warning(
                "Some nodes were not fully powered up and idle, "
                "running on a subset of nodes that are powered on and idle"
            )
            log.warning("Excluded Nodes: %s",
                                down_hosts)
        log.debug(hosts)
        log.debug(self.hosts)
        if len(self.hosts)<2:
            log.error(
                "Need more than 2 nodes to create slurm topology, "
                "less than 2 nodes were powered up and idle. "
            )
            sys.exit(1)

    def get_os_name(self):
        """
        Retrieves the operating system name from the first host in the list.

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
            output = slutil.srun([self.hosts[0]],cmd,shell=True)
            exit_code=output.returncode
            stdout=output.stdout
        except slutil.SrunExitCodeException as e:
            log.error("Error running command on host %s",self.hosts[0])
            log.error(e.stderr)
            sys.exit(e.returncode)
        except subprocesslib.TimeoutExpired:
            sys.exit(1)
        if exit_code==0:
            os_id = stdout.strip().strip('"')
            log.debug(f"OS ID for host {self.hosts[0]}: {os_id}")
            return os_id

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
            return "/opt/hpcx-v2.18-gcc-mlnx_ofed-ubuntu22.04-cuda12-x86_64/"
        if os_id=="almalinux":
            return "/opt/hpcx-v2.18-gcc-mlnx_ofed-redhat8-cuda12-x86_64/"
        log.error("OS Not supported, exiting")
        sys.exit(1)


    def check_sharp_hello(self):
        """
        Executes the sharp_hello command on the first host in the list and logs the output.

        This method constructs a command to run the `sharp_hello` executable located in the 
        `sharp_cmd_path` directory on the first host in the `hosts` list. It then executes 
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
            output = slutil.srun([self.hosts[0]],cmd)
            log.debug(output.stdout)
        except slutil.SrunExitCodeException as e:
            log.error("SHARP is disabled on cluster")
            log.error(e.stderr)
            sys.exit(e.returncode)
        except subprocesslib.TimeoutExpired:
            sys.exit(1)
        if output.returncode==0:
            log.debug("sharp_hello command passed")
            return 0


    def check_ibstatus(self) -> None:
        """
        Checks the availability of the 'ibstatus' command on the first host in the list.

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
            output = slutil.srun([self.hosts[0]],cmd)
            path=output.stdout.strip()
            log.debug(path)
        except slutil.SrunExitCodeException as e:
            log.error("Error running command on host %s",self.hosts[0])
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
        This method runs a command on multiple hosts to retrieve the Port GUIDs
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
            output = slutil.srun(self.hosts, cmd, shell=True)
        except slutil.SrunExitCodeException as e:
            log.error("Error running command on hosts")
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

        Logs:
            The output of the SHARP command is logged to `output_dir/logs/topology.log`.

        Raises:
            Any exceptions raised by `slutil.run_command` will propagate.
        """
        env=os.environ.copy()
        env["SHARP_SMX_UC_INTERFACE"]= "mlx5_ib0:1"
        if 'SHARP_CMD' not in env:
            command = (
                f"{self.sharp_cmd_path}sharp/bin/sharp_cmd topology "
                f"--ib-dev mlx5_ib0:1 "
                f"--guids_file {self.guids_file} "
                f"--topology_file {self.topo_file}"
            )
        else:
            command = (
                f"{env['SHARP_CMD']}sharp/bin/sharp_cmd topology "
                f"--ib-dev mlx5_ib0:1 "
                f"--guids_file {self.guids_file} "
                f"--topology_file {self.topo_file}"
            )

        try:
            output = slutil.srun([self.hosts[0]], command)
            log.debug(output.stdout)
        except slutil.SrunExitCodeException as e:
            log.error("Error running sharp_command on host %s",self.hosts[0])
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
    def write_slurm_topology(self)-> None:
        """
        Writes the SLURM topology configuration to a file or prints it to the console.

        This method generates the SLURM topology configuration based on the `torsets` attribute
        and either writes it to a file specified by `self.slurm_top_file` or prints it to the console,
        depending on the value of the `output` parameter.

        Returns:
            None
        """
        switches=[]
        if self.slurm_top_file:
            with open(self.slurm_top_file, 'w', encoding="utf-8") as file:
                for torset, hosts in self.torsets.items():
                    torset_index=torset[-2:]
                    file.write(f"SwitchName=sw{torset_index} Nodes={','.join(hosts)}\n")
                    print(f"SwitchName=sw{torset_index} Nodes={','.join(hosts)}\n")
                    switches.append(f"sw{torset_index}")
                if len(self.torsets)>1:
                    switch_name=int(torset_index)+1
                    file.write(f"SwitchName=sw{switch_name:02} Switches={','.join(switches)}\n")
                    print(f"SwitchName=sw{switch_name:02} Switches={','.join(switches)}\n")
        else:
            for torset, hosts in self.torsets.items():
                torset_index=torset[-2:]
                print(f"SwitchName=sw{torset_index} Nodes={','.join(hosts)}\n")
                switches.append(f"sw{torset_index}")
            if len(self.torsets)>1:
                switch_name=int(torset_index)+1
                print(f"SwitchName=sw{switch_name:02} Switches={','.join(switches)}\n")
    def run(self):
        """
        Executes the sequence of steps to generate and write the SLURM topology.
        Returns:
            None
        """
        log.debug("Retrieving hostnames")
        self.get_hostnames()
        log.debug("Retrieving sharp_cmd directory")
        self.sharp_cmd_path=self.get_sharp_cmd()
        log.debug("checking that sharp_hello_works")
        self.check_sharp_hello()
        log.debug("Checking ibstat can be run on all hosts")
        self.check_ibstatus()
        log.debug("Running ibstat on hosts to collect InfiniBand device GUIDs")
        self.retrieve_guids()
        log.debug("Finished collecting InfiniBand device GUIDs from hosts")
        self.write_guids_to_file()
        log.debug("Finished writing guids to %s", self.guids_file)
        self.generate_topo_file()
        log.debug("Topology file generated at %s", self.topo_file)
        self.device_guids_per_switch =  self.group_guids_per_switch()
        log.debug("Finished grouping device guids per switch")
        self.host_to_torset_map = self.identify_torsets()
        log.debug("Identified torsets for hosts")
        self.torsets = self.group_hosts_by_torset()
        log.debug("Finished grouping hosts by torsets")
        self.write_slurm_topology()
        if self.topo_file:
            log.info("Finished writing slurm topology from torsets to %s",
                          self.slurm_top_file)
        else:
            log.info("Printed slurm topology")
