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

from schemas import (
    ParseStrategy, CommandSchema,
    JOB_QUEUE_SCHEMAS, JOB_QUEUE_STATES,
    JOB_HISTORY_SCHEMAS, JOB_HISTORY_STATES, JOB_HISTORY_STATES_WITH_EXIT_CODES,
    JOB_HISTORY_SIX_MONTHS_SCHEMAS, JOB_HISTORY_ONE_WEEK_SCHEMAS, JOB_HISTORY_ONE_MONTH_SCHEMAS,
    JOB_PARTITION_SCHEMAS, JOB_PARTITION_HISTORY_SCHEMAS,
    JOB_PARTITION_HISTORY_SIX_MONTHS_SCHEMAS, JOB_PARTITION_HISTORY_ONE_WEEK_SCHEMAS,
    JOB_PARTITION_HISTORY_ONE_MONTH_SCHEMAS,
    NODE_SCHEMAS, NODE_STATE_PRIORITY, NODE_STATES_EXCLUSIVE, NODE_FLAGS, NODE_PARTITION_SCHEMAS,
    PARTITION_LIST_SCHEMA
)
from parsers import (
    parse_count_lines, parse_extract_number, parse_columns,
    parse_scontrol_partitions_json, parse_scontrol_nodes_json
)
from optimized_parser import (
    collect_job_history_six_months_optimized,
    collect_job_history_one_month_optimized,
    collect_job_history_one_week_optimized
)

logger = logging.getLogger('slurm-exporter.util')

