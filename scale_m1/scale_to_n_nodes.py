#!/opt/azurehpc/slurm/venv/bin/python3.11
"""
Scale SLURM cluster to exactly N nodes with topology optimization.
Usage: ./scale_to_n_nodes.py -p gpu -n/--target_count 504 -b/--overprovision 108
"""

import argparse
import sys
import time
import json
import subprocess
import logging
from pathlib import Path
from typing import List, Dict, Tuple
import math
from abc import ABC, abstractmethod


# Add the parent directory to Python path to import slurmcc modules
sys.path.insert(0, str(Path(__file__).parent))

from slurmcc.topology import output_block_nodelist
from slurmcc import util as slutil
# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)
class AzslurmTopology(ABC):
    @abstractmethod
    def generate_topology(self, partition: str, topology_file: str) -> str:
        """Generate the SLURM topology configuration."""
        pass
class AzslurmTopologyImpl(AzslurmTopology):

    def generate_topology(self, partition: str, topology_file: str) -> str:
        """Generate the SLURM topology configuration."""
        cmd = f"azslurm topology -n -p {partition} -o {topology_file}"
        try:
            result = slutil.run(cmd, shell=True, timeout=300)
            log.info(f"Topology generated: {topology_file}")
            return result.stdout
        except subprocess.CalledProcessError as e:
            log.error(f"Failed to generate topology: {e}")
            raise
class SlurmCommands(ABC):

    @abstractmethod
    def run_command(self, cmd: str) -> subprocess.CompletedProcess:
        ...
class SlurmCommandsImpl(SlurmCommands):

    def run_command(self, cmd: str) -> subprocess.CompletedProcess:
        """Run a SLURM command and return the result."""
        try:
            return slutil.run(cmd, shell=True, timeout=300)
        except subprocess.CalledProcessError as e:
            log.error(f"Command failed: {cmd}\nError: {e}")
            raise
        except subprocess.TimeoutExpired as e:
            log.error(f"Command timed out: {cmd}\nError: {e}")
            raise
