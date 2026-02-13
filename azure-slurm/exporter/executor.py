#!/usr/bin/env python3
"""
Slurm command executor.

This module contains the SlurmCommandExecutor class that executes Slurm
commands and collects metrics.
"""

import subprocess
import logging
import time
from typing import Dict, List
from datetime import datetime, timedelta

try:
    from .schemas import (
        ParseStrategy, CommandSchema,
        JOB_QUEUE_SCHEMAS, JOB_QUEUE_STATES,
        JOB_HISTORY_STATES, JOB_HISTORY_STATES_WITH_EXIT_CODES,
        JOB_HISTORY_OPTIMIZED_SCHEMA,
        JOB_PARTITION_SCHEMAS,
        NODE_SCHEMAS, NODE_STATE_PRIORITY, NODE_STATES_EXCLUSIVE, NODE_FLAGS, NODE_PARTITION_SCHEMAS,
        PARTITION_LIST_SCHEMA
    )
    from .parsers import (
        parse_count_lines, parse_extract_number, parse_columns,
        parse_scontrol_partitions_json, parse_scontrol_nodes_json,
        parse_sacct_job_history
    )
except ImportError:
    from schemas import (
        ParseStrategy, CommandSchema,
        JOB_QUEUE_SCHEMAS, JOB_QUEUE_STATES,
        JOB_HISTORY_STATES, JOB_HISTORY_STATES_WITH_EXIT_CODES,
        JOB_HISTORY_OPTIMIZED_SCHEMA,
        JOB_PARTITION_SCHEMAS,
        NODE_SCHEMAS, NODE_STATE_PRIORITY, NODE_STATES_EXCLUSIVE, NODE_FLAGS, NODE_PARTITION_SCHEMAS,
        PARTITION_LIST_SCHEMA
    )
    from parsers import (
        parse_count_lines, parse_extract_number, parse_columns,
        parse_scontrol_partitions_json, parse_scontrol_nodes_json,
        parse_sacct_job_history
    )

logger = logging.getLogger('slurm-exporter.util')

