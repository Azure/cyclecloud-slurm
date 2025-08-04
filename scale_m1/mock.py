from scale_to_n_nodes import SlurmCommands, AzslurmTopology

class MockSlurmCommands(SlurmCommands):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mock_nodes = [f"node-{i:03d}" for i in range(1, 613)]  # Mock 612 nodes
        self.mock_powering_nodes = []
        log.info("Running in TEST MODE - all commands will be mocked")

        self.nodes_dict = {}
    def run_command(self, cmd: str) -> subprocess.CompletedProcess:
        """Mock SLURM and system commands for test mode."""
        log.info(f"[TEST MODE] Would run: {cmd}")

        # Mock reservation creation
        if "scontrol create reservation" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "Reservation created", "")

        # Mock reservation show
        elif "scontrol show reservation" in cmd:
            res_count = self.round_up_to_multiple_of_18(self.target_count + self.overprovision)
            nodes_str = ",".join(self.mock_nodes[:res_count])
            output = f"ReservationName={self.reservation_name}\nNodes={nodes_str}\nNodeCnt={len(self.mock_nodes[:res_count])}"
            return subprocess.CompletedProcess(cmd, 0, output, "")

        # Mock powering nodes check
        elif "sinfo -p" in cmd and "powering_up" in cmd:
            output = "\n".join(self.mock_powering_nodes)
            return subprocess.CompletedProcess(cmd, 0, output, "")

        # Mock healthy idle nodes
        elif "scontrol show hostnames" in cmd:
            healthy_count = self.target_count + self.overprovision
            self.mock_nodes=self.mock_nodes[:healthy_count]  # Limit to healthy nodes
            nodes = "\n".join(self.mock_nodes)+"\n"
            return subprocess.CompletedProcess(cmd, 0, nodes, "")

        # Mock topology generation
        elif "azslurm topology" in cmd:
            self._create_mock_topology()
            return subprocess.CompletedProcess(cmd, 0, "Topology generated", "")

        # Mock node termination
        elif "scontrol update NodeName=" in cmd and "State=POWER_DOWN" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "Nodes updated", "")

        # Mock SLURM reconfigure
        elif "scontrol reconfigure" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "Configuration updated", "")

        # Mock reservation deletion
        elif "scontrol delete reservation" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "Reservation deleted", "")

        # Default mock response
        else:
            return subprocess.CompletedProcess(cmd, 0, "Mock command executed", "")
class MockTopology(AzslurmTopology):
    def __init__(self, slurm_commands: SlurmCommands):
        super().__init__()
        self.slurm_commands = slurm_commands
    def generate_topology(self, partition: str, topology_file: str) -> str:
        """Create a mock topology file for testing."""

        # Generate mock topology with blocks of 18 nodes each, comma-separated
        mock_topology_lines = []
        total_nodes = len(self.mock_nodes)  # Use mock nodes length for test mode
        log.info(f"[TEST MODE] Creating mock topology with {total_nodes} nodes")
        for i in range(0, total_nodes, 18):
            block_end = min(i + 18, total_nodes)
            block_nodes = self.mock_nodes[i:block_end]
            node_list = ",".join(block_nodes)
            block_name = f"block_{i//18 + 1:03d}"
            mock_topology_lines.append(f"BlockName={block_name} Nodes={node_list}")
        mock_topology = "# Mock topology for testing\n" + "\n".join(mock_topology_lines) + "\n"
        try:
            with open(self.topology_file, 'w', encoding='utf-8') as f:
                f.write(mock_topology)
            log.info(f"[TEST MODE] Created mock topology file: {self.topology_file}")
        except Exception as e:
            log.warning(f"[TEST MODE] Could not create mock topology file: {e}")

    def _get_mock_blocks(self) -> List[Dict]:
        """Generate mock blocks for testing."""
        total_nodes = self.target_count + self.overprovision
        blocks = []

        # Create blocks of 18 nodes each (mimicking your rounding logic)
        for i in range(0, total_nodes, 18):
            block_end = min(i + 18, total_nodes)
            block_nodes = self.mock_nodes[i:block_end]
            block_size = len(block_nodes)

            blocks.append({
                'blockname': f'block-{i//18 + 1}',
                'size': block_size,
                'nodelist': block_nodes
            })

        # Sort by size (smallest first for termination priority)
        blocks.sort(key=lambda x: x['size'])

        log.info(f"[TEST MODE] Generated {len(blocks)} mock blocks")
        return blocks
