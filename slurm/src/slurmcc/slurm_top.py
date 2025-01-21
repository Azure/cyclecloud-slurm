import os
import sys
import argparse
#from loguru import logger
import logging
import subprocess
from pathlib import Path
from pssh.clients.ssh import ParallelSSHClient, SSHClient
import datetime

log=logging.getLogger()
def parse_args():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--hosts', type=str, help="Specify the hostnames")
    group.add_argument('--partition', type=str, help="Specify the parititon")
    #parser.add_argument('--pkey_path', type=str, help='Path to user private key')
    #parser.add_argument('--sharp_cmd_path', type=str, help='Path to sharp_cmd')
    #parser.add_argument('--output_dir', type=str, help='Output directory for generated files')
    parser.add_argument('-o', '--output', action='store_true', help="Create slurm topology file")
    return parser.parse_args()
def run_parallel_cmd(hosts, private_key, cmd):
    try:
        client = ParallelSSHClient(hosts,pkey=f'{private_key}')
        output = client.run_command(cmd)
        client.join(output)
        return output
    except Exception as e:
        raise Exception(f"Error running command: {cmd}: {str(e)}")

def run_command(cmd, env= os.environ.copy(),stdout=subprocess.PIPE, stderr=subprocess.PIPE):
    log.debug(cmd)
    try:
        output = subprocess.run(cmd,env=env,stdout=stdout,stderr=stderr, shell=True, check=True,
                       encoding='utf-8')
        log.debug(output.stdout)
    except subprocess.CalledProcessError as e:
        log.error(f"cmd: {e.cmd}, rc: {e.returncode}")
        log.error(e.stderr)
        sys.exit(1)
    except Exception as e:
        log.error(e)
        raise
    return output
class TorsetTool:

    output_dir: Path
    guids_file: Path
    guid_to_host_map: dict = {}
    hosts_file: Path
    topo_file: Path
    slurm_top_file: Path
    device_guids_per_switch: list = []
    host_to_torset_map: dict = {}
    torsets: dict = {}

    def __init__(self):
        self.timestamp= datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = f"/data/azreen/topology/topology_ouput_{self.timestamp}"
        Path(self.output_dir).mkdir(exist_ok=True)
        Path(f"{self.output_dir}/logs").mkdir(exist_ok=True)
        logging.basicConfig(level=logging.DEBUG, # Set the log level to DEBUG to capture all levels of log messages
        format='%(asctime)s - %(levelname)s - %(message)s', # Define the log message format
        filename=f'{self.output_dir}/logs/slurm_top.log', # Set the log file name
        filemode='w' # Use 'w' to overwrite the log file each time or 'a' to append to it
        )
        self.hosts=[]
        self.hosts_file = f"{self.output_dir}/hostnames.txt"
        self.sharp_cmd_path = '/opt/hpcx-v2.18-gcc-mlnx_ofed-ubuntu22.04-cuda12-x86_64/'
        self.pkey="~/.ssh/id_rsa"
        self.guids_file = f"{self.output_dir}/guids.txt"
        self.topo_file = f"{self.output_dir}/topology.txt"
        self.slurm_top_file= "slurm_topology.conf"
    
    def check_sharp_hello(self):
        cmd = f"{self.sharp_cmd_path}sharp/bin/sharp_hello"
        run_command(cmd)
    
    def get_hostnames(self,hosts,partition) -> None:
        if partition:
            cmd = f'scontrol show hostnames $(sinfo -p {partition} -o "%N" -h)'
            command = f'scontrol show hostnames $(sinfo -p {partition} -t powered_down,powering_up,powering_down,power_down -o "%N" -h)'
            cmd_output = run_command(cmd)
            command_output = run_command(command)
            down_hosts=command_output.stdout.split('\n')
            hosts=cmd_output.stdout.split('\n')
            self.hosts = list(set(hosts)-set(down_hosts))
        else:
            cmd=['scontrol','show','hostnames', hosts]
            command = f'scontrol show hostnames $(sinfo -t powered_down,powering_up,powering_down,power_down -o "%N" -h)'
            cmd_output = run_command(cmd)
            command_output = run_command(command)
            down_hosts=command_output.stdout.split('\n')
            hosts=cmd_output.stdout.split('\n')
            self.hosts = list(set(hosts)-set(down_hosts))
    def check_ibstat(self, private_key) -> None:
        cmd= 'ibstat'
        output = run_parallel_cmd(self.hosts, private_key, cmd)
    def retrieve_guids(self, private_key) -> dict:
        cmd = 'ibstatus | grep mlx5_ib | cut -d" " -f3 | xargs -I% ibstat "%" | grep "Port GUID" | cut -d: -f2'
        output = run_parallel_cmd(self.hosts, private_key, cmd)
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
            run_command(command,env=env, stdout=fp)
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
        #delete this when not testing
        #self.torsets={"torset-00":["hpc-1","hpc-2","hpc-3"], "torset-01":["hpc-4","hpc-5"],"torset-02":["hpc-5","hpc-6"]}
        switches=[]
        with open(self.slurm_top_file,'w') as file:
            for torset, hosts in self.torsets.items():
                torset_index=torset[-2:]
                if output:
                    file.write(f"SwitchName=sw{torset_index} Nodes={','.join(hosts)}\n")
                print(f"SwitchName=sw{torset_index} Nodes={','.join(hosts)}\n")
                switches.append(f"sw{torset_index}")
            if len(self.torsets)>1:
                switch_name=int(torset_index)+1
                if output:
                    file.write(f"SwitchName=sw{switch_name:02} Switches={','.join(switches)}\n")
                print(f"SwitchName=sw{switch_name:02} Switches={','.join(switches)}\n")
    def run(self,hosts,partition,output):
        console_handler=logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        formatter=logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(formatter)
        logging.getLogger().addHandler(console_handler)
        logging.info("checking that sharp_hello_works")
        self.check_sharp_hello()
        logging.info("Retrieving hostnames")
        self.get_hostnames(hosts, partition)
        logging.info(f"Finished writing hostnames to {self.hosts_file}")
        logging.info("Checking ibstat can be run on all hosts")
        self.check_ibstat(self.pkey)
        logging.info("Running ibstat on hosts to collect InfiniBand device GUIDs")
        #guid_to_host_map = torset_tool.retrieve_guids(args.pkey_path)
        guid_to_host_map = self.retrieve_guids(self.pkey)
        logging.info("Finished collecting InfiniBand device GUIDs from hosts")
        self.write_guids_to_file()
        logging.info(f"Finished writing guids to {self.guids_file}")
        self.generate_topo_file()
        logging.info(f"Topology file generated at {self.topo_file}")
        self.device_guids_per_switch =  self.group_guids_per_switch()
        logging.info("Finished grouping device guids per switch")
        self.host_to_torset_map = self.identify_torsets()
        logging.info("Identified torsets for hosts")
        self.torsets = self.group_hosts_by_torset()
        logging.info("Finished grouping hosts by torsets")
        self.write_slurm_topology(output)
        if output:
            logging.info(f"Finished writing slurm topology from torsets to {self.slurm_top_file}")
        else:
            logging.info("Printed slurm topology")
        # torset_tool.write_hosts_by_torset()
        # logger.info(f"Hosts grouped by torset are written to files in {torset_tool.output_dir} directory")


