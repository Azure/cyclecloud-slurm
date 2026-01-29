#!/usr/bin/env python3
"""
Utility module for Slurm command execution with schema-based parsing.

This module defines schemas for Slurm commands and provides generic parsers
to extract metrics. If Slurm output formats change, only the schemas need updating.
"""

import subprocess
import logging
from typing import Dict, List, Callable, Any, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger('slurm-exporter.util')


class ParseStrategy(Enum):
    """Parsing strategy for command output."""
    COUNT_LINES = "count_lines"           # Count non-empty lines
    EXTRACT_NUMBER = "extract_number"     # Extract a number from output
    PARSE_COLUMNS = "parse_columns"       # Parse columnar output
    CUSTOM = "custom"                     # Use custom parser function


@dataclass
class CommandSchema:
    """
    Schema definition for a Slurm command.
    
    Attributes:
        name: Metric name to use
        command: Command as list of strings (without state-specific args)
        parse_strategy: How to parse the output
        description: Human-readable description
        command_args: Additional args to append to command
        parser_config: Configuration for the parser (depends on strategy)
        custom_parser: Optional custom parsing function
    """
    name: str
    command: List[str]
    parse_strategy: ParseStrategy
    description: str
    command_args: Optional[List[str]] = None
    parser_config: Optional[Dict[str, Any]] = None
    custom_parser: Optional[Callable[[str], float]] = None
    
    def build_command(self, **kwargs) -> List[str]:
        """
        Build the full command with additional arguments.
        
        Args:
            **kwargs: Key-value pairs to substitute in command_args
            
        Returns:
            Complete command as list
        """
        cmd = self.command.copy()
        if self.command_args:
            for arg in self.command_args:
                # Replace placeholders like {state} with actual values
                formatted_arg = arg.format(**kwargs) if isinstance(arg, str) else arg
                cmd.append(formatted_arg)
        return cmd


# ============================================================================
# SCHEMA DEFINITIONS
# ============================================================================

