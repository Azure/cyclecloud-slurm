# Azure Slurm Prometheus Exporter - Metrics Documentation

## Overview

The Azure Slurm Prometheus Exporter collects and exports Slurm cluster metrics in Prometheus format. Metrics are collected on-demand when Prometheus scrapes the `/metrics` endpoint (default: `http://localhost:9500/metrics`).

**Collection Frequency:** Metrics are collected **every time Prometheus scrapes** the endpoint (typically every 15-60 seconds depending on Prometheus configuration).

---

## Command Execution Summary

### Total Commands Per Scrape

The exporter runs the following number of commands per metric collection:

| Category | Commands | Details |
|----------|----------|---------|
| **Job Queue (Real-time)** | 7 | 1 total + 6 states |
| **Job History (Since reset)** | 13 | 6 states + 1 total + 6 per partition states |
| **Node Metrics** | 2 | 1 scontrol command (all nodes), 1 partition list |
| **Partition Job Metrics** | Variable | 6 states × N partitions + 1 × N partitions |
| **Partition Node Metrics** | 1 | Uses data from node metrics |
| **6-Month History** | 13 + 2 | Regular + state/exit code queries |
| **1-Week History** | 13 + 2 | Regular + state/exit code queries |
| **1-Month History** | 13 + 2 | Regular + state/exit code queries |
| **Cluster Info (Cached)** | 1 | Cached for 1 hour |

**Estimated Total: ~65-85 commands per scrape** (varies with number of partitions)

### Performance Optimization

- **Before scontrol migration:** 55+ `sinfo` commands per cycle
- **After scontrol migration:** 2 main commands (`scontrol show nodes --json`, `scontrol show partitions --json`)
- **Performance improvement:** 96% reduction in node/partition metric commands

---

## Metric Categories

### 1. Job Queue Metrics (Real-time)

**Update Frequency:** Every scrape (real-time)  
**Commands Executed:** 7 `squeue` commands  
**Source:** Current job queue

| Metric Name | Type | Description | Labels |
|-------------|------|-------------|--------|
| `squeue_jobs` | Gauge | Total jobs in queue | - |
| `squeue_jobs_running` | Gauge | Jobs in RUNNING state | - |
| `squeue_jobs_pending` | Gauge | Jobs in PENDING state | - |
| `squeue_jobs_configuring` | Gauge | Jobs in CONFIGURING state | - |
| `squeue_jobs_completing` | Gauge | Jobs in COMPLETING state | - |
| `squeue_jobs_suspended` | Gauge | Jobs in SUSPENDED state | - |
| `squeue_jobs_failed` | Gauge | Jobs in FAILED state | - |

**Commands:**
```bash
squeue -h                           # Total jobs
squeue -t RUNNING -h                # Running jobs
squeue -t PENDING -h                # Pending jobs
squeue -t CONFIGURING -h            # Configuring jobs
squeue -t COMPLETING -h             # Completing jobs
squeue -t SUSPENDED -h              # Suspended jobs
squeue -t FAILED -h                 # Failed jobs
```

---

### 2. Job History Metrics (Since Reset Time)

**Update Frequency:** Every scrape  
**Commands Executed:** 13 `sacct` commands  
**Source:** Historical job accounting data since reset time

| Metric Name | Type | Description | Labels |
|-------------|------|-------------|--------|
| `sacct_jobs_total_completed` | Gauge | Completed jobs since reset | - |
| `sacct_jobs_total_failed` | Gauge | Failed jobs since reset | - |
| `sacct_jobs_total_timeout` | Gauge | Timed out jobs since reset | - |
| `sacct_jobs_total_cancelled` | Gauge | Cancelled jobs since reset | - |
| `sacct_jobs_total_node_failed` | Gauge | Node failed jobs since reset | - |
| `sacct_jobs_total_out_of_memory` | Gauge | OOM jobs since reset | - |
| `sacct_jobs_total_submitted` | Gauge | Total submitted jobs since reset | - |

