# Slurm Exporter Integration Tests

Comprehensive integration test suite for the Azure Slurm Prometheus Exporter with schema-based architecture.

## Test Execution

```bash
# Run all tests
python -m pytest test/test_exporter_integration.py -v

# Run specific test class
python -m pytest test/test_exporter_integration.py::TestClusterInfoMetrics -v

# Run specific test
python -m pytest test/test_exporter_integration.py::TestClusterInfoMetrics::test_cluster_info_caching -v
```

## Test Coverage Summary

- **25 total tests** covering all major components
- **100% pass rate** on schema-based refactored architecture
- Tests use mocking to simulate Slurm and Azure command outputs
- Validates metric collection, parsing, caching, and error handling

---

## Test Classes

### 1. TestSlurmMetricsCollector

Tests the main `SlurmMetricsCollector` class that orchestrates metric collection.

#### test_init_default_reset_time
**Purpose**: Verify collector initializes with default reset time  
**Expected**: `reset_time` defaults to "24 hours ago"  
**Validates**: Default configuration for cumulative metrics

#### test_init_custom_reset_time
**Purpose**: Test custom reset time configuration  
**Expected**: Accepts custom values like "7 days ago"  
**Validates**: Configurable time windows for historical metrics

#### test_init_custom_timeout
**Purpose**: Test command execution timeout configuration  
**Expected**: Timeout value propagates to executor  
**Validates**: Configurable timeout prevents hung commands

#### test_collect_includes_job_metrics
**Purpose**: Verify job queue metrics are collected  
**Mocks**: `collect_job_queue_metrics()` returns job counts  
**Expected**: Metrics like `squeue_jobs`, `squeue_jobs_running`, `squeue_jobs_pending`  
**Validates**: Core job queue metrics exported correctly

#### test_collect_includes_partition_metrics_with_labels
**Purpose**: Test partition-specific metrics include partition labels  
**Mocks**: `collect_partition_job_metrics()` returns per-partition data  
**Expected**: Metrics have `partition` label (e.g., `partition="hpc"`)  
**Validates**: Partition-level monitoring capability

#### test_collect_groups_partition_metrics_correctly
**Purpose**: Verify same metric name for different partitions is grouped  
**Mocks**: Two partitions (hpc, htc) with same metric names  
**Expected**: Single metric family with multiple partition labels  
**Validates**: Proper Prometheus metric grouping (not duplicated metric names)

#### test_collect_includes_cumulative_metrics
**Purpose**: Test historical/total metrics are included  
**Mocks**: `collect_job_history_metrics()` returns totals  
**Expected**: Metrics like `sacct_jobs_total_completed`, `sacct_jobs_total_failed`  
**Validates**: Long-term trend tracking capability

#### test_collect_includes_meta_metrics
**Purpose**: Verify exporter emits operational metrics  
**Mocks**: All collection methods to avoid errors  
**Expected**: `slurm_exporter_collect_duration_seconds`, `slurm_exporter_last_collect_timestamp_seconds`  
**Validates**: Exporter health monitoring and performance tracking

#### test_collect_handles_exceptions
**Purpose**: Test graceful error handling during collection  
**Mocks**: One method raises exception  
**Expected**: Error metric `slurm_exporter_errors_total` is emitted  
**Validates**: Exporter doesn't crash on command failures

#### test_collect_partition_history_metrics_grouped
**Purpose**: Verify partition history metrics are properly grouped  
**Mocks**: Per-partition historical data  
**Expected**: Single metric family with partition labels, not separate metrics  
**Validates**: Consistent metric structure for historical data

---

### 2. TestMetricValues

Tests metric value formatting and validation.

#### test_metric_values_are_floats
**Purpose**: Ensure all metric values are numeric types  
**Expected**: All samples have `int` or `float` values  
**Validates**: Prometheus compatibility (requires numeric values)

