#!/opt/azurehpc/slurm/venv/bin/python3.11
"""
Scale SLURM cluster to exactly N nodes with topology optimization.
Usage: ./scale_m1 -p gpu -n/--target-count 504 -b/--overprovision 108
"""

import argparse
import json
import logging
import math
import os
import subprocess
import sys
import time as timelib

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Dict, Tuple, Union


# Add the parent directory to Python path to import slurmcc modules
sys.path.insert(0, str(Path(__file__).parent))

from slurmcc.topology import output_block_nodelist
from slurmcc import util as slutil


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

__LAST_MSG = ""
def cache_log(msg: str) -> None:
    "Don't repeat the last message"
    global __LAST_MSG
    if __LAST_MSG != msg:
        log.info(msg)
        __LAST_MSG = msg


class Clock(ABC):
    @abstractmethod
    def sleep(self, seconds: int):
        """Sleep for a given number of seconds."""
        ...

    @abstractmethod
    def time(self) -> float:
        """Get the current time in seconds since the epoch."""
        ...


class RealClock(Clock):
    def sleep(self, seconds: int):
        """Sleep for a given number of seconds."""
        timelib.sleep(seconds)

    def time(self) -> float:

        """Get the current time in seconds since the epoch."""
        return timelib.time()
    

CLOCK: Clock = RealClock()

class SlurmM1Error(Exception):
    """Base class for SLURM M1 errors."""
    pass


class NodeInvalidStateError(SlurmM1Error):
    """Raised when nodes are in an invalid state for scaling."""
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def __str__(self):
        return f"NodeInvalidStateError: {self.message}"


class SlurmCommandError(SlurmM1Error):
    """Raised when a SLURM command fails."""
    def __init__(self, command: str, returncode: int, output: str):
        super().__init__(f"Command '{command}' failed with return code {returncode}")
        self.command = command
        self.returncode = returncode
        self.output = output

    def __str__(self):
        return f"SlurmCommandError: Command '{self.command}' failed with return code {self.returncode}. Output: {self.output}"


class NoReservationError(SlurmM1Error):
    pass


class AzslurmTopology(ABC):
    @abstractmethod
    def generate_topology(self, partition: str, topology_file: str) -> str:
        """Generate the SLURM topology configuration."""
        ...


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
    def run_command(self, cmd: str, check: bool = True) -> subprocess.CompletedProcess:
        ...

    def update_states(self, count: int = 9):
        pass  # overridden for testing

    @abstractmethod
    def show_hostlist(self, nodes: list[str]) -> str:
        ...
    
    @abstractmethod
    def show_hostnames(self, node_str: str) -> list[str]:
        ...


class SlurmCommandsImpl(SlurmCommands):
    def run_command(self, cmd: str, check: bool = True) -> subprocess.CompletedProcess:
        """Run a SLURM command and return the result."""
        try:
            return slutil.run(cmd, shell=True, timeout=300, check=check)
        except subprocess.CalledProcessError as e:
            log.error(f"Command failed: {cmd}\nError: {e}")
            raise
        except subprocess.TimeoutExpired as e:
            log.error(f"Command timed out: {cmd}\nError: {e}")
            raise
    
    def show_hostlist(self, nodes: list[str]) -> str:
        return slutil.to_hostlist(nodes)
    
    def show_hostnames(self, node_str: str) -> list[str]:
        return slutil.from_hostlist(node_str)