# Job Queue Metrics (squeue - current state)
JOB_QUEUE_SCHEMAS = {
    'total': CommandSchema(
        name='squeue_jobs',
        command=['squeue'],
        command_args=['-h'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Total jobs in queue'
    ),
    'by_state': CommandSchema(
        name='squeue_jobs_{state}',
        command=['squeue'],
        command_args=['-t', '{state}', '-h'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Jobs in {state} state'
    )
}

# Job states to query from squeue
JOB_QUEUE_STATES = [
    'RUNNING', 'PENDING', 'CONFIGURING', 'COMPLETING',
    'SUSPENDED', 'FAILED'
]

# Job History Metrics (sacct - historical)
JOB_HISTORY_SCHEMAS = {
    'by_state': CommandSchema(
        name='sacct_jobs_total_{metric_name}',
        command=['sacct'],
        # start_time can be either:
        # - Relative: "24 hours ago", "7 days ago"
        # - Absolute: "2026-01-22T10:00:00", "2026-01-22"
        command_args=['-a', '-S', '{start_time}', '-E', 'now', '-s', '{state}', 
                     '--noheader', '-X', '-n'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Historical jobs in {state} state since start_time'
    ),
    'total_submitted': CommandSchema(
        name='sacct_jobs_total_submitted',
        command=['sacct'],
        command_args=['-S', '{start_time}', '-E', 'now', '-a', '-X', 
                     '-n', '--noheader'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Total jobs submitted since start_time'
    )
}

# Historical job states to query from sacct
# Format: (SACCT_STATE, metric_suffix)
JOB_HISTORY_STATES = [
    ('COMPLETED', 'completed'),
    ('FAILED', 'failed'),
    ('TIMEOUT', 'timeout'),
    ('NODE_FAIL', 'node_failed'),
    ('CANCELLED', 'cancelled'),
    ('PREEMPTED', 'preempted'),
    ('OUT_OF_MEMORY', 'out_of_memory')
]

# States to query for exit code analysis
JOB_HISTORY_STATES_WITH_EXIT_CODES = [
    'FAILED', 'TIMEOUT', 'NODE_FAIL', 'OUT_OF_MEMORY', 'CANCELLED'
]

# Job History Metrics - Last 6 Months (sacct - updated daily)
JOB_HISTORY_SIX_MONTHS_SCHEMAS = {
    'by_state': CommandSchema(
        name='sacct_jobs_total_six_months_{metric_name}',
        command=['sacct'],
        command_args=['-a', '-S', '{start_time}', '-E', 'now', '-s', '{state}', 
                     '--noheader', '-X', '-n'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Historical jobs in {state} state in last 6 months'
    ),
    'total_submitted': CommandSchema(
        name='sacct_jobs_total_six_months_submitted',
        command=['sacct'],
        command_args=['-S', '{start_time}', '-E', 'now', '-a', '-X', 
                     '-n', '--noheader'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Total jobs submitted in last 6 months'
    )
}

# Job History Metrics - Last Week (sacct - updated daily)
JOB_HISTORY_ONE_WEEK_SCHEMAS = {
    'by_state': CommandSchema(
        name='sacct_jobs_total_one_week_{metric_name}',
        command=['sacct'],
        command_args=['-a', '-S', '{start_time}', '-E', 'now', '-s', '{state}', 
                     '--noheader', '-X', '-n'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Historical jobs in {state} state in last week'
    ),
    'total_submitted': CommandSchema(
        name='sacct_jobs_total_one_week_submitted',
        command=['sacct'],
        command_args=['-S', '{start_time}', '-E', 'now', '-a', '-X', 
                     '-n', '--noheader'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Total jobs submitted in last week'
    )
}

# Job History Metrics - Last 24 Hours (sacct - updated hourly)
JOB_HISTORY_24_HOURS_SCHEMAS = {
    'by_state': CommandSchema(
        name='sacct_jobs_total_24_hours_{metric_name}',
        command=['sacct'],
        command_args=['-a', '-S', '{start_time}', '-E', 'now', '-s', '{state}', 
                     '--noheader', '-X', '-n'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Historical jobs in {state} state in last 24 hours'
    ),
    'total_submitted': CommandSchema(
        name='sacct_jobs_total_24_hours_submitted',
        command=['sacct'],
        command_args=['-S', '{start_time}', '-E', 'now', '-a', '-X', 
                     '-n', '--noheader'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Total jobs submitted in last 24 hours'
    )
}

# Partition-based Job History Metrics - Last 6 Months (sacct by partition - updated daily)
JOB_PARTITION_HISTORY_SIX_MONTHS_SCHEMAS = {
    'by_state': CommandSchema(
        name='sacct_partition_jobs_total_six_months_{metric_name}',
        command=['sacct'],
        command_args=['-a', '-r', '{partition}', '-S', '{start_time}', '-E', 'now', '-s', '{state}', 
                     '--noheader', '-X', '-n'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Historical jobs in {state} state for partition {partition} in last 6 months'
    ),
    'total_submitted': CommandSchema(
        name='sacct_partition_jobs_total_six_months_submitted',
        command=['sacct'],
        command_args=['-a', '-r', '{partition}', '-S', '{start_time}', '-E', 'now', '-X', 
                     '-n', '--noheader'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Total jobs submitted to partition {partition} in last 6 months'
    )
}

# Partition-based Job History Metrics - Last Week (sacct by partition - updated daily)
JOB_PARTITION_HISTORY_ONE_WEEK_SCHEMAS = {
    'by_state': CommandSchema(
        name='sacct_partition_jobs_total_one_week_{metric_name}',
        command=['sacct'],
        command_args=['-a', '-r', '{partition}', '-S', '{start_time}', '-E', 'now', '-s', '{state}', 
                     '--noheader', '-X', '-n'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Historical jobs in {state} state for partition {partition} in last week'
    ),
    'total_submitted': CommandSchema(
        name='sacct_partition_jobs_total_one_week_submitted',
        command=['sacct'],
        command_args=['-a', '-r', '{partition}', '-S', '{start_time}', '-E', 'now', '-X', 
                     '-n', '--noheader'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Total jobs submitted to partition {partition} in last week'
    )
}

# Partition-based Job History Metrics - Last 24 Hours (sacct by partition - updated hourly)
JOB_PARTITION_HISTORY_24_HOURS_SCHEMAS = {
    'by_state': CommandSchema(
        name='sacct_partition_jobs_total_24_hours_{metric_name}',
        command=['sacct'],
        command_args=['-a', '-r', '{partition}', '-S', '{start_time}', '-E', 'now', '-s', '{state}', 
                     '--noheader', '-X', '-n'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Historical jobs in {state} state for partition {partition} in last 24 hours'
    ),
    'total_submitted': CommandSchema(
        name='sacct_partition_jobs_total_24_hours_submitted',
        command=['sacct'],
        command_args=['-a', '-r', '{partition}', '-S', '{start_time}', '-E', 'now', '-X', 
                     '-n', '--noheader'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Total jobs submitted to partition {partition} in last 24 hours'
    )
}

# Node State Metrics (scontrol show nodes --json)
NODE_SCHEMAS = {
    'all_nodes': CommandSchema(
        name='scontrol_nodes',
        command=['scontrol', 'show', 'nodes', '--json'],
        command_args=[],
        parse_strategy=ParseStrategy.CUSTOM,
        description='All node information from scontrol in JSON format',
        custom_parser=None  # Will be set to parse_scontrol_nodes_json
    )
}

# Node states to extract from scontrol JSON output
# These are the state strings that appear in the "state" array
# Format: (STATE_STRING, metric_suffix)
NODE_STATES = [
    ('ALLOCATED', 'alloc'),
    ('IDLE', 'idle'),
    ('MIXED', 'mixed'),
    ('COMPLETING', 'completing'),
    ('MAINT', 'maint'),
    ('RESERVED', 'resv'),
    ('DOWN', 'down'),
    ('DRAIN', 'drain'),
    ('DRAINING', 'draining'),
    ('DRAINED', 'drained'),
    ('FAIL', 'fail'),
    ('POWERED_DOWN', 'powered_down'),
    ('POWERING_UP', 'powering_up'),
    ('CLOUD', 'cloud')
]

# Partition-based Job Queue Metrics (squeue by partition)
JOB_PARTITION_SCHEMAS = {
    'total': CommandSchema(
        name='squeue_partition_jobs',
        command=['squeue'],
        command_args=['-p', '{partition}', '-h'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Total jobs in partition {partition}'
    ),
    'by_state': CommandSchema(
        name='squeue_partition_jobs_{state}',
        command=['squeue'],
        command_args=['-p', '{partition}', '-t', '{state}', '-h'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Jobs in {state} state for partition {partition}'
    )
}

# Partition-based Job History Metrics (sacct by partition - historical)
JOB_PARTITION_HISTORY_SCHEMAS = {
    'by_state': CommandSchema(
        name='sacct_partition_jobs_total_{metric_name}',
        command=['sacct'],
        command_args=['-a', '-r', '{partition}', '-S', '{start_time}', '-E', 'now', '-s', '{state}', 
                     '--noheader', '-X', '-n'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Historical jobs in {state} state for partition {partition} since start_time'
    ),
    'total_submitted': CommandSchema(
        name='sacct_partition_jobs_total_submitted',
        command=['sacct'],
        command_args=['-a', '-r', '{partition}', '-S', '{start_time}', '-E', 'now', '-X', 
                     '-n', '--noheader'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Total jobs submitted to partition {partition} since start_time'
    )
}

# Partition-based Node Metrics (scontrol show nodes --json)
NODE_PARTITION_SCHEMAS = {
    'all_nodes': CommandSchema(
        name='scontrol_partition_nodes',
        command=['scontrol', 'show', 'nodes', '--json'],
        command_args=[],
        parse_strategy=ParseStrategy.CUSTOM,
        description='All node information from scontrol in JSON format (filtered by partition in parser)',
        custom_parser=None  # Will be set to parse_scontrol_nodes_json
    )
}

# Schema for getting partition list
PARTITION_LIST_SCHEMA = CommandSchema(
    name='partitions',
    command=['scontrol', 'show', 'partitions', '--json'],
    command_args=[],
    parse_strategy=ParseStrategy.CUSTOM,
    description='List all partitions from scontrol',
    custom_parser=None  # Will use parse_scontrol_partitions_json
)


# ============================================================================
# PARSER FUNCTIONS
# ============================================================================

def parse_count_lines(output: str) -> float:
    """
    Count non-empty lines in output.
    
    Args:
        output: Command output string
        
    Returns:
        Number of non-empty lines
    """
    if not output:
        return 0.0
    return float(len([line for line in output.split('\n') if line.strip()]))


def parse_extract_number(output: str) -> float:
    """
    Extract a number from output (assumes output is a single number).
    
    Args:
        output: Command output string
        
    Returns:
        The extracted number, or 0 if parsing fails
    """
    if not output:
        return 0.0
    try:
        return float(output.strip())
    except ValueError:
        logger.warning(f"Could not parse number from output: {output}")
        return 0.0


def parse_columns(output: str, config: Dict[str, Any]) -> float:
    """
    Parse columnar output.
    
    Args:
        output: Command output string
        config: Parser configuration with keys:
                - delimiter: Column delimiter (default: whitespace)
                - column_index: Which column to extract (0-based)
                - aggregation: How to aggregate values (sum, count, avg)
                
    Returns:
        Aggregated value
    """
    if not output:
        return 0.0
    
    delimiter = config.get('delimiter', None)
    column_index = config.get('column_index', 0)
    aggregation = config.get('aggregation', 'sum')
    
    values = []
    for line in output.split('\n'):
        if not line.strip():
            continue
        columns = line.split(delimiter)
        if column_index < len(columns):
            try:
                values.append(float(columns[column_index]))
            except ValueError:
                logger.warning(f"Could not parse value from column {column_index}: {columns[column_index]}")
    
    if not values:
        return 0.0
    
    if aggregation == 'sum':
        return sum(values)
    elif aggregation == 'count':
        return len(values)
    elif aggregation == 'avg':
        return sum(values) / len(values)
    else:
        logger.warning(f"Unknown aggregation method: {aggregation}")
        return 0.0


def parse_partition_list(output: str) -> List[str]:
    """
    Parse partition list from sinfo output (legacy support).
    
    Args:
        output: Command output string (partition names, one per line)
        
    Returns:
        List of partition names (without asterisks)
    """
    if not output:
        return []
    
    partitions = []
    for line in output.split('\n'):
        if not line.strip():
            continue
        # Remove asterisk from default partition
        partition = line.strip().rstrip('*')
        if partition and partition not in partitions:
            partitions.append(partition)
    
    return partitions


def parse_scontrol_partitions_json(output: str) -> List[str]:
    """
    Parse scontrol show partitions --json output and return partition names.
    
    Args:
        output: JSON output from scontrol show partitions --json
        
    Returns:
        List of partition names
    """
    import json
    
    if not output:
        return []
    
    try:
        data = json.loads(output)
        partitions_data = data.get('partitions', [])
        
        partition_names = []
        for partition in partitions_data:
            name = partition.get('name', '').strip()
            if name and name not in partition_names:
                partition_names.append(name)
        
        return partition_names
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse scontrol partitions JSON output: {e}")
        return []
    except Exception as e:
        logger.error(f"Error processing scontrol partition data: {e}")
        return []


def parse_scontrol_nodes_json(output: str, partition: Optional[str] = None) -> Dict[str, float]:
    """
    Parse scontrol show nodes --json output and return node state metrics.
    
    Args:
        output: JSON output from scontrol show nodes --json
        partition: Optional partition name to filter nodes by
        
    Returns:
        Dictionary of metric names to values
    """
    import json
    
    if not output:
        return {'scontrol_nodes': 0.0}
    
    try:
        data = json.loads(output)
        nodes = data.get('nodes', [])
        
        # Filter by partition if specified
        if partition:
            nodes = [n for n in nodes if partition in n.get('partitions', [])]
        
        # Count total nodes
        total_nodes = len(nodes)
        
        # Count nodes by state
        state_counts = {}
        
        for node in nodes:
            node_states = node.get('state', [])
            if not isinstance(node_states, list):
                node_states = [node_states] if node_states else []
            
            # Each node can have multiple states (e.g., ["IDLE", "CLOUD", "POWERED_DOWN"])
            # Count each state occurrence
            for state in node_states:
                state = state.upper()
                state_counts[state] = state_counts.get(state, 0) + 1
        
        # Build metrics dictionary
        metrics = {}
        prefix = 'scontrol_partition_nodes' if partition else 'scontrol_nodes'
        
        # Total nodes
        metrics[prefix] = float(total_nodes)
        
        # Map state counts to metric names using NODE_STATES mapping
        for state_str, metric_suffix in NODE_STATES:
            metric_name = f"{prefix}_{metric_suffix}"
            metrics[metric_name] = float(state_counts.get(state_str, 0))
        
        # Calculate total drain metric (all drain variants combined)
        drain_total = (
            metrics.get(f'{prefix}_drain', 0) +
            metrics.get(f'{prefix}_draining', 0) +
            metrics.get(f'{prefix}_drained', 0)
        )
        metrics[f'{prefix}_drain_total'] = drain_total
        
        return metrics
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse scontrol JSON output: {e}")
        return {'scontrol_nodes': 0.0}
    except Exception as e:
        logger.error(f"Error processing scontrol node data: {e}")
        return {'scontrol_nodes': 0.0}


# Map parse strategies to functions
PARSER_MAP = {
    ParseStrategy.COUNT_LINES: parse_count_lines,
    ParseStrategy.EXTRACT_NUMBER: parse_extract_number,
    ParseStrategy.PARSE_COLUMNS: parse_columns,
}


# ============================================================================
# COMMAND EXECUTOR
# ============================================================================

class SlurmCommandExecutor:
    """Executes Slurm commands based on schemas and returns parsed metrics."""
    
    def __init__(self, timeout: int = 30):
        """
        Initialize the command executor.
        
        Args:
            timeout: Command execution timeout in seconds
        """
        self.timeout = timeout
        self._cluster_info_cache = None
        self._cluster_info_cache_time = None
        self._cache_ttl = 86400  # 24 hours in seconds
    
    def run_command(self, cmd: List[str]) -> str:
        """
        Execute a shell command and return output.
        
        Args:
            cmd: Command as list of strings
            
        Returns:
            Command output as string
        """
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed: {' '.join(cmd)}: {e.stderr}")
            return ""
        except subprocess.TimeoutExpired:
            logger.error(f"Command timeout: {' '.join(cmd)}")
            return ""
        except Exception as e:
            logger.error(f"Command error: {' '.join(cmd)}: {e}")
            return ""
    
    def execute_schema(self, schema: CommandSchema, **kwargs) -> float:
        """
        Execute a command based on its schema and return parsed result.
        
        Args:
            schema: CommandSchema to execute
            **kwargs: Arguments to pass to schema.build_command()
            
        Returns:
            Parsed metric value
        """
        # Build the command
        cmd = schema.build_command(**kwargs)
        
        # Run the command
        output = self.run_command(cmd)
        
        # Parse the output
        if schema.parse_strategy == ParseStrategy.CUSTOM and schema.custom_parser:
            return schema.custom_parser(output)
        elif schema.parse_strategy in PARSER_MAP:
            parser = PARSER_MAP[schema.parse_strategy]
            if schema.parse_strategy == ParseStrategy.PARSE_COLUMNS:
                return parser(output, schema.parser_config or {})
            else:
                return parser(output)
        else:
            logger.error(f"Unknown parse strategy: {schema.parse_strategy}")
            return 0.0
    
    def collect_job_queue_metrics(self) -> Dict[str, float]:
        """
        Collect current job queue metrics using squeue.
        
        Returns:
            Dictionary of metric names to values
        """
        metrics = {}
        
        # Total jobs
        schema = JOB_QUEUE_SCHEMAS['total']
        metrics[schema.name] = self.execute_schema(schema)
        
        # Jobs by state
        schema = JOB_QUEUE_SCHEMAS['by_state']
        for state in JOB_QUEUE_STATES:
            metric_name = schema.name.format(state=state.lower())
            value = self.execute_schema(schema, state=state)
            metrics[metric_name] = value
            logger.debug(f"{metric_name}: {value}")
        
        return metrics
    
    def collect_job_history_metrics(self, start_time: str) -> Dict[str, float]:
        """
        Collect historical job metrics using sacct.
        
        Args:
            start_time: Start time for historical queries (e.g., "24 hours ago")
            
        Returns:
            Dictionary of metric names to values
        """
        metrics = {}
        
        # Jobs by historical state
        schema = JOB_HISTORY_SCHEMAS['by_state']
        for sacct_state, metric_suffix in JOB_HISTORY_STATES:
            metric_name = schema.name.format(metric_name=metric_suffix)
            value = self.execute_schema(schema, start_time=start_time, 
                                       state=sacct_state, metric_name=metric_suffix)
            metrics[metric_name] = value
            logger.debug(f"{metric_name}: {value}")
        
        # Total submitted
        schema = JOB_HISTORY_SCHEMAS['total_submitted']
        metrics[schema.name] = self.execute_schema(schema, start_time=start_time)
        
        return metrics
    
    def collect_job_history_metrics_by_state(self, start_time: str) -> Dict[str, float]:
        """
        Collect historical job metrics using sacct, organized by state for labeling.
        
        Args:
            start_time: Start time for historical queries (e.g., "24 hours ago")
            
        Returns:
            Dictionary with state as key, count as value
        """
        metrics_by_state = {}
        
        # Jobs by historical state
        schema = JOB_HISTORY_SCHEMAS['by_state']
        for sacct_state, metric_suffix in JOB_HISTORY_STATES:
            value = self.execute_schema(schema, start_time=start_time, 
                                       state=sacct_state, metric_name=metric_suffix)
            metrics_by_state[metric_suffix] = value
            logger.debug(f"State {metric_suffix}: {value}")
        
        return metrics_by_state
    
    def collect_node_metrics(self) -> Dict[str, float]:
        """
        Collect node state metrics using scontrol show nodes --json.
        
        Returns:
            Dictionary of metric names to values
        """
        schema = NODE_SCHEMAS['all_nodes']
        cmd = schema.build_command()
        output = self.run_command(cmd)
        
        # Parse JSON output to get all metrics at once
        metrics = parse_scontrol_nodes_json(output, partition=None)
        
        for metric_name, value in metrics.items():
            logger.debug(f"{metric_name}: {value}")
        
        return metrics
    
    def get_partitions(self) -> List[str]:
        """
        Get list of all partitions in the cluster using scontrol.
        
        Returns:
            List of partition names
        """
        cmd = PARTITION_LIST_SCHEMA.build_command()
        output = self.run_command(cmd)
        partitions = parse_scontrol_partitions_json(output)
        logger.debug(f"Found partitions: {partitions}")
        return partitions
    
    def collect_partition_job_metrics(self) -> Dict[str, Dict[str, float]]:
        """
        Collect job metrics per partition.
        
        Returns:
            Dictionary mapping partition names to metric dictionaries
            Format: {partition_name: {metric_name: value}}
        """
        partition_metrics = {}
        partitions = self.get_partitions()
        
        if not partitions:
            logger.warning("No partitions found")
            return partition_metrics
        
        for partition in partitions:
            metrics = {}
            
            # Total jobs in partition
            schema = JOB_PARTITION_SCHEMAS['total']
            metrics[schema.name] = self.execute_schema(schema, partition=partition)
            
            # Jobs by state in partition
            schema = JOB_PARTITION_SCHEMAS['by_state']
            for state in JOB_QUEUE_STATES:
                metric_name = schema.name.format(state=state.lower())
                value = self.execute_schema(schema, partition=partition, state=state)
                metrics[metric_name] = value
                logger.debug(f"{metric_name} [partition={partition}]: {value}")
            
            partition_metrics[partition] = metrics
        
        return partition_metrics
    
    def collect_partition_node_metrics(self) -> Dict[str, Dict[str, float]]:
        """
        Collect node metrics per partition using scontrol show nodes --json.
        
        Returns:
            Dictionary mapping partition names to metric dictionaries
            Format: {partition_name: {metric_name: value}}
        """
        partition_metrics = {}
        partitions = self.get_partitions()
        
        if not partitions:
            logger.warning("No partitions found")
            return partition_metrics
        
        # Get all nodes once with JSON output
        schema = NODE_PARTITION_SCHEMAS['all_nodes']
        cmd = schema.build_command()
        output = self.run_command(cmd)
        
        # Parse for each partition
        for partition in partitions:
            metrics = parse_scontrol_nodes_json(output, partition=partition)
            
            for metric_name, value in metrics.items():
                logger.debug(f"{metric_name} [partition={partition}]: {value}")
            
            partition_metrics[partition] = metrics
        
        return partition_metrics
    
    def collect_partition_job_history_metrics(self, start_time: str) -> Dict[str, Dict[str, float]]:
        """
        Collect historical job metrics per partition.
        
        Args:
            start_time: Start time for historical queries (e.g., "24 hours ago")
        
        Returns:
            Dictionary mapping partition names to metric dictionaries
            Format: {partition_name: {metric_name: value}}
        """
        partition_metrics = {}
        partitions = self.get_partitions()
        
        if not partitions:
            logger.warning("No partitions found")
            return partition_metrics
        
        for partition in partitions:
            metrics = {}
            
            # Jobs by historical state in partition
            schema = JOB_PARTITION_HISTORY_SCHEMAS['by_state']
            for sacct_state, metric_suffix in JOB_HISTORY_STATES:
                metric_name = schema.name.format(metric_name=metric_suffix)
                value = self.execute_schema(schema, partition=partition, 
                                           start_time=start_time, state=sacct_state, 
                                           metric_name=metric_suffix)
                metrics[metric_name] = value
                logger.debug(f"{metric_name} [partition={partition}]: {value}")
            
            # Total submitted to partition
            schema = JOB_PARTITION_HISTORY_SCHEMAS['total_submitted']
            metrics[schema.name] = self.execute_schema(schema, partition=partition, 
                                                       start_time=start_time)
            
            partition_metrics[partition] = metrics
        
        return partition_metrics
    
    def collect_job_history_six_months_metrics(self) -> Dict[str, any]:
        """
        Collect historical job metrics for the last 6 months using sacct.
        These metrics are updated daily and provide a rolling 6-month window.
        
        Returns:
            Dictionary with 'start_date' and 'metrics' keys
        """
        from datetime import datetime, timedelta
        
        # Calculate date 6 months ago in YYYY-MM-DD format
        six_months_ago = (datetime.now() - timedelta(days=180)).strftime('%Y-%m-%d')
        
        metrics = {}
        
        # Jobs by historical state (last 6 months)
        schema = JOB_HISTORY_SIX_MONTHS_SCHEMAS['by_state']
        for sacct_state, metric_suffix in JOB_HISTORY_STATES:
            metric_name = schema.name.format(metric_name=metric_suffix)
            value = self.execute_schema(schema, start_time=six_months_ago, 
                                       state=sacct_state, metric_name=metric_suffix)
            metrics[metric_name] = value
            logger.debug(f"{metric_name}: {value}")
        
        # Total submitted (last 6 months)
        schema = JOB_HISTORY_SIX_MONTHS_SCHEMAS['total_submitted']
        metrics[schema.name] = self.execute_schema(schema, start_time=six_months_ago)
        
        return {
            'start_date': six_months_ago,
            'metrics': metrics
        }
    
    def collect_job_history_six_months_metrics_by_state(self) -> Dict[str, any]:
        """
        Collect historical job metrics for the last 6 months, organized by state for labeling.
        
        Returns:
            Dictionary with 'start_date' and 'metrics_by_state' keys
        """
        from datetime import datetime, timedelta
        
        # Calculate date 6 months ago in YYYY-MM-DD format
        six_months_ago = (datetime.now() - timedelta(days=180)).strftime('%Y-%m-%d')
        
        metrics_by_state = {}
        
        # Jobs by historical state (last 6 months)
        schema = JOB_HISTORY_SIX_MONTHS_SCHEMAS['by_state']
        for sacct_state, metric_suffix in JOB_HISTORY_STATES:
            value = self.execute_schema(schema, start_time=six_months_ago, 
                                       state=sacct_state, metric_name=metric_suffix)
            metrics_by_state[metric_suffix] = value
            logger.debug(f"State {metric_suffix}: {value}")
        
        return {
            'start_date': six_months_ago,
            'metrics_by_state': metrics_by_state
        }
    
    def collect_job_history_six_months_metrics_by_state_and_exit_code(self) -> Dict[str, any]:
        """
        Collect historical job metrics for the last 6 months with state and exit code labels.
        
        Returns:
            Dictionary with 'start_date' and 'metrics' keys where metrics is a list of (state, exit_code, count) tuples
        """
        from datetime import datetime, timedelta
        from collections import defaultdict
        
        # Calculate date 6 months ago in YYYY-MM-DD format
        six_months_ago = (datetime.now() - timedelta(days=180)).strftime('%Y-%m-%d')
        
        # Build sacct command to get state and exit codes
        states = ','.join(JOB_HISTORY_STATES_WITH_EXIT_CODES)
        cmd = ['sacct', '-a', '-S', six_months_ago, '-E', 'now', '-s', states,
               '-o', 'State,ExitCode', '--parsable2', '-n', '-X']
        
        output = self.run_command(cmd)
        
        # Parse output and count by (state, exit_code)
        metrics = defaultdict(int)
        if output:
            for line in output.strip().split('\n'):
                if not line.strip():
                    continue
                parts = line.split('|')
                if len(parts) >= 2:
                    state = parts[0].strip()
                    exit_code = parts[1].strip()
                    # Normalize state name to metric suffix format
                    state_normalized = state.lower().replace('_', '_')
                    if state == 'NODE_FAIL':
                        state_normalized = 'node_failed'
                    elif state == 'OUT_OF_MEMORY':
                        state_normalized = 'out_of_memory'
                    else:
                        state_normalized = state.lower()
                    
                    metrics[(state_normalized, exit_code)] += 1
        
        # Convert to list format
        metrics_list = [(state, exit_code, count) for (state, exit_code), count in metrics.items()]
        
        return {
            'start_date': six_months_ago,
            'metrics': metrics_list
        }
    
    def collect_partition_job_history_six_months_metrics(self) -> Dict[str, any]:
        """
        Collect historical job metrics per partition for the last 6 months.
        These metrics are updated daily and provide a rolling 6-month window.
        
        Returns:
            Dictionary with 'start_date' and 'partition_metrics' keys
        """
        from datetime import datetime, timedelta
        
        # Calculate date 6 months ago in YYYY-MM-DD format
        six_months_ago = (datetime.now() - timedelta(days=180)).strftime('%Y-%m-%d')
        
        partition_metrics = {}
        partitions = self.get_partitions()
        
        if not partitions:
            logger.warning("No partitions found")
            return {
                'start_date': six_months_ago,
                'partition_metrics': partition_metrics
            }
        
        for partition in partitions:
            metrics = {}
            
            # Jobs by historical state in partition (last 6 months)
            schema = JOB_PARTITION_HISTORY_SIX_MONTHS_SCHEMAS['by_state']
            for sacct_state, metric_suffix in JOB_HISTORY_STATES:
                metric_name = schema.name.format(metric_name=metric_suffix)
                value = self.execute_schema(schema, partition=partition, 
                                           start_time=six_months_ago,
                                           state=sacct_state, metric_name=metric_suffix)
                metrics[metric_name] = value
                logger.debug(f"{metric_name} [partition={partition}]: {value}")
            
            # Total submitted to partition (last 6 months)
            schema = JOB_PARTITION_HISTORY_SIX_MONTHS_SCHEMAS['total_submitted']
            metrics[schema.name] = self.execute_schema(schema, partition=partition,
                                                       start_time=six_months_ago)
            
            partition_metrics[partition] = metrics
        
        return {
            'start_date': six_months_ago,
            'partition_metrics': partition_metrics
        }
    
    def collect_partition_job_history_six_months_metrics_by_state_and_exit_code(self) -> Dict[str, any]:
        """
        Collect historical job metrics per partition for the last 6 months with state and exit code labels.
        
        Returns:
            Dictionary with 'start_date' and 'partition_metrics' keys where partition_metrics contains
            partition -> list of (state, exit_code, count) tuples
        """
        from datetime import datetime, timedelta
        from collections import defaultdict
        
        # Calculate date 6 months ago in YYYY-MM-DD format
        six_months_ago = (datetime.now() - timedelta(days=180)).strftime('%Y-%m-%d')
        
        partition_metrics = {}
        partitions = self.get_partitions()
        
        if not partitions:
            logger.warning("No partitions found")
            return {
                'start_date': six_months_ago,
                'partition_metrics': partition_metrics
            }
        
        for partition in partitions:
            # Build sacct command to get state and exit codes for this partition
            states = ','.join(JOB_HISTORY_STATES_WITH_EXIT_CODES)
            cmd = ['sacct', '-a', '-r', partition, '-S', six_months_ago, '-E', 'now', '-s', states,
                   '-o', 'State,ExitCode', '--parsable2', '-n', '-X']
            
            output = self.run_command(cmd)
            
            # Parse output and count by (state, exit_code)
            metrics = defaultdict(int)
            if output:
                for line in output.strip().split('\n'):
                    if not line.strip():
                        continue
                    parts = line.split('|')
                    if len(parts) >= 2:
                        state = parts[0].strip()
                        exit_code = parts[1].strip()
                        # Normalize state name
                        state_normalized = state.lower()
                        if state == 'NODE_FAIL':
                            state_normalized = 'node_failed'
                        elif state == 'OUT_OF_MEMORY':
                            state_normalized = 'out_of_memory'
                        
                        metrics[(state_normalized, exit_code)] += 1
            
            # Convert to list format
            partition_metrics[partition] = [(state, exit_code, count) for (state, exit_code), count in metrics.items()]
        
        return {
            'start_date': six_months_ago,
            'partition_metrics': partition_metrics
        }
    
    def collect_job_history_one_week_metrics(self) -> Dict[str, any]:
        """
        Collect historical job metrics for the last week using sacct.
        These metrics are updated daily and provide a rolling 7-day window.
        
        Returns:
            Dictionary with 'start_date' and 'metrics' keys
        """
        from datetime import datetime, timedelta
        
        # Calculate date 1 week ago in YYYY-MM-DD format
        one_week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        
        metrics = {}
        
        # Jobs by historical state (last week)
        schema = JOB_HISTORY_ONE_WEEK_SCHEMAS['by_state']
        for sacct_state, metric_suffix in JOB_HISTORY_STATES:
            metric_name = schema.name.format(metric_name=metric_suffix)
            value = self.execute_schema(schema, start_time=one_week_ago, 
                                       state=sacct_state, metric_name=metric_suffix)
            metrics[metric_name] = value
            logger.debug(f"{metric_name}: {value}")
        
        # Total submitted (last week)
        schema = JOB_HISTORY_ONE_WEEK_SCHEMAS['total_submitted']
        metrics[schema.name] = self.execute_schema(schema, start_time=one_week_ago)
        
        return {
            'start_date': one_week_ago,
            'metrics': metrics
        }
    
    def collect_job_history_one_week_metrics_by_state(self) -> Dict[str, any]:
        """
        Collect historical job metrics for the last week, organized by state for labeling.
        
        Returns:
            Dictionary with 'start_date' and 'metrics_by_state' keys
        """
        from datetime import datetime, timedelta
        
        # Calculate date 1 week ago in YYYY-MM-DD format
        one_week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        
        metrics_by_state = {}
        
        # Jobs by historical state (last week)
        schema = JOB_HISTORY_ONE_WEEK_SCHEMAS['by_state']
        for sacct_state, metric_suffix in JOB_HISTORY_STATES:
            value = self.execute_schema(schema, start_time=one_week_ago, 
                                       state=sacct_state, metric_name=metric_suffix)
            metrics_by_state[metric_suffix] = value
            logger.debug(f"State {metric_suffix}: {value}")
        
        return {
            'start_date': one_week_ago,
            'metrics_by_state': metrics_by_state
        }
    
    def collect_job_history_one_week_metrics_by_state_and_exit_code(self) -> Dict[str, any]:
        """
        Collect historical job metrics for the last week with state and exit code labels.
        
        Returns:
            Dictionary with 'start_date' and 'metrics' keys where metrics is a list of (state, exit_code, count) tuples
        """
        from datetime import datetime, timedelta
        from collections import defaultdict
        
        # Calculate date 1 week ago in YYYY-MM-DD format
        one_week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        
        # Build sacct command to get state and exit codes
        states = ','.join(JOB_HISTORY_STATES_WITH_EXIT_CODES)
        cmd = ['sacct', '-a', '-S', one_week_ago, '-E', 'now', '-s', states,
               '-o', 'State,ExitCode', '--parsable2', '-n', '-X']
        
        output = self.run_command(cmd)
        
        # Parse output and count by (state, exit_code)
        metrics = defaultdict(int)
        if output:
            for line in output.strip().split('\n'):
                if not line.strip():
                    continue
                parts = line.split('|')
                if len(parts) >= 2:
                    state = parts[0].strip()
                    exit_code = parts[1].strip()
                    # Normalize state name to metric suffix format
                    state_normalized = state.lower().replace('_', '_')
                    if state == 'NODE_FAIL':
                        state_normalized = 'node_failed'
                    elif state == 'OUT_OF_MEMORY':
                        state_normalized = 'out_of_memory'
                    else:
                        state_normalized = state.lower()
                    
                    metrics[(state_normalized, exit_code)] += 1
        
        # Convert to list format
        metrics_list = [(state, exit_code, count) for (state, exit_code), count in metrics.items()]
        
        return {
            'start_date': one_week_ago,
            'metrics': metrics_list
        }
    
    def collect_partition_job_history_one_week_metrics(self) -> Dict[str, any]:
        """
        Collect historical job metrics per partition for the last week.
        These metrics are updated daily and provide a rolling 7-day window.
        
        Returns:
            Dictionary with 'start_date' and 'partition_metrics' keys
        """
        from datetime import datetime, timedelta
        
        # Calculate date 1 week ago in YYYY-MM-DD format
        one_week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        
        partition_metrics = {}
        partitions = self.get_partitions()
        
        if not partitions:
            logger.warning("No partitions found")
            return {
                'start_date': one_week_ago,
                'partition_metrics': partition_metrics
            }
        
        for partition in partitions:
            metrics = {}
            
            # Jobs by historical state in partition (last week)
            schema = JOB_PARTITION_HISTORY_ONE_WEEK_SCHEMAS['by_state']
            for sacct_state, metric_suffix in JOB_HISTORY_STATES:
                metric_name = schema.name.format(metric_name=metric_suffix)
                value = self.execute_schema(schema, partition=partition, 
                                           start_time=one_week_ago,
                                           state=sacct_state, metric_name=metric_suffix)
                metrics[metric_name] = value
                logger.debug(f"{metric_name} [partition={partition}]: {value}")
            
            # Total submitted to partition (last week)
            schema = JOB_PARTITION_HISTORY_ONE_WEEK_SCHEMAS['total_submitted']
            metrics[schema.name] = self.execute_schema(schema, partition=partition,
                                                       start_time=one_week_ago)
            
            partition_metrics[partition] = metrics
        
        return {
            'start_date': one_week_ago,
            'partition_metrics': partition_metrics
        }
    
    def collect_partition_job_history_one_week_metrics_by_state_and_exit_code(self) -> Dict[str, any]:
        """
        Collect historical job metrics per partition for the last week with state and exit code labels.
        
        Returns:
            Dictionary with 'start_date' and 'partition_metrics' keys where partition_metrics contains
            partition -> list of (state, exit_code, count) tuples
        """
        from datetime import datetime, timedelta
        from collections import defaultdict
        
        # Calculate date 1 week ago in YYYY-MM-DD format
        one_week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        
        partition_metrics = {}
        partitions = self.get_partitions()
        
        if not partitions:
            logger.warning("No partitions found")
            return {
                'start_date': one_week_ago,
                'partition_metrics': partition_metrics
            }
        
        for partition in partitions:
            # Build sacct command to get state and exit codes for this partition
            states = ','.join(JOB_HISTORY_STATES_WITH_EXIT_CODES)
            cmd = ['sacct', '-a', '-r', partition, '-S', one_week_ago, '-E', 'now', '-s', states,
                   '-o', 'State,ExitCode', '--parsable2', '-n', '-X']
            
            output = self.run_command(cmd)
            
            # Parse output and count by (state, exit_code)
            metrics = defaultdict(int)
            if output:
                for line in output.strip().split('\n'):
                    if not line.strip():
                        continue
                    parts = line.split('|')
                    if len(parts) >= 2:
                        state = parts[0].strip()
                        exit_code = parts[1].strip()
                        # Normalize state name
                        state_normalized = state.lower()
                        if state == 'NODE_FAIL':
                            state_normalized = 'node_failed'
                        elif state == 'OUT_OF_MEMORY':
                            state_normalized = 'out_of_memory'
                        
                        metrics[(state_normalized, exit_code)] += 1
            
            # Convert to list format
            partition_metrics[partition] = [(state, exit_code, count) for (state, exit_code), count in metrics.items()]
        
        return {
            'start_date': one_week_ago,
            'partition_metrics': partition_metrics
        }
    
    def collect_job_history_24_hours_metrics(self) -> Dict[str, any]:
        """
        Collect historical job metrics for the last 24 hours using sacct.
        These metrics are updated hourly and provide a rolling 24-hour window.
        
        Returns:
            Dictionary with 'start_datetime' and 'metrics' keys
        """
        from datetime import datetime, timedelta
        
        # Calculate datetime 24 hours ago in YYYY-MM-DDTHH:MM:SS format
        twenty_four_hours_ago = (datetime.now() - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%S')
        
        metrics = {}
        
        # Jobs by historical state (last 24 hours)
        schema = JOB_HISTORY_24_HOURS_SCHEMAS['by_state']
        for sacct_state, metric_suffix in JOB_HISTORY_STATES:
            metric_name = schema.name.format(metric_name=metric_suffix)
            value = self.execute_schema(schema, start_time=twenty_four_hours_ago, 
                                       state=sacct_state, metric_name=metric_suffix)
            metrics[metric_name] = value
            logger.debug(f"{metric_name}: {value}")
        
        # Total submitted (last 24 hours)
        schema = JOB_HISTORY_24_HOURS_SCHEMAS['total_submitted']
        metrics[schema.name] = self.execute_schema(schema, start_time=twenty_four_hours_ago)
        
        return {
            'start_datetime': twenty_four_hours_ago,
            'metrics': metrics
        }
    
    def collect_job_history_24_hours_metrics_by_state(self) -> Dict[str, any]:
        """
        Collect historical job metrics for the last 24 hours, organized by state for labeling.
        
        Returns:
            Dictionary with 'start_datetime' and 'metrics_by_state' keys
        """
        from datetime import datetime, timedelta
        
        # Calculate datetime 24 hours ago in YYYY-MM-DDTHH:MM:SS format
        twenty_four_hours_ago = (datetime.now() - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%S')
        
        metrics_by_state = {}
        
        # Jobs by historical state (last 24 hours)
        schema = JOB_HISTORY_24_HOURS_SCHEMAS['by_state']
        for sacct_state, metric_suffix in JOB_HISTORY_STATES:
            value = self.execute_schema(schema, start_time=twenty_four_hours_ago, 
                                       state=sacct_state, metric_name=metric_suffix)
            metrics_by_state[metric_suffix] = value
            logger.debug(f"State {metric_suffix}: {value}")
        
        return {
            'start_datetime': twenty_four_hours_ago,
            'metrics_by_state': metrics_by_state
        }
    
    def collect_job_history_24_hours_metrics_by_state_and_exit_code(self) -> Dict[str, any]:
        """
        Collect historical job metrics for the last 24 hours with state and exit code labels.
        
        Returns:
            Dictionary with 'start_datetime' and 'metrics' keys where metrics is a list of (state, exit_code, count) tuples
        """
        from datetime import datetime, timedelta
        from collections import defaultdict
        
        # Calculate datetime 24 hours ago in YYYY-MM-DDTHH:MM:SS format
        twenty_four_hours_ago = (datetime.now() - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%S')
        
        # Build sacct command to get state and exit codes
        states = ','.join(JOB_HISTORY_STATES_WITH_EXIT_CODES)
        cmd = ['sacct', '-a', '-S', twenty_four_hours_ago, '-E', 'now', '-s', states,
               '-o', 'State,ExitCode', '--parsable2', '-n', '-X']
        
        output = self.run_command(cmd)
        
        # Parse output and count by (state, exit_code)
        metrics = defaultdict(int)
        if output:
            for line in output.strip().split('\n'):
                if not line.strip():
                    continue
                parts = line.split('|')
                if len(parts) >= 2:
                    state = parts[0].strip()
                    exit_code = parts[1].strip()
                    # Normalize state name to metric suffix format
                    state_normalized = state.lower().replace('_', '_')
                    if state == 'NODE_FAIL':
                        state_normalized = 'node_failed'
                    elif state == 'OUT_OF_MEMORY':
                        state_normalized = 'out_of_memory'
                    else:
                        state_normalized = state.lower()
                    
                    metrics[(state_normalized, exit_code)] += 1
        
        # Convert to list format
        metrics_list = [(state, exit_code, count) for (state, exit_code), count in metrics.items()]
        
        return {
            'start_datetime': twenty_four_hours_ago,
            'metrics': metrics_list
        }
    
    def collect_partition_job_history_24_hours_metrics(self) -> Dict[str, any]:
        """
        Collect historical job metrics per partition for the last 24 hours.
        These metrics are updated hourly and provide a rolling 24-hour window.
        
        Returns:
            Dictionary with 'start_datetime' and 'partition_metrics' keys
        """
        from datetime import datetime, timedelta
        
        # Calculate datetime 24 hours ago in YYYY-MM-DDTHH:MM:SS format
        twenty_four_hours_ago = (datetime.now() - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%S')
        
        partition_metrics = {}
        partitions = self.get_partitions()
        
        if not partitions:
            logger.warning("No partitions found")
            return {
                'start_datetime': twenty_four_hours_ago,
                'partition_metrics': partition_metrics
            }
        
        for partition in partitions:
            metrics = {}
            
            # Jobs by historical state in partition (last 24 hours)
            schema = JOB_PARTITION_HISTORY_24_HOURS_SCHEMAS['by_state']
            for sacct_state, metric_suffix in JOB_HISTORY_STATES:
                metric_name = schema.name.format(metric_name=metric_suffix)
                value = self.execute_schema(schema, partition=partition, 
                                           start_time=twenty_four_hours_ago,
                                           state=sacct_state, metric_name=metric_suffix)
                metrics[metric_name] = value
                logger.debug(f"{metric_name} [partition={partition}]: {value}")
            
            # Total submitted to partition (last 24 hours)
            schema = JOB_PARTITION_HISTORY_24_HOURS_SCHEMAS['total_submitted']
            metrics[schema.name] = self.execute_schema(schema, partition=partition,
                                                       start_time=twenty_four_hours_ago)
            
            partition_metrics[partition] = metrics
        
        return {
            'start_datetime': twenty_four_hours_ago,
            'partition_metrics': partition_metrics
        }
    
    def collect_partition_job_history_24_hours_metrics_by_state_and_exit_code(self) -> Dict[str, any]:
        """
        Collect historical job metrics per partition for the last 24 hours with state and exit code labels.
        
        Returns:
            Dictionary with 'start_datetime' and 'partition_metrics' keys where partition_metrics contains
            partition -> list of (state, exit_code, count) tuples
        """
        from datetime import datetime, timedelta
        from collections import defaultdict
        
        # Calculate datetime 24 hours ago in YYYY-MM-DDTHH:MM:SS format
        twenty_four_hours_ago = (datetime.now() - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%S')
        
        partition_metrics = {}
        partitions = self.get_partitions()
        
        if not partitions:
            logger.warning("No partitions found")
            return {
                'start_datetime': twenty_four_hours_ago,
                'partition_metrics': partition_metrics
            }
        
        for partition in partitions:
            # Build sacct command to get state and exit codes for this partition
            states = ','.join(JOB_HISTORY_STATES_WITH_EXIT_CODES)
            cmd = ['sacct', '-a', '-r', partition, '-S', twenty_four_hours_ago, '-E', 'now', '-s', states,
                   '-o', 'State,ExitCode', '--parsable2', '-n', '-X']
            
            output = self.run_command(cmd)
            
            # Parse output and count by (state, exit_code)
            metrics = defaultdict(int)
            if output:
                for line in output.strip().split('\n'):
                    if not line.strip():
                        continue
                    parts = line.split('|')
                    if len(parts) >= 2:
                        state = parts[0].strip()
                        exit_code = parts[1].strip()
                        # Normalize state name
                        state_normalized = state.lower()
                        if state == 'NODE_FAIL':
                            state_normalized = 'node_failed'
                        elif state == 'OUT_OF_MEMORY':
                            state_normalized = 'out_of_memory'
                        
                        metrics[(state_normalized, exit_code)] += 1
            
            # Convert to list format
            partition_metrics[partition] = [(state, exit_code, count) for (state, exit_code), count in metrics.items()]
        
        return {
            'start_datetime': twenty_four_hours_ago,
            'partition_metrics': partition_metrics
        }
    
    def collect_cluster_info(self) -> Dict[str, any]:
        """
        Collect static cluster information (cached for 24 hours).
        
        Returns:
            Dictionary with cluster_name and partitions info
        """
        import time
        import json
        
        # Check if cache is still valid
        current_time = time.time()
        if (self._cluster_info_cache is not None and 
            self._cluster_info_cache_time is not None and
            (current_time - self._cluster_info_cache_time) < self._cache_ttl):
            logger.debug("Using cached cluster info")
            return self._cluster_info_cache
        
        logger.info("Refreshing cluster info cache")
        cluster_info = {
            'cluster_name': 'unknown',
            'partitions': []
        }
        
        try:
            # Get cluster name from azslurm config
            config_output = self.run_command(['azslurm', 'config'])
            if config_output:
                config_data = json.loads(config_output)
                cluster_info['cluster_name'] = config_data.get('cluster_name', 'unknown')
            
            # Get partition details from azslurm buckets
            buckets_output = self.run_command(['azslurm', 'buckets'])
            if buckets_output:
                lines = buckets_output.strip().split('\n')
                if len(lines) > 1:  # Skip header
                    # Track unique partitions (nodearrays without placement groups)
                    seen_partitions = set()
                    for line in lines[1:]:
                        parts = line.split()
                        if not parts:
                            continue
                        
                        # First column is always NODEARRAY
                        nodearray = parts[0]
                        
                        # Skip placement group entries (contain _pg in nodearray name)
                        if '_pg' in nodearray or not nodearray:
                            continue
                        if nodearray in seen_partitions:
                            continue
                        seen_partitions.add(nodearray)
                        
                        # When PLACEMENT_GROUP is empty, VM_SIZE is at index 1
                        # When PLACEMENT_GROUP has a value, VM_SIZE is at index 2
                        # We can tell by checking if index 1 starts with "Standard_"
                        vm_size = parts[1] if len(parts) > 1 and parts[1].startswith('Standard_') else (parts[2] if len(parts) > 2 else 'unknown')
                        
                        # AVAILABLE_COUNT is typically around index 6-7, but let's find it
                        # by looking for a numeric value after the VM_SIZE
                        available_count = '0'
                        for i, part in enumerate(parts):
                            if part.startswith('Standard_'):
                                # AVAILABLE_COUNT is 4 positions after VM_SIZE
                                # VM_SIZE, VCPU_COUNT, PCPU_COUNT, MEMORY, AVAILABLE_COUNT
                                if i + 4 < len(parts):
                                    available_count = parts[i + 4]
                                break
                        
                        # Get node list from sinfo
                        node_list = 'N/A'
                        sinfo_output = self.run_command(['sinfo', '-p', nodearray, '-h', '-o', '%N'])
                        if sinfo_output:
                            node_list = sinfo_output.strip()
                        
                        cluster_info['partitions'].append({
                            'name': nodearray,
                            'vm_size': vm_size,
                            'total_nodes': available_count,
                            'node_list': node_list
                        })
            
            # Cache the result
            self._cluster_info_cache = cluster_info
            self._cluster_info_cache_time = current_time
            logger.info(f"Cluster info cached: {cluster_info['cluster_name']}, {len(cluster_info['partitions'])} partitions")
            
        except Exception as e:
            logger.error(f"Error collecting cluster info: {e}")
        
        return cluster_info


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def get_all_metrics(start_time: str = "24 hours ago", timeout: int = 30) -> Dict[str, float]:
    """
    Collect all Slurm metrics.
    
    Args:
        start_time: Start time for cumulative metrics
        timeout: Command timeout in seconds
        
    Returns:
        Dictionary of all metrics
    """
    executor = SlurmCommandExecutor(timeout=timeout)
    
    metrics = {}
    metrics.update(executor.collect_job_queue_metrics())
    metrics.update(executor.collect_job_history_metrics(start_time))
    metrics.update(executor.collect_node_metrics())
    
    return metrics