**Commands:**
```bash
sacct -a -S {reset_time} -E now -s COMPLETED --noheader -X -n
sacct -a -S {reset_time} -E now -s FAILED --noheader -X -n
sacct -a -S {reset_time} -E now -s TIMEOUT --noheader -X -n
sacct -a -S {reset_time} -E now -s CANCELLED --noheader -X -n
sacct -a -S {reset_time} -E now -s NODE_FAIL --noheader -X -n
sacct -a -S {reset_time} -E now -s OUT_OF_MEMORY --noheader -X -n
sacct -S {reset_time} -E now -a -X -n --noheader
```

---

### 3. Node Metrics (Mutually Exclusive States)

**Update Frequency:** Every scrape  
**Commands Executed:** 2 commands (1 scontrol, 1 partition list)  
**Source:** `scontrol show nodes --json`

**State Assignment:** Each node is counted in **exactly ONE state** based on priority hierarchy. States are mutually exclusive and sum to total nodes.

**Priority (highest to lowest):**
1. POWERED_DOWN → DOWN → FAIL → DRAINED/DRAINING → MAINT → RESV → COMPLETING → ALLOC → MIXED → IDLE

| Metric Name | Type | Description | Labels |
|-------------|------|-------------|--------|
| `scontrol_nodes` | Gauge | **Total nodes** | - |
| `scontrol_nodes_powered_down` | Gauge | Powered down (highest priority) | - |
| `scontrol_nodes_powering_up` | Gauge | Powering up | - |
| `scontrol_nodes_down` | Gauge | Down/not responding | - |
| `scontrol_nodes_fail` | Gauge | Failed | - |
| `scontrol_nodes_drained` | Gauge | Fully drained | - |
| `scontrol_nodes_draining` | Gauge | Being drained (includes DRAIN state) | - |
| `scontrol_nodes_maint` | Gauge | Maintenance mode | - |
| `scontrol_nodes_resv` | Gauge | Reserved | - |
| `scontrol_nodes_completing` | Gauge | Job completing | - |
| `scontrol_nodes_alloc` | Gauge | Fully allocated | - |
| `scontrol_nodes_mixed` | Gauge | Partially allocated | - |
| `scontrol_nodes_idle` | Gauge | Available (lowest priority) | - |
| `scontrol_nodes_cloud` | Gauge | **Flag:** Cloud-capable nodes (tracked independently) | - |

**Note:** All state metrics (powered_down through idle) are mutually exclusive and sum to `scontrol_nodes`. The `cloud` metric is a flag that counts cloud-capable nodes independently of their state.

**Commands:**
```bash
scontrol show nodes --json          # All node data
scontrol show partitions --json     # Partition list
```

---

### 4. Partition Job Metrics

**Update Frequency:** Every scrape  
**Commands Executed:** (6 states + 1 total) × N partitions  
**Source:** `squeue` per partition

| Metric Name | Type | Description | Labels |
|-------------|------|-------------|--------|
| `squeue_partition_jobs_{state}` | Gauge | Jobs per state per partition | `partition` |
| `squeue_partition_jobs_total` | Gauge | Total jobs per partition | `partition` |

**Commands (per partition):**
```bash
squeue -p {partition} -t RUNNING -h
squeue -p {partition} -t PENDING -h
squeue -p {partition} -t CONFIGURING -h
squeue -p {partition} -t COMPLETING -h
squeue -p {partition} -t SUSPENDED -h
squeue -p {partition} -t FAILED -h
squeue -p {partition} -h
```

---

### 5. Partition Node Metrics (Mutually Exclusive States)

**Update Frequency:** Every scrape  
**Commands Executed:** 0 (reuses node data)  
**Source:** Filtered from `scontrol show nodes --json`

**State Assignment:** Each node counted in **exactly ONE state** per partition (same priority as global node metrics).

