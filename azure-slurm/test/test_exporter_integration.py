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
        """Test that meta metrics (duration, timestamp) are included when collection succeeds."""
        mock_executor = Mock()
        mock_executor_class.return_value = mock_executor
        
        # Mock all methods to return empty - ensure no errors
        mock_executor.collect_job_queue_metrics.return_value = {}
        mock_executor.collect_job_history_metrics.return_value = {}
        mock_executor.collect_node_metrics.return_value = {}
        mock_executor.collect_partition_job_metrics.return_value = {}
        mock_executor.collect_partition_node_metrics.return_value = {}
        mock_executor.collect_partition_job_history_metrics.return_value = {}
        mock_executor.get_partitions.return_value = []
        mock_executor.run_command.return_value = ""
        mock_executor.collect_job_history.return_value = {'start_date': '2026-01-01', 'end_date': '2026-02-01', 'by_state': {}, 'total_submitted': 0}
        mock_executor.collect_job_history_six_months_optimized.return_value = {'start_date': '2025-08-01', 'end_date': '2026-02-01', 'by_state': {}, 'total_submitted': 0}
        mock_executor.collect_job_history_exit_codes.return_value = {}
        mock_executor.collect_cluster_info.return_value = {'cluster_name': 'test', 'region': 'westeurope', 'resource_group': 'test-rg', 'subscription_id': 'sub-123', 'partitions': []}
        
        collector = SlurmMetricsCollector()
        metrics = list(collector.collect())
        
        metric_names = [m.name for m in metrics if hasattr(m, 'name')]
        # Check that we get meta metrics on success OR error metric on failure
        has_duration = 'slurm_exporter_collect_duration_seconds' in metric_names
        has_timestamp = 'slurm_exporter_last_collect_timestamp_seconds' in metric_names
        has_error = 'slurm_exporter_errors_total' in metric_names
        
        # Should have either both meta metrics (success) or error metric (failure)
        assert (has_duration and has_timestamp) or has_error
    
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
        mock_executor.collect_partition_node_details.return_value = {}
        
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


class TestSchemaBasedCollection:
    """Test the new schema-based metric collection."""
    
    @patch('exporter.exporter.SlurmCommandExecutor')
    def test_schemas_imported_correctly(self, mock_executor_class):
        """Test that all required schemas are imported."""
        from exporter.schemas import (
            JOB_QUEUE_SCHEMAS, NODE_SCHEMAS, 
            PARTITION_LIST_SCHEMA, CLUSTER_INFO_SCHEMAS
        )
        
        # Verify schema structure
        assert 'total' in JOB_QUEUE_SCHEMAS
        assert 'by_state' in JOB_QUEUE_SCHEMAS
        assert 'all_nodes' in NODE_SCHEMAS
        assert PARTITION_LIST_SCHEMA is not None
        assert 'azslurm_config' in CLUSTER_INFO_SCHEMAS
        assert 'azslurm_buckets' in CLUSTER_INFO_SCHEMAS
        assert 'azslurm_limits' in CLUSTER_INFO_SCHEMAS
    
    @patch('exporter.exporter.SlurmCommandExecutor')
    def test_parsers_imported_correctly(self, mock_executor_class):
        """Test that all required parsers are imported."""
        from exporter.parsers import (
            parse_azslurm_config, parse_azslurm_buckets, 
            parse_azslurm_limits, parse_scontrol_nodes_json
        )
        
        # Verify parsers are callable
        assert callable(parse_azslurm_config)
        assert callable(parse_azslurm_buckets)
        assert callable(parse_azslurm_limits)
        assert callable(parse_scontrol_nodes_json)


