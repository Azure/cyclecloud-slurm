#!/opt/azurehpc/slurm/venv/bin/python3.11
"""
Scale SLURM cluster to exactly N nodes with topology optimization.
Usage: ./scale_to_n_nodes.py -p gpu -n/--target_count 504 -b/--overprovision 108
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
from typing import List, Dict, Tuple


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
    def run_command(self, cmd: str) -> subprocess.CompletedProcess:
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
    
    def show_hostlist(self, nodes: list[str]) -> str:
        return slutil.to_hostlist(nodes)
    
    def show_hostnames(self, node_str: str) -> list[str]:
        return slutil.from_hostlist(node_str)


class NodeScaler:
    def __init__(self, partition: str, target_count: int, overprovision: int, 
                 slurm_commands: SlurmCommands, azslurm_topology: AzslurmTopology,
                 topology_file: str = "/etc/slurm/topology.conf",
                 automatic_termination: bool = True,
                 reservation_name: str = f"scale_m1"):
        self.partition = partition
        self.target_count = target_count
        self.overprovision = overprovision
        assert reservation_name
        self.reservation_name: str  = reservation_name
        self.topology_file = topology_file
        self.slurm_commands = slurm_commands
        self.azslurm_topology = azslurm_topology
        self.automatic_termination = automatic_termination

    def round_up_to_multiple_of_18(self, number: int) -> int:
        """Round up to nearest multiple of 18."""
        return math.ceil(number / 18) * 18

    def validate_nodes(self) -> None:
        cmd = f"sinfo -p {self.partition} -t powering_down -h -o '%N'"
        result = self.run_command(cmd)
        powering_nodes = result.stdout.strip()
        if powering_nodes:
            raise NodeInvalidStateError("Some nodes are in POWERING_DOWN state, cannot proceed with scaling.")
        
    def run_command(self, cmd: str) -> subprocess.CompletedProcess:
        """Run a command and return the result. In test mode, return mocked responses."""
        return self.slurm_commands.run_command(cmd)

    def create_reservation(self, node_count: int) -> bool:
        """Create a SLURM reservation for the specified number of nodes."""
        total_powered_up_nodes = len(get_powered_up_nodes(self.partition, self.slurm_commands))
        # current_healthy = len()
        # not_reservable = len(get_healthy_but_not_idle_nodes(self.partition, self.slurm_commands))
        # reservable_nodes = current_healthy - not_reservable
        current_healthy_set = set(get_healthy_nodes(self.partition, self.slurm_commands))
        not_reservable_set = set(get_healthy_but_not_idle_nodes(self.partition, self.slurm_commands))
        already_reserved = set(get_reserved(self.partition, self.slurm_commands))
        reservable_nodes_set = current_healthy_set - set(not_reservable_set) - set(already_reserved)

        new_healthy_minimum = node_count - len(current_healthy_set)
        new_powered_up_state = self.round_up_to_multiple_of_18(total_powered_up_nodes + new_healthy_minimum)
        to_power_up = new_powered_up_state - total_powered_up_nodes

        powered_down_nodes = get_powered_down_not_reserved(self.partition, self.slurm_commands)
        if len(powered_down_nodes) < to_power_up:
            raise SlurmM1Error(f"There are not enough nodes in a powered down state to fulfill this request - required {to_power_up} < {len(powered_down_nodes)}")
        
        sorted_powered_down_nodes = sorted(powered_down_nodes, key=lambda x: int(x.split("-")[-1]))
        to_power_up_set = set(sorted_powered_down_nodes[:to_power_up])

        newly_reserved_nodes = list(to_power_up_set) + list(reservable_nodes_set)

        if not newly_reserved_nodes:
            log.info("There is no reason to create a reservation, as we are not starting any new nodes")
            return False
        already_reserved_nodes = []
        try:
            reserved_nodes_str = self.show_reservation()
            if reserved_nodes_str:
                already_reserved_nodes = self.slurm_commands.show_hostnames(reserved_nodes_str)
        except NoReservationError:
            pass
        
        reservation_nodes = already_reserved_nodes + newly_reserved_nodes
        reservation_nodes_short = self.slurm_commands.show_hostlist(reservation_nodes)
        if not already_reserved_nodes:
            cmd = (f"scontrol create reservation ReservationName={self.reservation_name} "
                f"PartitionName={self.partition}  Nodes={reservation_nodes_short} "
                f"StartTime=now Duration=infinite User=root")
        else:
            cmd = (f"scontrol update ReservationName={self.reservation_name} "
                   f"Nodes={reservation_nodes_short}")

        try:
            self.run_command(cmd)
            log.info(f"Successfully updated reservation: {self.reservation_name}")
            return True
        except subprocess.CalledProcessError as e:
            log.error(f"Failed to update reservation: {e}")
            raise SlurmCommandError(cmd, e.returncode, e.output)

        
    def show_reservation(self) -> str:
        cmd_nodes = f"scontrol show reservation {self.reservation_name}"
        try:
            result = self.run_command(cmd_nodes)
            log.info(f"Reservation nodes: {result.stdout.strip()}")
            
            # Parse something like: "Nodes=ccw-gpu-[1-612]"
            nodebase = None
            for line in result.stdout.split():
                if line.startswith("Nodes="):
                    nodebase = line.split("=", 1)[1]
                    break
            if not nodebase:
                log.error("failed to get nodes from reservation")
                raise SlurmCommandError(cmd_nodes, 1, "No nodes found in reservation")
            return nodebase
        except subprocess.CalledProcessError:
            log.exception("Failed to get nodes from reservation")
            raise NoReservationError(self.reservation_name)

    def power_up_nodes(self) -> str:
        """
        Power up the specified number of nodes in the partition.
        In test mode, simulate powering up nodes.
        """
        
        # Build the node range string, e.g., ccw-gpu-[1-612]
        # Assume node naming convention: <clustername>-<partition>-<index>
        # Get clustername from the first node in the partition (if available)
        # We'll use scontrol show partition to get the node list

        node_str = self.show_reservation()

        cmd = f"scontrol update NodeName={node_str} State=power_up"
        try:
            log.info(cmd)
            self.run_command(cmd)
            log.info("Nodes powering up initiated successfully")
            return node_str
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

    def calculate_nodes_to_terminate(self, blocks: List[Dict], reserved_node_list: str) -> Tuple[List[str], int]:
        """Calculate which nodes need to be terminated to reach target count."""
        reserved_node_names = self.slurm_commands.show_hostnames(reserved_node_list)
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
            reserved_within_block = [x for x in block['nodelist'] if x in reserved_node_names][ :remaining_to_remove]

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

    def terminate_nodes(self, nodes: List[str]) -> None:
        """Terminate specified nodes using scontrol."""
        log.info(f"Terminating {len(nodes)} nodes...")

        # Convert list to comma-separated string
        node_list = ','.join(nodes)
        cmd = f"scontrol update NodeName={node_list} State=POWER_DOWN"

        try:
            self.run_command(cmd)
            log.info("Successfully initiated node termination")

            # Wait a bit for nodes to start powering down
            CLOCK.sleep(10)
        except subprocess.CalledProcessError as e:
            raise SlurmCommandError(cmd, e.returncode, e.output)

    def wait_for_nodes_to_terminate(self, node_str: str, timeout: int = 1200) -> None:
        """Wait for reserved nodes to terminate. In test mode, simulate the wait."""
        self.wait_for_nodes(timeout, "terminate", node_str)

    def wait_for_nodes(self, timeout: int, action: str, nodes: str) -> None:
        """Wait for reserved nodes to start. In test mode, simulate the wait."""
        log.info(f"Waiting for nodes to {action}...")
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

    def run(self) -> None:
        """Execute the complete scaling workflow."""
        # Step 0: Validate nodes
        self.validate_nodes()

        # Step 1: Create reservation
        reservation_count = self.target_count + self.overprovision
        if not self.create_reservation(reservation_count):
            healthy = len(get_healthy_nodes(self.partition, self.slurm_commands))
            log.warning("Exiting early - there was no need to create a reservation, so there are no nodes to take action on.")
            log.warning(f"Healthy={healthy} Target count={self.target_count}")
            return

        # Step 2: Wait for nodes to start
        node_list = self.power_up_nodes()
        
        self.wait_for_nodes_to_start(node_list)

        # Step 3: Check healthy nodes
        healthy_nodes = get_healthy_nodes(self.partition, self.slurm_commands)

        if len(healthy_nodes) < self.target_count:
            deficit = self.target_count - len(healthy_nodes)
            new_overprovision = self.overprovision + deficit
            log.error(f"Insufficient healthy nodes: {len(healthy_nodes)} < {self.target_count}")
            log.error(f"Try again with overprovision: {new_overprovision}")
            raise NodeInvalidStateError(f"Insufficient healthy nodes: {len(healthy_nodes)} < {self.target_count}")

        log.info(f"Sufficient healthy nodes: {len(healthy_nodes)} >= {self.target_count}")

        # Step 4: Generate initial topology
        self.generate_topology()

        # Step 5: Get ordered blocks
        blocks = self.get_ordered_blocks()
        if not blocks:
            log.error("No blocks found in topology")
            raise SlurmM1Error("No blocks found in topology")

        # Step 6: Calculate and terminate excess nodes
        nodes_to_terminate, final_count = self.calculate_nodes_to_terminate(blocks, node_list)

        if not self.automatic_termination:
            if nodes_to_terminate:
                log.info(" --- We recommend that you terminate the following nodes:")
                short_list = slutil.to_hostlist(nodes_to_terminate)
                log.info(" ---  $> scontrol update nodename=%s state=power_down", short_list)
                log.info(" --- After all of the nodes have reached a powering_down state, run the following:")
            else:
                log.info(" --- There are no nodes to terminate. Run the following:")
            log.info(" ---  $> azslurm topology > %s", os.path.realpath("/etc/slurm/topology.conf"))
            log.info(" --- and then run")
            log.info(" ---  $> scontrol reconfigure")
            log.info(" --- Then delete the reservation when you are content:")
            log.info(" ---  $> scontrol delete reservation %s", self.reservation_name)
            log.info(" --- To automate this in the future, run --automate-termination")
            return

        if nodes_to_terminate:
            self.terminate_nodes(nodes_to_terminate)

            # Wait for nodes to power down
            log.info("Waiting for nodes to power down...")
            # since we are using comma separated list here, just
            # ask for 25 at a time
            for i in range(0, len(nodes_to_terminate), 25):
                sub_list = nodes_to_terminate[i: i + 25]
                self.wait_for_nodes_to_terminate(','.join(sub_list))

            # Step 7: Re-generate topology
            self.generate_topology()
        else:
            log.info("No nodes need to be terminated")

        # Step 8: Reconfigure SLURM
        self.reconfigure_slurm()

        log.info(f"Successfully scaled cluster to {self.target_count} nodes!")
        log.info(f"Run 'scontrol delete reservation {self.reservation_name}' to release the nodes to the cluster.")


def get_healthy_but_not_idle_nodes(partition, slurm_commands) -> List[str]:
    """Get list of healthy and idle nodes in the partition."""
    return get_nodes_excluding_states(partition, slurm_commands, 
                                      "powered_down,powering_up,powering_down,power_down,drain,drained,draining,unknown,down,no_respond,fail,reboot,idle")


def get_powered_up_nodes(partition, slurm_commands) -> List[str]:
    """Get list of healthy and idle nodes in the partition."""
    return get_nodes_excluding_states(partition, slurm_commands, 
                                      "powered_down,powering_up,powering_down,power_down")


def get_powered_down_not_reserved(partition, slurm_commands) -> List[str]:
    """Get list of healthy and idle nodes in the partition."""
    sinfo_cmd = f'sinfo -p {partition} -o "%N" -h -N -t powered_down'
    powered_down = slurm_commands.run_command(sinfo_cmd).stdout.strip().split('\n')

    sinfo_cmd = f'sinfo -p {partition} -o "%N" -h -N -t reserved'
    reserved = slurm_commands.run_command(sinfo_cmd).stdout.strip().split('\n')
    return list(set(powered_down) - set(reserved))

def get_reserved(partition, slurm_commands) -> List[str]:
    """Get list of healthy and idle nodes in the partition."""
    sinfo_cmd = f'sinfo -p {partition} -o "%N" -h -N -t reserved'
    return slurm_commands.run_command(sinfo_cmd).stdout.strip().split('\n')


def get_unhealthy_nodes(partition: str, slurm_commands: SlurmCommands) -> List[str]:
    """Get list of healthy and idle nodes in the partition."""
    return get_nodes_excluding_states(partition, slurm_commands, "powered_down,powering_up,powering_down,power_down,idle,mixed,allocated")


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
    log.info(f"Excluding {len(excluded_host)} nodes with states {exclude_states}")
    
    nodes = sorted(list(hosts - excluded_host), key=lambda x: int(x.split('-')[-1]))
    log.info(f"Found {len(nodes)} nodes after excluding states {exclude_states}")
    return nodes


def main() -> None:
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
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose logging')
    parser.add_argument('--mock-topology', '-m', action='store_true',
                        help='Enable mock topology for testing')
    parser.add_argument('--automatic-termination', action='store_true',
                        help='Enable automatic termination of nodes and reconfiguring of topology')
    parser.add_argument('--reservation', required=False, help="Optional: use an existing reservation",
                        default="scale_m1")

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


    log.info(f"Starting cluster scaling:")
    log.info(f"  Partition: {args.partition}")
    log.info(f"  Target nodes: {args.target_count}")
    log.info(f"  Overprovision: {args.overprovision}")

    # Create and run scaler
    slurm_commands = SlurmCommandsImpl()
    azslurm_topology: AzslurmTopology
    if args.mock_topology:
        from mock import MockAzslurmTopology
        azslurm_topology = MockAzslurmTopology(slurm_commands)
    else:
        azslurm_topology = AzslurmTopologyImpl()
    
    scaler = NodeScaler(args.partition, args.target_count, args.overprovision, 
                       slurm_commands, azslurm_topology, reservation_name=args.reservation,
                       automatic_termination=args.automatic_termination)

    try:
        scaler.run()
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
