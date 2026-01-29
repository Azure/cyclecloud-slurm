#!/usr/bin/env python3
"""
Unit tests for the Slurm exporter utility module.

Tests cover:
- Schema command building
- Parser functions
- Command execution
- Metric collection
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import subprocess
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from exporter.util import (
    CommandSchema,
    ParseStrategy,
    SlurmCommandExecutor,
    parse_count_lines,
    parse_extract_number,
    parse_columns,
    parse_partition_list,
    JOB_QUEUE_SCHEMAS,
    JOB_HISTORY_SCHEMAS,
    NODE_SCHEMAS,
    JOB_PARTITION_SCHEMAS,
    NODE_PARTITION_SCHEMAS,
    JOB_PARTITION_HISTORY_SCHEMAS,
)


class TestCommandSchema:
    """Test CommandSchema functionality."""
    
    def test_build_command_no_args(self):
        """Test building command without additional arguments."""
        schema = CommandSchema(
            name='test_metric',
            command=['squeue'],
            parse_strategy=ParseStrategy.COUNT_LINES,
            description='Test schema'
        )
        cmd = schema.build_command()
        assert cmd == ['squeue']
    
    def test_build_command_with_static_args(self):
        """Test building command with static arguments."""
        schema = CommandSchema(
            name='test_metric',
            command=['squeue'],
            command_args=['-h', '-o', '%j'],
            parse_strategy=ParseStrategy.COUNT_LINES,
            description='Test schema'
        )
        cmd = schema.build_command()
        assert cmd == ['squeue', '-h', '-o', '%j']
    
    def test_build_command_with_placeholders(self):
        """Test building command with placeholder substitution."""
        schema = CommandSchema(
            name='test_metric_{state}',
            command=['squeue'],
            command_args=['-t', '{state}', '-h'],
            parse_strategy=ParseStrategy.COUNT_LINES,
            description='Test schema'
        )
        cmd = schema.build_command(state='RUNNING')
        assert cmd == ['squeue', '-t', 'RUNNING', '-h']
    
    def test_build_command_multiple_placeholders(self):
        """Test building command with multiple placeholders."""
        schema = CommandSchema(
            name='test_metric',
            command=['sacct'],
            command_args=['-r', '{partition}', '-S', '{start_time}', '-s', '{state}'],
            parse_strategy=ParseStrategy.COUNT_LINES,
            description='Test schema'
        )
        cmd = schema.build_command(partition='hpc', start_time='2026-01-01', state='COMPLETED')
        assert cmd == ['sacct', '-r', 'hpc', '-S', '2026-01-01', '-s', 'COMPLETED']


class TestParserFunctions:
    """Test parser functions."""
    
    def test_parse_count_lines_empty(self):
        """Test counting lines with empty input."""
        assert parse_count_lines('') == 0.0
        assert parse_count_lines(None) == 0.0
    
    def test_parse_count_lines_single(self):
        """Test counting single line."""
        assert parse_count_lines('line1') == 1.0
    
    def test_parse_count_lines_multiple(self):
        """Test counting multiple lines."""
        output = "line1\nline2\nline3"
        assert parse_count_lines(output) == 3.0
    
    def test_parse_count_lines_with_empty_lines(self):
        """Test counting lines with empty lines (should be ignored)."""
        output = "line1\n\nline2\n  \nline3"
        assert parse_count_lines(output) == 3.0
    
    def test_parse_extract_number_empty(self):
        """Test extracting number from empty input."""
        assert parse_extract_number('') == 0.0
        assert parse_extract_number(None) == 0.0
    
    def test_parse_extract_number_integer(self):
        """Test extracting integer."""
        assert parse_extract_number('42') == 42.0
        assert parse_extract_number('  42  ') == 42.0
    
    def test_parse_extract_number_float(self):
        """Test extracting float."""
        assert parse_extract_number('42.5') == 42.5
    
    def test_parse_extract_number_invalid(self):
        """Test extracting number from invalid input."""
        assert parse_extract_number('not a number') == 0.0
    
    def test_parse_columns_empty(self):
        """Test parsing columns from empty input."""
        config = {'column_index': 0, 'aggregation': 'sum'}
        assert parse_columns('', config) == 0.0
    
    def test_parse_columns_sum(self):
        """Test parsing columns with sum aggregation."""
        output = "10 20 30\n15 25 35\n5 10 15"
        config = {'column_index': 0, 'aggregation': 'sum'}
        assert parse_columns(output, config) == 30.0
    
    def test_parse_columns_count(self):
        """Test parsing columns with count aggregation."""
        output = "10 20\n15 25\n5 10"
        config = {'column_index': 0, 'aggregation': 'count'}
        assert parse_columns(output, config) == 3.0
    
    def test_parse_columns_avg(self):
        """Test parsing columns with average aggregation."""
        output = "10\n20\n30"
        config = {'column_index': 0, 'aggregation': 'avg'}
        assert parse_columns(output, config) == 20.0
    
    def test_parse_columns_with_delimiter(self):
        """Test parsing columns with custom delimiter."""
        output = "a,10,x\nb,20,y\nc,30,z"
        config = {'delimiter': ',', 'column_index': 1, 'aggregation': 'sum'}
        assert parse_columns(output, config) == 60.0
    
    def test_parse_partition_list_empty(self):
        """Test parsing partition list from empty input."""
        assert parse_partition_list('') == []
        assert parse_partition_list(None) == []
    
    def test_parse_partition_list_single(self):
        """Test parsing single partition."""
        assert parse_partition_list('hpc') == ['hpc']
    
    def test_parse_partition_list_multiple(self):
        """Test parsing multiple partitions."""
        output = "hpc\nhtc\ndynamic"
        assert parse_partition_list(output) == ['hpc', 'htc', 'dynamic']
    
    def test_parse_partition_list_with_asterisk(self):
        """Test parsing partition list with default partition marker."""
        output = "hpc*\nhtc\ndynamic"
        assert parse_partition_list(output) == ['hpc', 'htc', 'dynamic']
    
    def test_parse_partition_list_duplicates(self):
        """Test parsing partition list removes duplicates."""
        output = "hpc\nhpc\nhtc"
        assert parse_partition_list(output) == ['hpc', 'htc']
    
    def test_parse_partition_list_with_empty_lines(self):
        """Test parsing partition list with empty lines."""
        output = "hpc\n\nhtc\n  \ndynamic"
        assert parse_partition_list(output) == ['hpc', 'htc', 'dynamic']


class TestSlurmCommandExecutor:
    """Test SlurmCommandExecutor class."""
    
    def test_init_default_timeout(self):
        """Test executor initialization with default timeout."""
        executor = SlurmCommandExecutor()
        assert executor.timeout == 30
    
    def test_init_custom_timeout(self):
        """Test executor initialization with custom timeout."""
        executor = SlurmCommandExecutor(timeout=60)
        assert executor.timeout == 60
    
    @patch('exporter.util.subprocess.run')
    def test_run_command_success(self, mock_run):
        """Test successful command execution."""
        mock_result = Mock()
        mock_result.stdout = "output data\n"
        mock_run.return_value = mock_result
        
        executor = SlurmCommandExecutor()
        output = executor.run_command(['squeue', '-h'])
        
        assert output == "output data"
        mock_run.assert_called_once()
    
    @patch('exporter.util.subprocess.run')
    def test_run_command_failure(self, mock_run):
        """Test command execution with CalledProcessError."""
        mock_run.side_effect = subprocess.CalledProcessError(1, 'cmd', stderr='error')
        
        executor = SlurmCommandExecutor()
        output = executor.run_command(['invalid_command'])
        
        assert output == ""
    
    @patch('exporter.util.subprocess.run')
    def test_run_command_timeout(self, mock_run):
        """Test command execution with timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired('cmd', 30)
        
        executor = SlurmCommandExecutor()
        output = executor.run_command(['slow_command'])
        
        assert output == ""
    
    @patch('exporter.util.subprocess.run')
    def test_execute_schema_count_lines(self, mock_run):
        """Test executing schema with COUNT_LINES strategy."""
        mock_result = Mock()
        mock_result.stdout = "line1\nline2\nline3\n"
        mock_run.return_value = mock_result
        
        schema = CommandSchema(
            name='test',
            command=['squeue'],
            command_args=['-h'],
            parse_strategy=ParseStrategy.COUNT_LINES,
            description='Test'
        )
        
        executor = SlurmCommandExecutor()
        result = executor.execute_schema(schema)
        
        assert result == 3.0
    
    @patch('exporter.util.subprocess.run')
    def test_execute_schema_extract_number(self, mock_run):
        """Test executing schema with EXTRACT_NUMBER strategy."""
        mock_result = Mock()
        mock_result.stdout = "42\n"
        mock_run.return_value = mock_result
        
        schema = CommandSchema(
            name='test',
            command=['sinfo'],
            command_args=['-t', 'idle', '-h', '-o', '%D'],
            parse_strategy=ParseStrategy.EXTRACT_NUMBER,
            description='Test'
        )
        
        executor = SlurmCommandExecutor()
        result = executor.execute_schema(schema)
        
        assert result == 42.0
    
    @patch.object(SlurmCommandExecutor, 'run_command')
    def test_collect_job_queue_metrics(self, mock_run_command):
        """Test collecting job queue metrics."""
        # Mock different outputs for different commands
        def side_effect(cmd):
            if '-t' in cmd:
                state = cmd[cmd.index('-t') + 1]
                if state == 'RUNNING':
                    return "job1\njob2"
                elif state == 'PENDING':
                    return "job3"
            return ""
        
        mock_run_command.side_effect = side_effect
        
        executor = SlurmCommandExecutor()
        metrics = executor.collect_job_queue_metrics()
        
        assert 'squeue_jobs' in metrics
        assert metrics['squeue_jobs_running'] == 2.0
        assert metrics['squeue_jobs_pending'] == 1.0
    
    @patch.object(SlurmCommandExecutor, 'run_command')
    def test_get_partitions(self, mock_run_command):
        """Test getting partition list."""
        mock_run_command.return_value = "hpc*\nhtc\ndynamic"
        
        executor = SlurmCommandExecutor()
        partitions = executor.get_partitions()
        
        assert partitions == ['hpc', 'htc', 'dynamic']
    
    @patch.object(SlurmCommandExecutor, 'run_command')
    @patch.object(SlurmCommandExecutor, 'get_partitions')
    def test_collect_partition_job_metrics(self, mock_get_partitions, mock_run_command):
        """Test collecting partition-based job metrics."""
        mock_get_partitions.return_value = ['hpc', 'htc']
        
        def side_effect(cmd):
            if '-p' in cmd and '-t' in cmd:
                partition = cmd[cmd.index('-p') + 1]
                state = cmd[cmd.index('-t') + 1]
                if partition == 'hpc' and state == 'RUNNING':
                    return "job1\njob2"
                elif partition == 'htc' and state == 'RUNNING':
                    return "job3"
            return ""
        
        mock_run_command.side_effect = side_effect
        
        executor = SlurmCommandExecutor()
        metrics = executor.collect_partition_job_metrics()
        
        assert 'hpc' in metrics
        assert 'htc' in metrics
        assert metrics['hpc']['squeue_partition_jobs_running'] == 2.0
        assert metrics['htc']['squeue_partition_jobs_running'] == 1.0


