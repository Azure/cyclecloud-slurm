# Azure Slurm Prometheus Exporter

## Overview

The Azure Slurm Prometheus Exporter is a service that collects metrics from a Slurm cluster and exports them in Prometheus format. It runs continuously on the Slurm scheduler node and provides real-time and historical metrics about job states, node states, and partition usage.

## How It Works

### Architecture

The exporter uses a **schema-based command execution pattern** that separates the command definition from the parsing logic. This design makes it easy to maintain and extend without modifying core code.

```
┌─────────────────────────────────────────────────────────────┐
│                     Prometheus Scraper                       │
│                  (polls http://localhost:9500/metrics)       │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP GET
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              SlurmMetricsCollector (exporter.py)             │
│  • Orchestrates metric collection                           │
│  • Groups partition metrics by name                          │
│  • Yields Prometheus GaugeMetricFamily objects              │
└───────────────────────────┬─────────────────────────────────┘
                            │ collect()
                            ▼
┌─────────────────────────────────────────────────────────────┐
│           SlurmCommandExecutor (executor.py)                 │
│  • Executes Slurm commands via schemas                       │
│  • Uses optimized single-call approach for sacct            │
│  • Maps ParseStrategy enum to parser functions              │
│  • Returns parsed metric values (float or dict)             │
└───────────┬───────────────────────────────┬─────────────────┘
            │                               │
            │ execute_schema()              │ run_command()
            ▼                               ▼
┌───────────────────────┐       ┌───────────────────────────┐
│   Parsers (parsers.py)│       │    Slurm Commands         │
│  • parse_sacct_job_   │       │  squeue  │  sacct         │
│    history()          │       │  (queue) │ (history)      │
│  • parse_scontrol_    │       │  scontrol (nodes/parts)   │
│    nodes_json()       │       └───────────────────────────┘
│  • parse_scontrol_    │
│    partitions_json()  │
│  • parse_count_lines()│
│  • parse_columns()    │
└───────────────────────┘
```

### Schema-Based Design

Each metric is defined by a `CommandSchema` that specifies:
- **Command**: The base Slurm command to run (e.g., `squeue`, `sacct`, `scontrol`)
- **Arguments**: Command-line arguments with placeholders (e.g., `-t {state}`, `-p {partition}`, `-S {start_date}`)
- **Parse Strategy**: How to interpret the output:
  - `COUNT_LINES`: Count number of output lines
  - `EXTRACT_NUMBER`: Extract first number from output
  - `PARSE_COLUMNS`: Parse column-based output with config
  - `PARSE_SACCT_JOB_HISTORY`: Parse comprehensive sacct job data
  - `PARSE_SCONTROL_NODES`: Parse scontrol nodes JSON output
  - `PARSE_SCONTROL_PARTITIONS`: Parse scontrol partitions JSON output
  - `CUSTOM`: Custom parser function
- **Metric Name**: The Prometheus metric name

**Example Schema:**
```python
CommandSchema(
    name='slurm_jobs_{state}',
    command=['squeue'],
    command_args=['-t', '{state}', '-h'],
    parse_strategy=ParseStrategy.COUNT_LINES,
    description='Jobs in {state} state'
)
```

This schema is executed for each job state (RUNNING, PENDING, etc.), producing metrics like:
- `slurm_jobs_running`
- `slurm_jobs_pending`
- `slurm_jobs_failed`

## How It Runs

### Installation

The exporter is installed as part of the Azure Slurm package via `install.sh`:

1. **Exporter Files Copied**: 
   - `exporter.py` → `/opt/azurehpc/slurm/exporter/` (main service)
   - `executor.py` → `/opt/azurehpc/slurm/exporter/` (command execution)
   - `schemas.py` → `/opt/azurehpc/slurm/exporter/` (metric schemas)
   - `parsers.py` → `/opt/azurehpc/slurm/exporter/` (output parsers)
   - `util.py` → `/opt/azurehpc/slurm/exporter/` (convenience functions)
2. **Executable Created**: `azslurm-exporter` → `/opt/azurehpc/slurm/venv/bin/`
3. **SystemD Service Created**: `/etc/systemd/system/azslurm-exporter.service`
4. **Deployment Timestamp Recorded**: `/opt/azurehpc/slurm/cluster_deploy_time`