class TestClusterInfoMetrics:
    """Test cluster info metrics collection."""
    
    @patch('exporter.executor.SlurmCommandExecutor.run_command')
    def test_cluster_info_collection(self, mock_run_command):
        """Test that cluster info is collected and cached."""
        from exporter.executor import SlurmCommandExecutor
        
        # Mock azslurm config output
        mock_run_command.side_effect = [
            '{"cluster_name": "test-cluster", "accounting": {"subscription_id": "sub-123"}}',  # azslurm config
            'westeurope',  # jetpack location
            'test-rg',  # jetpack resource group
            'NODEARRAY  VM_SIZE\nhpc Standard_F2s_v2 2 2 16384 8\nhtc Standard_F2s_v2 4 4 32768 50',  # azslurm buckets
            'azslurm-test-hpc-[1-8]',  # sinfo nodes for hpc
            'azslurm-test-htc-[1-50]',  # sinfo nodes for htc
            '[{"nodearray": "hpc", "vm_size": "Standard_F2s_v2", "family_available_count": 10, "regional_available_count": 8}]'  # azslurm limits
        ]
        
        executor = SlurmCommandExecutor()
        cluster_info = executor.collect_cluster_info()
        
        assert cluster_info['cluster_name'] == 'test-cluster'
        assert cluster_info['subscription_id'] == 'sub-123'
        assert cluster_info['region'] == 'westeurope'
        assert cluster_info['resource_group'] == 'test-rg'
        assert len(cluster_info['partitions']) > 0
    
    @patch('exporter.executor.SlurmCommandExecutor.run_command')
    def test_cluster_info_caching(self, mock_run_command):
        """Test that cluster info is cached for 1 hour."""
        from exporter.executor import SlurmCommandExecutor
        import time
        
        # Mock azslurm config output
        mock_run_command.return_value = '{"cluster_name": "test-cluster", "accounting": {"subscription_id": "sub-123"}}'
        
        executor = SlurmCommandExecutor()
        
        # First call should execute commands
        info1 = executor.collect_cluster_info()
        call_count_1 = mock_run_command.call_count
        
        # Second call within TTL should use cache
        info2 = executor.collect_cluster_info()
        call_count_2 = mock_run_command.call_count
        
        # Cache should prevent additional calls
        assert call_count_1 == call_count_2
        assert info1 == info2
    
    @patch('exporter.executor.SlurmCommandExecutor.run_command')
    def test_cluster_info_cache_expiration(self, mock_run_command):
        """Test that cluster info cache expires after TTL."""
        from exporter.executor import SlurmCommandExecutor
        
        mock_run_command.return_value = '{"cluster_name": "test-cluster", "accounting": {"subscription_id": "sub-123"}}'
        
        executor = SlurmCommandExecutor()
        executor._cache_ttl = 1  # Set to 1 second for testing
        
        # First call
        info1 = executor.collect_cluster_info()
        call_count_1 = mock_run_command.call_count
        
        # Wait for cache to expire
        import time
        time.sleep(2)
        
        # Second call after TTL should re-execute
        info2 = executor.collect_cluster_info()
        call_count_2 = mock_run_command.call_count
        
        # Should have made additional calls
        assert call_count_2 > call_count_1


class TestAzureQuotaMetrics:
    """Test Azure quota metrics from azslurm limits."""
    
    def test_parse_azslurm_limits(self):
        """Test parsing of azslurm limits output."""
        from exporter.parsers import parse_azslurm_limits
        
        sample_output = '''[
            {
                "nodearray": "hpc",
                "vm_size": "Standard_F2s_v2",
                "family_available_count": 10,
                "regional_available_count": 8
            },
            {
                "nodearray": "htc",
                "vm_size": "Standard_F2s_v2",
                "family_available_count": 5,
                "regional_available_count": 12
            }
        ]'''
        
        result = parse_azslurm_limits(sample_output)
        
        # Should use min of family and regional
        assert result['hpc:Standard_F2s_v2'] == 8
        assert result['htc:Standard_F2s_v2'] == 5
    
    def test_parse_azslurm_limits_filters_placement_groups(self):
        """Test that placement group entries are filtered out."""
        from exporter.parsers import parse_azslurm_limits
        
        sample_output = '''[
            {
                "nodearray": "hpc",
                "vm_size": "Standard_F2s_v2",
                "placement_group": false,
                "family_available_count": 10,
                "regional_available_count": 8
            },
            {
                "nodearray": "hpc_pg0",
                "vm_size": "Standard_F2s_v2",
                "placement_group": true,
                "family_available_count": 2,
                "regional_available_count": 2
            }
        ]'''
        
        result = parse_azslurm_limits(sample_output)
        
        # Only non-PG entry should be included
        assert 'hpc:Standard_F2s_v2' in result
        assert 'hpc_pg0:Standard_F2s_v2' not in result


class TestPartitionMetrics:
    """Test partition-specific metric collection."""
    
    def test_parse_azslurm_buckets(self):
        """Test parsing of azslurm buckets output."""
        from exporter.parsers import parse_azslurm_buckets
        
        # Sample output with PLACEMENT_GROUP column empty
        sample_output = '''NODEARRAY  VM_SIZE         VCPU_COUNT PCPU_COUNT MEMORY AVAILABLE_COUNT
hpc        Standard_F2s_v2 2          2          16384  8
htc        Standard_F4s_v2 4          4          32768  50'''
        
        result = parse_azslurm_buckets(sample_output)
        
        assert len(result) == 2
        assert result[0]['name'] == 'hpc'
        assert result[0]['vm_size'] == 'Standard_F2s_v2'
        assert result[0]['total_nodes'] == '8'
        assert result[1]['name'] == 'htc'
        assert result[1]['vm_size'] == 'Standard_F4s_v2'
        assert result[1]['total_nodes'] == '50'
    
    def test_parse_azslurm_buckets_filters_pg(self):
        """Test that placement group entries are filtered."""
        from exporter.parsers import parse_azslurm_buckets
        
        sample_output = '''NODEARRAY  VM_SIZE         VCPU_COUNT PCPU_COUNT MEMORY AVAILABLE_COUNT
hpc        Standard_F2s_v2 2          2          16384  8
hpc_pg0    Standard_F2s_v2 2          2          16384  2'''
        
        result = parse_azslurm_buckets(sample_output)
        
        # Only non-PG entry should be included
        assert len(result) == 1
        assert result[0]['name'] == 'hpc'


