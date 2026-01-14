
### 1.1 Job Metrics (All gauges)

| slurm_exporter Metric (25.05+)| Slurm Metrics Plugin Metric (25.11+)| Description | Equivalent sacct/scontrol Command |
|--------|-------------|-------------|----------------------------------|
| `slurm_jobs_completed_total` | `slurm_jobs_completed`|Jobs completed successfully | `sacct -s COMPLETED --noheader \| wc -l`<br>`squeue -t COMPLETED -h \| wc -l` |
| `slurm_jobs_running_total` | `slurm_jobs_running`|Jobs currently running | `squeue -t RUNNING -h \| wc -l` |
| `slurm_jobs_pending_total` | `slurm_jobs_pending` |Jobs waiting in queue | `squeue -t PENDING -h \| wc -l` |
| `slurm_jobs_configuring_total` | `slurm_jobs_configuring` |Jobs in CONFIGURING state | `squeue -t CONFIGURING -h \| wc -l` |
| `slurm_jobs_completing_total` |`slurm_jobs_completing` |Jobs in COMPLETING state | `squeue -t COMPLETING -h \| wc -l` |
| `slurm_jobs_failed_total` | `slurm_jobs_failed`|Jobs that failed | `sacct -s FAILED --noheader \| wc -l`<br>`squeue -t FAILED -h \| wc -l` |
| `slurm_jobs_timeout_total` |`slurm_jobs_timeout` |Jobs exceeded time limit | `sacct -s TIMEOUT --noheader \| wc -l` |
| `slurm_jobs_nodefail_total` |`slurm_jobs_node_failed` |Jobs failed due to node failure | `sacct -s NODE_FAIL --noheader \| wc -l` |
| `slurm_jobs_cancelled_total` |`slurm_jobs_cancelled` |Jobs that were cancelled | `sacct -s CANCELLED --noheader \| wc -l` |
| `slurm_jobs_suspended_total` |`slurm_jobs_suspended` |Jobs currently suspended | `squeue -t SUSPENDED -h \| wc -l` |
| `slurm_jobs_preempted_total` | `slurm_jobs_preempted` |Jobs that were preempted | `sacct -s PREEMPTED --noheader \| wc -l` |

### 1.2 Job Metrics (Cumulative)

| slurm_exporter Metric (25.05+) | Description | Equivalent sacct/scontrol Command |
|--------|-------------|----------------------------------|
| `slurm_scheduler_jobs_submitted_total` | Number of jobs submitted since last reset | 
| `slurm_scheduler_jobs_completed_total` | Number of jobs completed since last reset | `sacct -S "$START" -E now -a -X -n -s COMPLETED --noheader\| wc -l` |
| `slurm_scheduler_jobs_started_total` | Number of jobs started since last reset |
| | Number of jobs failed since last reset| `sacct -S "$START" -E now -a -X -n -s FAILED --noheader\| wc -l` |
| | Number of jobs cancelled since last reset| `sacct -S "$START" -E now -a -X -n -s CANCELLED --noheader\| wc -l` |

**sacct Notes:**
- Use `-S` and `-E` flags to specify time range (e.g., `-S now-1hour -E now`)
- `squeue` shows current queue state (real-time)
- `sacct` queries historical accounting database

---
### 2. Node State Metrics (All Gauges)

| slurm_exporter Metric (25.05+)| Slurm Metrics Plugin Metric (25.11+)| Description | Equivalent sinfo/scontrol Command |
|--------|-------------|-------------|----------------------------------|
| `slurm_nodes_total` | `slurm_nodes` | Total number of nodes | `sinfo -N -h \| wc -l`<br>`scontrol show nodes -o \| wc -l` |
| `slurm_nodes_allocated_total` | `slurm_nodes_alloc` | Nodes fully allocated | `sinfo -t alloc -h -o "%D"` |
| `slurm_nodes_idle_total` | `slurm_nodes_idle` | Idle nodes | `sinfo -t idle -h -o "%D"` |
| `slurm_nodes_mixed_total` | `slurm_nodes_mixed` | Partially allocated nodes | `sinfo -t mix -h -o "%D"` |
| `slurm_nodes_completing_total` | `slurm_nodes_completing` | Nodes with completing jobs | `sinfo -t comp -h -o "%D"` |
| `slurm_nodes_maintenance_total` | `slurm_nodes_maint` | Nodes in maintenance | `sinfo -t maint -h -o "%D"` |
| `slurm_nodes_reserved_total` | `slurm_nodes_resv` | Reserved nodes | `sinfo -t resv -h -o "%D"` |
| `slurm_nodes_down_total` | `slurm_nodes_down` | Down nodes | `sinfo -t down -h -o "%D"`<br>`scontrol show nodes -o \| grep "State=DOWN" \| wc -l` |
| `slurm_nodes_drain_total` | `slurm_nodes_drain`<br> `slurm_nodes_draining` <br> `slurm_nodes_drained` | Draining/drained nodes | `sinfo -t drain,drng -h -o "%D"`<br>`scontrol show nodes -o \| grep -E "State=DRAIN\|State=DRNG" \| wc -l` |
| `slurm_nodes_error_total` |  | Nodes in error state | `sinfo -t err -h -o "%D"` |
| `slurm_nodes_fail_total` | `slurm_nodes_fail` | Failed nodes | `sinfo -t fail -h -o "%D"` |
|  | `slurm_nodes_powered_down` | Number of nodes powered down | `sinfo -t powered_down -h -o "%D"` |
|  | `slurm_nodes_powering_up` | Number of nodes powering up | `sinfo -t powering_up -h -o "%D"` |