### SystemD Service

The exporter runs as a systemd service under the `slurm` user:

```ini
[Unit]
Description=Azure Slurm Prometheus Exporter
After=network.target slurmd.service
Wants=slurmd.service

[Service]
Type=simple
ExecStart=/opt/azurehpc/slurm/venv/bin/azslurm-exporter --port 9500 --reset-time "2026-01-26T12:00:00"
Restart=on-failure
RestartSec=5s
User=slurm
Group=slurm
WorkingDirectory=/opt/azurehpc/slurm/exporter
```

### Service Management

```bash
# Start the exporter
sudo systemctl start azslurm-exporter

# Check status
sudo systemctl status azslurm-exporter

# View logs
sudo journalctl -u azslurm-exporter -f

# Restart
sudo systemctl restart azslurm-exporter

# Stop
sudo systemctl stop azslurm-exporter
```

### Command-Line Options

The exporter accepts the following arguments:

| Option | Default | Description |
|--------|---------|-------------|
| `--port` | 9500 | Port to expose metrics on |
| `--reset-time` | "24 hours ago" | Start time for cumulative metrics |
| `--timeout` | 30 | Command execution timeout (seconds) |
| `--log-level` | INFO | Logging level (DEBUG, INFO, WARNING, ERROR) |

### Reset Time

The **reset time** determines the starting point for cumulative (historical) metrics. It supports:

- **Relative times**: `"24 hours ago"`, `"7 days ago"`, `"1 week ago"`
- **Absolute timestamps**: `"2026-01-26T12:00:00"`, `"2026-01-26"`

On deployment, the cluster creation timestamp is stored in `/opt/azurehpc/slurm/cluster_deploy_time` and used as the default reset time, ensuring cumulative metrics track all jobs since cluster deployment.

## Accessing Metrics

### HTTP Endpoint

Metrics are exposed at: **http://localhost:9500/metrics**

```bash
# View all metrics
curl http://localhost:9500/metrics

# Filter for specific metric
curl http://localhost:9500/metrics | grep slurm_jobs_running
```

### Prometheus Integration

Configure Prometheus to scrape the exporter:

```yaml
scrape_configs:
  - job_name: 'slurm'
    static_configs:
      - targets: ['<scheduler-node-ip>:9500']
```

## Exported Metrics

The exporter provides three categories of metrics:

### 1. Current State Metrics (Real-time)

These metrics show the **current state** of the cluster at the moment of collection.

#### Job Queue Metrics
Source: `squeue` (shows jobs currently in the queue)

| Metric | Description | Source Command |
|--------|-------------|----------------|
| `slurm_jobs` | Total jobs in queue | `squeue -h` |
| `slurm_jobs_running` | Running jobs | `squeue -t RUNNING -h` |
| `slurm_jobs_pending` | Pending jobs | `squeue -t PENDING -h` |
| `slurm_jobs_configuring` | Configuring jobs | `squeue -t CONFIGURING -h` |
| `slurm_jobs_completing` | Completing jobs | `squeue -t COMPLETING -h` |
| `slurm_jobs_suspended` | Suspended jobs | `squeue -t SUSPENDED -h` |
| `slurm_jobs_failed` | Failed jobs | `squeue -t FAILED -h` |

#### Node State Metrics
Source: `scontrol show nodes --json` (shows current node states with detailed information)

| Metric | Description | Source Command |
|--------|-------------|----------------|
| `slurm_nodes` | Total nodes | `sinfo -N -h` |
| `slurm_nodes_alloc` | Allocated nodes | `sinfo -t alloc -h -o '%D'` |
| `slurm_nodes_idle` | Idle nodes | `sinfo -t idle -h -o '%D'` |
| `slurm_nodes_mixed` | Mixed nodes | `sinfo -t mix -h -o '%D'` |
| `slurm_nodes_down` | Down nodes | `sinfo -t down -h -o '%D'` |
| `slurm_nodes_drain` | Draining nodes | `sinfo -t drain -h -o '%D'` |
| `slurm_nodes_draining` | Draining nodes | `sinfo -t drng -h -o '%D'` |
| `slurm_nodes_drained` | Drained nodes | `sinfo -t drained -h -o '%D'` |
| `slurm_nodes_drain_total` | All drain variants combined | Calculated |
| `slurm_nodes_maint` | Maintenance nodes | `sinfo -t maint -h -o '%D'` |
| `slurm_nodes_fail` | Failed nodes | `sinfo -t fail -h -o '%D'` |
| `slurm_nodes_powered_down` | Powered down nodes | `sinfo -t powered_down -h -o '%D'` |
| `slurm_nodes_powering_up` | Powering up nodes | `sinfo -t powering_up -h -o '%D'` |

