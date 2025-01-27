import os
import sys
import argparse
import logging
from pathlib import Path
from . import util as util

import datetime

def parse_args():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-n','--nodes', type=str, help="Specify the hostnames for the nodes")
    group.add_argument('-p,','--partition', type=str, help="Specify the parititon")
    parser.add_argument('-o', '--output', type=str, help="Specify slurm topology file output")
    return parser.parse_args()

class Topology:

    output_dir: Path
    guids_file: Path
    guid_to_host_map: dict = {}
    hosts_file: Path
    topo_file: Path
    slurm_top_file: Path
    device_guids_per_switch: list = []
    host_to_torset_map: dict = {}
    torsets: dict = {}
    TEST_TOPOLOGY=False
    def __init__(self,output):
        self.timestamp= datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = f"/data/azreen/topology/topology_ouput_{self.timestamp}"
        Path(self.output_dir).mkdir(exist_ok=True)
        Path(f"{self.output_dir}/logs").mkdir(exist_ok=True)
        logging.basicConfig(level=logging.DEBUG, # Set the log level to DEBUG to capture all levels of log messages
        format='%(asctime)s - %(levelname)s - %(message)s', # Define the log message format
        filename=f'/data/azreen/topology/logs/slurm_top.log', # Set the log file name
        filemode='a' # Use 'w' to overwrite the log file each time or 'a' to append to it
        )
        self.hosts=[]
        self.sharp_cmd_path = None
        #self.pkey="~/.ssh/id_rsa"
        self.guids_file = f"{self.output_dir}/guids.txt"
        self.topo_file = f"{self.output_dir}/topology.txt"
        self.slurm_top_file= output
    
    def get_hostnames(self,hosts,partition) -> None:
        def get_hostlist(cmd) -> list:
            output=util.run_command(cmd)
            return output.stdout.split('\n')[:-1]
        partition_cmd = f'-p {partition} ' if partition else ''
        validate_cmd= f'scontrol show hostnames $(sinfo -o "%N" -h)'
        host_cmd = f'scontrol show hostnames $(sinfo -p {partition} -o "%N" -h)' if partition else f'scontrol show hostnames {hosts}'
        down_cmd = f'scontrol show hostnames $(sinfo {partition_cmd}-t powered_down,powering_up,powering_down,power_down -o "%N" -h)'
        all_hosts=get_hostlist(validate_cmd)
        hosts=get_hostlist(host_cmd)
        down_hosts=get_hostlist(down_cmd)
        valid_hosts = set(hosts)&set(all_hosts)
        invalid_hosts = set(hosts)-set(all_hosts)
        powered_down_hosts = set(hosts)&set(down_hosts)
        self.hosts = list(valid_hosts-powered_down_hosts)
        if len(self.hosts)<len(hosts):
            logging.warning("Some nodes were either powered down or invalid, running on a subset of nodes that are powered on")
            if invalid_hosts:
                logging.warning(f"Invalid Nodes: {invalid_hosts}")
            if powered_down_hosts:
                logging.warning(f"Powered Down Nodes: {powered_down_hosts}")
        logging.debug(hosts)
        logging.debug(self.hosts)
        if len(self.hosts)<2:
            logging.error("Need more than 2 nodes to create slurm topology, nodes given were either invalid or powered down or less than two nodes")
            sys.exit(1)
    
    def get_os_name(self):
        cmd = "grep '^ID=' /etc/os-release | cut -d'=' -f2"
        output = util.run_parallel_cmd([self.hosts[0]],cmd)
        exit_code=output[0].exit_code
        stdout=output[0].stdout
        stderr = output[0].stderr
        if exit_code==0:
            os_id = ''.join(stdout).strip()
            logging.debug(os_id)
            return os_id
        else:
            logging.error(f"Exit code: {exit_code}")
            for line in stderr:
                logging.error(line)
            sys.exit(1)
    def get_sharp_cmd(self):
        os_id=self.get_os_name()
        if os_id == "ubuntu":
            return "/opt/hpcx-v2.18-gcc-mlnx_ofed-ubuntu22.04-cuda12-x86_64/"
        elif os_id=="almalinux":
            return "/opt/hpcx-v2.18-gcc-mlnx_ofed-redhat8-cuda12-x86_64/"
        else:
            logging.error("OS Not supported, exiting")
            sys.exit(1)


    def check_sharp_hello(self):
        cmd = f"{self.sharp_cmd_path}sharp/bin/sharp_hello"
        output = util.run_parallel_cmd([self.hosts[0]],cmd)
        for line in output[0].stdout:
            logging.debug(line)
        if output[0].exit_code!=0:
            logging.error("sharp_hello command failed")
            for line in output[0].stderr:
                logging.error(line)
            sys.exit(output[0].exit_code)
        else:
            logging.debug("sharp_hello command passed")
        
    def check_ibstatus(self) -> None:
        cmd ="python3 -c \"import shutil; print(shutil.which('ibstatus'))\""
        output = util.run_parallel_cmd([self.hosts[0]],cmd)
        path=None
        for line in output[0].stdout:
            logging.debug(line)
            path=line
        if path=="None":
            logging.error("The 'ibstatus' command is not available")
            sys.exit(1)
        else:
            logging.debug("The 'ibstatus' command is available.")

    def retrieve_guids(self) -> dict:
        cmd = 'ibstatus | grep mlx5_ib | cut -d" " -f3 | xargs -I% ibstat "%" | grep "Port GUID" | cut -d: -f2'
        output = util.run_parallel_cmd(self.hosts, cmd)
        for host_out in output:
            for guid in host_out.stdout:
                # Querying GUIDs from ibstat will have pattern 0x0099999999999999, but Sharp will return 0x99999999999999
                # - So we need to remove the leading 00 after 0x
                self.guid_to_host_map[guid.replace('0x00', '0x').strip()]=host_out.host

    def write_guids_to_file(self):
        with open(self.guids_file, 'w') as f:
            for guid in self.guid_to_host_map.keys():
                f.write(f"{guid}\n")

    def generate_topo_file(self):
        env=os.environ.copy()
        env["SHARP_SMX_UC_INTERFACE"]= "mlx5_ib0:1"
        if 'SHARP_CMD' not in env:
            command = f"{self.sharp_cmd_path}sharp/bin/sharp_cmd topology --ib-dev mlx5_ib0:1 --guids_file {self.guids_file} --topology_file {self.topo_file}"
        else:
            command = [ f"{env['SHARP_CMD']}sharp/bin/sharp_cmd", "topology", "--ib-dev", "mlx5_ib0:1", "--guids_file", self.guids_file, "--topology_file", self.topo_file]
        with open(f"{self.output_dir}/logs/topology.log",'w') as fp:
            util.run_command(command,env=env, stdout=fp)
    def group_guids_per_switch(self) -> list:
        guids_per_switch = []
        with open(self.topo_file, 'r') as f:
            for line in f:
                if 'Nodes=' not in line:
                    continue
                # 'SwitchName=ibsw2 Nodes=0x155dfffd341acb,0x155dfffd341b0b'
                guids_per_switch.append(line.strip().split(' ')[1].split('=')[1])
        return guids_per_switch

    def identify_torsets(self) -> dict:
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
        torsets = {}
        for host, torset in self.host_to_torset_map.items():
            if torset not in torsets:
                torsets[torset] = [host]
            else:
                torsets[torset].append(host)
        return torsets
    def write_slurm_topology(self,output)-> None:
        switches=[]
        if output:
            with open(self.slurm_top_file,'w') as file:
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
    def run(self,hosts,partition,output):
        TEST_TOPOLOGY=False
        console_handler=logging.StreamHandler()
        console_handler.setLevel(logging.WARNING)
        formatter=logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(formatter)
        logging.getLogger().addHandler(console_handler)
        logging.debug("Retrieving hostnames")
        self.get_hostnames(hosts, partition)
        logging.debug("Retrieving sharp_cmd directory")
        self.sharp_cmd_path=self.get_sharp_cmd()
        logging.debug("checking that sharp_hello_works")
        if not TEST_TOPOLOGY:
            self.check_sharp_hello()
            logging.debug("Checking ibstat can be run on all hosts")
            self.check_ibstatus()
            logging.debug("Running ibstat on hosts to collect InfiniBand device GUIDs")
            self.retrieve_guids()
            logging.debug("Finished collecting InfiniBand device GUIDs from hosts")
            self.write_guids_to_file()
            logging.debug(f"Finished writing guids to {self.guids_file}")
            self.generate_topo_file()
            logging.debug(f"Topology file generated at {self.topo_file}")
        else:
            pass
        self.device_guids_per_switch =  self.group_guids_per_switch()
        logging.debug("Finished grouping device guids per switch")
        self.host_to_torset_map = self.identify_torsets()
        logging.debug("Identified torsets for hosts")
        self.torsets = self.group_hosts_by_torset()
        logging.debug("Finished grouping hosts by torsets")
        self.write_slurm_topology(output)
        if output:
            logging.info(f"Finished writing slurm topology from torsets to {self.slurm_top_file}")
        else:
            logging.info("Printed slurm topology")

def main():
    args = parse_args()
    topology = Topology(args.output)
    topology.run(args.nodes, args.partition, args.output)
if __name__ == '__main__':
    main()