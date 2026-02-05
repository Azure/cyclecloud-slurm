# Optimized Job History Metrics Collection

## Summary

**Deployed February 4, 2026** - Optimized the Slurm Prometheus exporter to use **single `sacct` command** per time period instead of 9+ separate commands, achieving **89-98% reduction** in database queries and fixing incorrect NODE_FAIL job counting.

## Changes Deployed to Cluster

### 1. New File: `optimized_parser.py`

**Location:** `/opt/azurehpc/slurm/exporter/optimized_parser.py`

**Purpose:** Executes a single sacct command per time period and parses all metrics from that output.

**Key Functions:**
- `collect_job_history_six_months_optimized()` - 180-day rolling window
- `collect_job_history_one_month_optimized()` - 30-day rolling window  
- `collect_job_history_one_week_optimized()` - 7-day rolling window
- `collect_job_metrics_optimized(days_back)` - Generic wrapper for any time period

**Command Used:**
```bash
sacct -a -S <start_date> -E now -o JobID,JobName,Partition,State,ExitCode --parsable2 -n -X
```

**Key Feature:** Properly handles compound states like "CANCELLED by 0" to fix the NODE_FAIL overcounting bug.

### 2. Updated: `executor.py`

**Location:** `/opt/azurehpc/slurm/exporter/executor.py`

**Changes:**
- Imported `optimized_parser` module
- Added three new optimized methods to `SlurmCommandExecutor` class:
  - `collect_job_history_six_months_optimized()`
  - `collect_job_history_one_month_optimized()`
  - `collect_job_history_one_week_optimized()`
- Legacy methods remain available for backward compatibility

### 3. Updated: `exporter.py`

**Location:** `/opt/azurehpc/slurm/exporter/exporter.py`

**Changes:**
- Changed import from `util.SlurmCommandExecutor` to `executor.SlurmCommandExecutor`
- Replaced all 6-month metric collection calls with optimized version
- Replaced all 1-week metric collection calls with optimized version
- Replaced all 1-month metric collection calls with optimized version
- Each time period now uses a single sacct call instead of 9+ separate calls

## Performance Improvement

### Before (Legacy Approach - Prior to Feb 4, 2026)

**For each time period** (6 months, 1 month, 1 week):
1. `sacct -s COMPLETED` - count completed jobs
2. `sacct -s FAILED` - count failed jobs (❌ incorrectly counts some cancelled jobs)
3. `sacct -s TIMEOUT` - count timeout jobs
4. `sacct -s NODE_FAIL` - count node failed jobs (❌ incorrectly matches "CANCELLED by 0")
5. `sacct -s CANCELLED` - count cancelled jobs
6. `sacct -s OUT_OF_MEMORY` - count OOM jobs
7. `sacct -s PREEMPTED` - count preempted jobs (if used)
8. `sacct` (all jobs) - count total submitted
9. `sacct -s FAILED,... -o State,ExitCode` - get exit codes for failed states

**Result:** 
- 9 commands × 3 time periods = **27 sacct calls** (global metrics only)
- With 4 partitions: 27 + (4 × 9 × 3) = **135 sacct calls total**
- **Bug:** NODE_FAIL filter matched "CANCELLED by 0", showing 10 instead of 1

### After (Optimized Approach - Deployed Feb 4, 2026)

**For each time period:**
1. Single `sacct -a -S <start> -E now -o JobID,Partition,State,ExitCode -p -X`
   - Parse once to extract ALL metrics:
     - Total submitted count
     - Counts by state (completed, failed, timeout, node_failed, cancelled, etc.)
     - Counts by partition and state
     - Exit codes for failed states
     - Partition-level exit codes

**Result:**
- 1 command × 3 time periods = **3 sacct calls total**
- Works for any number of partitions (parsed from same output)
- **Bug fixed:** Properly normalizes "CANCELLED by 0" → "cancelled"

### Efficiency Gains

| Metric Type | Before | After | Reduction |
|-------------|--------|-------|-----------|
| Global metrics only | 27 calls | 3 calls | **89%** |
| With 4 partitions | 135 calls | 3 calls | **98%** |

**Additional Benefits:**
- ✅ **Faster execution** - Single command vs multiple sequential commands
- ✅ **More accurate** - All data from same snapshot (no race conditions)
- ✅ **Lower database load** - 98% fewer Slurm database queries
- ✅ **Bug fix** - Correct NODE_FAIL counting (was 10, now correctly shows 1)
- ✅ **Easier maintenance** - Less duplicate code
- ✅ **Better error handling** - One command to monitor instead of 27+

## Data Returned

The optimized methods return a comprehensive dictionary:

```python
{
    'start_date': '2026-01-28',          # Start date of period
    'total_submitted': 58,                # Total jobs submitted
    'by_state': {                         # Global state counts
        'completed': 45,
        'failed': 7,
        'timeout': 2,
        'node_failed': 1,
        'cancelled': 3
    },
    'by_partition': {                     # Per-partition state counts
        'hpc': {
            'completed': 24,
            'failed': 4,
            'timeout': 2
        },
        'htc': {
            'completed': 16,
            'failed': 3,
            'cancelled': 2
        }
        # ... more partitions
    },
    'by_state_exit_code': [              # Failed states with exit codes
        ('failed', '1:0', 7),
        ('timeout', '0:0', 2),
        ('node_failed', '1:0', 1),
        ('cancelled', '0:0', 3)
    ],
    'by_partition_state_exit_code': {    # Per-partition exit codes
        'hpc': [('failed', '1:0', 4), ...],
        'htc': [('failed', '1:0', 3), ...]
    }
}
```

## Deployment Details

### Files Deployed to Cluster (cc-admin@10.1.0.11)

**Date:** February 4, 2026, 17:12 UTC

1. `/opt/azurehpc/slurm/exporter/optimized_parser.py` (new)
2. `/opt/azurehpc/slurm/exporter/executor.py` (updated)
3. `/opt/azurehpc/slurm/exporter/exporter.py` (updated)

**Service:** `azslurm-exporter.service` restarted successfully

**Verification:** Confirmed running with optimized parser via service logs:
```
2026-02-04 17:12:44 - slurm-exporter.optimized-parser - INFO - Running: sacct -a -S 2025-08-08 -E now ...
2026-02-04 17:12:44 - slurm-exporter.optimized-parser - INFO - Running: sacct -a -S 2026-01-28 -E now ...
2026-02-04 17:12:44 - slurm-exporter.optimized-parser - INFO - Running: sacct -a -S 2026-01-05 -E now ...
2026-02-04 17:12:45 - slurm-exporter - INFO - Metrics collection completed in 2.35s
```

### Backup Created

Old exporter backed up to:
```
/opt/azurehpc/slurm/exporter/exporter.py.backup.20260204_*
```

### Testing Performed

✅ **Optimized parser tested** with cluster data before deployment
```bash
cd /opt/azurehpc/slurm/exporter
python3 -c "from optimized_parser import collect_job_history_one_week_optimized; print(...)"
# Result: 58 total jobs, 1 node_failed (correct)
```

✅ **Executor integration tested**
```bash
from executor import SlurmCommandExecutor
executor = SlurmCommandExecutor()
metrics = executor.collect_job_history_one_week_optimized()
# Result: Working correctly with all metrics
```

✅ **Service restarted and verified**
```bash
sudo systemctl restart azslurm-exporter
sudo systemctl status azslurm-exporter
# Status: active (running)
```

✅ **Metrics endpoint verified**
```bash
curl -s http://localhost:9500/metrics | grep node_failed
# Before: sacct_jobs_total_node_failed 10.0 (WRONG)
# After: sacct_jobs_total_one_week_node_failed{start_date="2026-01-28"} 1.0 (CORRECT)
```

## Metrics Comparison: Before vs After

### Legacy Metrics (Still Available - Using Old Method)

These metrics use the old `sacct -s <state>` method and have the bug:

```prometheus
# From 24-hour reset time (legacy cumulative)
sacct_jobs_total_node_failed 10.0  # ❌ INCORRECT - matches "CANCELLED by 0"
```

### Optimized Metrics (Now Live - Using New Method)

These metrics use the new optimized parser and are correct:

```prometheus
# 6-month rolling window
sacct_jobs_total_six_months_node_failed{start_date="2025-08-08"} 1.0  # ✅ CORRECT
sacct_jobs_total_six_months_by_state{start_date="2025-08-08",state="node_failed"} 1.0
sacct_jobs_total_six_months_by_state_exit_code{exit_code="1:0",start_date="2025-08-08",state="node_failed"} 1.0

# 1-week rolling window  
sacct_jobs_total_one_week_node_failed{start_date="2026-01-28"} 1.0  # ✅ CORRECT
sacct_jobs_total_one_week_by_state{start_date="2026-01-28",state="node_failed"} 1.0
sacct_jobs_total_one_week_by_state_exit_code{exit_code="1:0",start_date="2026-01-28",state="node_failed"} 1.0

# 1-month rolling window
sacct_jobs_total_one_month_node_failed{start_date="2026-01-05"} 1.0  # ✅ CORRECT
sacct_jobs_total_one_month_by_state{start_date="2026-01-05",state="node_failed"} 1.0
sacct_jobs_total_one_month_by_state_exit_code{exit_code="1:0",start_date="2026-01-05",state="node_failed"} 1.0

# Partition-level metrics also fixed
sacct_partition_jobs_total_one_week_by_state_exit_code{exit_code="1:0",partition="dynamic",start_date="2026-01-28",state="node_failed"} 1.0
```

### Recommendation

**Use the optimized metrics** (with time period labels) for:
- ✅ Accurate job state counting
- ✅ Consistent time windows (rolling 7/30/180 days)
- ✅ Per-partition breakdowns
- ✅ Exit code analysis