class NodeScaler:
    def __init__(self, target_count: int, overprovision: int, 
                 slurm_commands: SlurmCommands, azslurm_topology: AzslurmTopology,
                 topology_file: str = "/etc/slurm/topology.conf",
                 reservation_name: str = f"scale_m1"):
        self.target_count = target_count
        self.overprovision = overprovision
        self.topology_file = topology_file
        self.slurm_commands = slurm_commands
        self.azslurm_topology = azslurm_topology
        self.reservation_name = reservation_name
        self.partition, self.reserved_nodes = parse_reservation(reservation_name, slurm_commands)

    def round_up_to_multiple_of_18(self, number: int) -> int:
        """Round up to nearest multiple of 18."""
        return math.ceil(number / 18) * 18

    def validate_nodes(self) -> None:
        cmd = f"sinfo -p {self.partition} -t powering_down -h -o '%N'"
        result = self.run_command(cmd)
        powering_nodes = result.stdout.strip()
        if powering_nodes:
            raise NodeInvalidStateError("Some nodes are in POWERING_DOWN state, cannot proceed with scaling.")
        
    def run_command(self, cmd: str, check: bool = True) -> subprocess.CompletedProcess:
        """Run a command and return the result. In test mode, return mocked responses."""
        return self.slurm_commands.run_command(cmd, check=check)

    def power_up_nodes(self, node_count: int) -> str:
        """
        Power up at least node_count healthy nodes, while guaranteeing
        we are within the rack boundaries.
        """
        # get our list of actually reserved nodess
        reserved_nodes = set(self.reserved_nodes)

        powered_down = get_powered_down(self.partition, self.slurm_commands)
        currently_powered_up_nodes = len(get_powered_up_nodes(self.partition, self.slurm_commands))
        current_healthy_set = set(get_healthy_nodes(self.partition, self.slurm_commands))

        new_healthy_delta = node_count - len(current_healthy_set)
        if new_healthy_delta <= 0:
            log.warning(f"No need to create any nodes {node_count} {len(current_healthy_set)}")
            return ""

        # we need a multiple of 18 total nodes to be powered up (after considering powered and unhealthy)
        new_powered_up_target = self.round_up_to_multiple_of_18(currently_powered_up_nodes + new_healthy_delta)
        power_up_delta = new_powered_up_target - currently_powered_up_nodes

        # we can only power up reserved and powered down nodes
        reserved_and_powered_down = set(powered_down).intersection(reserved_nodes)
        sorted_powered_down_nodes = sorted_nodes(reserved_and_powered_down)

        if len(sorted_powered_down_nodes) < power_up_delta:
            raise SlurmM1Error(f"There are not enough nodes in a powered down state to fulfill this request - required {power_up_delta} < {len(sorted_powered_down_nodes)} {locals()}")

        assert power_up_delta > 0
        power_up_delta_nodes = sorted_powered_down_nodes[:power_up_delta]

        power_up_delta_nodes_str = self.slurm_commands.show_hostlist(power_up_delta_nodes)
        cmd = f"scontrol update NodeName={power_up_delta_nodes_str} State=power_up"
        try:
            log.info(cmd)
            self.run_command(cmd)
            log.info("Nodes powering up initiated successfully")
            self.run_command(f"azslurm resume --node-list {power_up_delta_nodes_str}")
            return power_up_delta_nodes_str
        except subprocess.CalledProcessError as e:
            log.error("Failed to power up nodes")
            raise SlurmCommandError(cmd, e.returncode, e.output)

    def wait_for_nodes_to_start(self, node_str: str, timeout: int = 7200) -> None:
        """Wait for reserved nodes to start. In test mode, simulate the wait."""
        self.wait_for_nodes(timeout, "start", node_str)

    def generate_topology(self) -> None:
        """Generate topology configuration file using azslurm CLI."""
        log.info("Generating topology configuration using azslurm CLI...")
        self.azslurm_topology.generate_topology(self.partition, self.topology_file)

    def get_ordered_blocks(self) -> List[Dict]:
        """Get blocks ordered by number of healthy nodes. In test mode, return mock data."""
        try:
            json_output = output_block_nodelist(self.topology_file, table=False)
            blocks = json.loads(json_output)
            log.info(f"Found {len(blocks)} blocks in topology in {self.topology_file}")
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
            reserved_within_block = [x for x in block['nodelist'] if x in self.reserved_nodes][ :remaining_to_remove]

            # Terminate entire block, as long as it is in the reservation
            nodes_to_terminate.extend(reserved_within_block)
            remaining_to_remove -= len(reserved_within_block)
            assert remaining_to_remove >= 0
            if len(reserved_within_block) == block_size:
                log.info(f"Terminating entire block {block['blockname']} ({block_size} nodes)")
            else:
                log.info(f"Terminating partial block {block['blockname']} ({len(reserved_within_block)} nodes)")


        final_count = total_nodes - len(nodes_to_terminate)
        log.info(f"Will terminate {len(nodes_to_terminate)} nodes, resulting in {final_count} nodes")

        return nodes_to_terminate, final_count

    def terminate_nodes(self, nodes_str: str) -> None:
        """Terminate specified nodes using scontrol."""
        # Convert list to comma-separated string
        cmd = f"scontrol update NodeName={nodes_str} State=POWER_DOWN"

        try:
            self.run_command(cmd)
            log.info("Successfully initiated node termination")
        except subprocess.CalledProcessError as e:
            raise SlurmCommandError(cmd, e.returncode, e.output)

    def wait_for_nodes_to_terminate(self, node_str: str, timeout: int = 1200) -> None:
        """Wait for reserved nodes to terminate. In test mode, simulate the wait."""
        self.wait_for_nodes(timeout, "terminate", node_str)

    def wait_for_nodes(self, timeout: int, action: str, nodes: str) -> None:
        """Wait for reserved nodes to start. In test mode, simulate the wait."""
        assert nodes
        log.info(f"Waiting for nodes to {action} {nodes}...")
        start_time = CLOCK.time()
        filter_state = 'powering_up' if action == 'start' else 'powering_down'
        terminal_states = ['POWERED_UP'] if action == 'start' else ['POWERED_DOWN', 'POWERING_DOWN']
        secondary_terminal_states = ['POWERED_DOWN', 'POWERING_DOWN'] if action == 'start' else []
        not_responsive_nodes = set()
        terminal_state_nodes_for_logging = set()
        secondary_state_nodes_for_logging = set()
        powering_up_nodes = set()
        while CLOCK.time() - start_time < timeout:
            nodes_not_in_terminal_state = set()
            state_counts: dict[str, int] = {}
            try:
                cmd = f"sinfo -n {nodes} -h -N -o '%N %T'"
                result = self.run_command(cmd)
            except subprocess.CalledProcessError as e:
                log.warning(f"Error checking node status: {e}")

            lines = [x for x in result.stdout.splitlines() if x.strip()]
            assert len(lines) > 1
            for line in lines:
                if not line.strip():
                    continue

                node, state = line.split()

                power_state = "POWERED_UP"
                if not state[-1].isalpha():
                    if state[-1] == "~":
                        power_state = "POWERED_DOWN"
                    elif state[-1] == "%":
                        power_state = "POWERING_DOWN"
                    elif state[-1] == "#":
                        power_state = "POWERING_UP"
                        if action == "start":
                            powering_up_nodes.add(node)
                    elif state[-1] == "*":
                        if node not in not_responsive_nodes:
                            not_responsive_nodes.add(node)
                            log.warning(f"Node {node} is not responsive")
                    elif state[-1] == "!":
                        log.debug("Intermediate state found for node %s", node)
                        power_state = "INTERMEDIATE"
                        pass
                    else:
                        log.warning(f"Unknown power state symbol '{state[-1]}' for node {node}")
                        power_state = "UNKNOWN"
                
                state_counts[power_state] = state_counts.get(power_state, 0) + 1
                
                if power_state in terminal_states:
                    terminal_state_nodes_for_logging.add(node)
                elif power_state in secondary_terminal_states and node in powering_up_nodes:
                    if node not in secondary_state_nodes_for_logging:
                        secondary_state_nodes_for_logging.add(node)
                        log.warning(f"Node {node} has  moved from state {terminal_states} to state {power_state}")
                        # This is considered a successful state
                        # Specifically a node that had powered up is now powering down/powered down
                else:
                    nodes_not_in_terminal_state.add(node)

            if not nodes_not_in_terminal_state:
                log.info(f"All nodes have finished {filter_state}")
                return
            
            unexpected_states = terminal_state_nodes_for_logging.intersection(nodes_not_in_terminal_state)
            if unexpected_states:
                log.error(f"The following nodes {unexpected_states} previously reached their terminal state {terminal_states} but are no longer in that/those state(s).")
            
            cache_log(f"Current power states: {state_counts}")
            CLOCK.sleep(5)
            self.slurm_commands.update_states()  # Update states in test mode

        log.error(f"Timeout waiting for nodes to {action} after {timeout} seconds")
        raise SlurmM1Error(f"Timeout waiting for nodes to {action}")
    
    def reconfigure_slurm(self) -> None:
        """Reconfigure SLURM to apply topology changes."""
        try:
            log.info("Reconfiguring SLURM...")
            self.run_command("scontrol reconfigure")
            log.info("SLURM reconfiguration completed")
        except subprocess.CalledProcessError as e:
            raise SlurmCommandError("scontrol reconfigure", e.returncode, e.output)


    def power_up(self) -> None:
        """Execute the complete scaling workflow."""
        log.error(f"Starting cluster scaling:")
        log.info(f"  Partition: {self.partition}")
        log.info(f"  Target nodes: {self.target_count}")
        log.info(f"  Overprovision: {self.overprovision}")
        # Step 0: Validate nodes
        self.validate_nodes()
        
        # Step 1: Create reservation
        target_plus_buffer = self.target_count + self.overprovision

        # Step 2: Wait for nodes to start
        power_up_list = self.power_up_nodes(target_plus_buffer)
        
        if power_up_list:
            self.wait_for_nodes_to_start(power_up_list)

        # Step 3: Check healthy nodes
        healthy_nodes = get_healthy_nodes(self.partition, self.slurm_commands)

        if len(healthy_nodes) < self.target_count:
            deficit = self.target_count - len(healthy_nodes)
            new_overprovision = self.overprovision + deficit
            log.error(f"Insufficient healthy nodes: {len(healthy_nodes)} < {self.target_count}")
            log.error(f"Try again with overprovision: {new_overprovision}")
            raise NodeInvalidStateError(f"Insufficient healthy nodes: {len(healthy_nodes)} < {self.target_count}")

        log.info(f"Sufficient healthy nodes: {len(healthy_nodes)} >= {self.target_count}")

    def prune(self) -> str:
        """Returns a suggested hostlist of nodes to terminate"""
        # Step 4: Generate initial topology
        self.generate_topology()

        # Step 5: Get ordered blocks
        blocks = self.get_ordered_blocks()
        if not blocks:
            log.error("No blocks found in topology")
            raise SlurmM1Error("No blocks found in topology")

        # Step 6: Calculate and terminate excess nodes
        nodes_to_terminate, final_count = self.calculate_nodes_to_terminate(blocks)
        if not nodes_to_terminate:
            return ""
        log.info(f"Suggesting powering down {len(nodes_to_terminate)} nodes")
        short_list = self.slurm_commands.show_hostlist(nodes_to_terminate)
        
        return short_list
    
    def prune_now(self) -> None:
        """automates the pruning (termination), topology regeneration and reconfiguration of slurm"""
        to_prune = self.prune()
        if to_prune:
            self.terminate_nodes(to_prune)

            # Wait for nodes to power down
            log.info("Waiting for nodes to power down...")
            self.wait_for_nodes_to_terminate(to_prune)

            # Step 7: Re-generate topology
            self.generate_topology()
        else:
            log.info("No nodes need to be terminated")

        # Step 8: Reconfigure SLURM
        self.reconfigure_slurm()

        log.info(f"Successfully scaled cluster to {self.target_count} nodes!")
        log.info(f"Run 'scontrol delete reservation {self.reservation_name}' to release the nodes to the cluster.")