| Metric Name | Type | Description | Labels |
|-------------|------|-------------|--------|
| `scontrol_partition_nodes` | Gauge | **Total nodes in partition** | `partition` |
| `scontrol_partition_nodes_powered_down` | Gauge | Powered down | `partition` |
| `scontrol_partition_nodes_powering_up` | Gauge | Powering up | `partition` |
| `scontrol_partition_nodes_down` | Gauge | Down/not responding | `partition` |
| `scontrol_partition_nodes_fail` | Gauge | Failed | `partition` |
| `scontrol_partition_nodes_drained` | Gauge | Fully drained | `partition` |
| `scontrol_partition_nodes_draining` | Gauge | Being drained | `partition` |
| `scontrol_partition_nodes_maint` | Gauge | Maintenance mode | `partition` |
| `scontrol_partition_nodes_resv` | Gauge | Reserved | `partition` |
| `scontrol_partition_nodes_completing` | Gauge | Job completing | `partition` |
| `scontrol_partition_nodes_alloc` | Gauge | Fully allocated | `partition` |
| `scontrol_partition_nodes_mixed` | Gauge | Partially allocated | `partition` |
| `scontrol_partition_nodes_idle` | Gauge | Available | `partition` |
| `scontrol_partition_nodes_cloud` | Gauge | **Flag:** Cloud-capable | `partition` |

**Note:** All state metrics (powered_down through idle) are mutually exclusive and sum to `scontrol_partition_nodes` for each partition. The `cloud` metric is independent.

**Commands:** None (data reused from node metrics)

---

### 6. Partition Job History Metrics

**Update Frequency:** Every scrape  
**Commands Executed:** (6 states + 1 total) × N partitions  
**Source:** `sacct` per partition since reset time

| Metric Name | Type | Description | Labels |
|-------------|------|-------------|--------|
| `sacct_partition_jobs_total_{state}` | Gauge | Historical jobs per state per partition | `partition` |
| `sacct_partition_jobs_total_submitted` | Gauge | Total submitted per partition | `partition` |

**Commands (per partition):**
```bash
sacct -a -r {partition} -S {reset_time} -E now -s COMPLETED --noheader -X -n
sacct -a -r {partition} -S {reset_time} -E now -s FAILED --noheader -X -n
sacct -a -r {partition} -S {reset_time} -E now -s TIMEOUT --noheader -X -n
sacct -a -r {partition} -S {reset_time} -E now -s CANCELLED --noheader -X -n
sacct -a -r {partition} -S {reset_time} -E now -s NODE_FAIL --noheader -X -n
sacct -a -r {partition} -S {reset_time} -E now -s OUT_OF_MEMORY --noheader -X -n
sacct -r {partition} -S {reset_time} -E now -a -X -n --noheader
```

---

### 7. Six-Month Rolling Job History

**Update Frequency:** Every scrape  
**Commands Executed:** 13 base + 1 state/exit query  
**Source:** `sacct` for last 180 days

| Metric Name | Type | Description | Labels |
|-------------|------|-------------|--------|
| `sacct_jobs_total_six_months_{state}` | Gauge | Jobs per state (6 months) | `start_date` |
| `sacct_jobs_total_six_months_submitted` | Gauge | Total submitted (6 months) | `start_date` |
| `sacct_jobs_total_six_months_by_state` | Gauge | Jobs by state (6 months) | `state`, `start_date` |
| `sacct_jobs_total_six_months_by_state_exit_code` | Gauge | Jobs by state and exit code | `state`, `exit_code`, `start_date` |
| `sacct_partition_jobs_total_six_months_{state}` | Gauge | Partition jobs per state | `partition`, `start_date` |
| `sacct_partition_jobs_total_six_months_submitted` | Gauge | Partition total submitted | `partition`, `start_date` |
| `sacct_partition_jobs_total_six_months_by_state_exit_code` | Gauge | Partition jobs by state/exit | `partition`, `state`, `exit_code`, `start_date` |

**Date Format:** `start_date` label uses `YYYY-MM-DD` format

**Commands:**
```bash
sacct -a -S {six_months_ago} -E now -s {state} --noheader -X -n
sacct -S {six_months_ago} -E now -a -X -n --noheader
sacct -a -S {six_months_ago} -E now -s {states} -o State,ExitCode --parsable2 -n -X
# Plus per-partition variants
```

