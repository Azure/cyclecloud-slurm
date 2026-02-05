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
JOB_HISTORY_SCHEMAS = {
    'by_state': CommandSchema(
        name='sacct_jobs_total_{metric_name}',
        command=['sacct'],
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

# Job History Metrics - Last Month (sacct - updated daily)
JOB_HISTORY_ONE_MONTH_SCHEMAS = {
    'by_state': CommandSchema(
        name='sacct_jobs_total_one_month_{metric_name}',
        command=['sacct'],
        command_args=['-a', '-S', '{start_time}', '-E', 'now', '-s', '{state}', 
                     '--noheader', '-X', '-n'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Historical jobs in {state} state in last month'
    ),
    'total_submitted': CommandSchema(
        name='sacct_jobs_total_one_month_submitted',
        command=['sacct'],
        command_args=['-S', '{start_time}', '-E', 'now', '-a', '-X', 
                     '-n', '--noheader'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Total jobs submitted in last month'
    )
}


# ============================================================================
# NODE SCHEMAS
# ============================================================================

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

# Node states with priority hierarchy for mutually exclusive counting
# Each node is counted in exactly ONE state based on highest priority
# Priority is determined by order (first match wins)
# Format: (STATE_STRING, metric_suffix, priority)
NODE_STATE_PRIORITY = [
    ('POWERED_DOWN', 'powered_down', 1),      # Highest priority - node is off
    ('POWERING_UP', 'powering_up', 2),        # Node is starting
    ('DOWN', 'down', 3),                      # Node not responding
    ('FAIL', 'fail', 4),                      # Node has failed
    ('DRAINED', 'drained', 5),                # Node fully drained
    ('DRAINING', 'draining', 6),              # Node being drained  
    ('DRAIN', 'draining', 6),                 # Alias for draining
    ('MAINT', 'maint', 7),                    # Maintenance mode
    ('RESERVED', 'resv', 8),                  # Node reserved
    ('COMPLETING', 'completing', 9),          # Job completing
    ('ALLOCATED', 'alloc', 10),               # Node fully allocated
    ('MIXED', 'mixed', 11),                   # Node partially allocated
    ('IDLE', 'idle', 12),                     # Lowest priority - available
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

# Partition-based Job History Metrics - Last 6 Months
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

# Partition-based Job History Metrics - Last Week
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

# Partition-based Job History Metrics - Last Month
JOB_PARTITION_HISTORY_ONE_MONTH_SCHEMAS = {
    'by_state': CommandSchema(
        name='sacct_partition_jobs_total_one_month_{metric_name}',
        command=['sacct'],
        command_args=['-a', '-r', '{partition}', '-S', '{start_time}', '-E', 'now', '-s', '{state}', 
                     '--noheader', '-X', '-n'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Historical jobs in {state} state for partition {partition} in last month'
    ),
    'total_submitted': CommandSchema(
        name='sacct_partition_jobs_total_one_month_submitted',
        command=['sacct'],
        command_args=['-r', '{partition}', '-S', '{start_time}', '-E', 'now', '-a', '-X', 
                     '-n', '--noheader'],
        parse_strategy=ParseStrategy.COUNT_LINES,
        description='Total jobs submitted to partition {partition} in last month'
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
