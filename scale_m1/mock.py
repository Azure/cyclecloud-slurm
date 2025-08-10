import logging
import shlex
import subprocess
import time

from scale_to_n_nodes import SlurmCommands, AzslurmTopology, get_healthy_nodes, Clock


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)


def parse_command(x: str) -> dict:
    """Parses sinfo/scontrol commands into a dictionary. Only really relevant for
    our specific use cases, DO NOT REUSE
    "command a=b -c 'd e'" become {'command': 'command', 'a': 'b', '-c': 'd e'}
    """
    ret = {}
    toks = shlex.split(x)
    i = 0
    while i < len(toks):
        tok = toks[i]
        if "=" in tok:
            key, value = tok.split("=", 1)
        elif tok.startswith("-") and i + 1 < len(toks):
            key = tok
            value = toks[i + 1]
            i = i + 1
        else:
            key = value = tok
        ret[key] = value
        i = i + 1
    return ret


class MockClock(Clock):
    def __init__(self, start_time: float = None):
        super().__init__()
        self.current_time = start_time if start_time else time.time()

    def sleep(self, seconds: float):
        log.info(f"[TEST MODE] Mock sleep for {seconds} seconds")
        self.current_time += seconds

    def time(self) -> float:
        return self.current_time


class MockSlurmCommands(SlurmCommands):
    """Mock version of Slurm. Typical use case
            mock_slurm = MockSlurmCommands("/tmp/topology.conf")
            mock_slurm.create_nodes([f"hpc-{x+1}" for x in range(18)])
            mock_slurm.simulate_failed_converge(["hpc-3"])
            mock_slurm.run_command("scontrol update nodename=hpc-3,hpc-4 state=power_up)
            # node will not actually enter POWERING_UP until this is called, to simulate
            # the actual delay in slurm
            mock_slurm.update_states()
             # sinfo works - so you can also just query states
            assert mock_slurm.run_command("sinfo -t powering_up -N -o '%N').stdout.strip().split() == ["hpc-3", "hpc-4"]
            # call update states again and one node is now powered_up, the other is powering_down
            mock_slurm.update_states()
            assert mock_slurm.node_dicts["hpc-3"]["power_state"] == "POWERED_UP"
            assert mock_slurm.node_dicts["hpc-4"]["power_state"] == "POWERING_DOWN"
            assert mock_slurm.run_command("sinfo -t powering_down -N -o '%N').stdout.strip() == "hpc-4"
    """
    def __init__(self, topology_file: str = "/etc/slurm/topology.conf"):
        self.topology_file = topology_file
        self.last_topology = ""
        log.info("Running in TEST MODE - all commands will be mocked")
        self.nodes_dict: dict[str, dict] = {}
        self.reservation_name: str = ""
        self.reservation_nodes: list[str] = []
        self.reservation_partition: str = ""

    def read_topology(self) -> str:
        """Read the current SLURM topology file."""
        with open(self.topology_file, 'r', encoding='utf-8') as f:
            topology = f.read()
        log.info(f"[TEST MODE] Read mock topology file: {self.topology_file}")
        return topology


    def create_nodes(self, partition: str, count: int):
        """Create mock nodes for testing."""
        log.info(f"[TEST MODE] Creating {count} mock nodes in partition '{partition}'")
        assert count >= 18, "Count must be greater than 18 for mock nodes"
        for i in range(count):
            node_name = f"{partition}-{i + 1}"
            self.nodes_dict[node_name] = {
                'partition': partition,
                'state': 'IDLE',
                'power_state': 'POWERED_DOWN',
                'reservation_name': ''
            }
        log.info(f"[TEST MODE] Created {len(self.nodes_dict)} total mock nodes")
    
    def show_hostlist(self, nodes: list[str]) -> str:
        assert sorted(nodes, key=lambda x: int(x.split("-")[-1])) == nodes
        return ",".join(nodes)
    
    def show_hostnames(self, node_str: str) -> list[str]:
        return node_str.split(",")


    def alloc_nodes(self, nodes: list[str]) -> None:
        for node in nodes:
            assert self.nodes_dict[node]["power_state"] == "POWERED_UP", f"invalid state {self.nodes_dict[node]}"
            self.nodes_dict[node]["state"] = "allocated"

    def drain_nodes(self, nodes: list[str]) -> None:
        for node in nodes:
            assert self.nodes_dict[node]["power_state"] == "POWERED_UP", f"invalid state {self.nodes_dict[node]}"
            self.nodes_dict[node]["state"] = "draining"

    def down_nodes(self, nodes: list[str]) -> None:
        for node in nodes:
            assert self.nodes_dict[node]["power_state"] == "POWERED_UP", f"invalid state {self.nodes_dict[node]}"
            self.nodes_dict[node]["state"] = "down"

    def reserve_nodes(self, nodes: list[str], reservation_name: str = "scale_m1") -> None:
        for node in nodes:
            self.nodes_dict[node]["reservation_name"] = reservation_name

    def simulate_failed_converge(self, failed_nodes: list):
        """Simulate some nodes as unhealthy for testing."""
        log.info(f"[TEST MODE] Simulating failed converge for nodes: {failed_nodes}")
        for node in failed_nodes:
            if node in self.nodes_dict:
                self.nodes_dict[node]['simulate_failure'] = True
        log.info(f"[TEST MODE] Updated states for failed nodes: {failed_nodes}")

    def update_states(self, count=9):
        """Update mock node states based on simulated failures."""
        log.info(f"[TEST MODE] Updating {count} mock node states")
        for node_name, node_data in self.nodes_dict.items():
            if node_data['power_state'] == 'POWERING_UP':
                if node_data.get('simulate_failure'):
                    # # TODO will mess with reservation
                    # and yes it did.
                    # node_data['state'] = 'DOWN'
                    node_data['power_state'] = 'POWERING_DOWN'
                else:
                    node_data['power_state'] = 'POWERED_UP'
                count -= 1
            elif node_data['power_state'] == 'POWERING_DOWN':
                node_data['power_state'] = 'POWERED_DOWN'
                count -= 1
            # Update one node and return
            elif node_data['power_state'] == 'PRE_POWERING_UP':
                node_data['power_state'] = 'POWERING_UP'
                count -= 1
            elif node_data['power_state'] == 'PRE_POWERING_DOWN':
                node_data['power_state'] = 'POWERING_DOWN'
                count -= 1
            # Update one node and return
            if count <= 0:
                log.info("[TEST MODE] Mock node states updated")
                return
        log.info(f"[TEST MODE] Mock {count} node states remaining")

    def sinfo(self, cmd: str, cmd_parsed: dict) -> subprocess.CompletedProcess:
        if '-t' in cmd_parsed:
            states = cmd_parsed['-t'].upper().split(',')
            ret = []
            for node_name, node_dict in self.nodes_dict.items():
                if (node_dict['power_state'].upper() in states or 
                    node_dict['state'].upper() in states):
                    ret.append(node_name)
                elif "RESERVED" in states and node_dict.get("reservation_name"):
                    # handle reserved by looking at res name NOT state - drained etc can be reserved.
                    ret.append(node_name)
            nodes_str = "\n".join(ret) + "\n"
        elif cmd_parsed['-o'] == '%N':
            nodes_str = "\n".join(self.nodes_dict.keys()) + "\n"
        elif cmd_parsed['-o'] == '%N %T':
            ret = []
            target_nodes = cmd_parsed['-n'].split(',')
            for node_name, node_dict in self.nodes_dict.items():
                if node_name not in target_nodes:
                    continue
                state = node_dict['state'].upper()
                assert state in ['IDLE', 'DOWN', 'DRAINING', 'DRAINED', 'RESERVED', 'ALLOCATED'], f"Unknown state: {state}"
                if node_dict['power_state']=="POWERED_UP":
                    pass
                elif node_dict['power_state']=="POWERED_DOWN":
                    state += '~'
                elif node_dict['power_state']=="POWERING_UP":
                    state += '#'
                elif node_dict['power_state']=="POWERING_DOWN":
                    state += '%'
                elif node_dict['power_state'].startswith("PRE_"):
                    state += '!'
                ret.append(f"{node_name} {state}")
            nodes_str = "\n".join(ret) + "\n"
        else:
            raise ValueError(f"Unsupported sinfo output format: {cmd_parsed['-o']}")

        return subprocess.CompletedProcess(cmd, 0, nodes_str, "")
    
    def scontrol_create_reservation(self, cmd: str, cmd_parsed: dict) ->subprocess.CompletedProcess:
        assert not self.reservation_nodes
        self.reservation_name = cmd_parsed["ReservationName"]
        
        self.reservation_nodes = cmd_parsed["Nodes"].split(",")
        self.reservation_partition = cmd_parsed["PartitionName"]

        for node_name in self.reservation_nodes:
            node_dict = self.nodes_dict[node_name]
            assert node_dict['partition'] == cmd_parsed["PartitionName"]
            assert node_dict["state"].upper() not in ["MIXED", "ALLOCATED"]
            node_dict['reservation_name'] = self.reservation_name

        log.info(f"[TEST MODE] Mock reservation created: {self.reservation_name}")
        return subprocess.CompletedProcess(cmd, 0, "Mock reservation created", "")
    
    def scontrol_update_reservation(self, cmd: str, cmd_parsed: dict) -> subprocess.CompletedProcess:
        assert cmd_parsed["ReservationName"] == self.reservation_name, f"{cmd_parsed} res_name={self.reservation_name}"
        self.reservation_nodes = cmd_parsed["Nodes"].split(",")
        for node in self.reservation_nodes:
            node_dict = self.nodes_dict[node]
            if node in self.reservation_nodes:
                node_dict["state"] = "RESERVED"
            elif node_dict["state"] == "RESERVED":
                node_dict["state"] = "IDLE"
        return subprocess.CompletedProcess(cmd, 0, "Mock reservation updated", "")
    
    def scontrol_update_nodename(self, cmd: str, cmd_parsed: dict) -> subprocess.CompletedProcess:
        states = {'power_up':'PRE_POWERING_UP', 'power_down':'PRE_POWERING_DOWN'}
        node_list = cmd_parsed.get("NodeName", "").split(',')
        new_state = cmd_parsed.get("State", "").lower()
        for node_name in node_list:
            if new_state == "power_up" and self.nodes_dict[node_name]['power_state'] == "POWERED_UP":
                continue
            if new_state == "power_up":
                self.nodes_dict[node_name]["created_a_vm"] = True
            self.nodes_dict[node_name]['power_state'] = states[new_state]

            log.info(f"[TEST MODE] Mock node {node_name} power state updated to {new_state}")

        # mimic M1 assertion that all VMSS requests end up having a multiple of 18 
        if new_state == "power_up" and any([n.get("created_a_vm") for n in self.nodes_dict.values()]):
            has_a_vm = 0
            for node_name, node_dict in self.nodes_dict.items():
                if node_dict["power_state"] in ["PRE_POWERING_UP", "POWERING_UP", "POWERED_UP"]:
                    has_a_vm += 1
            assert has_a_vm % 18 == 0, f"This would result in an improper m1 allocation - {has_a_vm} total vms"
        
        return subprocess.CompletedProcess(cmd, 0, "Mock nodes updated", "")
    
    def _power_up(self, node_names: list[str]) -> None:
        for node_name in node_names:
            self.nodes_dict[node_name]['power_state'] = "PRE_POWERING_UP"
    
    def scontrol_show_reservation(self, cmd: str, cmd_parsed: dict) -> subprocess.CompletedProcess:
        if self.reservation_name == cmd.split()[-1]:
            res_count = len(self.reservation_nodes)
            output = f"""ReservationName={self.reservation_name}
            Nodes={','.join(self.reservation_nodes)}
            NodeCnt={res_count}
            PartitionName={self.reservation_partition}"""
            return subprocess.CompletedProcess(cmd, 0, output, "")
        else:
            return subprocess.CompletedProcess(cmd, 1, "Reservation not found", "")

    def run_command(self, cmd: str, check: bool = True) -> subprocess.CompletedProcess:
        """Mock SLURM and system commands for test mode."""
        ret = self._run_command(cmd)
        if ret.returncode != 0 and check:
            raise subprocess.CalledProcessError(ret.returncode, cmd, ret.output, ret.stderr)
        return ret
    
    def _run_command(self, cmd: str) -> subprocess.CompletedProcess:
        log.info(f"[TEST MODE] Would run: {cmd}")
        cmd_parsed = parse_command(cmd)

        if "azslurm" in cmd_parsed:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        
        if "scontrol" in cmd_parsed:
            if "create" in cmd_parsed:
                if "reservation" in cmd_parsed:
                    return self.scontrol_create_reservation(cmd, cmd_parsed)
            elif "update" in cmd_parsed:
                if "NodeName" in cmd_parsed and "State" in cmd_parsed:
                    return self.scontrol_update_nodename(cmd, cmd_parsed)
                elif "ReservationName" in cmd_parsed:
                    return self.scontrol_update_reservation(cmd, cmd_parsed)
                elif "partitionname" in cmd_parsed:
                    return subprocess.CompletedProcess(cmd, 0, "", "")
            elif "reconfigure" in cmd:
                self.last_topology = self.read_topology()
                return subprocess.CompletedProcess(cmd, 0, "Mock reconfigure executed", "")
            elif "show" in cmd_parsed:
                if "reservation" in cmd_parsed:
                    return self.scontrol_show_reservation(cmd, cmd_parsed)
                elif "hostnames" in cmd_parsed:
                    assert len(cmd.strip().split()) > 3
                    nodes = cmd.split()[-1].split(',')
                    return subprocess.CompletedProcess(cmd, 0, "\n".join(nodes) + "\n", "")
                elif "topology" in cmd_parsed:
                    return subprocess.CompletedProcess(cmd, 0, self.last_topology, "")
        elif "sinfo" in cmd_parsed:
            return self.sinfo(cmd, cmd_parsed)
        
        raise RuntimeError(f"Unknown cmd {cmd}")

    def node_state_counts(self) -> dict[str, int]:
        counts = {"idle": 0, "reserved": 0, "powered_up": 0, "powered_down": 0, "draining": 0,
                  "down": 0, "allocated": 0, "created_a_vm": 0, "total": len(self.nodes_dict)}
        for node_dict in self.nodes_dict.values():
            power_state = node_dict["power_state"].lower()
            if power_state not in counts:
                counts[power_state] = 0
            counts[power_state] = counts[power_state] + 1

            state = node_dict["state"].lower()
            if state not in counts:
                counts[state] = 0
            counts[state] = counts[state] + 1
            if node_dict.get("reservation_name"):
                counts["reserved"] += 1
            if node_dict.get("created_a_vm"):
                counts["created_a_vm"] += 1
        return counts

        