---

### 8. One-Week Rolling Job History

**Update Frequency:** Every scrape  
**Commands Executed:** 13 base + 1 state/exit query  
**Source:** `sacct` for last 7 days

| Metric Name | Type | Description | Labels |
|-------------|------|-------------|--------|
| `sacct_jobs_total_one_week_{state}` | Gauge | Jobs per state (1 week) | `start_date` |
| `sacct_jobs_total_one_week_submitted` | Gauge | Total submitted (1 week) | `start_date` |
| `sacct_jobs_total_one_week_by_state` | Gauge | Jobs by state (1 week) | `state`, `start_date` |
| `sacct_jobs_total_one_week_by_state_exit_code` | Gauge | Jobs by state and exit code | `state`, `exit_code`, `start_date` |
| `sacct_partition_jobs_total_one_week_{state}` | Gauge | Partition jobs per state | `partition`, `start_date` |
| `sacct_partition_jobs_total_one_week_submitted` | Gauge | Partition total submitted | `partition`, `start_date` |
| `sacct_partition_jobs_total_one_week_by_state_exit_code` | Gauge | Partition jobs by state/exit | `partition`, `state`, `exit_code`, `start_date` |

**Date Format:** `start_date` label uses `YYYY-MM-DD` format

---

### 9. One-Month Rolling Job History

**Update Frequency:** Every scrape  
**Commands Executed:** 13 base + 1 state/exit query  
**Source:** `sacct` for last 30 days

| Metric Name | Type | Description | Labels |
|-------------|------|-------------|--------|
| `sacct_jobs_total_one_month_{state}` | Gauge | Jobs per state (1 month) | `start_date` |
| `sacct_jobs_total_one_month_submitted` | Gauge | Total submitted (1 month) | `start_date` |
| `sacct_jobs_total_one_month_by_state` | Gauge | Jobs by state (1 month) | `state`, `start_date` |
| `sacct_jobs_total_one_month_by_state_exit_code` | Gauge | Jobs by state and exit code | `state`, `exit_code`, `start_date` |
| `sacct_partition_jobs_total_one_month_{state}` | Gauge | Partition jobs per state | `partition`, `start_date` |
| `sacct_partition_jobs_total_one_month_submitted` | Gauge | Partition total submitted | `partition`, `start_date` |
| `sacct_partition_jobs_total_one_month_by_state_exit_code` | Gauge | Partition jobs by state/exit | `partition`, `state`, `exit_code`, `start_date` |

**Date Format:** `start_date` label uses `YYYY-MM-DD` format

---

### 10. Cluster Information

**Update Frequency:** Cached for 1 hour  
**Commands Executed:** 2 commands + N sinfo commands (cached)  
**Source:** `azslurm config`, `azslurm buckets`

| Metric Name | Type | Description | Labels |
|-------------|------|-------------|--------|
| `azslurm_cluster_info` | Gauge | Cluster name (value=1) | `cluster_name` |
| `azslurm_partition_info` | Gauge | Partition details (value=1) | `partition`, `vm_size`, `total_nodes`, `node_list` |

**Commands:**
```bash
azslurm config                       # Get cluster name
azslurm buckets                      # Get partition VM sizes and node counts
sinfo -p {partition} -h -o '%N'      # Get node list per partition (N partitions)
```

---

## Job States Reference

### Queue States (squeue)
- `RUNNING` - Job is currently running
- `PENDING` - Job is waiting to run
- `CONFIGURING` - Job is being configured
- `COMPLETING` - Job is completing
- `SUSPENDED` - Job is suspended
- `FAILED` - Job failed

### History States (sacct)
- `COMPLETED` - Job completed successfully
- `FAILED` - Job failed
- `TIMEOUT` - Job exceeded time limit
- `CANCELLED` - Job was cancelled by user
- `NODE_FAIL` - Job failed due to node failure
- `OUT_OF_MEMORY` - Job ran out of memory

### Node States (scontrol)

