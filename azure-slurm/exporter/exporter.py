#!/usr/bin/env python3
"""
Azure Slurm Prometheus Exporter

Exports Slurm cluster metrics in Prometheus format using schema-based
command execution.
"""

import sys
import time
import logging
import argparse
from typing import Optional

from prometheus_client import start_http_server, REGISTRY
from prometheus_client.core import GaugeMetricFamily

# Import our schema-based utilities
try:
    from .executor import SlurmCommandExecutor
except ImportError:
    # Fallback for when run as a script rather than a package
    from executor import SlurmCommandExecutor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('slurm-exporter')


# Slurm exit code to reason mapping
SLURM_EXIT_CODE_MAPPING = {
    "0:0": "",
    "1:0": "General failure",
    "2:0": "Misuse of shell built-in",
    "126:0": "Command invoked cannot execute",
    "127:0": "Command not found",
    "128:0": "Invalid argument to exit",
    "129:0": "SIGHUP",
    "130:0": "SIGINT - Ctrl+C",
    "131:0": "SIGQUIT",
    "134:0": "SIGABRT",
    "137:0": "SIGKILL - Force killed",
    "139:0": "SIGSEGV - Segfault",
    "141:0": "SIGPIPE",
    "143:0": "SIGTERM - Terminated",
    "152:0": "SIGXCPU - CPU limit",
    "153:0": "SIGXFSZ - File size limit",
}


def get_exit_code_reason(exit_code: str) -> str:
    """Convert Slurm exit code to human-readable reason."""
    return SLURM_EXIT_CODE_MAPPING.get(exit_code, "Other")