### 2. Cumulative Metrics (Historical)

These metrics show **totals since the reset time** (cluster deployment or configured start time).

#### Job History Metrics
Source: **Optimized single `sacct` call** that retrieves all job data at once

| Metric | Description | Implementation |
|--------|-------------|----------------|
| `sacct_jobs_total_submitted` | Total jobs submitted | Extracted from optimized sacct output |
| `sacct_jobs_total_completed` | Successfully completed jobs | Extracted from optimized sacct output |
| `sacct_jobs_total_failed` | Failed jobs | Extracted from optimized sacct output |
| `sacct_jobs_total_timeout` | Timed out jobs | Extracted from optimized sacct output |
| `sacct_jobs_total_node_failed` | Node failure jobs | Extracted from optimized sacct output |
| `sacct_jobs_total_cancelled` | Cancelled jobs | Extracted from optimized sacct output |
| `sacct_jobs_total_out_of_memory` | OOM jobs | Extracted from optimized sacct output |

**Optimized Command** (single call for all metrics):
```bash
sacct -a -S <start_date> --format=JobID,JobName,Partition,State,ExitCode --parsable2
```

This single command is parsed by `parse_sacct_job_history()` to extract:
- Job counts by state
- Job counts by partition
- Job counts by state and exit code
- Partition-specific state breakdowns

**Performance**: Reduced from 27-135 sacct calls to just **3 calls per collection cycle** (one each for 6-month, 1-month, and 1-week windows).

### 3. Partition-Labeled Metrics

These metrics include a **partition label** to filter by partition (e.g., `hpc`, `htc`, `dynamic`).

#### Partition Job Metrics (Current State)
Source: `squeue -p <partition>`

| Metric | Labels | Description |
|--------|--------|-------------|
| `slurm_partition_jobs` | `partition` | Total jobs in partition |
| `slurm_partition_jobs_running` | `partition` | Running jobs in partition |
| `slurm_partition_jobs_pending` | `partition` | Pending jobs in partition |
| `slurm_partition_jobs_configuring` | `partition` | Configuring jobs in partition |
| `slurm_partition_jobs_completing` | `partition` | Completing jobs in partition |
| `slurm_partition_jobs_suspended` | `partition` | Suspended jobs in partition |
| `slurm_partition_jobs_failed` | `partition` | Failed jobs in partition |

**Example Output:**
```
slurm_partition_jobs_running{partition="hpc"} 5.0
slurm_partition_jobs_running{partition="htc"} 2.0
slurm_partition_jobs_pending{partition="hpc"} 10.0
slurm_partition_jobs_pending{partition="htc"} 3.0
```

#### Partition Node Metrics (Current State)
Source: `sinfo -p <partition>`

| Metric | Labels | Description |
|--------|--------|-------------|
| `slurm_partition_nodes` | `partition` | Total nodes in partition |
| `slurm_partition_nodes_alloc` | `partition` | Allocated nodes in partition |
| `slurm_partition_nodes_idle` | `partition` | Idle nodes in partition |
| `slurm_partition_nodes_mixed` | `partition` | Mixed nodes in partition |
| `slurm_partition_nodes_down` | `partition` | Down nodes in partition |
| `slurm_partition_nodes_drain_total` | `partition` | All drain states combined |

#### Partition Job History Metrics (Cumulative)
Source: **Extracted from optimized sacct output** (no additional calls)