def get_powered_up_nodes(partition, slurm_commands) -> List[str]:
    """Get list of healthy and idle nodes in the partition."""
    return get_nodes_excluding_states(partition, slurm_commands, 
                                      "powered_down,powering_up,powering_down,power_down")


def get_powered_down(partition, slurm_commands) -> List[str]:
    sinfo_cmd = f'sinfo -p {partition} -o "%N" -h -N -t powered_down'
    return sorted_nodes(slurm_commands.run_command(sinfo_cmd).stdout.strip().split('\n'))


def get_healthy_nodes(partition: str, slurm_commands: SlurmCommands) -> List[str]:
    return get_nodes_excluding_states(partition, slurm_commands,
                                       "powered_down,powering_up,powering_down,power_down,drain,drained,draining,unknown,down,no_respond,fail,reboot")


def get_nodes_excluding_states(partition: str, slurm_commands: SlurmCommands, exclude_states: str) -> List[str]:
    """Get list of healthy and idle nodes in the partition."""
    partition_cmd = f'-p {partition} '
    sinfo_cmd = f'sinfo -p {partition} -o "%N" -h -N'
    hosts = set(slurm_commands.run_command(sinfo_cmd).stdout.strip().split('\n'))
    
    sinfo_cmd = f'sinfo {partition_cmd}-t {exclude_states} -o "%N" -h -N'
    excluded_host = set(slurm_commands.run_command(sinfo_cmd).stdout.strip().split('\n'))
    log.debug(f"Excluding {len(excluded_host)} nodes with states {exclude_states}")
    
    nodes = sorted_nodes(list(hosts - excluded_host))
    log.debug(f"Found {len(nodes)} nodes after excluding states {exclude_states}")
    return nodes


