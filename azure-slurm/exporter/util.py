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
        name='slurm_jobs',
        command=['squeue'],
        command_args=['-h'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Total jobs in queue'
    ),
    'by_state': CommandSchema(
        name='slurm_jobs_{state}',
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
        name='slurm_jobs_{metric_name}',
        command=['sacct'],
        # start_time can be either:
        # - Relative: "24 hours ago", "7 days ago"
        # - Absolute: "2026-01-22T10:00:00", "2026-01-22"
        command_args=['-S', '{start_time}', '-E', 'now', '-s', '{state}', 
                     '--noheader', '-X', '-n'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Historical jobs in {state} state since start_time'
    ),
    'total_submitted': CommandSchema(
        name='slurm_jobs_total_submitted',
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

# Node State Metrics (sinfo)
NODE_SCHEMAS = {
    'total': CommandSchema(
        name='slurm_nodes',
        command=['sinfo'],
        command_args=['-N', '-h'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Total number of nodes'
    ),
    'by_state': CommandSchema(
        name='slurm_nodes_{metric_name}',
        command=['sinfo'],
        command_args=['-t', '{state}', '-h', '-o', '%D'],
        parse_strategy=ParseStrategy.EXTRACT_NUMBER,
        description='Nodes in {state} state'
    )
}

# Node states to query from sinfo
# Format: (SINFO_STATE, metric_suffix)
NODE_STATES = [
    ('alloc', 'alloc'),
    ('idle', 'idle'),
    ('mix', 'mixed'),
    ('comp', 'completing'),
    ('maint', 'maint'),
    ('resv', 'resv'),
    ('down', 'down'),
    ('drain', 'drain'),
    ('drng', 'draining'),
    ('drained', 'drained'),
    ('fail', 'fail'),
    ('powered_down', 'powered_down'),
    ('powering_up', 'powering_up')
]

# Partition-based Job Queue Metrics (squeue by partition)
JOB_PARTITION_SCHEMAS = {
    'total': CommandSchema(
        name='slurm_partition_jobs',
        command=['squeue'],
        command_args=['-p', '{partition}', '-h'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Total jobs in partition {partition}'
    ),
    'by_state': CommandSchema(
        name='slurm_partition_jobs_{state}',
        command=['squeue'],
        command_args=['-p', '{partition}', '-t', '{state}', '-h'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Jobs in {state} state for partition {partition}'
    )
}

# Partition-based Job History Metrics (sacct by partition - historical)
JOB_PARTITION_HISTORY_SCHEMAS = {
    'by_state': CommandSchema(
        name='slurm_partition_jobs_{metric_name}',
        command=['sacct'],
        command_args=['-r', '{partition}', '-S', '{start_time}', '-E', 'now', '-s', '{state}', 
                     '--noheader', '-X', '-n'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Historical jobs in {state} state for partition {partition} since start_time'
    ),
    'total_submitted': CommandSchema(
        name='slurm_partition_jobs_total_submitted',
        command=['sacct'],
        command_args=['-r', '{partition}', '-S', '{start_time}', '-E', 'now', '-a', '-X', 
                     '-n', '--noheader'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Total jobs submitted to partition {partition} since start_time'
    )
}

# Partition-based Node Metrics (sinfo by partition)
NODE_PARTITION_SCHEMAS = {
    'total': CommandSchema(
        name='slurm_partition_nodes',
        command=['sinfo'],
        command_args=['-p', '{partition}', '-N', '-h'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Total nodes in partition {partition}'
    ),
    'by_state': CommandSchema(
        name='slurm_partition_nodes_{metric_name}',
        command=['sinfo'],
        command_args=['-p', '{partition}', '-t', '{state}', '-h', '-o', '%D'],
        parse_strategy=ParseStrategy.EXTRACT_NUMBER,
        description='Nodes in {state} state for partition {partition}'
    )
}

# Schema for getting partition list
PARTITION_LIST_SCHEMA = CommandSchema(
    name='partitions',
    command=['sinfo'],
    command_args=['-h', '-o', '%P'],
    parse_strategy=ParseStrategy.CUSTOM,
    description='List all partitions'
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
    Parse partition list from sinfo output.
    
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
    
    def collect_node_metrics(self) -> Dict[str, float]:
        """
        Collect node state metrics using sinfo.
        
        Returns:
            Dictionary of metric names to values
        """
        metrics = {}
        
        # Total nodes
        schema = NODE_SCHEMAS['total']
        metrics[schema.name] = self.execute_schema(schema)
        
        # Nodes by state
        schema = NODE_SCHEMAS['by_state']
        for sinfo_state, metric_suffix in NODE_STATES:
            metric_name = schema.name.format(metric_name=metric_suffix)
            value = self.execute_schema(schema, state=sinfo_state, 
                                       metric_name=metric_suffix)
            metrics[metric_name] = value
            logger.debug(f"{metric_name}: {value}")
        
        # Calculate total drain metric (all variants combined)
        drain_total = (
            metrics.get('slurm_nodes_drain', 0) +
            metrics.get('slurm_nodes_draining', 0) +
            metrics.get('slurm_nodes_drained', 0)
        )
        metrics['slurm_nodes_drain_total'] = drain_total
        
        return metrics
    
    def get_partitions(self) -> List[str]:
        """
        Get list of all partitions in the cluster.
        
        Returns:
            List of partition names
        """
        cmd = PARTITION_LIST_SCHEMA.build_command()
        output = self.run_command(cmd)
        partitions = parse_partition_list(output)
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
        Collect node metrics per partition.
        
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
            
            # Total nodes in partition
            schema = NODE_PARTITION_SCHEMAS['total']
            metrics[schema.name] = self.execute_schema(schema, partition=partition)
            
            # Nodes by state in partition
            schema = NODE_PARTITION_SCHEMAS['by_state']
            for sinfo_state, metric_suffix in NODE_STATES:
                metric_name = schema.name.format(metric_name=metric_suffix)
                value = self.execute_schema(schema, partition=partition, 
                                           state=sinfo_state, metric_name=metric_suffix)
                metrics[metric_name] = value
                logger.debug(f"{metric_name} [partition={partition}]: {value}")
            
            # Calculate total drain metric for partition
            drain_total = (
                metrics.get('slurm_partition_nodes_drain', 0) +
                metrics.get('slurm_partition_nodes_draining', 0) +
                metrics.get('slurm_partition_nodes_drained', 0)
            )
            metrics['slurm_partition_nodes_drain_total'] = drain_total
            
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