| Metric | Labels | Description |
|--------|--------|-------------|
| `sacct_partition_jobs_total_submitted` | `partition` | Total jobs submitted to partition |
| `sacct_partition_jobs_total_completed` | `partition` | Completed jobs in partition |
| `sacct_partition_jobs_total_failed` | `partition` | Failed jobs in partition |
| `sacct_partition_jobs_total_timeout` | `partition` | Timed out jobs in partition |
| `sacct_partition_jobs_total_node_failed` | `partition` | Node failure jobs in partition |
| `sacct_partition_jobs_total_cancelled` | `partition` | Cancelled jobs in partition |
| `sacct_partition_jobs_total_out_of_memory` | `partition` | OOM jobs in partition |

**Performance**: These metrics are extracted from the same optimized sacct calls used for global job history - **no additional commands required**.

#### Rolling Window Metrics (6-month, 1-month, 1-week)

In addition to cumulative metrics since reset time, the exporter also provides **rolling window metrics** for three time periods:

| Time Period | Start Date Calculation | Metrics Provided |
|-------------|------------------------|------------------|
| 6 months | 180 days ago | `sacct_jobs_total_six_months_*` with `start_date` label |
| 1 month | 30 days ago | `sacct_jobs_total_one_month_*` with `start_date` label |
| 1 week | 7 days ago | `sacct_jobs_total_one_week_*` with `start_date` label |

Each window includes:
- Total submitted jobs
- Jobs by state (completed, failed, timeout, cancelled, node_failed)
- Jobs by state with `state` label
- Jobs by state and exit code with `state`, `exit_code`, and `reason` labels
- Partition-specific breakdowns

**Example Output:**
```
sacct_jobs_total_six_months_submitted{start_date="2025-08-17"} 280.0
sacct_jobs_total_six_months_by_state{start_date="2025-08-17",state="completed"} 203.0
sacct_jobs_total_six_months_by_state_exit_code{exit_code="1:0",reason="General failure",start_date="2025-08-17",state="failed"} 27.0
sacct_partition_jobs_total_six_months_completed{partition="hpc",start_date="2025-08-17"} 120.0
```

**Example Prometheus Query:**
```promql
# Running jobs in HPC partition
slurm_partition_jobs_running{partition="hpc"}

# Total completed jobs across all partitions in last week
sum(sacct_partition_jobs_total_one_week_completed)

# Compare running jobs between partitions
slurm_partition_jobs_running{partition=~"hpc|htc"}

# Failed jobs with exit code 1 in last month
sacct_jobs_total_one_month_by_state_exit_code{state="failed",exit_code="1:0"}
```

### 4. Meta Metrics

These metrics provide information about the exporter itself.

| Metric | Description |
|--------|-------------|
| `slurm_exporter_collect_duration_seconds` | Time spent collecting metrics |
| `slurm_exporter_last_collect_timestamp_seconds` | Timestamp of last successful collection |
| `slurm_exporter_errors_total` | Number of collection errors (1 if error occurred) |

## Metric Collection Flow

### 1. Prometheus Scrape Request
```
Prometheus → HTTP GET /metrics → SlurmMetricsCollector.collect()
```

### 2. Collection Process
```python
def collect(self):
    # 1. Collect current job queue metrics (squeue)
    job_metrics = executor.collect_job_queue_metrics()
    
    # 2. Collect historical job metrics (optimized single sacct call)
    job_history_metrics = executor.collect_job_history_metrics(reset_time)
    
    # 3. Collect node metrics (scontrol show nodes --json)
    node_metrics = executor.collect_node_metrics()
    
    # 4. Collect partition job metrics (squeue per partition)
    partition_job_metrics = executor.collect_partition_job_metrics()
    
    # 5. Collect partition node metrics (scontrol show nodes --json per partition)
    partition_node_metrics = executor.collect_partition_node_metrics()
    
    # 6. Collect partition historical metrics (extracted from global sacct data)
    partition_history_metrics = executor.collect_partition_job_history_metrics(reset_time)
    
    # 7. Collect rolling window metrics (6-month, 1-month, 1-week)
    six_month_metrics = executor.collect_job_history_six_months_optimized()
    one_month_metrics = executor.collect_job_history_one_month_optimized()
    one_week_metrics = executor.collect_job_history_one_week_optimized()
    
    # 8. Yield all metrics as Prometheus GaugeMetricFamily
```

