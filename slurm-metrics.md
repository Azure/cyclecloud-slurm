
### 1.1 Job Status Metrics (squeue snapshot)

| Description | Slurm Metrics Plugin Metric (25.11+) (all gauges)| sacct/squeue Command | slurmrestd query |
|-------------|-------------|----------------------------------|---------------|
|Total jobs in queue | `slurm_jobs`| `squeue -h \| wc -l` | `curl  -H X-SLURM-USER-TOKEN:$SLURM_JWT -X GET 'http://localhost:6820/slurmdb/v0.0.43/jobs/' \| jq '.jobs \| length'` |
|Jobs currently running | `slurm_jobs_running`| `squeue -t RUNNING -h \| wc -l` | `curl  -H X-SLURM-USER-TOKEN:$SLURM_JWT -X GET 'http://localhost:6820/slurmdb/v0.0.43/jobs/' #filter for RUNNING STATE` |
|Jobs waiting in queue | `slurm_jobs_pending` | `squeue -t PENDING -h \| wc -l` | `curl  -H X-SLURM-USER-TOKEN:$SLURM_JWT -X GET 'http://localhost:6820/slurmdb/v0.0.43/jobs/' #filter for PENDING STATE`|
|Jobs in configuring state | `slurm_jobs_configuring` | `squeue -t CONFIGURING -h \| wc -l` | `curl  -H X-SLURM-USER-TOKEN:$SLURM_JWT -X GET 'http://localhost:6820/slurmdb/v0.0.43/jobs/' #filter for CONFIGURING state`|
|Jobs in completing state |`slurm_jobs_completing` | `squeue -t COMPLETING -h \| wc -l` | `curl  -H X-SLURM-USER-TOKEN:$SLURM_JWT -X GET 'http://localhost:6820/slurmdb/v0.0.43/jobs/' #filter for COMPLETING STATE` |
|Jobs that failed | `slurm_jobs_failed`| `sacct -s FAILED --noheader \| wc -l`<br>`squeue -t FAILED -h \| wc -l` | `curl  -H X-SLURM-USER-TOKEN:$SLURM_JWT -X GET 'http://localhost:6820/slurmdb/v0.0.43/jobs/' #filter for FAILED State` |
|Jobs completed successfully | `slurm_jobs_completed`| `sacct -s COMPLETED --noheader \| wc -l`<br>`squeue -t COMPLETED -h \| wc -l` | `curl  -H X-SLURM-USER-TOKEN:$SLURM_JWT -X GET 'http://localhost:6820/slurmdb/v0.0.43/jobs/' #filter for COMPLETED State` |
|Jobs exceeded time limit |`slurm_jobs_timeout` | `sacct -s TIMEOUT --noheader \| wc -l` | `curl  -H X-SLURM-USER-TOKEN:$SLURM_JWT -X GET 'http://localhost:6820/slurmdb/v0.0.43/jobs/' #filter for TIMEOUT state` |
|Jobs failed due to node failure |`slurm_jobs_node_failed` | `sacct -s NODE_FAIL --noheader \| wc -l` | `curl  -H X-SLURM-USER-TOKEN:$SLURM_JWT -X GET 'http://localhost:6820/slurmdb/v0.0.43/jobs/' #filter for NODE_FAIL State` |
|Jobs that were cancelled |`slurm_jobs_cancelled` | `sacct -s CANCELLED --noheader \| wc -l` | `curl  -H X-SLURM-USER-TOKEN:$SLURM_JWT -X GET 'http://localhost:6820/slurmdb/v0.0.43/jobs/' #filter for CANCELLED STATE` |
|Jobs currently suspended |`slurm_jobs_suspended` | `squeue -t SUSPENDED -h \| wc -l` | `curl  -H X-SLURM-USER-TOKEN:$SLURM_JWT -X GET 'http://localhost:6820/slurmdb/v0.0.43/jobs/' #filter for SUSPENDED STATE` |
|Jobs that were preempted | `slurm_jobs_preempted` | `sacct -s PREEMPTED --noheader \| wc -l` | `curl  -H X-SLURM-USER-TOKEN:$SLURM_JWT -X GET 'http://localhost:6820/slurmdb/v0.0.43/jobs/' #filter for PREEMPTED state` |

### 1.2 Job Status Metrics (cumulative)
| Description | Slurm Metrics Plugin Metric (25.11+) (all gauges)| sacct/scontrol Command | slurmrestd query|
|-------------|-------------|----------------------------------|------------------|
|Total Number of jobs submitted since last reset |  | `sacct -S "$START" -E now -a -X -n --noheader\| wc -l`  | `curl -H X-SLURM-USER-TOKEN:$SLURM_JWT -X GET "http://localhost:6820/slurmdb/v0.0.43/jobs/  --data-urlencode "start_time=${START}" \| jq '.jobs \| length'` |
|Total Number of jobs completed since last reset |  | `sacct -S "$START" -E now -a -X -n -s COMPLETED --noheader\| wc -l`  | `curl -H X-SLURM-USER-TOKEN:$SLURM_JWT -X GET "http://localhost:6820/slurmdb/v0.0.43/jobs/ --data-urlencode "start_time=${START}" #filter for COMPLETED STATE` |
|Total Number of jobs failed since last reset |  | `sacct -S "$START" -E now -a -X -n -s CANCELLED --noheader\| wc -l` | `curl -H X-SLURM-USER-TOKEN:$SLURM_JWT -X GET "http://localhost:6820/slurmdb/v0.0.43/jobs/ --data-urlencode "start_time=${START}" #filter for FAILED STATE` |
|Total Number of jobs cancelled since last reset |  | `sacct -S "$START" -E now -a -X -n -s FAILED --noheader\| wc -l`| `curl -H X-SLURM-USER-TOKEN:$SLURM_JWT -X GET "http://localhost:6820/slurmdb/v0.0.43/jobs/ --data-urlencode "start_time=${START}" #filter for CANCELLED STATE` |