# Map parse strategies to functions
PARSER_MAP = {
    ParseStrategy.COUNT_LINES: parse_count_lines,
    ParseStrategy.EXTRACT_NUMBER: parse_extract_number,
    ParseStrategy.PARSE_COLUMNS: parse_columns,
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
    
    # ========================================================================
    # OPTIMIZED JOB HISTORY METHODS (Single sacct call per time period)
    # ========================================================================
    
    def collect_job_history_six_months_optimized(self) -> Dict[str, any]:
        """
        Collect all 6-month job history metrics with a SINGLE sacct call.
        
        This optimized version replaces multiple sacct calls with one,
        reducing overhead by ~89% (1 call vs 9+ calls).
        
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
        return collect_job_history_six_months_optimized(timeout=self.timeout)
    
    def collect_job_history_one_month_optimized(self) -> Dict[str, any]:
        """
        Collect all 1-month job history metrics with a SINGLE sacct call.
        
        Returns:
            Dictionary with comprehensive metrics (same structure as six_months)
        """
        return collect_job_history_one_month_optimized(timeout=self.timeout)
    
    def collect_job_history_one_week_optimized(self) -> Dict[str, any]:
        """
        Collect all 1-week job history metrics with a SINGLE sacct call.
        
        Returns:
            Dictionary with comprehensive metrics (same structure as six_months)
        """
        return collect_job_history_one_week_optimized(timeout=self.timeout)
    
    # ========================================================================
    # LEGACY JOB HISTORY METHODS (Multiple sacct calls - kept for compatibility)
    # ========================================================================
    
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
    
    def collect_job_history_one_month_metrics(self) -> Dict[str, any]:
        """
        Collect historical job metrics for the last month using sacct.
        These metrics are updated daily and provide a rolling 30-day window.
        
        Returns:
            Dictionary with 'start_date' and 'metrics' keys
        """
        from datetime import datetime, timedelta
        
        # Calculate date 30 days ago in YYYY-MM-DD format
        thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        
        metrics = {}
        
        # Jobs by historical state (last month)
        schema = JOB_HISTORY_ONE_MONTH_SCHEMAS['by_state']
        for sacct_state, metric_suffix in JOB_HISTORY_STATES:
            metric_name = schema.name.format(metric_name=metric_suffix)
            value = self.execute_schema(schema, start_time=thirty_days_ago, 
                                       state=sacct_state, metric_name=metric_suffix)
            metrics[metric_name] = value
            logger.debug(f"{metric_name}: {value}")
        
        # Total submitted (last month)
        schema = JOB_HISTORY_ONE_MONTH_SCHEMAS['total_submitted']
        metrics[schema.name] = self.execute_schema(schema, start_time=thirty_days_ago)
        
        return {
            'start_date': thirty_days_ago,
            'metrics': metrics
        }
    
    def collect_job_history_one_month_metrics_by_state(self) -> Dict[str, any]:
        """
        Collect historical job metrics for the last month, organized by state for labeling.
        
        Returns:
            Dictionary with 'start_date' and 'metrics_by_state' keys
        """
        from datetime import datetime, timedelta
        
        # Calculate date 30 days ago in YYYY-MM-DD format
        thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        
        metrics_by_state = {}
        
        # Jobs by historical state (last month)
        schema = JOB_HISTORY_ONE_MONTH_SCHEMAS['by_state']
        for sacct_state, metric_suffix in JOB_HISTORY_STATES:
            value = self.execute_schema(schema, start_time=thirty_days_ago, 
                                       state=sacct_state, metric_name=metric_suffix)
            metrics_by_state[metric_suffix] = value
            logger.debug(f"State {metric_suffix}: {value}")
        
        return {
            'start_date': thirty_days_ago,
            'metrics_by_state': metrics_by_state
        }
    
    def collect_job_history_one_month_metrics_by_state_and_exit_code(self) -> Dict[str, any]:
        """
        Collect historical job metrics for the last month with state and exit code labels.
        
        Returns:
            Dictionary with 'start_date' and 'metrics' keys where metrics is a list of (state, exit_code, count) tuples
        """
        from datetime import datetime, timedelta
        from collections import defaultdict
        
        # Calculate date 30 days ago in YYYY-MM-DD format
        thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        
        # Build sacct command to get state and exit codes
        states = ','.join(JOB_HISTORY_STATES_WITH_EXIT_CODES)
        cmd = ['sacct', '-a', '-S', thirty_days_ago, '-E', 'now', '-s', states,
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
            'start_date': thirty_days_ago,
            'metrics': metrics_list
        }
    
    def collect_partition_job_history_one_month_metrics(self) -> Dict[str, any]:
        """
        Collect historical job metrics per partition for the last month.
        These metrics are updated daily and provide a rolling 30-day window.
        
        Returns:
            Dictionary with 'start_date' and 'partition_metrics' keys
        """
        from datetime import datetime, timedelta
        
        # Calculate date 30 days ago in YYYY-MM-DD format
        thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        
        partition_metrics = {}
        partitions = self.get_partitions()
        
        if not partitions:
            logger.warning("No partitions found")
            return {
                'start_date': thirty_days_ago,
                'partition_metrics': partition_metrics
            }
        
        for partition in partitions:
            metrics = {}
            
            # Jobs by historical state in partition (last month)
            schema = JOB_PARTITION_HISTORY_ONE_MONTH_SCHEMAS['by_state']
            for sacct_state, metric_suffix in JOB_HISTORY_STATES:
                metric_name = schema.name.format(metric_name=metric_suffix)
                value = self.execute_schema(schema, partition=partition, 
                                           start_time=thirty_days_ago,
                                           state=sacct_state, metric_name=metric_suffix)
                metrics[metric_name] = value
                logger.debug(f"{metric_name} [partition={partition}]: {value}")
            
            # Total submitted to partition (last month)
            schema = JOB_PARTITION_HISTORY_ONE_MONTH_SCHEMAS['total_submitted']
            metrics[schema.name] = self.execute_schema(schema, partition=partition,
                                                       start_time=thirty_days_ago)
            
            partition_metrics[partition] = metrics
        
        return {
            'start_date': thirty_days_ago,
            'partition_metrics': partition_metrics
        }
    
    def collect_partition_job_history_one_month_metrics_by_state_and_exit_code(self) -> Dict[str, any]:
        """
        Collect historical job metrics per partition for the last month with state and exit code labels.
        
        Returns:
            Dictionary with 'start_date' and 'partition_metrics' keys where partition_metrics contains
            partition -> list of (state, exit_code, count) tuples
        """
        from datetime import datetime, timedelta
        from collections import defaultdict
        
        # Calculate date 30 days ago in YYYY-MM-DD format
        thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        
        partition_metrics = {}
        partitions = self.get_partitions()
        
        if not partitions:
            logger.warning("No partitions found")
            return {
                'start_date': thirty_days_ago,
                'partition_metrics': partition_metrics
            }
        
        for partition in partitions:
            # Build sacct command to get state and exit codes for this partition
            states = ','.join(JOB_HISTORY_STATES_WITH_EXIT_CODES)
            cmd = ['sacct', '-a', '-r', partition, '-S', thirty_days_ago, '-E', 'now', '-s', states,
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
            'start_date': thirty_days_ago,
            'partition_metrics': partition_metrics
        }
    
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
                        # We can tell by checking if index 1 starts with "Standard_" AND doesn't contain '_pg'
                        # (placement groups end with _pg0, _pg1, etc.)
                        vm_size_index = 1 if (len(parts) > 1 and parts[1].startswith('Standard_') and '_pg' not in parts[1]) else 2
                        vm_size = parts[vm_size_index] if len(parts) > vm_size_index else 'unknown'
                        
                        # Extract AVAILABLE_COUNT based on VM_SIZE position
                        # Columns after VM_SIZE: VCPU_COUNT, PCPU_COUNT, MEMORY, AVAILABLE_COUNT
                        # So AVAILABLE_COUNT is at vm_size_index + 4
                        available_count = '0'
                        if vm_size_index + 4 < len(parts):
                            available_count = parts[vm_size_index + 4]
                        
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