### 3. Schema Execution

**Simple metrics (COUNT_LINES, EXTRACT_NUMBER):**
```python
# 1. Build command from schema
cmd = ['squeue', '-t', 'RUNNING', '-h']

# 2. Execute command
output = subprocess.run(cmd, capture_output=True, text=True)

# 3. Parse output using strategy
value = parse_count_lines(output.stdout)  # Count lines

# 4. Return metric value (float)
return value
```

**Optimized metrics (PARSE_SACCT_JOB_HISTORY):**
```python
# 1. Build command from schema with parameters
cmd = ['sacct', '-a', '-S', '2026-01-14', '--format=JobID,JobName,Partition,State,ExitCode', '--parsable2']

# 2. Execute command once
output = subprocess.run(cmd, capture_output=True, text=True)

# 3. Parse output to extract all job data
job_data = parse_sacct_job_history(output.stdout, '2026-01-14')
# Returns: {
#   'start_date': '2026-01-14',
#   'total_submitted': 280,
#   'by_state': {'completed': 203, 'failed': 50, ...},
#   'by_partition': {'hpc': {'completed': 120, ...}, ...},
#   'by_state_exit_code': [('failed', '1:0', 27), ...],
#   'by_partition_state_exit_code': {'hpc': [('failed', '1:0', 15), ...], ...}
# }

# 4. Extract multiple metrics from single parse
for state, count in job_data['by_state'].items():
    metrics[f'sacct_jobs_total_{state}'] = float(count)
metrics['sacct_jobs_total_submitted'] = float(job_data['total_submitted'])
```

### 4. Partition Metric Grouping

Partition metrics are **grouped by metric name** before being yielded to Prometheus. This ensures proper Prometheus behavior where each metric name appears only once with multiple label values.

**Before Grouping (incorrect):**
```python
# This would create multiple metrics with the same name
GaugeMetricFamily('slurm_partition_jobs_running', ..., labels=['partition'])
    .add_metric(['hpc'], 5.0)
GaugeMetricFamily('slurm_partition_jobs_running', ..., labels=['partition'])
    .add_metric(['htc'], 2.0)  # ❌ Duplicate metric name
```

**After Grouping (correct):**
```python
# One metric with all partition labels
GaugeMetricFamily('slurm_partition_jobs_running', ..., labels=['partition'])
    .add_metric(['hpc'], 5.0)
    .add_metric(['htc'], 2.0)  # ✅ Single metric, multiple labels
```

## Troubleshooting

### Check if Service is Running
```bash
sudo systemctl status azslurm-exporter
```

### View Logs
```bash
# Real-time logs
sudo journalctl -u azslurm-exporter -f

# Last 100 lines
sudo journalctl -u azslurm-exporter -n 100

# Logs since yesterday
sudo journalctl -u azslurm-exporter --since yesterday
```

### Test Manually
Run the exporter manually to see detailed output:
```bash
sudo -u slurm /opt/azurehpc/slurm/venv/bin/azslurm-exporter --log-level DEBUG
```

### Common Issues

#### Metrics Show Zero Values
**Cause**: The `slurm` user needs the `-a` flag for `sacct` to see all users' jobs.

**Solution**: All historical schemas include `-a` flag:
```python
command_args=['-a', '-S', '{start_time}', '-E', 'now', ...]
```

#### Permission Denied
**Cause**: Service running as wrong user.

**Solution**: Ensure service runs as `slurm` user:
```bash
sudo systemctl cat azslurm-exporter | grep User
# Should show: User=slurm
```

#### Command Timeout
**Cause**: Slurm commands taking too long.

**Solution**: Increase timeout:
```bash
# Edit service file
sudo systemctl edit azslurm-exporter

# Add timeout flag
ExecStart=/opt/azurehpc/slurm/venv/bin/azslurm-exporter --port 9500 --timeout 60
```

## Testing

### Unit Tests
Test schema definitions and parsers:
```bash
cd /opt/azurehpc/slurm
pytest test/test_exporter_util.py -v
```

### Integration Tests
Test the full collector:
```bash
pytest test/test_exporter_integration.py -v
```