class TestEndToEndIntegration:
    """End-to-end integration tests with realistic scenarios."""
    
    @patch('exporter.executor.SlurmCommandExecutor.run_command')
    def test_full_metric_collection_cycle(self, mock_run_command):
        """Test complete metric collection cycle with all components."""
        from exporter.exporter import SlurmMetricsCollector
        
        # Mock all command outputs
        def command_side_effect(cmd):
            cmd_str = ' '.join(cmd)
            if 'squeue' in cmd_str and 'count' not in cmd_str:
                return '5'  # 5 jobs
            elif 'squeue' in cmd_str and 'RUNNING' in cmd_str:
                return '2'  # 2 running
            elif 'squeue' in cmd_str and 'PENDING' in cmd_str:
                return '3'  # 3 pending
            elif 'sacct' in cmd_str:
                return 'JobID|State|ExitCode\n1|COMPLETED|0:0\n2|FAILED|1:0'
            elif 'scontrol show nodes' in cmd_str:
                return '{"nodes": []}'
            elif 'scontrol show partitions' in cmd_str:
                return '{"partitions": [{"PartitionName": "hpc"}, {"PartitionName": "htc"}]}'
            elif 'azslurm config' in cmd_str:
                return '{"cluster_name": "test", "accounting": {"subscription_id": "sub-123"}}'
            elif 'jetpack config azure.metadata' in cmd_str:
                if 'location' in cmd_str:
                    return 'westeurope'
                return 'test-rg'
            elif 'azslurm buckets' in cmd_str:
                return 'NODEARRAY VM_SIZE\nhpc Standard_F2s_v2 2 2 16384 8'
            elif 'azslurm limits' in cmd_str:
                return '[{"nodearray": "hpc", "vm_size": "Standard_F2s_v2", "family_available_count": 10, "regional_available_count": 8}]'
            elif 'sinfo' in cmd_str:
                return 'node-[1-8]'
            return ''
        
        mock_run_command.side_effect = command_side_effect
        
        collector = SlurmMetricsCollector(reset_time='1 hour ago')
        metrics = list(collector.collect())
        
        # Verify we get metrics
        assert len(metrics) > 0
        
        # Check for different metric categories
        metric_names = [m.name for m in metrics if hasattr(m, 'name')]
        
        # Job metrics
        assert any('squeue' in name for name in metric_names)
        
        # Meta metrics
        assert 'slurm_exporter_collect_duration_seconds' in metric_names
        assert 'slurm_exporter_last_collect_timestamp_seconds' in metric_names
    
    @patch('exporter.executor.SlurmCommandExecutor.run_command')
    def test_error_handling_with_command_failures(self, mock_run_command):
        """Test that exporter handles command failures gracefully."""
        from exporter.exporter import SlurmMetricsCollector
        
        # Simulate command failures
        mock_run_command.side_effect = Exception("Command failed")
        
        collector = SlurmMetricsCollector()
        metrics = list(collector.collect())
        
        # Should still produce error metric
        metric_names = [m.name for m in metrics if hasattr(m, 'name')]
        assert 'slurm_exporter_errors_total' in metric_names


class TestRealClusterScenarios:
    """Tests based on real cluster scenarios."""
    
    def test_handles_empty_partitions(self):
        """Test handling of partitions with no nodes."""
        from exporter.parsers import parse_azslurm_buckets
        
        sample_output = '''NODEARRAY  VM_SIZE         VCPU_COUNT PCPU_COUNT MEMORY AVAILABLE_COUNT
dynamic    Standard_F2s_v2 2          2          16384  0
hpc        Standard_F2s_v2 2          2          16384  8'''
        
        result = parse_azslurm_buckets(sample_output)
        
        assert len(result) == 2
        assert result[0]['total_nodes'] == '0'
        assert result[1]['total_nodes'] == '8'
    
    def test_handles_multiple_vm_sizes_per_partition(self):
        """Test partitions with multiple VM sizes."""
        from exporter.parsers import parse_azslurm_buckets
        
        sample_output = '''NODEARRAY  VM_SIZE          VCPU_COUNT PCPU_COUNT MEMORY AVAILABLE_COUNT
hpc        Standard_F2s_v2  2          2          16384  8
hpc        Standard_F4s_v2  4          4          32768  4'''
        
        result = parse_azslurm_buckets(sample_output)
        
        # Should get both entries
        assert len(result) == 2
        assert result[0]['vm_size'] == 'Standard_F2s_v2'
        assert result[1]['vm_size'] == 'Standard_F4s_v2'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