def get_reservable_nodes(partition: str, slurm_commands: SlurmCommands):
    return get_nodes_excluding_states(partition, slurm_commands, "reserved,maint,allocated,mixed")


def sorted_nodes(nodes: Union[list[str], set[str]]) -> list[str]:
    nodes = list(nodes)
    if len(nodes) == 1 and nodes[0].strip() == "":
        return []
    return sorted(nodes, key=lambda x: int(x.split("-")[-1]))


def create_reservation(reservation_name: str, partition: str,  slurm_commands: SlurmCommands) -> bool:
    """Create a SLURM reservation for the specified number of nodes."""
    slurm_commands.run_command(f"scontrol update partitionname={partition} state=DOWN")
    log.info("Set partition %s DOWN and sleeping 15 seconds to ensure valid sinfo information for proper reservation creation", partition)
    CLOCK.sleep(15)
    reservable_nodes = get_reservable_nodes(partition, slurm_commands)
    if not reservable_nodes:
        raise SlurmM1Error("There are no reservable any nodes.")
    reservation_nodes_short = slurm_commands.show_hostlist(reservable_nodes)
    cmd = (f"scontrol create reservation ReservationName={reservation_name} "
                f"PartitionName={partition}  Nodes={reservation_nodes_short} "
                f"StartTime=now Duration=infinite User=root")
    try:
        slurm_commands.run_command(cmd)
        log.info(f"Successfully created reservation: {reservation_name}")
        return True
    except subprocess.CalledProcessError as e:
        log.error(f"Failed to update reservation: {e}")
        raise SlurmCommandError(cmd, e.returncode, e.output)
    finally:
        log.info("Setting partition %s UP", partition)
        slurm_commands.run_command(f"scontrol update partitionname={partition} state=UP")


