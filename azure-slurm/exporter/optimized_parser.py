#!/usr/bin/env python3
"""
Optimized job history parser that runs sacct once per time period.

Instead of running multiple sacct commands for different states,
this runs sacct once with -p flag and parses all metrics from the output.
"""

import subprocess
import logging
from typing import Dict, List, Tuple
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger('slurm-exporter.optimized-parser')


def normalize_state(state: str) -> str:
    """
    Normalize state names to metric suffix format.
    
    Args:
        state: Raw state from sacct
        
    Returns:
        Normalized state name
    """
    # Handle compound states like "CANCELLED by 0"
    if 'CANCELLED by' in state:
        return 'cancelled'
    
    # Handle special states
    if state == 'NODE_FAIL':
        return 'node_failed'
    elif state == 'OUT_OF_MEMORY':
        return 'out_of_memory'
    else:
        return state.lower()


def parse_sacct_output(output: str) -> List[Dict[str, str]]:
    """
    Parse sacct -p output into a list of job dictionaries.
    
    Args:
        output: Raw sacct output with -p (parsable) flag
        
    Returns:
        List of job dictionaries with keys from header
    """
    if not output:
        return []
    
    lines = output.strip().split('\n')
    if len(lines) < 1:
        return []
    
    # First line is header
    header = [h.strip() for h in lines[0].split('|') if h.strip()]
    
    jobs = []
    for line in lines[1:]:
        if not line.strip():
            continue
        
        # Skip job steps (lines with .batch, .extern, etc)
        if '.batch' in line or '.extern' in line or '.0' in line:
            continue
        
        parts = line.split('|')
        if len(parts) < len(header):
            continue
        
        job = {}
        for i, key in enumerate(header):
            job[key] = parts[i].strip() if i < len(parts) else ''
        
        jobs.append(job)
    
    return jobs


def run_sacct_command(start_time: str, timeout: int = 30) -> str:
    """
    Run sacct command to get all jobs in a time period.
    
    Args:
        start_time: Start time in YYYY-MM-DD format
        timeout: Command timeout in seconds
        
    Returns:
        Raw command output
    """
    cmd = ['sacct', '-a', '-S', start_time, '-E', 'now', '-p', '-X', '-n']
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        logger.error(f"sacct command failed: {e.stderr}")
        return ""
    except subprocess.TimeoutExpired:
        logger.error(f"sacct command timeout")
        return ""
    except Exception as e:
        logger.error(f"sacct command error: {e}")
        return ""


def collect_job_metrics_optimized(days_back: int, timeout: int = 30) -> Dict[str, any]:
    """
    Collect all job history metrics by running sacct once.
    
    Args:
        days_back: Number of days to look back
        timeout: Command timeout in seconds
        
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
    from datetime import datetime, timedelta
    
    # Calculate start date
    start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
    
    # Run sacct once with all needed fields
    cmd = ['sacct', '-a', '-S', start_date, '-E', 'now', 
           '-o', 'JobID,JobName,Partition,State,ExitCode', 
           '--parsable2', '-n', '-X']
    
    logger.info(f"Running: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True
        )
        output = result.stdout.strip()
    except subprocess.CalledProcessError as e:
        logger.error(f"sacct command failed: {e.stderr}")
        return _empty_metrics(start_date)
    except subprocess.TimeoutExpired:
        logger.error(f"sacct command timeout")
        return _empty_metrics(start_date)
    except Exception as e:
        logger.error(f"sacct command error: {e}")
        return _empty_metrics(start_date)
    
    # Parse output
    state_counts = defaultdict(int)
    partition_state_counts = defaultdict(lambda: defaultdict(int))
    state_exit_code_counts = defaultdict(lambda: defaultdict(int))
    partition_state_exit_code_counts = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    
    total_jobs = 0
    
    if output:
        for line in output.strip().split('\n'):
            if not line.strip():
                continue
            
            parts = line.split('|')
            if len(parts) < 5:
                continue
            
            job_id, job_name, partition, state, exit_code = parts[:5]
            
            # Normalize state
            state_normalized = normalize_state(state.strip())
            
            # Count by state
            state_counts[state_normalized] += 1
            total_jobs += 1
            
            # Count by partition and state
            if partition.strip():
                partition_state_counts[partition.strip()][state_normalized] += 1
            
            # Track exit codes for failed states
            if state.strip() in ['FAILED', 'TIMEOUT', 'NODE_FAIL', 'OUT_OF_MEMORY', 'CANCELLED'] or 'CANCELLED by' in state.strip():
                exit_code_clean = exit_code.strip()
                state_exit_code_counts[state_normalized][exit_code_clean] += 1
                
                if partition.strip():
                    partition_state_exit_code_counts[partition.strip()][state_normalized][exit_code_clean] += 1
    
    # Convert to final format
    by_state_exit_code = []
    for state, exit_codes in state_exit_code_counts.items():
        for exit_code, count in exit_codes.items():
            by_state_exit_code.append((state, exit_code, count))
    
    by_partition_state_exit_code = {}
    for partition, states in partition_state_exit_code_counts.items():
        partition_metrics = []
        for state, exit_codes in states.items():
            for exit_code, count in exit_codes.items():
                partition_metrics.append((state, exit_code, count))
        by_partition_state_exit_code[partition] = partition_metrics
    
    return {
        'start_date': start_date,
        'total_submitted': total_jobs,
        'by_state': dict(state_counts),
        'by_partition': {p: dict(states) for p, states in partition_state_counts.items()},
        'by_state_exit_code': by_state_exit_code,
        'by_partition_state_exit_code': by_partition_state_exit_code
    }


def _empty_metrics(start_date: str) -> Dict[str, any]:
    """Return empty metrics structure."""
    return {
        'start_date': start_date,
        'total_submitted': 0,
        'by_state': {},
        'by_partition': {},
        'by_state_exit_code': [],
        'by_partition_state_exit_code': {}
    }


def collect_job_history_six_months_optimized(timeout: int = 30) -> Dict[str, any]:
    """Collect 6-month job history with single sacct call."""
    return collect_job_metrics_optimized(180, timeout)


def collect_job_history_one_month_optimized(timeout: int = 30) -> Dict[str, any]:
    """Collect 1-month job history with single sacct call."""
    return collect_job_metrics_optimized(30, timeout)


def collect_job_history_one_week_optimized(timeout: int = 30) -> Dict[str, any]:
    """Collect 1-week job history with single sacct call."""
    return collect_job_metrics_optimized(7, timeout)


if __name__ == '__main__':
    # Test the optimized parser
    logging.basicConfig(level=logging.INFO)
    
    print("Testing 1-week job history collection...")
    metrics = collect_job_history_one_week_optimized()
    
    print(f"\nStart date: {metrics['start_date']}")
    print(f"Total submitted: {metrics['total_submitted']}")
    print(f"\nBy state:")
    for state, count in sorted(metrics['by_state'].items()):
        print(f"  {state}: {count}")
    
    print(f"\nBy partition:")
    for partition, states in sorted(metrics['by_partition'].items()):
        print(f"  {partition}:")
        for state, count in sorted(states.items()):
            print(f"    {state}: {count}")
    
    print(f"\nBy state and exit code:")
    for state, exit_code, count in sorted(metrics['by_state_exit_code']):
        print(f"  {state} [{exit_code}]: {count}")
