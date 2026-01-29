#!/usr/bin/env python3
"""
Integration tests for the Slurm Prometheus exporter.

Tests the full metric collection and export workflow.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from exporter.exporter import SlurmMetricsCollector
from prometheus_client.core import GaugeMetricFamily


class TestSlurmMetricsCollector:
    """Test the main metrics collector."""
    
    def test_init_default_reset_time(self):
        """Test initialization with default reset time."""
        collector = SlurmMetricsCollector()
        assert collector.reset_time == "24 hours ago"
        assert collector.executor is not None
    
    def test_init_custom_reset_time(self):
        """Test initialization with custom reset time."""
        collector = SlurmMetricsCollector(reset_time="7 days ago")
        assert collector.reset_time == "7 days ago"
    
    def test_init_custom_timeout(self):
        """Test initialization with custom timeout."""
        collector = SlurmMetricsCollector(timeout=60)
        assert collector.executor.timeout == 60
    
    @patch('exporter.exporter.SlurmCommandExecutor')
    def test_collect_includes_job_metrics(self, mock_executor_class):
        """Test that collect() yields job metrics."""
        mock_executor = Mock()
        mock_executor_class.return_value = mock_executor
        
        # Mock job queue metrics
        mock_executor.collect_job_queue_metrics.return_value = {
            'squeue_jobs': 5.0,
            'squeue_jobs_running': 2.0,
            'squeue_jobs_pending': 3.0
        }
        
        # Mock other methods to return empty
        mock_executor.collect_job_history_metrics.return_value = {}
        mock_executor.collect_node_metrics.return_value = {}
        mock_executor.collect_partition_job_metrics.return_value = {}
        mock_executor.collect_partition_node_metrics.return_value = {}
        mock_executor.collect_partition_job_history_metrics.return_value = {}
        
        collector = SlurmMetricsCollector()
        metrics = list(collector.collect())
        
        # Should have job metrics + duration + timestamp
        assert len(metrics) >= 3
        
        # Check that job metrics are present
        metric_names = [m.name for m in metrics if hasattr(m, 'name')]
        assert 'squeue_jobs' in metric_names
    
    @patch('exporter.exporter.SlurmCommandExecutor')
    def test_collect_includes_partition_metrics_with_labels(self, mock_executor_class):
        """Test that partition metrics include partition labels."""
        mock_executor = Mock()
        mock_executor_class.return_value = mock_executor
        
        # Mock empty non-partition metrics
        mock_executor.collect_job_queue_metrics.return_value = {}
        mock_executor.collect_job_history_metrics.return_value = {}
        mock_executor.collect_node_metrics.return_value = {}
        
        # Mock partition metrics
        mock_executor.collect_partition_job_metrics.return_value = {
            'hpc': {
                'squeue_partition_jobs': 5.0,
                'squeue_partition_jobs_running': 2.0
            },
            'htc': {
                'squeue_partition_jobs': 3.0,
                'squeue_partition_jobs_running': 1.0
            }
        }
        mock_executor.collect_partition_node_metrics.return_value = {}
        mock_executor.collect_partition_job_history_metrics.return_value = {}
        
        collector = SlurmMetricsCollector()
        metrics = list(collector.collect())
        
        # Find partition job metrics
        partition_metrics = [m for m in metrics if hasattr(m, 'name') and 'partition' in m.name]
        assert len(partition_metrics) > 0
        
        # Check that metrics have partition label
        for metric in partition_metrics:
            if hasattr(metric, '_labelnames'):
                assert 'partition' in metric._labelnames
    
    @patch('exporter.exporter.SlurmCommandExecutor')
    def test_collect_groups_partition_metrics_correctly(self, mock_executor_class):
        """Test that partition metrics are grouped by metric name."""
        mock_executor = Mock()
        mock_executor_class.return_value = mock_executor
        
        # Mock empty non-partition metrics
        mock_executor.collect_job_queue_metrics.return_value = {}
        mock_executor.collect_job_history_metrics.return_value = {}
        mock_executor.collect_node_metrics.return_value = {}
        mock_executor.collect_partition_node_metrics.return_value = {}
        
        # Mock partition job metrics with same metric name for different partitions
        mock_executor.collect_partition_job_metrics.return_value = {
            'hpc': {
                'squeue_partition_jobs_running': 2.0,
                'squeue_partition_jobs_pending': 1.0
            },
            'htc': {
                'squeue_partition_jobs_running': 3.0,
                'squeue_partition_jobs_pending': 2.0
            }
        }
        mock_executor.collect_partition_job_history_metrics.return_value = {}
        
        collector = SlurmMetricsCollector()
        metrics = list(collector.collect())
        
        # Count how many times 'squeue_partition_jobs_running' appears
        running_metrics = [m for m in metrics if hasattr(m, 'name') and m.name == 'squeue_partition_jobs_running']
        
        # Should appear only once (grouped), not once per partition
        assert len(running_metrics) == 1
    
    @patch('exporter.exporter.SlurmCommandExecutor')
    def test_collect_includes_cumulative_metrics(self, mock_executor_class):
        """Test that cumulative (total) metrics are included."""
        mock_executor = Mock()
        mock_executor_class.return_value = mock_executor
        
        # Mock empty current state metrics
        mock_executor.collect_job_queue_metrics.return_value = {}
        mock_executor.collect_node_metrics.return_value = {}
        mock_executor.collect_partition_job_metrics.return_value = {}
        mock_executor.collect_partition_node_metrics.return_value = {}
        
        # Mock cumulative metrics
        mock_executor.collect_job_history_metrics.return_value = {
            'sacct_jobs_total_completed': 100.0,
            'sacct_jobs_total_failed': 5.0,
            'sacct_jobs_total_submitted': 105.0
        }
        mock_executor.collect_partition_job_history_metrics.return_value = {}
        
        collector = SlurmMetricsCollector()
        metrics = list(collector.collect())
        
        # Check for total metrics
        metric_names = [m.name for m in metrics if hasattr(m, 'name')]
        assert 'sacct_jobs_total_completed' in metric_names
        assert 'sacct_jobs_total_failed' in metric_names
    
    @patch('exporter.exporter.SlurmCommandExecutor')
    def test_collect_includes_meta_metrics(self, mock_executor_class):
        """Test that meta metrics (duration, timestamp) are included."""
        mock_executor = Mock()
        mock_executor_class.return_value = mock_executor
        
        # Mock all methods to return empty
        mock_executor.collect_job_queue_metrics.return_value = {}
        mock_executor.collect_job_history_metrics.return_value = {}
        mock_executor.collect_node_metrics.return_value = {}
        mock_executor.collect_partition_job_metrics.return_value = {}
        mock_executor.collect_partition_node_metrics.return_value = {}
        mock_executor.collect_partition_job_history_metrics.return_value = {}
        
        collector = SlurmMetricsCollector()
        metrics = list(collector.collect())
        
        metric_names = [m.name for m in metrics if hasattr(m, 'name')]
        assert 'slurm_exporter_collect_duration_seconds' in metric_names
        assert 'slurm_exporter_last_collect_timestamp_seconds' in metric_names
    
    @patch('exporter.exporter.SlurmCommandExecutor')
    def test_collect_handles_exceptions(self, mock_executor_class):
        """Test that collect() handles exceptions gracefully."""
        mock_executor = Mock()
        mock_executor_class.return_value = mock_executor
        
        # Make one method raise an exception
        mock_executor.collect_job_queue_metrics.side_effect = Exception("Test error")
        
        collector = SlurmMetricsCollector()
        metrics = list(collector.collect())
        
        # Should still yield error metric
        metric_names = [m.name for m in metrics if hasattr(m, 'name')]
        assert 'slurm_exporter_errors_total' in metric_names
    
    @patch('exporter.exporter.SlurmCommandExecutor')
    def test_collect_partition_history_metrics_grouped(self, mock_executor_class):
        """Test that partition history metrics are properly grouped."""
        mock_executor = Mock()
        mock_executor_class.return_value = mock_executor
        
        # Mock empty non-history metrics
        mock_executor.collect_job_queue_metrics.return_value = {}
        mock_executor.collect_job_history_metrics.return_value = {}
        mock_executor.collect_node_metrics.return_value = {}
        mock_executor.collect_partition_job_metrics.return_value = {}
        mock_executor.collect_partition_node_metrics.return_value = {}
        
        # Mock partition history metrics
        mock_executor.collect_partition_job_history_metrics.return_value = {
            'hpc': {
                'sacct_partition_jobs_total_completed': 50.0,
                'sacct_partition_jobs_total_failed': 2.0
            },
            'htc': {
                'sacct_partition_jobs_total_completed': 30.0,
                'sacct_partition_jobs_total_failed': 1.0
            }
        }
        
        collector = SlurmMetricsCollector()
        metrics = list(collector.collect())
        
        # Find total_completed metrics
        completed_metrics = [m for m in metrics 
                           if hasattr(m, 'name') 
                           and m.name == 'sacct_partition_jobs_total_completed']
        
        # Should be grouped into one metric with multiple labels
        assert len(completed_metrics) == 1


class TestMetricValues:
    """Test that metric values are correctly formatted."""
    
    @patch('exporter.exporter.SlurmCommandExecutor')
    def test_metric_values_are_floats(self, mock_executor_class):
        """Test that all metric values are floats."""
        mock_executor = Mock()
        mock_executor_class.return_value = mock_executor
        
        mock_executor.collect_job_queue_metrics.return_value = {
            'squeue_jobs': 5.0,
            'squeue_jobs_running': 2.0
        }
        mock_executor.collect_job_history_metrics.return_value = {}
        mock_executor.collect_node_metrics.return_value = {}
        mock_executor.collect_partition_job_metrics.return_value = {}
        mock_executor.collect_partition_node_metrics.return_value = {}
        mock_executor.collect_partition_job_history_metrics.return_value = {}
        
        collector = SlurmMetricsCollector()
        metrics = list(collector.collect())
        
        # All samples should have float values
        for metric in metrics:
            if hasattr(metric, 'samples'):
                for sample in metric.samples:
                    assert isinstance(sample.value, (int, float))
    
    @patch('exporter.exporter.SlurmCommandExecutor')
    def test_metric_values_non_negative(self, mock_executor_class):
        """Test that metric values are non-negative."""
        mock_executor = Mock()
        mock_executor_class.return_value = mock_executor
        
        mock_executor.collect_job_queue_metrics.return_value = {
            'squeue_jobs': 5.0
        }
        mock_executor.collect_job_history_metrics.return_value = {}
        mock_executor.collect_node_metrics.return_value = {}
        mock_executor.collect_partition_job_metrics.return_value = {}
        mock_executor.collect_partition_node_metrics.return_value = {}
        mock_executor.collect_partition_job_history_metrics.return_value = {}
        
        collector = SlurmMetricsCollector()
        metrics = list(collector.collect())
        
        # All count/gauge values should be >= 0
        for metric in metrics:
            if hasattr(metric, 'samples'):
                for sample in metric.samples:
                    if 'duration' not in sample.name:  # Duration can be any positive value
                        assert sample.value >= 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