class SlurmMetricsCollector:
    """Collects Slurm metrics using schema-based command execution."""
    
    def __init__(self, reset_time: Optional[str] = None, timeout: int = 30):
        """
        Initialize the Slurm metrics collector.
        
        Args:
            reset_time: Time to use for cumulative metrics (e.g., "24 hours ago")
            timeout: Command execution timeout in seconds
        """
        self.reset_time = reset_time or "24 hours ago"
        self.executor = SlurmCommandExecutor(timeout=timeout)
        logger.info(f"Initialized SlurmMetricsCollector with reset_time={self.reset_time}")
    
    def collect(self):
        """
        Collect all metrics and yield them in Prometheus format.
        
        This method is called by the Prometheus client library.
        """
        start_time = time.time()
        
        try:
            # Collect job queue metrics (current state)
            logger.debug("Collecting job queue metrics...")
            job_metrics = self.executor.collect_job_queue_metrics()
            for metric_name, value in job_metrics.items():
                gauge = GaugeMetricFamily(
                    metric_name,
                    f'Slurm job queue metric: {metric_name}',
                    labels=[]
                )
                gauge.add_metric([], value)
                yield gauge
            
            # Collect per-job node allocation metrics
            logger.debug("Collecting per-job node allocation metrics...")
            try:
                jobs_with_nodes_output = self.executor.run_command(
                    ['squeue', '-h', '-o', '%i|%j|%P|%t|%D', '--states=RUNNING']
                )
                
                # Create single gauge family for all jobs
                job_nodes_gauge = GaugeMetricFamily(
                    'squeue_job_nodes_allocated',
                    'Number of nodes allocated/requested per job',
                    labels=['job_id', 'job_name', 'partition', 'state']
                )
                
                for line in jobs_with_nodes_output.strip().split('\n'):
                    if not line:
                        continue
                    parts = line.split('|')
                    if len(parts) != 5:
                        continue
                    job_id, job_name, partition, state, num_nodes = parts
                    try:
                        job_nodes_gauge.add_metric(
                            [job_id, job_name, partition, state],
                            float(num_nodes)
                        )
                    except (ValueError, IndexError):
                        logger.warning(f"Failed to parse job node allocation: {line}")
                        continue
                
                yield job_nodes_gauge
            except Exception as e:
                logger.error(f"Failed to collect per-job node metrics: {e}")
            
            # Collect job history metrics (cumulative)
            logger.debug("Collecting job history metrics...")
            job_history_metrics = self.executor.collect_job_history_metrics(self.reset_time)
            for metric_name, value in job_history_metrics.items():
                gauge = GaugeMetricFamily(
                    metric_name,
                    f'Slurm cumulative job metric: {metric_name}',
                    labels=[]
                )
                gauge.add_metric([], value)
                yield gauge
            
            # Collect node metrics
            logger.debug("Collecting node metrics...")
            node_metrics = self.executor.collect_node_metrics()
            for metric_name, value in node_metrics.items():
                gauge = GaugeMetricFamily(
                    metric_name,
                    f'Slurm node metric: {metric_name}',
                    labels=[]
                )
                gauge.add_metric([], value)
                yield gauge
            
            # Collect partition-based job metrics
            logger.debug("Collecting partition job metrics...")
            partition_job_metrics = self.executor.collect_partition_job_metrics()
            # Group metrics by metric name across all partitions
            metrics_by_name = {}
            for partition, metrics in partition_job_metrics.items():
                for metric_name, value in metrics.items():
                    if metric_name not in metrics_by_name:
                        metrics_by_name[metric_name] = []
                    metrics_by_name[metric_name].append((partition, value))
            
            # Yield one gauge per metric name with all partitions
            for metric_name, partition_values in metrics_by_name.items():
                gauge = GaugeMetricFamily(
                    metric_name,
                    f'Slurm partition job metric: {metric_name}',
                    labels=['partition']
                )
                for partition, value in partition_values:
                    gauge.add_metric([partition], value)
                yield gauge
            
            # Collect partition-based node metrics
            logger.debug("Collecting partition node metrics...")
            partition_node_metrics = self.executor.collect_partition_node_metrics()
            
            # Only yield the total count metric (scontrol_partition_nodes), not the per-state ones
            # The per-state metrics will come from the detailed collection below
            total_gauge = GaugeMetricFamily(
                'scontrol_partition_nodes',
                'Total nodes per partition',
                labels=['partition']
            )
            for partition, metrics in partition_node_metrics.items():
                if 'scontrol_partition_nodes' in metrics:
                    total_gauge.add_metric([partition], metrics['scontrol_partition_nodes'])
            yield total_gauge
            
            # Now collect and yield detailed metrics with nodelist and reason labels for each state
            logger.debug("Collecting partition node metrics with details...")
            partition_node_details = self.executor.collect_partition_node_details()
            
            # Group by metric name (state) and collect all partition/nodelist/reason combinations
            metrics_by_state = {}
            
            # First, get all partitions from the detailed data
            all_partitions = set(partition_node_details.keys())
            
            # Import NODE_STATES_EXCLUSIVE to ensure we export all states
            try:
                from .schemas import NODE_STATES_EXCLUSIVE
            except ImportError:
                from schemas import NODE_STATES_EXCLUSIVE
            
            # Initialize all state metrics with empty lists
            for state in NODE_STATES_EXCLUSIVE:
                metric_name = f'scontrol_partition_nodes_{state}'
                metrics_by_state[metric_name] = []
            
            # Populate metrics with actual data
            for partition, state_details in partition_node_details.items():
                for state, details_list in state_details.items():
                    metric_name = f'scontrol_partition_nodes_{state}'
                    
                    # Add each nodelist/reason combination for this partition/state
                    for detail in details_list:
                        nodelist = detail['nodelist']
                        reason = detail['reason'] if detail['reason'] else 'none'
                        count = detail['count']
                        metrics_by_state[metric_name].append((partition, nodelist, reason, count))
            
            # For each partition, ensure all states are represented (add 0-count entries for missing states)
            for partition in all_partitions:
                for state in NODE_STATES_EXCLUSIVE:
                    metric_name = f'scontrol_partition_nodes_{state}'
                    # Check if this partition already has this state
                    has_state = any(p == partition for p, _, _, _ in metrics_by_state[metric_name])
                    if not has_state:
                        # Add a zero-count entry for this partition/state
                        metrics_by_state[metric_name].append((partition, 'none', 'none', 0))
            
            # Yield one gauge per metric name (state) with partition, nodelist, and reason labels
            for metric_name, metric_values in metrics_by_state.items():
                gauge = GaugeMetricFamily(
                    metric_name,
                    f'Slurm partition node metric with nodelist and reason: {metric_name}',
                    labels=['partition', 'nodelist', 'reason']
                )
                for partition, nodelist, reason, count in metric_values:
                    gauge.add_metric([partition, nodelist, reason], float(count))
                yield gauge
            
            # Collect partition-based job history metrics (cumulative)
            logger.debug("Collecting partition job history metrics...")
            partition_job_history_metrics = self.executor.collect_partition_job_history_metrics(self.reset_time)
            # Group metrics by metric name across all partitions
            metrics_by_name = {}
            for partition, metrics in partition_job_history_metrics.items():
                for metric_name, value in metrics.items():
                    if metric_name not in metrics_by_name:
                        metrics_by_name[metric_name] = []
                    metrics_by_name[metric_name].append((partition, value))
            
            # Yield one gauge per metric name with all partitions
            for metric_name, partition_values in metrics_by_name.items():
                gauge = GaugeMetricFamily(
                    metric_name,
                    f'Slurm partition cumulative job metric: {metric_name}',
                    labels=['partition']
                )
                for partition, value in partition_values:
                    gauge.add_metric([partition], value)
                yield gauge
            
            # Collect job history metrics for last 6 months (OPTIMIZED - single sacct call)
            logger.debug("Collecting 6-month job history metrics (optimized)...")
            six_months_data = self.executor.collect_job_history_six_months_optimized()
            start_date = six_months_data['start_date']
            
            # Total submitted
            gauge = GaugeMetricFamily(
                'sacct_jobs_total_six_months_submitted',
                'Slurm 6-month rolling job metric: submitted',
                labels=['start_date']
            )
            gauge.add_metric([start_date], float(six_months_data['total_submitted']))
            yield gauge
            
            # Individual state metrics
            for state, count in six_months_data['by_state'].items():
                gauge = GaugeMetricFamily(
                    f'sacct_jobs_total_six_months_{state}',
                    f'Slurm 6-month rolling job metric: {state}',
                    labels=['start_date']
                )
                gauge.add_metric([start_date], float(count))
                yield gauge
            
            # Metric with state labels
            jobs_by_state_gauge = GaugeMetricFamily(
                'sacct_jobs_total_six_months_by_state',
                'Slurm 6-month rolling job metric by state',
                labels=['state', 'start_date']
            )
            for state, count in six_months_data['by_state'].items():
                jobs_by_state_gauge.add_metric([state, start_date], float(count))
            yield jobs_by_state_gauge
            
            # Metric with state and exit code labels
            jobs_by_state_exit_gauge = GaugeMetricFamily(
                'sacct_jobs_total_six_months_by_state_exit_code',
                'Slurm 6-month rolling job metric by state and exit code',
                labels=['state', 'exit_code', 'reason', 'start_date']
            )
            for state, exit_code, count in six_months_data['by_state_exit_code']:
                reason = get_exit_code_reason(exit_code)
                jobs_by_state_exit_gauge.add_metric([state, exit_code, reason, start_date], float(count))
            yield jobs_by_state_exit_gauge
            
            # Partition-based 6-month metrics (from same optimized call)
            logger.debug("Collecting partition 6-month job history metrics (from optimized data)...")
            # Group metrics by metric name across all partitions
            metrics_by_name = {}
            for partition, states in six_months_data['by_partition'].items():
                # Total submitted for partition
                partition_total = sum(states.values())
                metric_name = 'sacct_partition_jobs_total_six_months_submitted'
                if metric_name not in metrics_by_name:
                    metrics_by_name[metric_name] = []
                metrics_by_name[metric_name].append((partition, partition_total))
                
                # Individual states for partition
                for state, count in states.items():
                    metric_name = f'sacct_partition_jobs_total_six_months_{state}'
                    if metric_name not in metrics_by_name:
                        metrics_by_name[metric_name] = []
                    metrics_by_name[metric_name].append((partition, count))
            
            # Yield one gauge per metric name with all partitions
            for metric_name, partition_values in metrics_by_name.items():
                gauge = GaugeMetricFamily(
                    metric_name,
                    f'Slurm partition 6-month rolling job metric: {metric_name}',
                    labels=['partition', 'start_date']
                )
                for partition, value in partition_values:
                    gauge.add_metric([partition, start_date], float(value))
                yield gauge
            
            # Partition 6-month job history with state and exit code labels
            partition_jobs_by_state_exit_gauge = GaugeMetricFamily(
                'sacct_partition_jobs_total_six_months_by_state_exit_code',
                'Slurm partition 6-month rolling job metric by state and exit code',
                labels=['partition', 'state', 'exit_code', 'reason', 'start_date']
            )
            for partition, metrics_list in six_months_data['by_partition_state_exit_code'].items():
                for state, exit_code, count in metrics_list:
                    reason = get_exit_code_reason(exit_code)
                    partition_jobs_by_state_exit_gauge.add_metric([partition, state, exit_code, reason, start_date], float(count))
            yield partition_jobs_by_state_exit_gauge
            
            # Collect job history metrics for last week (OPTIMIZED - single sacct call)
            logger.debug("Collecting 1-week job history metrics (optimized)...")
            week_data = self.executor.collect_job_history_one_week_optimized()
            week_start_date = week_data['start_date']
            
            # Total submitted
            gauge = GaugeMetricFamily(
                'sacct_jobs_total_one_week_submitted',
                'Slurm 1-week rolling job metric: submitted',
                labels=['start_date']
            )
            gauge.add_metric([week_start_date], float(week_data['total_submitted']))
            yield gauge
            
            # Individual state metrics
            for state, count in week_data['by_state'].items():
                gauge = GaugeMetricFamily(
                    f'sacct_jobs_total_one_week_{state}',
                    f'Slurm 1-week rolling job metric: {state}',
                    labels=['start_date']
                )
                gauge.add_metric([week_start_date], float(count))
                yield gauge
            
            # Metric with state labels
            jobs_week_by_state_gauge = GaugeMetricFamily(
                'sacct_jobs_total_one_week_by_state',
                'Slurm 1-week rolling job metric by state',
                labels=['state', 'start_date']
            )
            for state, count in week_data['by_state'].items():
                jobs_week_by_state_gauge.add_metric([state, week_start_date], float(count))
            yield jobs_week_by_state_gauge
            
            # Metric with state and exit code labels
            jobs_week_by_state_exit_gauge = GaugeMetricFamily(
                'sacct_jobs_total_one_week_by_state_exit_code',
                'Slurm 1-week rolling job metric by state and exit code',
                labels=['state', 'exit_code', 'reason', 'start_date']
            )
            for state, exit_code, count in week_data['by_state_exit_code']:
                reason = get_exit_code_reason(exit_code)
                jobs_week_by_state_exit_gauge.add_metric([state, exit_code, reason, week_start_date], float(count))
            yield jobs_week_by_state_exit_gauge
            
            # Partition-based 1-week metrics (from same optimized call)
            logger.debug("Collecting partition 1-week job history metrics (from optimized data)...")
            metrics_by_name = {}
            for partition, states in week_data['by_partition'].items():
                # Total submitted for partition
                partition_total = sum(states.values())
                metric_name = 'sacct_partition_jobs_total_one_week_submitted'
                if metric_name not in metrics_by_name:
                    metrics_by_name[metric_name] = []
                metrics_by_name[metric_name].append((partition, partition_total))
                
                # Individual states for partition
                for state, count in states.items():
                    metric_name = f'sacct_partition_jobs_total_one_week_{state}'
                    if metric_name not in metrics_by_name:
                        metrics_by_name[metric_name] = []
                    metrics_by_name[metric_name].append((partition, count))
            
            # Yield one gauge per metric name with all partitions
            for metric_name, partition_values in metrics_by_name.items():
                gauge = GaugeMetricFamily(
                    metric_name,
                    f'Slurm partition 1-week rolling job metric: {metric_name}',
                    labels=['partition', 'start_date']
                )
                for partition, value in partition_values:
                    gauge.add_metric([partition, week_start_date], float(value))
                yield gauge
            
            # Partition 1-week job history with state and exit code labels
            partition_jobs_week_by_state_exit_gauge = GaugeMetricFamily(
                'sacct_partition_jobs_total_one_week_by_state_exit_code',
                'Slurm partition 1-week rolling job metric by state and exit code',
                labels=['partition', 'state', 'exit_code', 'reason', 'start_date']
            )
            for partition, metrics_list in week_data['by_partition_state_exit_code'].items():
                for state, exit_code, count in metrics_list:
                    reason = get_exit_code_reason(exit_code)
                    partition_jobs_week_by_state_exit_gauge.add_metric([partition, state, exit_code, reason, week_start_date], float(count))
            yield partition_jobs_week_by_state_exit_gauge
            
            # Collect job history metrics for last month (updated daily)
            logger.debug("Collecting 1-month job history metrics...")
            # Collect job history metrics for last month (OPTIMIZED - single sacct call)
            logger.debug("Collecting 1-month job history metrics (optimized)...")
            month_data = self.executor.collect_job_history_one_month_optimized()
            month_start_date = month_data['start_date']
            
            # Total submitted
            gauge = GaugeMetricFamily(
                'sacct_jobs_total_one_month_submitted',
                'Slurm 30-day rolling job metric: submitted',
                labels=['start_date']
            )
            gauge.add_metric([month_start_date], float(month_data['total_submitted']))
            yield gauge
            
            # Individual state metrics
            for state, count in month_data['by_state'].items():
                gauge = GaugeMetricFamily(
                    f'sacct_jobs_total_one_month_{state}',
                    f'Slurm 30-day rolling job metric: {state}',
                    labels=['start_date']
                )
                gauge.add_metric([month_start_date], float(count))
                yield gauge
            
            # Metric with state labels
            jobs_1m_by_state_gauge = GaugeMetricFamily(
                'sacct_jobs_total_one_month_by_state',
                'Slurm 30-day rolling job metric by state',
                labels=['state', 'start_date']
            )
            for state, count in month_data['by_state'].items():
                jobs_1m_by_state_gauge.add_metric([state, month_start_date], float(count))
            yield jobs_1m_by_state_gauge
            
            # Metric with state and exit code labels
            jobs_1m_by_state_exit_gauge = GaugeMetricFamily(
                'sacct_jobs_total_one_month_by_state_exit_code',
                'Slurm 30-day rolling job metric by state and exit code',
                labels=['state', 'exit_code', 'reason', 'start_date']
            )
            for state, exit_code, count in month_data['by_state_exit_code']:
                reason = get_exit_code_reason(exit_code)
                jobs_1m_by_state_exit_gauge.add_metric([state, exit_code, reason, month_start_date], float(count))
            yield jobs_1m_by_state_exit_gauge
            
            # Partition-based 1-month metrics (from same optimized call)
            logger.debug("Collecting partition 1-month job history metrics (from optimized data)...")
            metrics_by_name = {}
            for partition, states in month_data['by_partition'].items():
                # Total submitted for partition
                partition_total = sum(states.values())
                metric_name = 'sacct_partition_jobs_total_one_month_submitted'
                if metric_name not in metrics_by_name:
                    metrics_by_name[metric_name] = []
                metrics_by_name[metric_name].append((partition, partition_total))
                
                # Individual states for partition
                for state, count in states.items():
                    metric_name = f'sacct_partition_jobs_total_one_month_{state}'
                    if metric_name not in metrics_by_name:
                        metrics_by_name[metric_name] = []
                    metrics_by_name[metric_name].append((partition, count))
            
            # Yield one gauge per metric name with all partitions
            for metric_name, partition_values in metrics_by_name.items():
                gauge = GaugeMetricFamily(
                    metric_name,
                    f'Slurm partition 30-day rolling job metric: {metric_name}',
                    labels=['partition', 'start_date']
                )
                for partition, value in partition_values:
                    gauge.add_metric([partition, month_start_date], float(value))
                yield gauge
            
            # Partition 1-month job history with state and exit code labels
            partition_jobs_1m_by_state_exit_gauge = GaugeMetricFamily(
                'sacct_partition_jobs_total_one_month_by_state_exit_code',
                'Slurm partition 30-day rolling job metric by state and exit code',
                labels=['partition', 'state', 'exit_code', 'reason', 'start_date']
            )
            for partition, metrics_list in month_data['by_partition_state_exit_code'].items():
                for state, exit_code, count in metrics_list:
                    reason = get_exit_code_reason(exit_code)
                    partition_jobs_1m_by_state_exit_gauge.add_metric([partition, state, exit_code, reason, month_start_date], float(count))
            yield partition_jobs_1m_by_state_exit_gauge
            
            # Collect cluster info (cached for 1 hour)
            logger.debug("Collecting cluster info...")
            cluster_info = self.executor.collect_cluster_info()
            
            # Cluster name info metric (always 1, just provides cluster name as label)
            cluster_name_gauge = GaugeMetricFamily(
                'azslurm_cluster_info',
                'Static cluster information from azslurm',
                labels=['cluster_name', 'region', 'resource_group', 'subscription_id']
            )
            cluster_name_gauge.add_metric(
                [cluster_info['cluster_name'], cluster_info['region'], 
                 cluster_info['resource_group'], cluster_info['subscription_id']], 
                1
            )
            yield cluster_name_gauge
            
            # Partition info metric with labels
            partition_info_gauge = GaugeMetricFamily(
                'azslurm_partition_info',
                'Static partition information from azslurm with VM size and node details',
                labels=['partition', 'vm_size', 'node_list', 'available_azure_quota']
            )
            for partition in cluster_info.get('partitions', []):
                partition_info_gauge.add_metric(
                    [partition['name'], partition['vm_size'], partition['node_list'], 
                     partition.get('available_azure_quota', '0')],
                    float(partition['total_nodes'])
                )
            yield partition_info_gauge
            
            # Export collection duration
            duration = time.time() - start_time
            duration_gauge = GaugeMetricFamily(
                'slurm_exporter_collect_duration_seconds',
                'Time spent collecting Slurm metrics',
                labels=[]
            )
            duration_gauge.add_metric([], duration)
            yield duration_gauge
            
            # Export last successful collection timestamp
            timestamp_gauge = GaugeMetricFamily(
                'slurm_exporter_last_collect_timestamp_seconds',
                'Timestamp of last successful metric collection',
                labels=[]
            )
            timestamp_gauge.add_metric([], time.time())
            yield timestamp_gauge
            
            logger.info(f"Metrics collection completed in {duration:.2f}s")
            
        except Exception as e:
            logger.error(f"Error collecting metrics: {e}", exc_info=True)
            # Export error metric
            error_gauge = GaugeMetricFamily(
                'slurm_exporter_errors_total',
                'Total number of collection errors',
                labels=[]
            )
            error_gauge.add_metric([], 1)
            yield error_gauge


