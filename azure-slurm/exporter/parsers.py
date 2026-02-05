#!/usr/bin/env python3
"""
Parser functions for Slurm command output.

This module contains all parsing functions for converting Slurm command
output into metrics.
"""

import json
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger('slurm-exporter.util')


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


def parse_scontrol_nodes_json(output: str, partition: Optional[str] = None,
                              node_states: Optional[List] = None) -> Dict[str, float]:
    """
    Parse scontrol show nodes --json output and return node state metrics.
    Uses priority-based state assignment - each node counted in exactly ONE state.
    
    Args:
        output: JSON output from scontrol show nodes --json
        partition: Optional partition name to filter nodes by
        node_states: Ignored (kept for backwards compatibility)
        
    Returns:
        Dictionary of metric names to values (states are mutually exclusive)
    """
    from schemas import NODE_STATE_PRIORITY, NODE_STATES_EXCLUSIVE, NODE_FLAGS
    
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
        
        # Initialize state counters (mutually exclusive)
        state_counts = {suffix: 0 for suffix in NODE_STATES_EXCLUSIVE}
        
        # Initialize flag counters (independent tracking)
        flag_counts = {suffix: 0 for _, suffix in NODE_FLAGS}
        
        # Assign each node to exactly ONE state based on priority
        for node in nodes:
            node_states_list = node.get('state', [])
            if not isinstance(node_states_list, list):
                node_states_list = [node_states_list] if node_states_list else []
            
            # Convert to uppercase for matching
            node_states_upper = [s.upper() for s in node_states_list]
            
            # Find highest priority state for this node
            assigned_state = None
            highest_priority = 999
            
            for state_str, metric_suffix, priority in NODE_STATE_PRIORITY:
                if state_str in node_states_upper and priority < highest_priority:
                    assigned_state = metric_suffix
                    highest_priority = priority
            
            # Count this node in its assigned state
            if assigned_state:
                state_counts[assigned_state] += 1
            else:
                # Fallback to idle if no recognized state
                state_counts['idle'] += 1
            
            # Track flags independently
            for flag_str, flag_suffix in NODE_FLAGS:
                if flag_str in node_states_upper:
                    flag_counts[flag_suffix] += 1
        
        # Build metrics dictionary
        metrics = {}
        prefix = 'scontrol_partition_nodes' if partition else 'scontrol_nodes'
        
        # Total nodes
        metrics[prefix] = float(total_nodes)
        
        # Add mutually exclusive state metrics
        for state_suffix in NODE_STATES_EXCLUSIVE:
            metric_name = f"{prefix}_{state_suffix}"
            metrics[metric_name] = float(state_counts[state_suffix])
        
        # Add flag metrics (independent counters)
        for flag_suffix in flag_counts:
            metric_name = f"{prefix}_{flag_suffix}"
            metrics[metric_name] = float(flag_counts[flag_suffix])
        
        return metrics
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse scontrol JSON output: {e}")
        return {'scontrol_nodes': 0.0}
    except Exception as e:
        logger.error(f"Error processing scontrol node data: {e}")
        return {'scontrol_nodes': 0.0}