class MockAzslurmTopology(AzslurmTopology):
    def __init__(self, slurm_commands: SlurmCommands):
        super().__init__()
        self.slurm_commands = slurm_commands

    def generate_topology(self, partition: str, topology_file: str) -> str:
        """Create a mock topology file for testing."""
        mock_topology_lines = []
        nodes = get_healthy_nodes(partition, self.slurm_commands)
        total_nodes = len(nodes)
        log.info(f"[TEST MODE] Creating mock topology with {total_nodes} nodes")
        blocks = {}
        mock_topology_lines.append(f"# Mock topology for testing")
        for node in nodes:
            node_index = int(node.split("-")[-1])
            block_index = (node_index - 1) // 18
            if block_index not in blocks:
                blocks[block_index] = []
            blocks[block_index].append(node)
        for block, node_list in blocks.items():
            block_name = f"block_{block + 1:03d}"
            node_list_str = ",".join(node_list)
        
            mock_topology_lines.append(f"BlockName={block_name} Nodes={node_list_str}")
        mock_topology_lines.append("BlockSizes=1")

        mock_topology = "\n".join(mock_topology_lines) + "\n"
        
        with open(topology_file, 'w', encoding='utf-8') as f:
            f.write(mock_topology)
        log.info(f"[TEST MODE] Created mock topology file: {topology_file}")
        return mock_topology


