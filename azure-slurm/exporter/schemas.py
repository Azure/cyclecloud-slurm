#!/usr/bin/env python3
"""
Schema definitions for Slurm command execution.

This module contains all CommandSchema definitions and state lists for
Slurm metrics collection.
"""

from typing import Dict, List, Callable, Any, Optional
from dataclasses import dataclass
from enum import Enum


class ParseStrategy(Enum):
    """Parsing strategy for command output."""
    COUNT_LINES = "count_lines"           # Count non-empty lines
    EXTRACT_NUMBER = "extract_number"     # Extract a number from output
    PARSE_COLUMNS = "parse_columns"       # Parse columnar output
    PARSE_SACCT_JOB_HISTORY = "parse_sacct_job_history"  # Parse sacct job history output
    PARSE_SCONTROL_NODES = "parse_scontrol_nodes"        # Parse scontrol nodes JSON output
    PARSE_SCONTROL_PARTITIONS = "parse_scontrol_partitions"  # Parse scontrol partitions JSON output
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
# JOB QUEUE SCHEMAS
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


# ============================================================================
# JOB HISTORY SCHEMAS
# ============================================================================

# Job History Metrics (sacct - historical)

# States to query from sacct for job history
JOB_HISTORY_STATES = [
    ('COMPLETED', 'completed'),
    ('FAILED', 'failed'),
    ('TIMEOUT', 'timeout'),
    ('CANCELLED', 'cancelled'),
    ('NODE_FAIL', 'node_failed'),
    ('OUT_OF_MEMORY', 'out_of_memory')
]

# States to query for exit code analysis
JOB_HISTORY_STATES_WITH_EXIT_CODES = [
    'FAILED', 'TIMEOUT', 'NODE_FAIL', 'OUT_OF_MEMORY', 'CANCELLED'
]

# Job History Metrics - OPTIMIZED (single sacct call)
# Returns comprehensive metrics dict instead of single float
JOB_HISTORY_OPTIMIZED_SCHEMA = CommandSchema(
    name='sacct_job_history_optimized',
    command=['sacct'],
    command_args=['-a', '-S', '{start_date}', '-E', 'now',
                  '-o', 'JobID,JobName,Partition,State,ExitCode',
                  '--parsable2', '-n', '-X'],
    parse_strategy=ParseStrategy.PARSE_SACCT_JOB_HISTORY,
    description='Optimized job history collection (single sacct call)'
)


# ============================================================================
# NODE SCHEMAS
# ============================================================================

# Node State Metrics (scontrol show nodes --json)
NODE_SCHEMAS = {
    'all_nodes': CommandSchema(
        name='scontrol_nodes',
        command=['scontrol', 'show', 'nodes', '--json'],
        command_args=[],
        parse_strategy=ParseStrategy.PARSE_SCONTROL_NODES,
        description='All node information from scontrol in JSON format'
    )
}

# Node states with priority hierarchy for mutually exclusive counting
# Each node is counted in exactly ONE state based on highest priority
# Priority is determined by order (first match wins)
# Format: (STATE_STRING, metric_suffix, priority)
NODE_STATE_PRIORITY = [
    ('POWERED_DOWN', 'powered_down', 1),      # Highest priority - node is off
    ('POWERING_UP', 'powering_up', 2),        # Node is starting
    ('DOWN', 'down', 3),                      # Node not responding
    ('FAIL', 'fail', 4),                      # Node has failed
    ('DRAINED', 'drained', 5),                # Node fully drained (DRAINED state)
    ('DRAINING', 'draining', 6),              # Node being drained (ALLOCATED+DRAIN)
    ('DRAIN', 'drained', 7),                  # Node drained but not allocated
    ('MAINT', 'maint', 8),                    # Maintenance mode
    ('RESERVED', 'resv', 9),                  # Node reserved
    ('COMPLETING', 'completing', 10),         # Job completing
    ('ALLOCATED', 'alloc', 11),               # Node fully allocated
    ('MIXED', 'mixed', 12),                   # Node partially allocated
    ('IDLE', 'idle', 13),                     # Lowest priority - available
]

# Metric suffixes for the final mutually exclusive states
# These states are guaranteed to be non-overlapping
NODE_STATES_EXCLUSIVE = [
    'powered_down',
    'powering_up', 
    'down',
    'fail',
    'drained',
    'draining',
    'maint',
    'resv',
    'completing',
    'alloc',
    'mixed',
    'idle'
]

# Flag states that can be tracked separately (not mutually exclusive)
# These track additional node properties independent of primary state
NODE_FLAGS = [
    ('CLOUD', 'cloud'),  # Azure auto-scaling capable node
]


# ============================================================================
# PARTITION SCHEMAS
# ============================================================================

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

# Partition-based Node Metrics (scontrol show nodes --json)
NODE_PARTITION_SCHEMAS = {
    'all_nodes': CommandSchema(
        name='scontrol_partition_nodes',
        command=['scontrol', 'show', 'nodes', '--json'],
        command_args=[],
        parse_strategy=ParseStrategy.PARSE_SCONTROL_NODES,
        description='All node information from scontrol in JSON format (filtered by partition in parser)'
    )
}

# Schema for getting partition list
PARTITION_LIST_SCHEMA = CommandSchema(
    name='partitions',
    command=['scontrol', 'show', 'partitions', '--json'],
    command_args=[],
    parse_strategy=ParseStrategy.PARSE_SCONTROL_PARTITIONS,
    description='List all partitions from scontrol'
)

# Cluster info schemas
CLUSTER_INFO_SCHEMAS = {
    'azslurm_config': CommandSchema(
        name='azslurm_config',
        command=['azslurm', 'config'],
        command_args=[],
        parse_strategy=ParseStrategy.CUSTOM,
        description='Get cluster configuration from azslurm'
    ),
    'jetpack_location': CommandSchema(
        name='azure_location',
        command=['sudo', '/opt/cycle/jetpack/bin/jetpack', 'config', 'azure.metadata.compute.location'],
        command_args=[],
        parse_strategy=ParseStrategy.CUSTOM,
        description='Get Azure region from jetpack'
    ),
    'jetpack_resource_group': CommandSchema(
        name='azure_resource_group',
        command=['sudo', '/opt/cycle/jetpack/bin/jetpack', 'config', 'azure.metadata.compute.resourceGroupName'],
        command_args=[],
        parse_strategy=ParseStrategy.CUSTOM,
        description='Get Azure resource group from jetpack'
    ),
    'azslurm_buckets': CommandSchema(
        name='azslurm_buckets',
        command=['azslurm', 'buckets'],
        command_args=[],
        parse_strategy=ParseStrategy.CUSTOM,
        description='Get partition details from azslurm buckets'
    ),
    'azslurm_limits': CommandSchema(
        name='azslurm_limits',
        command=['azslurm', 'limits'],
        command_args=[],
        parse_strategy=ParseStrategy.CUSTOM,
        description='Get Azure quota limits from azslurm'
    ),
    'sinfo_nodes': CommandSchema(
        name='sinfo_nodes',
        command=['sinfo'],
        command_args=['-p', '{partition}', '-h', '-o', '%N'],
        parse_strategy=ParseStrategy.CUSTOM,
        description='Get node list for partition from sinfo'
    )
}