# Map parse strategies to functions
PARSER_MAP = {
    ParseStrategy.COUNT_LINES: parse_count_lines,
    ParseStrategy.EXTRACT_NUMBER: parse_extract_number,
    ParseStrategy.PARSE_COLUMNS: parse_columns,
    ParseStrategy.PARSE_SCONTROL_NODES: parse_scontrol_nodes_json,
    ParseStrategy.PARSE_SCONTROL_PARTITIONS: parse_scontrol_partitions_json,
    ParseStrategy.PARSE_SACCT_JOB_HISTORY: parse_sacct_job_history,
}

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
        self._cache_ttl = 3600  # 1 hour in seconds
    
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
            elif schema.parse_strategy == ParseStrategy.PARSE_SCONTROL_NODES:
                # parse_scontrol_nodes_json can take optional partition parameter
                partition = kwargs.get('partition', None)
                return parser(output, partition)
            else:
                return parser(output)
        else:
            logger.error(f"Unknown parse strategy: {schema.parse_strategy}")
            return 0.0
    
    def execute_schema_dict(self, schema: CommandSchema, **kwargs) -> Dict[str, any]:
        """
        Execute a command based on its schema and return parsed dict result.
        Similar to execute_schema but for parsers that return complex structures.
        
        Args:
            schema: CommandSchema to execute
            **kwargs: Arguments to pass to schema.build_command() and custom_parser
            
        Returns:
            Parsed metric dictionary
        """
        # Build the command
        cmd = schema.build_command(**kwargs)
        
        # Run the command
        output = self.run_command(cmd)
        
        # Parse the output - custom_parser should accept output and other kwargs
        if schema.parse_strategy == ParseStrategy.CUSTOM and schema.custom_parser:
            # Pass kwargs like start_date to the parser
            return schema.custom_parser(output, **kwargs)
        elif schema.parse_strategy == ParseStrategy.PARSE_SACCT_JOB_HISTORY:
            # parse_sacct_job_history requires start_date parameter
            parser = PARSER_MAP[schema.parse_strategy]
            start_date = kwargs.get('start_date')
            return parser(output, start_date)
        else:
            logger.error(f"execute_schema_dict requires CUSTOM or PARSE_SACCT_JOB_HISTORY strategy")
            return {}
    
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
        Collect historical job metrics using sacct with optimized single-call approach.
        
        Args:
            start_time: Start time for historical queries (e.g., "24 hours ago")
            
        Returns:
            Dictionary of metric names to values
        """
        metrics = {}
        
        # Get comprehensive job data from single optimized call
        job_data = self.collect_job_history(start_time)
        
        # Extract by-state metrics
        for sacct_state, metric_suffix in JOB_HISTORY_STATES:
            metric_name = f'sacct_jobs_total_{metric_suffix}'
            # Get count from by_state dict, default to 0 if state not present
            state_lower = sacct_state.lower().replace('_', '_')
            value = float(job_data['by_state'].get(state_lower, 0))
            metrics[metric_name] = value
            logger.debug(f"{metric_name}: {value}")
        
        # Total submitted is already in the optimized response
        metrics['sacct_jobs_total_submitted'] = float(job_data['total_submitted'])
        
        return metrics
    
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
        Collect historical job metrics per partition using optimized single sacct call.
        
        Args:
            start_time: Start time for historical queries (e.g., "2026-01-01")
        
        Returns:
            Dictionary mapping partition names to metric dictionaries
            Format: {partition_name: {metric_name: value}}
        """
        # Use optimized single-call method
        job_data = self.collect_job_history(start_time)
        
        partition_metrics = {}
        
        # Extract partition-level data from optimized result
        for partition, state_counts in job_data.get('by_partition', {}).items():
            metrics = {}
            
            # Add state counts
            for state, count in state_counts.items():
                metric_name = f"sacct_partition_jobs_total_{state}"
                metrics[metric_name] = float(count)
                logger.debug(f"{metric_name} [partition={partition}]: {count}")
            
            # Calculate total submitted for this partition
            total_submitted = sum(state_counts.values())
            metrics['sacct_partition_jobs_total_submitted'] = float(total_submitted)
            
            partition_metrics[partition] = metrics
        
        return partition_metrics
    
    # ========================================================================
    # OPTIMIZED JOB HISTORY METHODS (Single sacct call per time period)
    # ========================================================================
    
    def collect_job_history(self, start_date: str) -> Dict[str, any]:
        """
        Collect job history metrics with a SINGLE sacct call.
        
        Args:
            start_date: Start date in YYYY-MM-DD format
        
        Returns:
            Dictionary with comprehensive metrics:
            {
                'start_date': str,
                'total_submitted': int,
                'by_state': {state: count},
                'by_partition': {partition: {state: count}},
                'by_state_exit_code': [(state, exit_code, count)],
                'by_partition_state_exit_code': {partition: [(state, exit_code, count)]}
            }
        """
        return self.execute_schema_dict(JOB_HISTORY_OPTIMIZED_SCHEMA, start_date=start_date)
    
    def collect_job_history_six_months_optimized(self) -> Dict[str, any]:
        """
        Collect all 6-month job history metrics with a SINGLE sacct call.
        
        This optimized version replaces multiple sacct calls with one,
        reducing overhead by ~89% (1 call vs 9+ calls).
        """
        days_back = 180
        start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
        return self.collect_job_history(start_date)
    
    def collect_job_history_one_month_optimized(self) -> Dict[str, any]:
        """Collect all 1-month job history metrics with a SINGLE sacct call."""
        days_back = 30
        start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
        return self.collect_job_history(start_date)
    
    def collect_job_history_one_week_optimized(self) -> Dict[str, any]:
        """Collect all 1-week job history metrics with a SINGLE sacct call."""
        days_back = 7
        start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
        return self.collect_job_history(start_date)
    
    def collect_cluster_info(self) -> Dict[str, any]:
        """
        Collect static cluster information (cached for 1 hour).
        
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
            'region': 'unknown',
            'resource_group': 'unknown',
            'subscription_id': 'unknown',
            'partitions': []
        }
        
        try:
            # Get cluster name and subscription from azslurm config
            config_output = self.run_command(['azslurm', 'config'])
            if config_output:
                config_data = json.loads(config_output)
                cluster_info['cluster_name'] = config_data.get('cluster_name', 'unknown')
                if 'accounting' in config_data and 'subscription_id' in config_data['accounting']:
                    cluster_info['subscription_id'] = config_data['accounting']['subscription_id']
            
            # Get Azure metadata (region, resource group) from jetpack
            try:
                region_output = self.run_command(['sudo', '/opt/cycle/jetpack/bin/jetpack', 'config', 'azure.metadata.compute.location'])
                if region_output and 'Error:' not in region_output:
                    cluster_info['region'] = region_output.strip()
                
                rg_output = self.run_command(['sudo', '/opt/cycle/jetpack/bin/jetpack', 'config', 'azure.metadata.compute.resourceGroupName'])
                if rg_output and 'Error:' not in rg_output:
                    cluster_info['resource_group'] = rg_output.strip()
            except Exception as e:
                logger.warning(f"Could not retrieve Azure metadata: {e}")
            
            # Get partition details from azslurm buckets
            buckets_output = self.run_command(['azslurm', 'buckets'])
            if buckets_output:
                lines = buckets_output.strip().split('\n')
                if len(lines) > 1:  # Skip header
                    # Track unique partition+vm_size combinations
                    seen_partition_vmsize = set()
                    # Cache node lists per partition to avoid redundant sinfo calls
                    partition_node_lists = {}
                    
                    for line in lines[1:]:
                        parts = line.split()
                        if not parts:
                            continue
                        
                        # First column is always NODEARRAY
                        nodearray = parts[0]
                        
                        # Skip placement group entries (contain _pg in nodearray name)
                        if '_pg' in nodearray or not nodearray:
                            continue
                        
                        # When PLACEMENT_GROUP is empty, VM_SIZE is at index 1
                        # When PLACEMENT_GROUP has a value, VM_SIZE is at index 2
                        # We can tell by checking if index 1 starts with "Standard_" AND doesn't contain '_pg'
                        # (placement groups end with _pg0, _pg1, etc.)
                        vm_size_index = 1 if (len(parts) > 1 and parts[1].startswith('Standard_') and '_pg' not in parts[1]) else 2
                        vm_size = parts[vm_size_index] if len(parts) > vm_size_index else 'unknown'
                        
                        # Skip duplicate partition+vm_size combinations
                        partition_vmsize_key = f"{nodearray}:{vm_size}"
                        if partition_vmsize_key in seen_partition_vmsize:
                            continue
                        seen_partition_vmsize.add(partition_vmsize_key)
                        
                        # Extract AVAILABLE_COUNT based on VM_SIZE position
                        # Columns after VM_SIZE: VCPU_COUNT, PCPU_COUNT, MEMORY, AVAILABLE_COUNT
                        # So AVAILABLE_COUNT is at vm_size_index + 4
                        available_count = '0'
                        if vm_size_index + 4 < len(parts):
                            available_count = parts[vm_size_index + 4]
                        
                        # Get node list from sinfo (cached per partition)
                        # Note: sinfo returns all nodes in partition regardless of VM size
                        # so all VM sizes in the same partition will have the same node_list
                        if nodearray not in partition_node_lists:
                            node_list = 'N/A'
                            sinfo_output = self.run_command(['sinfo', '-p', nodearray, '-h', '-o', '%N'])
                            if sinfo_output:
                                node_list = sinfo_output.strip()
                            partition_node_lists[nodearray] = node_list
                        else:
                            node_list = partition_node_lists[nodearray]
                        
                        cluster_info['partitions'].append({
                            'name': nodearray,
                            'vm_size': vm_size,
                            'total_nodes': available_count,
                            'node_list': node_list,
                            'available_azure_quota': '0'  # Will be filled in below
                        })
            
            # Get Azure quota limits from azslurm limits
            try:
                limits_output = self.run_command(['azslurm', 'limits'])
                if limits_output:
                    limits_data = json.loads(limits_output)
                    # Build a map of (nodearray, vm_size) -> min(family_available_count, regional_available_count)
                    quota_map = {}
                    for limit_entry in limits_data:
                        nodearray = limit_entry.get('nodearray', '')
                        vm_size = limit_entry.get('vm_size', '')
                        # Skip placement group entries
                        if not nodearray or limit_entry.get('placement_group'):
                            continue
                        
                        family_available = limit_entry.get('family_available_count', 0)
                        regional_available = limit_entry.get('regional_available_count', 0)
                        min_quota = min(family_available, regional_available)
                        
                        # Store quota per nodearray+vm_size combination
                        quota_key = f"{nodearray}:{vm_size}"
                        quota_map[quota_key] = min_quota
                    
                    # Update partitions with quota info
                    for partition in cluster_info['partitions']:
                        quota_key = f"{partition['name']}:{partition['vm_size']}"
                        partition['available_azure_quota'] = str(quota_map.get(quota_key, 0))
            except Exception as e:
                logger.warning(f"Could not retrieve Azure quota limits: {e}")
            
            # Cache the result
            self._cluster_info_cache = cluster_info
            self._cluster_info_cache_time = current_time
            logger.info(f"Cluster info cached: {cluster_info['cluster_name']}, {len(cluster_info['partitions'])} partitions")
            
        except Exception as e:
            logger.error(f"Error collecting cluster info: {e}")
        
        return cluster_info