def main():
    """Main entry point for the exporter."""
    parser = argparse.ArgumentParser(
        description='Azure Slurm Prometheus Exporter'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=9500,
        help='Port to expose metrics on (default: 9500)'
    )
    parser.add_argument(
        '--reset-time',
        type=str,
        default='24 hours ago',
        help='Reset time for cumulative metrics (default: "24 hours ago")'
    )
    parser.add_argument(
        '--timeout',
        type=int,
        default=30,
        help='Command execution timeout in seconds (default: 30)'
    )
    parser.add_argument(
        '--log-level',
        type=str,
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='Logging level (default: INFO)'
    )
    
    args = parser.parse_args()
    
    # Set logging level
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    
    logger.info(f"Starting Azure Slurm Exporter on port {args.port}")
    logger.info(f"Reset time for cumulative metrics: {args.reset_time}")
    logger.info(f"Command timeout: {args.timeout}s")
    
    # Register the collector
    collector = SlurmMetricsCollector(
        reset_time=args.reset_time,
        timeout=args.timeout
    )
    REGISTRY.register(collector)
    
    # Start HTTP server
    start_http_server(args.port)
    logger.info(f"Exporter started successfully. Metrics available at http://localhost:{args.port}/metrics")
    
    # Keep the script running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Exporter stopped by user")
        sys.exit(0)


if __name__ == '__main__':
    main()