from scale_to_n_nodes import SlurmCommands, AzslurmTopology, get_healthy_idle_nodes, Clock
import subprocess
import logging
import time
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)


def parse_command(x: str) -> dict:
    import shlex
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
    def __init__(self, topology_file: str = "/etc/slurm/topology.conf"):
        self.topology_file = topology_file
        self.last_topology = self.read_topology()
        log.info("Running in TEST MODE - all commands will be mocked")
        self.nodes_dict = {}

    def read_topology(self) -> str:
        """Read the current SLURM topology file."""
        try:
            with open(self.topology_file, 'r', encoding='utf-8') as f:
                topology = f.read()
            log.info(f"[TEST MODE] Read mock topology file: {self.topology_file}")
            return topology
        except Exception as e:
            log.warning(f"[TEST MODE] Could not read mock topology file: {e}")
            return ""

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

    def simulate_failed_converge(self, failed_nodes: list):
        """Simulate some nodes as unhealthy for testing."""
        log.info(f"[TEST MODE] Simulating failed converge for nodes: {failed_nodes}")
        for node in failed_nodes:
            if node in self.nodes_dict:
                self.nodes_dict[node]['simulate_failure'] = True
        log.info(f"[TEST MODE] Updated states for failed nodes: {failed_nodes}")

    def update_states(self, count=9):
        """Update mock node states based on simulated failures."""
        log.info("[TEST MODE] Updating mock node states")
        for node_name, node_data in self.nodes_dict.items():
            if node_data['power_state'] == 'POWERING_UP':
                if node_data.get('simulate_failure'):
                    node_data['state'] = 'DOWN'
                    node_data['power_state'] = 'POWERING_DOWN'
                else:
                    node_data['state'] = 'IDLE'
                    node_data['power_state'] = 'POWERED_UP'
                count -= 1
            elif node_data['power_state'] == 'POWERING_DOWN':
                node_data['state'] = 'IDLE'
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
                return
        log.info("[TEST MODE] Mock node states updated")

    def run_command(self, cmd: str) -> subprocess.CompletedProcess:
        """Mock SLURM and system commands for test mode."""
        log.info(f"[TEST MODE] Would run: {cmd}")
        cmd_parsed = parse_command(cmd)
        
        if "scontrol" in cmd_parsed:
            if "create" in cmd_parsed:
                if "reservation" in cmd_parsed:
                    self.reservation_name = cmd_parsed["ReservationName"]
                    self.node_count = int(cmd_parsed["NodeCnt"])
                    assert self.node_count > 0, "Node count must be greater than 0"
                    assert self.node_count <= len(self.nodes_dict), "Not enough mock nodes available"

                    for node_name, node_dict in list(self.nodes_dict.items())[:self.node_count]:
                        assert node_dict['partition'] == cmd_parsed["PartitionName"]
                        node_dict['reservation_name'] = self.reservation_name
                    log.info(f"[TEST MODE] Mock reservation created: {self.reservation_name}")
                    return subprocess.CompletedProcess(cmd, 0, "Mock reservation created", "")
                elif "node" in cmd_parsed:
                    node_list = cmd_parsed.get("NodeName", "").split(',')
                    for node_name in node_list:
                        if node_name not in self.nodes_dict:
                            self.nodes_dict[node_name] = {
                                'partition': 'mock',
                                'state': 'IDLE',
                                'power_state': 'POWERED_DOWN',
                                'reservation_name': ''
                            }
                    log.info(f"[TEST MODE] Mock nodes updated: {node_list}")
                    return subprocess.CompletedProcess(cmd, 0, "Mock nodes updated", "")
            elif "update" in cmd_parsed:
                if "NodeName" in cmd_parsed and "State" in cmd_parsed:
                    states = {'power_up':'PRE_POWERING_UP', 'power_down':'PRE_POWERING_DOWN'}
                    node_list = cmd_parsed.get("NodeName", "").split(',')
                    new_state = cmd_parsed.get("State", "").lower()
                    for node_name in node_list:
                        if node_name in self.nodes_dict:
                            self.nodes_dict[node_name]['power_state'] = states[new_state]
                            log.info(f"[TEST MODE] Mock node {node_name} power state updated to {new_state}")
                    return subprocess.CompletedProcess(cmd, 0, "Mock nodes updated", "")
            elif "delete" in cmd_parsed:
                assert "reservation" in cmd_parsed
                assert self.reservation_name in cmd.split()[-1], "Reservation name must be specified"
                log.info(f"[TEST MODE] Mock reservation deleted: {self.reservation_name}")
                for node_name, node_data in self.nodes_dict.items():
                    if node_data['reservation_name'] == self.reservation_name:
                        node_data['reservation_name'] = ""
                self.reservation_name = ""
                return subprocess.CompletedProcess(cmd, 0, "Mock reservation deleted", "")
            elif "reconfigure" in cmd:
                self.last_topology = self.read_topology()
                return subprocess.CompletedProcess(cmd, 0, "Mock reconfigure executed", "")
            elif "show" in cmd_parsed:
                if "reservation" in cmd_parsed:
                    if self.reservation_name in cmd.split()[-1]:
                        res_nodes = [node for node, data in self.nodes_dict.items() if data['reservation_name'] == self.reservation_name]
                        res_count = len(res_nodes)
                        output = f"ReservationName={self.reservation_name}\nNodes={','.join(res_nodes)}\nNodeCnt={res_count}"
                        return subprocess.CompletedProcess(cmd, 0, output, "")
                    else:
                        return subprocess.CompletedProcess(cmd, 1, "Reservation not found", "")
                elif "hostnames" in cmd_parsed:
                    assert len(cmd.strip().split()) > 3
                    nodes = cmd.split()[-1].split(',')
                    return subprocess.CompletedProcess(cmd, 0, "\n".join(nodes) + "\n", "")
                elif "topology" in cmd_parsed:
                    return subprocess.CompletedProcess(cmd, 0, self.last_topology, "")
        
        elif "sinfo" in cmd_parsed:
            if '-t' in cmd_parsed:
                states = cmd_parsed['-t'].upper().split(',')
                ret = []
                for node_name, node_dict in self.nodes_dict.items():
                    if (node_dict['power_state'].upper() in states or 
                        node_dict['state'].upper() in states):
                        ret.append(node_name)
                nodes = "\n".join(ret) + "\n"
            elif cmd_parsed['-o'] == '%N':
                nodes = "\n".join(self.nodes_dict.keys()) + "\n"
            elif cmd_parsed['-o'] == '%N %T':
                ret = []
                target_nodes = cmd_parsed['-n'].split(',')
                for node_name, node_dict in self.nodes_dict.items():
                    if node_name not in target_nodes:
                        continue
                    state = node_dict['state'].upper()
                    assert state in ['IDLE', 'DOWN', 'DRAINING', 'DRAINED', 'RESERVED'], f"Unknown state: {state}"
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
                nodes = "\n".join(ret) + "\n"
            else:
                raise ValueError(f"Unsupported sinfo output format: {cmd_parsed['-o']}")
                
            return subprocess.CompletedProcess(cmd, 0, nodes, "")
        # Default mock response
        return subprocess.CompletedProcess(cmd, 0, "Mock command executed", "")

        
class MockAzslurmTopology(AzslurmTopology):
    def __init__(self, slurm_commands: SlurmCommands):
        super().__init__()
        self.slurm_commands = slurm_commands

    def generate_topology(self, partition: str, topology_file: str) -> str:
        """Create a mock topology file for testing."""
        mock_topology_lines = []
        nodes = get_healthy_idle_nodes(partition, self.slurm_commands)
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