def main():
    args = parse_args()
    #log.add(f"/data/azreen/topology/torset-tool.log", rotation = "500 MB", enqueue= True, level="INFO")
    # console_handler =logging.StreamHandler()
    # console_handler.setLevel(logging.INFO)
    # formatter=logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    # console_handler.setFormatter(formatter)
    # logging.getLogger().addHandler(console_handler)
    torset_tool = TorsetTool()
    torset_tool.run(args.hosts, args.partition, args.output)
    # logging.info("Retrieving hostnames")
    # torset_tool.get_hostnames(args.hosts, args.partition)
    # logging.info(f"Finished writing hostnames to {torset_tool.hosts_file}")
    # logging.info("Checking ibstat can be run on all hosts")
    # torset_tool.check_ibstat("~/.ssh/id_rsa")
    # logging.info("Running ibstat on hosts to collect InfiniBand device GUIDs")
    # #guid_to_host_map = torset_tool.retrieve_guids(args.pkey_path)
    # guid_to_host_map = torset_tool.retrieve_guids("~/.ssh/id_rsa")
    # logging.info("Finished collecting InfiniBand device GUIDs from hosts")
    # torset_tool.write_guids_to_file()
    # logging.info(f"Finished writing guids to {torset_tool.guids_file}")
    # torset_tool.generate_topo_file()
    # logging.info(f"Topology file generated at {torset_tool.topo_file}")
    # torset_tool.device_guids_per_switch =  torset_tool.group_guids_per_switch()
    # logging.info("Finished grouping device guids per switch")
    # torset_tool.host_to_torset_map = torset_tool.identify_torsets()
    # logging.info("Identified torsets for hosts")
    # torset_tool.torsets = torset_tool.group_hosts_by_torset()
    # logging.info("Finished grouping hosts by torsets")
    # if args.output:
    #     torset_tool.write_slurm_topology()
    #     logging.info(f"Finished writing slurm topology from torsets to {torset_tool.slurm_top_file}")
    # torset_tool.write_hosts_by_torset()
    # logger.info(f"Hosts grouped by torset are written to files in {torset_tool.output_dir} directory")

if __name__ == '__main__':
    main()