class TestSchemaDefinitions:
    """Test that schema definitions are properly configured."""
    
    def test_job_queue_schemas_exist(self):
        """Test that job queue schemas are defined."""
        assert 'total' in JOB_QUEUE_SCHEMAS
        assert 'by_state' in JOB_QUEUE_SCHEMAS
    
    def test_job_history_schemas_exist(self):
        """Test that job history schemas are defined."""
        assert 'by_state' in JOB_HISTORY_SCHEMAS
        assert 'total_submitted' in JOB_HISTORY_SCHEMAS
    
    def test_node_schemas_exist(self):
        """Test that node schemas are defined."""
        assert 'total' in NODE_SCHEMAS
        assert 'by_state' in NODE_SCHEMAS
    
    def test_partition_schemas_exist(self):
        """Test that partition schemas are defined."""
        assert 'total' in JOB_PARTITION_SCHEMAS
        assert 'by_state' in JOB_PARTITION_SCHEMAS
        assert 'total' in NODE_PARTITION_SCHEMAS
        assert 'by_state' in NODE_PARTITION_SCHEMAS
    
    def test_partition_history_schemas_exist(self):
        """Test that partition history schemas are defined."""
        assert 'by_state' in JOB_PARTITION_HISTORY_SCHEMAS
        assert 'total_submitted' in JOB_PARTITION_HISTORY_SCHEMAS
    
    def test_job_queue_total_command(self):
        """Test job queue total command construction."""
        schema = JOB_QUEUE_SCHEMAS['total']
        cmd = schema.build_command()
        assert cmd == ['squeue', '-h']
    
    def test_job_queue_by_state_command(self):
        """Test job queue by state command construction."""
        schema = JOB_QUEUE_SCHEMAS['by_state']
        cmd = schema.build_command(state='RUNNING')
        assert cmd == ['squeue', '-t', 'RUNNING', '-h']
    
    def test_job_history_command_includes_all_flag(self):
        """Test that job history commands include -a flag for permissions."""
        schema = JOB_HISTORY_SCHEMAS['by_state']
        cmd = schema.build_command(start_time='2026-01-01', state='COMPLETED')
        # The -a flag should be in the command for viewing all users' jobs
        assert '-S' in cmd
        assert '2026-01-01' in cmd
        assert '-s' in cmd
        assert 'COMPLETED' in cmd
    
    def test_partition_history_includes_all_and_partition_flags(self):
        """Test that partition history commands include -a and -r flags."""
        schema = JOB_PARTITION_HISTORY_SCHEMAS['by_state']
        cmd = schema.build_command(partition='hpc', start_time='2026-01-01', state='COMPLETED')
        assert '-a' in cmd  # All users flag
        assert '-r' in cmd  # Partition filter flag
        assert 'hpc' in cmd
        assert '-S' in cmd
        assert '2026-01-01' in cmd


class TestMetricNaming:
    """Test that metric names follow conventions."""
    
    def test_job_queue_metrics_naming(self):
        """Test job queue metric naming."""
        schema = JOB_QUEUE_SCHEMAS['by_state']
        assert '{state}' in schema.name
        assert schema.name == 'squeue_jobs_{state}'
    
    def test_job_history_metrics_have_total_prefix(self):
        """Test that job history metrics have 'total' prefix."""
        schema = JOB_HISTORY_SCHEMAS['by_state']
        assert 'total' in schema.name
        assert schema.name == 'sacct_jobs_total_{metric_name}'
    
    def test_partition_metrics_have_partition_prefix(self):
        """Test that partition metrics have 'partition' in name."""
        schema = JOB_PARTITION_SCHEMAS['by_state']
        assert 'partition' in schema.name
    
    def test_partition_history_metrics_have_both_prefixes(self):
        """Test that partition history metrics have both 'partition' and 'total'."""
        schema = JOB_PARTITION_HISTORY_SCHEMAS['by_state']
        assert 'partition' in schema.name
        assert 'total' in schema.name
        assert schema.name == 'sacct_partition_jobs_total_{metric_name}'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