def parse_reservation(reservation_name: str, slurm_commands: SlurmCommands) -> Tuple[str, list[str]]:
    cmd_nodes = f"scontrol show reservation {reservation_name}"
    
    result = slurm_commands.run_command(cmd_nodes, check=False)
    if result.returncode != 0:
        raise NoReservationError(reservation_name)
    log.info(f"Reservation nodes: {result.stdout.strip()}")
    
    # Parse something like: "Nodes=ccw-gpu-[1-612]"
    reserved_nodes_str = None
    partition = None
    assert "PartitionName" in result.stdout
    for line in result.stdout.split():
        if line.startswith("Nodes="):
            reserved_nodes_str = line.split("=", 1)[1]
        elif line.startswith("PartitionName="):
            partition = line.split("=", 1)[1]
    if not reserved_nodes_str :
        log.error("failed to get nodes from reservation")
        raise SlurmCommandError(cmd_nodes, 1, f"No nodes found in reservation - {result.stdout}")
    if not partition:
        log.error("failed to get partition from reservation")
        raise SlurmCommandError(cmd_nodes, 1, f"No partition found in reservation - {result.stdout}")
    return partition, sorted_nodes(slurm_commands.show_hostnames(reserved_nodes_str))


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Scale SLURM cluster to exactly N nodes with topology optimization.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  ./scale_m1 create_reservation -p gpu
  ./scale_m1 power_up -n 504 -b 108
  ./scale_m1 prune -n 504 > to_terminate.txt
  ...
  ./scale_m1 prune_now -n 504
        '''
    )

    subparser = parser.add_subparsers()
    create_res = subparser.add_parser("create_reservation")
    create_res.add_argument('-p', '--partition', required=True,
                        help='SLURM partition name')
    create_res.add_argument('--reservation', required=False, help="Optional: use an existing reservation",
                        default="scale_m1")
    create_res.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose logging')
    create_res.set_defaults(cmd="create_reservation")

    prune = subparser.add_parser("prune")
    prune.set_defaults(cmd="prune", overprovision=0, mock_topology=False, timeout=1800)
    prune.add_argument('-n', '--target-count', type=int, required=True,
                        help='Target number of nodes')
    prune.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose logging')
    prune.add_argument('--reservation', required=False, help="Optional: use an existing reservation",
                        default="scale_m1")
    
    prune_now = subparser.add_parser("prune_now")
    prune_now.set_defaults(cmd="prune_now", overprovision=0, mock_topology=False, timeout=1800)
    prune_now.add_argument('-n', '--target-count', type=int, required=True,
                        help='Target number of nodes')
    prune_now.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose logging')
    prune_now.add_argument('--reservation', required=False, help="Optional: use an existing reservation",
                        default="scale_m1")
    prune_now.add_argument("--termination-list", help="T")
    
    power_up = subparser.add_parser("power_up")
    power_up.set_defaults(cmd="power_up")
    
    power_up.add_argument('-n', '--target-count', type=int, required=True,
                        help='Target number of nodes')
    power_up.add_argument('-b', '--overprovision', type=int, required=True,
                        help='Number of additional nodes to overprovision')
    power_up.add_argument('--reservation', required=False, help="Optional: use an existing reservation",
                        default="scale_m1")
    power_up.add_argument('--timeout', type=int, default=1800,
                        help='Timeout for waiting for nodes to start (seconds, default: 1800)')
    power_up.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose logging')
    power_up.add_argument('--mock-topology', '-m', action='store_true',
                        help='Enable mock topology for testing')


    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    slurm_commands = SlurmCommandsImpl()
    if args.cmd == "create_reservation":
        create_reservation(args.reservation, args.partition, slurm_commands)
        return
    
    # Validate arguments
    if args.target_count <= 0:
        log.error("Target count must be positive")
        sys.exit(1)

    if args.overprovision < 0:
        log.error("Overprovision must be non-negative")
        sys.exit(1)

    azslurm_topology: AzslurmTopology
    if args.mock_topology:
        from mock import MockAzslurmTopology
        azslurm_topology = MockAzslurmTopology(slurm_commands)
    else:
        azslurm_topology = AzslurmTopologyImpl()

    try:
        scaler = NodeScaler(args.target_count, args.overprovision, 
                       slurm_commands, azslurm_topology, reservation_name=args.reservation)
        if args.cmd == "power_up":
            scaler.power_up()
        elif args.cmd == "prune":
            print(scaler.prune())
        elif args.cmd == "prune_now":
            scaler.prune_now()

    except NoReservationError as e:
        log.error(f"Please create the reservation {args.reservation} first by running `scale_m1 create_reservation --partition PARTITION` first")
        sys.exit(1)
    except SlurmM1Error as e:
        log.error(f"Scaling failed: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        log.info("Scaling interrupted by user")
        sys.exit(130)
    except Exception as e:
        log.exception(f"Unexpected error during scaling: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
