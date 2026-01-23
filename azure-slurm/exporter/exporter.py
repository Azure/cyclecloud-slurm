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
from .util import SlurmCommandExecutor

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