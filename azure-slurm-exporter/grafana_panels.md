# Grafana Panels

## Partition Specifications Table

| Spec | hpc | htc | gpu | dynamic |
|------|-----|-----|-----|---------|
| **partition** | hpc | htc | gpu | dynamic |
| **node_list** | azslurm-exporter-hpc-[1-16] | azslurm-exporter-htc-[1-50] | N/A | N/A |
| **vm_size** | Standard_F2s_v2 | Standard_F2s_v2 | Standard_NC24rs_v3 | Standard_F2s_v2 |
| **available_nodes** | 16 | 34 | 0 | 34 |

### How to Create This Table in Grafana

**Panel Type:** Table

**Query:**
```promql
azslurm_partition_info
```
**Format:** Table (or Instant)

**Transformations (Working Approach):**

1. **Series to rows**
   - This converts each time series frame into table rows
   
2. **Organize fields**
   - Hide: `Time`
   - Keep: `partition`, `node_list`, `vm_size`, `Value`
   - Reorder: Move `Value` to last position

3. **Partition by values**
   - **Field:** `partition`
   - This pivots partition values into separate columns (hpc, htc, gpu, dynamic)
   
4. **Organize fields** (optional - for final cleanup)
   - Rename columns and set display order
   - First column shows the spec row names

**Alternative Approach Using Separate Queries:**

Create 4 separate queries, one for each partition:

**Query A (hpc):**
```promql
azslurm_partition_info{partition="hpc"}
```
Legend: `{{partition}}`

**Query B (htc):**
```promql
azslurm_partition_info{partition="htc"}
```
Legend: `{{partition}}`

**Query C (gpu):**
```promql
azslurm_partition_info{partition="gpu"}
```
Legend: `{{partition}}`

**Query D (dynamic):**
```promql
azslurm_partition_info{partition="dynamic"}
```
Legend: `{{partition}}`

**Format:** Table

**Transformations:**
1. **Outer join** (joins all queries by time)
2. **Organize fields**
   - Rename fields to show spec names:
     - `node_list` → `node_list`
     - `vm_size` → `vm_size`
     - `partition` → `partition`
     - `Value A` → `hpc`
     - `Value B` → `htc`
     - `Value C` → `gpu`
     - `Value D` → `dynamic`

**Manual Table Creation (Simplest):**

For a static table showing all specs in one view, use an **Instant query** and manual field mapping:

1. Set **Format:** Table
2. Query: `azslurm_partition_info`
3. **Transformations:**
   - **Group by** → `partition` field
   - **Reduce** → Show all fields
   - Create calculated fields for each spec row using the labels