**sacct Notes:**
- Use `-S` and `-E` flags to specify time range (e.g., `-S now-1hour -E now`)
- `squeue` shows current queue state (real-time)
- `sacct` queries historical accounting database

**slurmrestd Notes:**

Slurmrestd provides extensive job metadata and we can parse it for job_state/state to get the metrics above as well as filter for specifc timestamps ie last reset to get cumulative values of job statuses. For the sake of simplicity, I didn't include specific commands to parse the output but json output can be parsed via python script. 

---
### 2. Node State Metrics 

| Description | Slurm Metrics Plugin Metric (25.11+) (all gauges)| sinfo/scontrol Command | slurmrestd query|
|-------------|-------------|----------------------------------|------------|
| Total number of nodes | `slurm_nodes` | `sinfo -N -h \| wc -l`<br>`scontrol show nodes -o \| wc -l` | `curl -H X-SLURM-USER-TOKEN:$SLURM_JWT -X GET 'http://localhost:6820/slurm/v0.0.43/nodes' \| jq '.nodes \| length'` |
| Nodes fully allocated | `slurm_nodes_alloc` | `sinfo -t alloc -h -o "%D"` | `curl -H X-SLURM-USER-TOKEN:$SLURM_JWT -X GET 'http://localhost:6820/slurm/v0.0.43/nodes' \| jq '[.nodes[] \| select(.state // [] \| contains(["ALLOCATED"]))] \| length'` |
| Idle nodes | `slurm_nodes_idle` | `sinfo -t idle -h -o "%D"` | `curl -H X-SLURM-USER-TOKEN:$SLURM_JWT -X GET 'http://localhost:6820/slurm/v0.0.43/nodes' \| jq '[.nodes[] \| select(.state // [] \| contains(["IDLE"]))] \| length'` |
| Partially allocated nodes | `slurm_nodes_mixed` | `sinfo -t mix -h -o "%D"` | `curl -H X-SLURM-USER-TOKEN:$SLURM_JWT -X GET 'http://localhost:6820/slurm/v0.0.43/nodes' \| jq '[.nodes[] \| select(.state // [] \| contains(["MIXED"]))] \| length'` |
| Nodes with completing jobs | `slurm_nodes_completing` | `sinfo -t comp -h -o "%D"` | `curl -H X-SLURM-USER-TOKEN:$SLURM_JWT -X GET 'http://localhost:6820/slurm/v0.0.43/nodes' \| jq '[.nodes[] \| select(.state // [] \| contains(["COMPLETING"]))] \| length'` |
| Nodes in maintenance | `slurm_nodes_maint` | `sinfo -t maint -h -o "%D"` | `curl -H X-SLURM-USER-TOKEN:$SLURM_JWT -X GET 'http://localhost:6820/slurm/v0.0.43/nodes' \| jq '[.nodes[] \| select(.state // [] \| contains(["MAINTENANCE"]))] \| length'` |
| Reserved nodes | `slurm_nodes_resv` | `sinfo -t resv -h -o "%D"` | `curl -H X-SLURM-USER-TOKEN:$SLURM_JWT -X GET 'http://localhost:6820/slurm/v0.0.43/nodes' \| jq '[.nodes[] \| select(.state // [] \| contains(["RESERVED"]))] \| length'` |
| Down nodes | `slurm_nodes_down` | `sinfo -t down -h -o "%D"`<br>`scontrol show nodes -o \| grep "State=DOWN" \| wc -l` | `curl -H X-SLURM-USER-TOKEN:$SLURM_JWT -X GET 'http://localhost:6820/slurm/v0.0.43/nodes' \| jq '[.nodes[] \| select(.state // [] \| contains(["DOWN"]))] \| length'` |
| Draining/drained nodes | `slurm_nodes_drain`<br> `slurm_nodes_draining` <br> `slurm_nodes_drained` | `sinfo -t drain,drng -h -o "%D"`<br>`scontrol show nodes -o \| grep -E "State=DRAIN\|State=DRNG" \| wc -l` | `curl -H X-SLURM-USER-TOKEN:$SLURM_JWT -X GET 'http://localhost:6820/slurm/v0.0.43/nodes' \| jq '[.nodes[] \| select(.state // [] \| contains(["DRAIN", "DRAINING", "DRAINED"]))] \| length'` |
| Failed nodes | `slurm_nodes_fail` | `sinfo -t fail -h -o "%D"` | `curl -H X-SLURM-USER-TOKEN:$SLURM_JWT -X GET 'http://localhost:6820/slurm/v0.0.43/nodes' \| jq '[.nodes[] \| select(.state // [] \| contains(["FAIL"]))] \| length'` |
| Number of nodes powered down | `slurm_nodes_powered_down` | `sinfo -t powered_down -h -o "%D"` | `curl -H X-SLURM-USER-TOKEN:$SLURM_JWT -X GET 'http://localhost:6820/slurm/v0.0.43/nodes' \| jq '[.nodes[] \| select(.state // [] \| contains(["POWERED_DOWN"]))] \| length'` |
| Number of nodes powering up | `slurm_nodes_powering_up` | `sinfo -t powering_up -h -o "%D"` | `curl -H X-SLURM-USER-TOKEN:$SLURM_JWT -X GET 'http://localhost:6820/slurm/v0.0.43/nodes' \| jq '[.nodes[] \| select(.state // [] \| contains(["POWERING_UP"]))] \| length'` |