class NodeScaler:
    def __init__(self, partition: str, target_count: int, overprovision: int, slurm_commands: SlurmCommands, azslurm_topology: AzslurmTopology):
        self.partition = partition
        self.target_count = target_count
        self.overprovision = overprovision
        self.reservation_name = f"scale_reservation_{int(time.time())}"
        self.topology_file = "/etc/slurm/topology.conf"
        self.slurm_commands = slurm_commands
        self.azslurm_topology = azslurm_topology
        # Test mode data
    def round_up_to_multiple_of_18(self, number: int) -> int:
        """Round up to nearest multiple of 18."""
        return math.ceil(number / 18) * 18

    def run_command(self, cmd: str) -> subprocess.CompletedProcess:
        """Run a command and return the result. In test mode, return mocked responses."""
        return self.slurm_commands.run_command(cmd)

    def create_reservation(self, node_count: int) -> bool:
        """Create a SLURM reservation for the specified number of nodes."""
        # Round up to nearest multiple of 18
        reservation_count = self.round_up_to_multiple_of_18(node_count)
        log.info(f"Creating reservation for {reservation_count} nodes (rounded up from {node_count})")

        cmd = (f"scontrol create reservation ReservationName={self.reservation_name} "
               f"PartitionName={self.partition} NodeCnt={reservation_count} "
               f"StartTime=now Duration=2:00:00 User=root")

        try:
            self.run_command(cmd)
            log.info(f"Successfully created reservation: {self.reservation_name}")
            return True
        except subprocess.CalledProcessError:
            log.error("Failed to create reservation")
            return False

    def power_up_nodes(self, node_count: int) -> bool:
        """
        Power up the specified number of nodes in the partition.
        In test mode, simulate powering up nodes.
        """
        node_count=self.round_up_to_multiple_of_18(node_count)
        # if self.test_mode:
        #     log.info(f"[TEST MODE] Simulating power up of {node_count} nodes in partition {self.partition}")
        #     # Simulate that nodes are being powered up
        #     self.mock_powering_nodes = self.mock_nodes[:node_count]
        #     time.sleep(2)
        #     self.mock_powering_nodes = []
        #     log.info(f"[TEST MODE] All {node_count} mock nodes powered up")
        #     return True

        log.info(f"Powering up {node_count} nodes in partition {self.partition}")
        # Build the node range string, e.g., ccw-gpu-[1-612]
        # Assume node naming convention: <clustername>-<partition>-<index>
        # Get clustername from the first node in the partition (if available)
        # We'll use scontrol show partition to get the node list
        cmd_nodes = f"scontrol show reservation {self.reservation_name} | grep Nodes="
        try:
            result = self.run_command(cmd_nodes)
            # Parse something like: "Nodes=ccw-gpu-[1-612]"
            nodebase=None
            for line in result.stdout.split():
                if line.startswith("Nodes="):
                    nodebase = line.split("=", 1)[1]
                    break
            if not nodebase:
                log.error("failed to get nodes from reservation")
                return False
        except Exception:
            log.error("Failed to get nodes from reservation")
            return False

        cmd = f"scontrol update NodeName={nodebase} State=power_up"
        try:
            self.run_command(cmd)
            log.info("Nodes powering up initiated successfully")
            return True
        except subprocess.CalledProcessError:
            log.error("Failed to power up nodes")
            return False

    def wait_for_nodes_to_start(self, timeout: int = 1800) -> bool:
        """Wait for reserved nodes to start. In test mode, simulate the wait."""
        # if self.test_mode:
        #     log.info("[TEST MODE] Simulating node startup wait...")
        #     # Simulate some powering nodes initially
        #     self.mock_powering_nodes = self.mock_nodes[:5]  # First 5 nodes "powering up"
        #     time.sleep(2)  # Brief pause for realism
        #     self.mock_powering_nodes = []  # All nodes now ready
        #     log.info("[TEST MODE] All mock nodes are now ready")
        #     return True

        # Original implementation
        log.info("Waiting for nodes to start...")
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                cmd = f"sinfo -p {self.partition} -t powering_up -h -o '%N'"
                result = self.run_command(cmd)
                powering_nodes = result.stdout.strip()
                if not powering_nodes:
                    log.info("All nodes have finished powering up")
                    return True
                else:
                    log.info(f"Still waiting for nodes to power up: {powering_nodes}")

            except subprocess.CalledProcessError:
                log.warning("Error checking node status, retrying...")

            time.sleep(30)

        log.error(f"Timeout waiting for nodes to start after {timeout} seconds")
        return False

    def get_healthy_idle_nodes(self) -> List[str]:
        """Get list of healthy and idle nodes in the partition."""
        def get_hostlist(cmd) -> set:
            try:
                output=self.run_command(cmd)
            except subprocess.CalledProcessError:
                sys.exit(1)
            except subprocess.TimeoutExpired:
                sys.exit(1)
            return set(output.stdout.split('\n')[:-1])
        try:
            partition_cmd = f'-p {self.partition} '
            host_cmd = f'scontrol show hostnames $(sinfo -p {self.partition} -o "%N" -h)'
            partition_states = "powered_down,powering_up,powering_down,power_down,drain,drained,draining,unknown,down,no_respond,fail,reboot"
            sinfo_cmd = f'sinfo {partition_cmd}-t {partition_states} -o "%N" -h'
            down_cmd = f'scontrol show hostnames $({sinfo_cmd})'
            hosts=get_hostlist(host_cmd)
            down_hosts=get_hostlist(down_cmd)
            nodes=list(hosts-down_hosts)
            log.info(f"Found {len(nodes)} healthy and idle nodes")
            return nodes
        except subprocess.CalledProcessError:
            log.error("Failed to get healthy idle nodes")
            return []

    def generate_topology(self) -> bool:
        """Generate topology configuration file using azslurm CLI."""
        log.info("Generating topology configuration using azslurm CLI...")
        self.azslurm_topology.generate_topology(self.partition, self.topology_file)
    def get_ordered_blocks(self) -> List[Dict]:
        """Get blocks ordered by number of healthy nodes. In test mode, return mock data."""
        # if self.test_mode:
        #     return self._get_mock_blocks()
        try:
            json_output = output_block_nodelist(self.topology_file, table=False)
            blocks = json.loads(json_output)
            log.info(f"Found {len(blocks)} blocks in topology")
            return blocks
        except Exception as e:
            log.error(f"Failed to parse topology blocks: {e}")
            return []

    def calculate_nodes_to_terminate(self, blocks: List[Dict]) -> Tuple[List[str], int]:
        """Calculate which nodes need to be terminated to reach target count."""
        # Count total healthy nodes
        total_nodes = sum(block['size'] for block in blocks)
        nodes_to_remove = total_nodes - self.target_count

        if nodes_to_remove <= 0:
            log.info(f"Already at or below target count ({total_nodes} <= {self.target_count})")
            return [], total_nodes

        log.info(f"Need to remove {nodes_to_remove} nodes from {total_nodes} total")

        nodes_to_terminate = []
        remaining_to_remove = nodes_to_remove

        # Start with smallest blocks (already sorted by size)
        for block in blocks:
            if remaining_to_remove <= 0:
                break

            block_size = block['size']

            if remaining_to_remove >= block_size:
                # Terminate entire block
                nodes_to_terminate.extend(block['nodelist'])
                remaining_to_remove -= block_size
                log.info(f"Terminating entire block {block['blockname']} ({block_size} nodes)")
            else:
                # Terminate partial block
                nodes_to_terminate.extend(block['nodelist'][:remaining_to_remove])
                log.info(f"Terminating {remaining_to_remove} nodes from block {block['blockname']}")
                remaining_to_remove = 0

        final_count = total_nodes - len(nodes_to_terminate)
        log.info(f"Will terminate {len(nodes_to_terminate)} nodes, resulting in {final_count} nodes")

        return nodes_to_terminate, final_count

    def terminate_nodes(self, nodes: List[str]) -> bool:
        """Terminate specified nodes using scontrol."""

        if not nodes:
            log.info("No nodes to terminate")
            return True
        # if self.test_mode:
        #     log.info(f"[TEST MODE] Would terminate nodes: {', '.join(nodes)}")
        #     # Simulate termination by removing from mock list
        #     self.mock_nodes = [n for n in self.mock_nodes if n not in nodes]

        log.info(f"Terminating {len(nodes)} nodes...")

        # Convert list to comma-separated string
        node_list = ','.join(nodes)
        cmd = f"scontrol update NodeName={node_list} State=POWER_DOWN"

        try:
            self.run_command(cmd)
            log.info("Successfully initiated node termination")

            # Wait a bit for nodes to start powering down
            time.sleep(10)
            return True
        except subprocess.CalledProcessError:
            log.error("Failed to terminate nodes")
            return False

    def reconfigure_slurm(self) -> bool:
        """Reconfigure SLURM to apply topology changes."""
        log.info("Reconfiguring SLURM...")
        try:
            self.run_command("scontrol reconfigure")
            log.info("SLURM reconfiguration completed")
            return True
        except subprocess.CalledProcessError:
            log.error("Failed to reconfigure SLURM")
            return False

    def release_reservation(self) -> bool:
        """Release the SLURM reservation."""
        log.info(f"Releasing reservation: {self.reservation_name}")
        try:
            cmd = f"scontrol delete reservation {self.reservation_name}"
            self.run_command(cmd)
            log.info("Reservation released successfully")
            return True
        except subprocess.CalledProcessError:
            log.error("Failed to release reservation")
            return False

    def cleanup(self):
        """Clean up temporary files and reservations."""
        # Try to release reservation if it still exists
        try:
            self.release_reservation()
        except:
            pass

    def run(self) -> bool:
        """Execute the complete scaling workflow."""
        try:
            # Step 1: Create reservation
            reservation_count = self.target_count + self.overprovision
            if not self.create_reservation(reservation_count):
                return False

            # Step 2: Wait for nodes to start
            if not self.power_up_nodes(reservation_count):
                log.error("Failed to power up nodes")
                return False
            # Add a delay to allow nodes to start powering up
            time.sleep(5)
            if not self.wait_for_nodes_to_start():
                log.error("Nodes failed to start in time")
                return False

            # Step 3: Check healthy nodes
            healthy_nodes = self.get_healthy_idle_nodes()
            if len(healthy_nodes) < self.target_count:
                deficit = self.target_count - len(healthy_nodes)
                new_overprovision = self.overprovision + deficit
                log.error(f"Insufficient healthy nodes: {len(healthy_nodes)} < {self.target_count}")
                log.error(f"Try again with overprovision: {new_overprovision}")
                return False

            log.info(f"Sufficient healthy nodes: {len(healthy_nodes)} >= {self.target_count}")

            # Step 4: Generate initial topology
            if not self.generate_topology():
                return False

            # Step 5: Get ordered blocks
            blocks = self.get_ordered_blocks()
            if not blocks:
                log.error("No blocks found in topology")
                return False

            # Step 6: Calculate and terminate excess nodes
            nodes_to_terminate, final_count = self.calculate_nodes_to_terminate(blocks)

            if nodes_to_terminate:
                if not self.terminate_nodes(nodes_to_terminate):
                    return False

                # Wait for nodes to power down
                log.info("Waiting for nodes to power down...")
                time.sleep(10)

                # Step 7: Re-generate topology
                if not self.generate_topology():
                    return False

            # Step 8: Reconfigure SLURM
            if not self.reconfigure_slurm():
                return False

            # Step 9: Release reservation
            if not self.release_reservation():
                return False

            log.info(f"Successfully scaled cluster to {self.target_count} nodes!")
            return True

        except Exception as e:
            log.error(f"Unexpected error during scaling: {e}")
            return False