### Manual Verification
Test metrics with real cluster data:
```bash
# Submit test jobs
sbatch -p hpc -n 1 --wrap "sleep 60"
sbatch -p htc -n 1 --wrap "sleep 60"

# Check metrics
curl http://localhost:9500/metrics | grep partition_jobs_running

# Should show:
# slurm_partition_jobs_running{partition="hpc"} 1.0
# slurm_partition_jobs_running{partition="htc"} 1.0
```

## Design Principles

### 1. Schema-Based Extensibility
Adding a new metric requires only defining a schema—no code changes:
```python
NEW_SCHEMA = CommandSchema(
    name='slurm_custom_metric',
    command=['sinfo'],
    command_args=['--custom-flag'],
    parse_strategy=ParseStrategy.COUNT_LINES,
    description='Custom metric'
)
```

### 2. Separation of Concerns
- **exporter.py**: Orchestration and Prometheus integration
- **executor.py**: Command execution and schema-based metric collection
- **schemas.py**: Metric definitions and parse strategies
- **parsers.py**: Pure parsing functions (no command execution)
- **util.py**: Convenience functions and public API
- **install.sh**: Deployment and service management

### 3. Fail-Safe Operation
- Commands timeout after 30 seconds (configurable)
- Errors are logged but don't crash the service
- Error metric (`slurm_exporter_errors_total`) tracks failures
- Service auto-restarts on failure

### 4. Prometheus Best Practices
- One gauge per metric name (not per label value)
- Consistent naming: `slurm_<resource>_<state>`
- Clear descriptions for all metrics
- Labels used for dimensions (partition)

## Performance

### Collection Speed
Typical collection time: **0.56-0.59 seconds** for:
- 6 partitions
- 280 jobs submitted (historical)
- Comprehensive metrics across 3 time windows

**Optimization Achievement**: Reduced from 2.0-2.75 seconds to 0.56-0.59 seconds through:
- Single-call sacct approach (3 calls total instead of 27-135+)
- Eliminated redundant command execution
- Efficient data extraction from parsed output

### Command Efficiency

**Before Optimization:**
- Global job history: 6-8 sacct calls (one per state)
- Partition job history: 6-8 sacct calls × 6 partitions = 36-48 calls
- Rolling windows: 3 time periods × (6-8 + 36-48) calls = 126-168 calls
- **Total: ~130-180 sacct calls per collection**

**After Optimization:**
- Global + partition history: 1 sacct call (parsed for all states and partitions)
- Rolling windows: 3 time periods × 1 call = 3 calls
- **Total: 3 sacct calls per collection** ✅

### Resource Usage
- **CPU**: Minimal (< 1% during collection)
- **Memory**: ~100 MB
- **Network**: Negligible (local HTTP only)
- **Disk I/O**: Minimal (only for Slurm accounting database reads)

### Optimization Strategy

**Single-Call Pattern:**
```python
# Instead of multiple filtered calls:
# sacct -s COMPLETED -S <time>  # Call 1
# sacct -s FAILED -S <time>     # Call 2
# sacct -s TIMEOUT -S <time>    # Call 3
# ...

# Use one comprehensive call:
cmd = ['sacct', '-a', '-S', start_date, 
       '--format=JobID,JobName,Partition,State,ExitCode', '--parsable2']
output = run_command(cmd)
job_data = parse_sacct_job_history(output, start_date)

# Extract all metrics from parsed data:
# - by_state: {'completed': 203, 'failed': 50, ...}
# - by_partition: {'hpc': {'completed': 120, ...}, ...}
# - by_state_exit_code: [('failed', '1:0', 27), ...]
# - by_partition_state_exit_code: {...}
```

## Summary

The Azure Slurm Prometheus Exporter provides comprehensive cluster monitoring by:

1. **Running as a systemd service** on the scheduler node
2. **Executing Slurm commands** (squeue, sacct, sinfo) via schemas
3. **Parsing command output** using configurable strategies
4. **Grouping partition metrics** to comply with Prometheus format
5. **Exposing metrics** at http://localhost:9500/metrics
6. **Tracking both real-time and historical data** for jobs, nodes, and partitions

The schema-based design makes it maintainable, extensible, and resilient to Slurm version changes.