#### test_metric_values_non_negative
**Purpose**: Verify count/gauge metrics are non-negative  
**Expected**: Values >= 0 (except duration which can be any positive)  
**Validates**: Logical consistency (can't have negative job counts)

---

### 3. TestSchemaBasedCollection

Tests the new schema-based architecture implementation.

#### test_schemas_imported_correctly
**Purpose**: Verify all required schemas are available  
**Expected**: `JOB_QUEUE_SCHEMAS`, `NODE_SCHEMAS`, `PARTITION_LIST_SCHEMA`, `CLUSTER_INFO_SCHEMAS` exist  
**Validates**: Schema module structure is correct

#### test_parsers_imported_correctly
**Purpose**: Verify all parser functions are available and callable  
**Expected**: `parse_azslurm_config`, `parse_azslurm_buckets`, `parse_azslurm_limits`, `parse_scontrol_nodes_json`  
**Validates**: Parser module completeness

---

### 4. TestClusterInfoMetrics

Tests the refactored `collect_cluster_info()` method that was split into schemas and parsers.

#### test_cluster_info_collection
**Purpose**: Test complete cluster info collection workflow  
**Mocks**: Command outputs for:
  - `azslurm config` → cluster name, subscription ID
  - `jetpack config` → Azure region, resource group
  - `azslurm buckets` → partition details
  - `sinfo` → node lists per partition
  - `azslurm limits` → Azure quota information  
**Expected**: Dictionary with:
  - `cluster_name`, `subscription_id`, `region`, `resource_group`
  - `partitions[]` array with partition metadata  
**Validates**: End-to-end cluster metadata collection

#### test_cluster_info_caching
**Purpose**: Verify cluster info is cached to avoid excessive command execution  
**Mocks**: Command execution tracking  
**Expected**: Second call within TTL doesn't execute commands  
**Validates**: Performance optimization (1-hour cache)

#### test_cluster_info_cache_expiration
**Purpose**: Test cache expires after TTL (time-to-live)  
**Setup**: Sets `_cache_ttl = 1` second for testing  
**Expected**: After 2 seconds, commands re-execute  
**Validates**: Cache doesn't serve stale data indefinitely

---

### 5. TestAzureQuotaMetrics

Tests Azure quota parsing from `azslurm limits` command.

#### test_parse_azslurm_limits
**Purpose**: Test parsing of Azure quota limits JSON  
**Input**: JSON with `family_available_count` and `regional_available_count`  
**Expected**: Returns `{nodearray:vm_size → min(family, regional)}`  
**Example**: 
  - Input: family=10, regional=8 → Output: 8
  - Input: family=5, regional=12 → Output: 5  
**Validates**: Quota calculation uses most restrictive limit

#### test_parse_azslurm_limits_filters_placement_groups
**Purpose**: Verify placement group entries are excluded  
**Input**: JSON with `placement_group: true/false`  
**Expected**: Only entries with `placement_group: false` included  
**Rationale**: Placement groups are internal subdivisions, not user-facing partitions  
**Validates**: Correct quota aggregation (no double-counting)

---

### 6. TestPartitionMetrics

Tests partition parsing from `azslurm buckets` command.

#### test_parse_azslurm_buckets
**Purpose**: Test parsing of partition/bucket table output  
**Input**: Table with columns:
  - `NODEARRAY` (partition name)
  - `VM_SIZE` (Azure VM SKU)
  - `AVAILABLE_COUNT` (node capacity)  
**Expected**: Array of `{name, vm_size, total_nodes}` dicts  
**Validates**: Partition metadata extraction

#### test_parse_azslurm_buckets_filters_pg
**Purpose**: Verify `_pg` (placement group) entries are filtered  
**Input**: Buckets with names like `hpc` and `hpc_pg0`  
**Expected**: Only `hpc` included (no `hpc_pg0`)  
**Rationale**: Placement groups are internal, not separate partitions  
**Validates**: Deduplication logic works correctly

---

### 7. TestEndToEndIntegration

End-to-end tests simulating real exporter operation.

#### test_full_metric_collection_cycle
**Purpose**: Test complete metric collection with all components  
**Mocks**: All Slurm/Azure commands with realistic outputs  
**Flow**:
  1. Job queue metrics (squeue)
  2. Historical metrics (sacct)
  3. Node metrics (scontrol)
  4. Partition info (scontrol show partitions)
  5. Cluster info (azslurm config, jetpack, buckets, limits)  
**Expected**: Multiple metric categories produced  
**Validates**: Full integration of all collection methods

#### test_error_handling_with_command_failures
**Purpose**: Test exporter resilience to command failures  
**Mocks**: All commands raise exceptions  
**Expected**: Error metric emitted, exporter doesn't crash  
**Validates**: Production reliability (partial data better than no data)

---

### 8. TestRealClusterScenarios

Tests based on actual cluster configurations observed in production.

#### test_handles_empty_partitions
**Purpose**: Test partitions with zero available nodes  
**Input**: Bucket with `AVAILABLE_COUNT = 0`  
**Expected**: Partition included with `total_nodes = "0"`  
**Scenario**: Dynamic partition or maintenance mode  
**Validates**: Handles edge case without errors

#### test_handles_multiple_vm_sizes_per_partition
**Purpose**: Test partition with heterogeneous VM types  
**Input**: Same partition name with different VM_SIZE entries  
**Expected**: Separate entries for each VM size  
**Scenario**: Mixed instance partition (e.g., F2 and F4 in same partition)  
**Validates**: Multi-instance-type support

---

## Key Testing Patterns

### Mocking Strategy
Tests use `unittest.mock.patch` to mock:
- Command execution (`run_command`)
- Executor methods (`collect_*_metrics`)
- External dependencies (Slurm, Azure CLI)

### Realistic Data
Mock outputs simulate actual command formats:
```python
# azslurm config
'{"cluster_name": "test-cluster", "accounting": {"subscription_id": "sub-123"}}'

# azslurm buckets
'NODEARRAY  VM_SIZE         VCPU_COUNT PCPU_COUNT MEMORY AVAILABLE_COUNT\nhpc        Standard_F2s_v2 2          2          16384  8'

# azslurm limits
'[{"nodearray": "hpc", "vm_size": "Standard_F2s_v2", "family_available_count": 10, "regional_available_count": 8}]'
```

### Assertion Strategies
- **Presence checks**: Verify metrics exist in output
- **Label validation**: Ensure partition/state labels present
- **Grouping tests**: Confirm metrics grouped correctly (not duplicated)
- **Value validation**: Check numeric types and non-negative values
- **Error scenarios**: Verify graceful degradation

---

## Test Data Flow

```
┌─────────────────────────────────────────────────────────┐
│ SlurmMetricsCollector.collect()                         │
└─────────────────┬───────────────────────────────────────┘
                  │
                  ├─► collect_job_queue_metrics()
                  │   └─► JOB_QUEUE_SCHEMAS → parse_count_lines()
                  │
                  ├─► collect_job_history_metrics()
                  │   └─► JOB_HISTORY_OPTIMIZED_SCHEMA → parse_sacct_job_history()
                  │
                  ├─► collect_node_metrics()
                  │   └─► NODE_SCHEMAS → parse_scontrol_nodes_json()
                  │
                  ├─► collect_partition_*_metrics()
                  │   └─► Per-partition schemas with partition label
                  │
                  └─► collect_cluster_info()  [NEW REFACTORED]
                      ├─► CLUSTER_INFO_SCHEMAS['azslurm_config'] → parse_azslurm_config()
                      ├─► CLUSTER_INFO_SCHEMAS['jetpack_location']
                      ├─► CLUSTER_INFO_SCHEMAS['jetpack_resource_group']
                      ├─► CLUSTER_INFO_SCHEMAS['azslurm_buckets'] → parse_azslurm_buckets()
                      ├─► CLUSTER_INFO_SCHEMAS['sinfo_nodes']
                      └─► CLUSTER_INFO_SCHEMAS['azslurm_limits'] → parse_azslurm_limits()
```

---

## Coverage Highlights

### Schema-Based Architecture ✅
- All schemas imported and structured correctly
- All parsers callable and tested
- Command execution through schema abstraction

### Cluster Info Refactoring ✅
- Replaced 137-line inline code with schema-based approach
- Caching tested (1-hour TTL)
- Cache expiration tested
- All 6 cluster info schemas validated

### Azure Integration ✅
- Quota calculation (min of family/regional limits)
- Placement group filtering
- Multi-VM-size partition support
- Empty partition handling

### Error Resilience ✅
- Command failure handling
- Exception propagation tested
- Error metrics emitted
- Partial data collection continues

### Prometheus Compatibility ✅
- Metric grouping validated
- Label structure correct
- Value types validated (float/int)
- Non-negative values enforced

---

## Future Test Enhancements

### Potential Additions
1. **Performance tests**: Measure collection duration under load
2. **Memory tests**: Verify no memory leaks in long-running scenarios
3. **Concurrency tests**: Test parallel metric collection
4. **Integration with real Prometheus**: End-to-end scraping tests
5. **Edge case expansion**: More real-world scenarios from production clusters
6. **Schema validation tests**: Ensure schemas produce valid commands
7. **Parser robustness**: Test malformed command outputs

### Test Maintenance
- Update mocks when command formats change
- Add tests for new metrics as features are added
- Maintain realistic mock data based on production observations
- Document breaking changes in test behavior

---

## Running Tests in CI/CD

### Prerequisites
```bash
pip install pytest prometheus-client
```

### GitHub Actions Example
```yaml
- name: Run Integration Tests
  run: |
    cd azure-slurm
    pytest test/test_exporter_integration.py -v --tb=short
```

### Coverage Report
```bash
pytest test/test_exporter_integration.py --cov=exporter --cov-report=html
```

---

## Test Philosophy

These tests follow the **"Test Behavior, Not Implementation"** principle:
- Tests validate **what** the exporter does (metrics produced)
- Tests don't over-specify **how** it does it (internal logic)
- Mocking isolates units from external dependencies
- Tests remain stable across refactoring (as proven by schema-based refactor)

The comprehensive test suite ensures the exporter:
1. **Collects accurate metrics** from Slurm and Azure
2. **Handles errors gracefully** without crashing
3. **Performs efficiently** with caching and optimization
4. **Exports correct format** for Prometheus consumption
5. **Maintains functionality** across code changes