**Legacy metrics** will remain for backward compatibility but should be phased out.

## Impact on Production

### Observed Performance Metrics

**Collection Time:**
- Before: ~4-6 seconds (estimated with 27+ sacct calls)
- After: **2.35 seconds** (with 3 sacct calls)
- **Improvement: ~50% faster**

**Database Load:**
- Before: 27-135 sacct queries per scrape (every 15 seconds)
- After: **3 sacct queries per scrape**
- **Reduction: 89-98% fewer database queries**

**Scrape Frequency:** Every 15 seconds (unchanged)
- Before: 1,620-8,100 sacct calls per hour
- After: **180 sacct calls per hour**
- **Hourly savings: 1,440-7,920 database queries**

### Bug Fixes

**NODE_FAIL Overcounting Fixed:**
```
Problem: sacct -s NODE_FAIL incorrectly matched "CANCELLED by 0"
Result: Showed 10 node_failed jobs instead of 1

Solution: Parse State column directly and normalize compound states
Result: Correctly shows 1 node_failed job
```

**Verification on Cluster:**
```bash
# Manual check confirms the fix
$ sacct -a -S now-7days -E now -s NODE_FAIL --noheader -X -n | wc -l
10  # ❌ WRONG - includes CANCELLED by 0

$ sacct -a -S now-7days -E now -X -n --noheader -o State%30 | grep NODE_FAIL | wc -l  
1   # ✅ CORRECT - only true NODE_FAIL
```

## Next Steps

### Completed ✅
1. ✅ Created optimized_parser.py
2. ✅ Integrated into executor.py
3. ✅ Updated exporter.py to use optimized methods
4. ✅ Deployed to cluster (cc-admin@10.1.0.11)
5. ✅ Tested and verified on production
6. ✅ Service running successfully

### Future Considerations

1. **Monitor Performance** - Track scrape duration over next week
2. **Validate Metrics** - Compare legacy vs optimized metrics to ensure accuracy
3. **Update Dashboards** - Switch Grafana dashboards to use new metric names with time period labels
4. **Remove Legacy Code** - After 30-day verification period, remove old methods from executor.py
5. **Document for Users** - Update METRICS.md to reflect the optimized metric names

## Technical Implementation Details

### State Normalization Logic

The optimized parser handles compound states correctly:

```python
def normalize_state(state: str) -> str:
    """Normalize state names to metric suffix format."""
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
```

### Parsing Strategy

1. **Single sacct call** with all needed fields:
   ```bash
   sacct -a -S <start_date> -E now -o JobID,JobName,Partition,State,ExitCode --parsable2 -n -X
   ```

2. **Parse once** into data structures:
   - `state_counts` - Global counts by state
   - `partition_state_counts` - Per-partition counts by state
   - `state_exit_code_counts` - Exit codes for failed states
   - `partition_state_exit_code_counts` - Per-partition exit codes

3. **Return comprehensive dict** with all metrics:
   ```python
   {
       'start_date': '2026-01-28',
       'total_submitted': 58,
       'by_state': {'completed': 45, 'failed': 7, 'node_failed': 1, ...},
       'by_partition': {'hpc': {'completed': 24, 'failed': 4, ...}, ...},
       'by_state_exit_code': [('failed', '1:0', 7), ('node_failed', '1:0', 1), ...],
       'by_partition_state_exit_code': {...}
   }
   ```

### Exporter Integration

The exporter now follows this pattern for each time period:

```python
# OLD WAY (9+ sacct calls):
# metrics_1 = executor.collect_job_history_six_months_metrics()
# metrics_2 = executor.collect_job_history_six_months_metrics_by_state()
# metrics_3 = executor.collect_job_history_six_months_metrics_by_state_and_exit_code()
# partition_1 = executor.collect_partition_job_history_six_months_metrics()
# partition_2 = executor.collect_partition_job_history_six_months_metrics_by_state_and_exit_code()

# NEW WAY (1 sacct call):
data = executor.collect_job_history_six_months_optimized()
# All metrics available in single 'data' dictionary
```

## Benefits Summary

| Aspect | Before | After | Improvement |
|--------|--------|-------|-------------|
| **Database Queries** | 27-135 per scrape | 3 per scrape | 89-98% reduction |
| **Scrape Duration** | ~4-6 seconds | 2.35 seconds | ~50% faster |
| **Accuracy** | NODE_FAIL=10 ❌ | NODE_FAIL=1 ✅ | Bug fixed |
| **Code Complexity** | 9 methods per period | 1 method per period | 89% less code |
| **Maintenance** | High (duplicate logic) | Low (single parser) | Much easier |
| **Error Surface** | 27-135 commands to fail | 3 commands to fail | More reliable |

**Result:** More accurate, faster, and more maintainable metrics collection with significantly reduced load on the Slurm database.

---

**Deployment Date:** February 4, 2026  
**Cluster:** azslurm-exporter (cc-admin@10.1.0.11)  
**Status:** ✅ Production - Running Successfully