def main():
    parser = argparse.ArgumentParser(
        description='Scale SLURM cluster to exactly N nodes with topology optimization.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  ./scale_to_n_nodes.py -p gpu -n 504 -b 108
  ./scale_to_n_nodes.py --partition gpu --target_count 504 --overprovision 108 --test
        '''
    )

    parser.add_argument('-p', '--partition', required=True,
                        help='SLURM partition name')
    parser.add_argument('-n', '--target_count', type=int, required=True,
                        help='Target number of nodes')
    parser.add_argument('-b', '--overprovision', type=int, required=True,
                        help='Number of additional nodes to overprovision')
    parser.add_argument('--timeout', type=int, default=1800,
                        help='Timeout for waiting for nodes to start (seconds, default: 1800)')
    parser.add_argument('--test', action='store_true',
                        help='Run in test mode (mock all SLURM commands)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose logging')

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Validate arguments
    if args.target_count <= 0:
        log.error("Target count must be positive")
        sys.exit(1)

    if args.overprovision < 0:
        log.error("Overprovision must be non-negative")
        sys.exit(1)

    mode_str = " (TEST MODE)" if args.test else ""
    log.info(f"Starting cluster scaling{mode_str}:")
    log.info(f"  Partition: {args.partition}")
    log.info(f"  Target nodes: {args.target_count}")
    log.info(f"  Overprovision: {args.overprovision}")

    # Create and run scaler
    scaler = NodeScaler(args.partition, args.target_count, args.overprovision, args.test)

    try:
        success = scaler.run()
        if success:
            log.info("Scaling completed successfully!")
            sys.exit(0)
        else:
            log.error("Scaling failed!")
            sys.exit(1)
    except KeyboardInterrupt:
        log.info("Scaling interrupted by user")
        scaler.cleanup()
        sys.exit(130)
    except Exception as e:
        log.error(f"Unexpected error: {e}")
        scaler.cleanup()
        sys.exit(1)

if __name__ == "__main__":
    main()