**Mutually Exclusive States (Priority-Based Assignment):**

Each node is counted in exactly ONE state based on the following priority (highest to lowest):

1. `POWERED_DOWN` - Node powered off (cloud nodes)
2. `POWERING_UP` - Node starting up (cloud nodes)  
3. `DOWN` - Node not responding/offline
4. `FAIL` - Node has failed
5. `DRAINED` - Node fully drained (no new jobs)
6. `DRAINING` - Node being drained (finishing current jobs)
7. `MAINT` - Node in maintenance mode
8. `RESERVED` - Node reserved for specific use
9. `COMPLETING` - Jobs completing on node
10. `ALLOCATED` - Node fully allocated to jobs
11. `MIXED` - Node partially allocated (some cores free)
12. `IDLE` - Node available and idle (lowest priority)

**Independent Flags:**
- `CLOUD` - Azure auto-scaling capable node (tracked separately from state)

**Example:** A node with states `[DRAIN, IDLE, CLOUD]` is counted as:
- State: `draining` (highest priority)
- Flag: `cloud` (independent counter)

**Verification:** For any partition or globally:
```
sum(all state metrics) == total_nodes
```

---

## Configuration

### Environment Variables
- `PROMETHEUS_PORT` - Port for metrics endpoint (default: 9500)
- `RESET_TIME` - Start time for cumulative metrics (default: service start time)
- `COMMAND_TIMEOUT` - Timeout for Slurm commands in seconds (default: 30)

### Service Configuration
The exporter runs as a systemd service: `azslurm-exporter.service`

```bash
# View service status
sudo systemctl status azslurm-exporter

# View logs
sudo journalctl -u azslurm-exporter -f

# Restart service
sudo systemctl restart azslurm-exporter
```

---

## Performance Characteristics

### Command Execution
- **Parallel Execution:** None (sequential to avoid overwhelming Slurm)
- **Timeout:** 30 seconds per command (configurable)
- **Caching:** Cluster info cached for 1 hour
- **Data Reuse:** Node data fetched once and reused for partition metrics

### Scrape Duration
Typical scrape duration depends on:
- Number of partitions: ~2-5
- Number of nodes: ~50-100
- Job history volume: Variable
- **Estimated:** 5-15 seconds per scrape

### Resource Usage
- **CPU:** Low (command execution overhead)
- **Memory:** ~15-20 MB
- **Network:** Minimal (local Slurm commands only)

---

## Example Queries

### Prometheus Queries

```promql
# Current running jobs
squeue_jobs_running

# Job completion rate (6 months)
rate(sacct_jobs_total_six_months_completed[5m])

# Nodes powering up (auto-scaling activity)
scontrol_nodes_powering_up

# Partition utilization
scontrol_partition_nodes_alloc / scontrol_partition_nodes * 100

# Cloud node count per partition
scontrol_partition_nodes_cloud{partition="hpc"}

# Failed jobs in last month
sacct_jobs_total_one_month_failed

# Job state distribution
sacct_jobs_total_one_month_by_state

# Exit code analysis
sacct_jobs_total_six_months_by_state_exit_code{state="failed"}
```

---

## Changelog

### 2026-01-29
- **MAJOR:** Migrated from `sinfo` to `scontrol show nodes --json`
  - Reduced commands from 55+ to 2 for node/partition metrics
  - Performance improvement: 96% reduction
  - Added CLOUD state tracking for Azure auto-scaling nodes
  - Updated metric names from `sinfo_*` to `scontrol_*`

### 2026-01-30
- Changed 24-hour metrics to 30-day (one month) rolling window
- Updated label from `start_datetime` to `start_date` for consistency with 6-month and 1-week metrics
- Changed date format from `YYYY-MM-DDTHH:MM:SS` to `YYYY-MM-DD` for one-month metrics

---

## Support

For issues or questions:
1. Check service logs: `sudo journalctl -u azslurm-exporter -n 100`
2. Verify metrics endpoint: `curl http://localhost:9500/metrics`
3. Check Slurm commands manually: `scontrol show nodes --json`
