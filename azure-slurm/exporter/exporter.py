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
    from .util import SlurmCommandExecutor
except ImportError:
    # Fallback for when run as a script rather than a package
    from util import SlurmCommandExecutor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('slurm-exporter')


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
            # Group metrics by metric name across all partitions
            metrics_by_name = {}
            for partition, metrics in partition_node_metrics.items():
                for metric_name, value in metrics.items():
                    if metric_name not in metrics_by_name:
                        metrics_by_name[metric_name] = []
                    metrics_by_name[metric_name].append((partition, value))
            
            # Yield one gauge per metric name with all partitions
            for metric_name, partition_values in metrics_by_name.items():
                gauge = GaugeMetricFamily(
                    metric_name,
                    f'Slurm partition node metric: {metric_name}',
                    labels=['partition']
                )
                for partition, value in partition_values:
                    gauge.add_metric([partition], value)
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
            
            # Collect job history metrics for last 6 months (updated daily)
            logger.debug("Collecting 6-month job history metrics...")
            job_history_six_months_data = self.executor.collect_job_history_six_months_metrics()
            start_date = job_history_six_months_data['start_date']
            for metric_name, value in job_history_six_months_data['metrics'].items():
                gauge = GaugeMetricFamily(
                    metric_name,
                    f'Slurm 6-month rolling job metric: {metric_name}',
                    labels=['start_date']
                )
                gauge.add_metric([start_date], value)
                yield gauge
            
            # Collect 6-month job history with state labels
            logger.debug("Collecting 6-month job history by state...")
            job_history_six_months_by_state = self.executor.collect_job_history_six_months_metrics_by_state()
            start_date_state = job_history_six_months_by_state['start_date']
            jobs_by_state_gauge = GaugeMetricFamily(
                'sacct_jobs_total_six_months_by_state',
                'Slurm 6-month rolling job metric by state',
                labels=['state', 'start_date']
            )
            for state, value in job_history_six_months_by_state['metrics_by_state'].items():
                jobs_by_state_gauge.add_metric([state, start_date_state], value)
            yield jobs_by_state_gauge
            
            # Collect 6-month job history with state and exit code labels
            logger.debug("Collecting 6-month job history by state and exit code...")
            job_history_six_months_exit = self.executor.collect_job_history_six_months_metrics_by_state_and_exit_code()
            start_date_exit = job_history_six_months_exit['start_date']
            jobs_by_state_exit_gauge = GaugeMetricFamily(
                'sacct_jobs_total_six_months_by_state_exit_code',
                'Slurm 6-month rolling job metric by state and exit code',
                labels=['state', 'exit_code', 'start_date']
            )
            for state, exit_code, count in job_history_six_months_exit['metrics']:
                jobs_by_state_exit_gauge.add_metric([state, exit_code, start_date_exit], float(count))
            yield jobs_by_state_exit_gauge
            
            # Collect partition-based job history metrics for last 6 months (updated daily)
            logger.debug("Collecting partition 6-month job history metrics...")
            partition_job_history_six_months_data = self.executor.collect_partition_job_history_six_months_metrics()
            partition_start_date = partition_job_history_six_months_data['start_date']
            # Group metrics by metric name across all partitions
            metrics_by_name = {}
            for partition, metrics in partition_job_history_six_months_data['partition_metrics'].items():
                for metric_name, value in metrics.items():
                    if metric_name not in metrics_by_name:
                        metrics_by_name[metric_name] = []
                    metrics_by_name[metric_name].append((partition, value))
            
            # Yield one gauge per metric name with all partitions
            for metric_name, partition_values in metrics_by_name.items():
                gauge = GaugeMetricFamily(
                    metric_name,
                    f'Slurm partition 6-month rolling job metric: {metric_name}',
                    labels=['partition', 'start_date']
                )
                for partition, value in partition_values:
                    gauge.add_metric([partition, partition_start_date], value)
                yield gauge
            
            # Collect partition 6-month job history with state and exit code labels
            logger.debug("Collecting partition 6-month job history by state and exit code...")
            partition_job_history_six_months_exit = self.executor.collect_partition_job_history_six_months_metrics_by_state_and_exit_code()
            partition_start_date_exit = partition_job_history_six_months_exit['start_date']
            partition_jobs_by_state_exit_gauge = GaugeMetricFamily(
                'sacct_partition_jobs_total_six_months_by_state_exit_code',
                'Slurm partition 6-month rolling job metric by state and exit code',
                labels=['partition', 'state', 'exit_code', 'start_date']
            )
            for partition, metrics_list in partition_job_history_six_months_exit['partition_metrics'].items():
                for state, exit_code, count in metrics_list:
                    partition_jobs_by_state_exit_gauge.add_metric([partition, state, exit_code, partition_start_date_exit], float(count))
            yield partition_jobs_by_state_exit_gauge
            
            # Collect job history metrics for last week (updated daily)
            logger.debug("Collecting 1-week job history metrics...")
            job_history_one_week_data = self.executor.collect_job_history_one_week_metrics()
            week_start_date = job_history_one_week_data['start_date']
            for metric_name, value in job_history_one_week_data['metrics'].items():
                gauge = GaugeMetricFamily(
                    metric_name,
                    f'Slurm 1-week rolling job metric: {metric_name}',
                    labels=['start_date']
                )
                gauge.add_metric([week_start_date], value)
                yield gauge
            
            # Collect 1-week job history with state labels
            logger.debug("Collecting 1-week job history by state...")
            job_history_one_week_by_state = self.executor.collect_job_history_one_week_metrics_by_state()
            week_start_date_state = job_history_one_week_by_state['start_date']
            jobs_week_by_state_gauge = GaugeMetricFamily(
                'sacct_jobs_total_one_week_by_state',
                'Slurm 1-week rolling job metric by state',
                labels=['state', 'start_date']
            )
            for state, value in job_history_one_week_by_state['metrics_by_state'].items():
                jobs_week_by_state_gauge.add_metric([state, week_start_date_state], value)
            yield jobs_week_by_state_gauge
            
            # Collect 1-week job history with state and exit code labels
            logger.debug("Collecting 1-week job history by state and exit code...")
            job_history_one_week_exit = self.executor.collect_job_history_one_week_metrics_by_state_and_exit_code()
            week_start_date_exit = job_history_one_week_exit['start_date']
            jobs_week_by_state_exit_gauge = GaugeMetricFamily(
                'sacct_jobs_total_one_week_by_state_exit_code',
                'Slurm 1-week rolling job metric by state and exit code',
                labels=['state', 'exit_code', 'start_date']
            )
            for state, exit_code, count in job_history_one_week_exit['metrics']:
                jobs_week_by_state_exit_gauge.add_metric([state, exit_code, week_start_date_exit], float(count))
            yield jobs_week_by_state_exit_gauge
            
            # Collect partition-based job history metrics for last week (updated daily)
            logger.debug("Collecting partition 1-week job history metrics...")
            partition_job_history_one_week_data = self.executor.collect_partition_job_history_one_week_metrics()
            partition_week_start_date = partition_job_history_one_week_data['start_date']
            # Group metrics by metric name across all partitions
            metrics_by_name = {}
            for partition, metrics in partition_job_history_one_week_data['partition_metrics'].items():
                for metric_name, value in metrics.items():
                    if metric_name not in metrics_by_name:
                        metrics_by_name[metric_name] = []
                    metrics_by_name[metric_name].append((partition, value))
            
            # Yield one gauge per metric name with all partitions
            for metric_name, partition_values in metrics_by_name.items():
                gauge = GaugeMetricFamily(
                    metric_name,
                    f'Slurm partition 1-week rolling job metric: {metric_name}',
                    labels=['partition', 'start_date']
                )
                for partition, value in partition_values:
                    gauge.add_metric([partition, partition_week_start_date], value)
                yield gauge
            
            # Collect partition 1-week job history with state and exit code labels
            logger.debug("Collecting partition 1-week job history by state and exit code...")
            partition_job_history_one_week_exit = self.executor.collect_partition_job_history_one_week_metrics_by_state_and_exit_code()
            partition_week_start_date_exit = partition_job_history_one_week_exit['start_date']
            partition_jobs_week_by_state_exit_gauge = GaugeMetricFamily(
                'sacct_partition_jobs_total_one_week_by_state_exit_code',
                'Slurm partition 1-week rolling job metric by state and exit code',
                labels=['partition', 'state', 'exit_code', 'start_date']
            )
            for partition, metrics_list in partition_job_history_one_week_exit['partition_metrics'].items():
                for state, exit_code, count in metrics_list:
                    partition_jobs_week_by_state_exit_gauge.add_metric([partition, state, exit_code, partition_week_start_date_exit], float(count))
            yield partition_jobs_week_by_state_exit_gauge
            
            # Collect job history metrics for last 24 hours (updated hourly)
            logger.debug("Collecting 24-hour job history metrics...")
            job_history_24_hours_data = self.executor.collect_job_history_24_hours_metrics()
            hours_start_datetime = job_history_24_hours_data['start_datetime']
            for metric_name, value in job_history_24_hours_data['metrics'].items():
                gauge = GaugeMetricFamily(
                    metric_name,
                    f'Slurm 24-hour rolling job metric: {metric_name}',
                    labels=['start_datetime']
                )
                gauge.add_metric([hours_start_datetime], value)
                yield gauge
            
            # Collect 24-hour job history with state labels
            logger.debug("Collecting 24-hour job history by state...")
            job_history_24_hours_by_state = self.executor.collect_job_history_24_hours_metrics_by_state()
            hours_start_datetime_state = job_history_24_hours_by_state['start_datetime']
            jobs_24h_by_state_gauge = GaugeMetricFamily(
                'sacct_jobs_total_24_hours_by_state',
                'Slurm 24-hour rolling job metric by state',
                labels=['state', 'start_datetime']
            )
            for state, value in job_history_24_hours_by_state['metrics_by_state'].items():
                jobs_24h_by_state_gauge.add_metric([state, hours_start_datetime_state], value)
            yield jobs_24h_by_state_gauge
            
            # Collect 24-hour job history with state and exit code labels
            logger.debug("Collecting 24-hour job history by state and exit code...")
            job_history_24_hours_exit = self.executor.collect_job_history_24_hours_metrics_by_state_and_exit_code()
            hours_start_datetime_exit = job_history_24_hours_exit['start_datetime']
            jobs_24h_by_state_exit_gauge = GaugeMetricFamily(
                'sacct_jobs_total_24_hours_by_state_exit_code',
                'Slurm 24-hour rolling job metric by state and exit code',
                labels=['state', 'exit_code', 'start_datetime']
            )
            for state, exit_code, count in job_history_24_hours_exit['metrics']:
                jobs_24h_by_state_exit_gauge.add_metric([state, exit_code, hours_start_datetime_exit], float(count))
            yield jobs_24h_by_state_exit_gauge
            
            # Collect partition-based job history metrics for last 24 hours (updated hourly)
            logger.debug("Collecting partition 24-hour job history metrics...")
            partition_job_history_24_hours_data = self.executor.collect_partition_job_history_24_hours_metrics()
            partition_hours_start_datetime = partition_job_history_24_hours_data['start_datetime']
            # Group metrics by metric name across all partitions
            metrics_by_name = {}
            for partition, metrics in partition_job_history_24_hours_data['partition_metrics'].items():
                for metric_name, value in metrics.items():
                    if metric_name not in metrics_by_name:
                        metrics_by_name[metric_name] = []
                    metrics_by_name[metric_name].append((partition, value))
            
            # Yield one gauge per metric name with all partitions
            for metric_name, partition_values in metrics_by_name.items():
                gauge = GaugeMetricFamily(
                    metric_name,
                    f'Slurm partition 24-hour rolling job metric: {metric_name}',
                    labels=['partition', 'start_datetime']
                )
                for partition, value in partition_values:
                    gauge.add_metric([partition, partition_hours_start_datetime], value)
                yield gauge
            
            # Collect partition 24-hour job history with state and exit code labels
            logger.debug("Collecting partition 24-hour job history by state and exit code...")
            partition_job_history_24_hours_exit = self.executor.collect_partition_job_history_24_hours_metrics_by_state_and_exit_code()
            partition_hours_start_datetime_exit = partition_job_history_24_hours_exit['start_datetime']
            partition_jobs_24h_by_state_exit_gauge = GaugeMetricFamily(
                'sacct_partition_jobs_total_24_hours_by_state_exit_code',
                'Slurm partition 24-hour rolling job metric by state and exit code',
                labels=['partition', 'state', 'exit_code', 'start_datetime']
            )
            for partition, metrics_list in partition_job_history_24_hours_exit['partition_metrics'].items():
                for state, exit_code, count in metrics_list:
                    partition_jobs_24h_by_state_exit_gauge.add_metric([partition, state, exit_code, partition_hours_start_datetime_exit], float(count))
            yield partition_jobs_24h_by_state_exit_gauge
            
            # Collect cluster info (cached for 24 hours)
            logger.debug("Collecting cluster info...")
            cluster_info = self.executor.collect_cluster_info()
            
            # Cluster name info metric (always 1, just provides cluster name as label)
            cluster_name_gauge = GaugeMetricFamily(
                'azslurm_cluster_info',
                'Static cluster information from azslurm',
                labels=['cluster_name']
            )
            cluster_name_gauge.add_metric([cluster_info['cluster_name']], 1)
            yield cluster_name_gauge
            
            # Partition info metric with labels
            partition_info_gauge = GaugeMetricFamily(
                'azslurm_partition_info',
                'Static partition information from azslurm with VM size and node details',
                labels=['partition', 'vm_size', 'node_list']
            )
            for partition in cluster_info.get('partitions', []):
                partition_info_gauge.add_metric(
                    [partition['name'], partition['vm_size'], partition['node_list']],
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