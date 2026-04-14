# Azure Slurm Exporter HA mode

**Goals**:
 - Ensure only the active controller exports metrics to prevent duplicate data in Prometheus dashboards.
 - Ensure we are exporting accurate data at all times ( ie between failover)


## Considerations:
**Exporter only runs on primary**: start the exporter on the backup when it becomes primary
- Pros:
    - let slurm handle failover detection via hooks
- Cons:
    - won't have full job history since backup wasnt keeping track
    - if controller goes down slurm hooks wont run
- would have to still stop original controller from exporting somehow


**Exporters run on both primary and BACKUP**
- Both controllers will collect metrics:
    - Pros:
        -   Job history data is accurate
        -   Simple infrastructure, continue to collect only export when active controller
        -   Dont need to consider stopping collect tasks when controller is down
    - Cons:
        -   2x load on slurmctld
- Only active controller collects and exports:
    - Pros:
        -   Less load on slurmctld
    - Cons:
        -   More complex
        -   need to figure out how to conserve job history

**Sacct Job History**:
- primary node and backup node runs sacct collector to keep track of job history counter
    - Pros:
        - During failover, backup will have accurate data
    - Cons:
        - 2x load on system duplicated work
- active controller only runs sacct collector but saves state of counter in State Save location
    - Pros:
        - 1x load on system
        - even if azslurm-exporter crashes it will load last counter data
        - backup will load last counter data at failover

**Failover Detection**:
- SlurmctldPrimaryOnProg, SlurmctldPrimaryOffProg
    - Pros:
        - Slurm handles failover detection:
        - can send a signal to exporter to inidicate that it is primary or backup now (controller has to be up for these programs to work)
    - Cons:
        - SlurmctldPrimaryOffProg doesnt run when a controller goes down/hangs

- scontrol ping
    - Pros:
        - tells us which controllers are up
        - if both controllers are up then primary is always the active one
        - can figure out which controller is active by applying logic
    - STATES:

            primary: up
            backup: up
            active: primary

            primary: down
            backup: up
            active: backup

            primary: down
            backup: down
            active : None

            primary: up
            backup: down
            active: primary

- slurmctld systemd
    - Pros:
        - can parse "Running as Primary Controller" to detect failover
        - can parse " slurmctld running in background mode" to detect when backup mode
        - can gate on whether slurmctld is active or not
    - Cons:
        - can't figure out when primary relinqueshes control in logs if it goes down
        - slow

## Design Decisions

Scontrol ping to detect failover:
 - gives us most accurate active controller at a given time

Exporter Runs on both nodes:
 - When exporter detects it is not the active controller it will run in idle mode -- no collecting or exporting
 - When exporter detects it is the active controller it will run in active mode -- collecting and exporting

Exporter in active mode will save sacct job counter state in save state location for backup to load in when failover occurs or when azslurm-exporter crashes on primary it can still load in last state if avail
 - All other collectors are gauges and stateless so they can just start when exporter goes in active mode

Create a background role transition handling task method in CompositeCollector to continuosly check the role of the controller (if it is active or not) every 30s because SlurmCtldTimeout is 30s
- if transitions from not active to active  start all collectors
- if transitions from active to not active stop all collectors
- no transition = no op
- save all active collectors in a list

collect function will now export metrics only from active collectors list

Prometheus is configured on both nodes and will ingest from both exporters but exporters will be the one
limiting metrics

## Abstract Proposal:

```
class ControllerRoleChecker():
    Methods:
    - initialize()         → Detect if HA is enabled using jetpack config slurm.ha_enabled
    - check_role()        → Run scontrol ping to determine role using logic
    - is_ha_enabled()      → Return if cluster is in HA mode
```
```
class Sacct(Base Collector):
    New Methods:
    _load_state()
    → Read state JSON from StateSaveLocation
    → Restore time window (starttime, endtime)
    → Restore counter values for all labels
    → if doesnt exist -- counter starts at 0 starttime = 1 hour before

    _save_state()
    → Write state JSON to StateSaveLocation
    → Include: hostname, timestamp, time_window, counters
    → Use atomic write (temp file + rename)
    → Use file locking (fcntl) to prevent corruption

    File location:
    /sched/{cluster_name}/spool/slurmctld/sacct_exporter_state.json
    {
    "version": "1.0",
    "hostname": "scheduler-1",
    "timestamp": 1713115950,
    "time_window": {
        "starttime": "2026-04-14T16:47:00",
        "endtime": "2026-04-14T16:52:00"
        },
    "counters": {
        "partition=hpc,exit_code=0:0,reason=,state=completed": 1234
        }
    }
```


```
Current CompositeCollector intialize_collectors method:
    1. Initialize all collectors (Squeue, Sacct, Sinfo, Azslurm, Jetpack)
    2. Start all collectors
```

```
Proposed Flow:
    1. Initialize ControllerRoleChecker (if HA enabled)
    └─ ControllerRoleChecker.initialize()
    └─ Detect HA mode

    2. Determine initial role
    └─ is_primary = ControllerRoleChecker.check_role()

    3. Initialize ALL collectors (regardless of role)
    └─ Squeue, Sacct, Sinfo, Azslurm, Jetpack
    └─ All collectors call initialize() but NOT start()

    4. Start collectors based on role
    IF PRIMARY:
        └─ Start all collectors
    ELSE (BACKUP):
        └─ Don't start any collectors (mode)
```
Add background role transition handling task method in CompositeCollector (runs every 30s)

```
async _monitor_role_transitions()
    Get current role from ControllerRoleChecker
    ├─ Compare with previous role
    ├─ If changed from BACKUP → PRIMARY:
    │   └─ Call _start_all_collectors()
    ├─ If changed from PRIMARY → BACKUP:
    │   └─ Call _stop_all_collectors()
    └─ Update previous_role for next iteration

    _start_all_collectors()
        For each collector:
        1. Check if already started (skip if yes)
        2. If Sacct collector:
            └─ Reload counter state from shared storage
        3. Call collector.start() to launch async tasks
        4. Add to _active_collectors list

    _stop_all_collectors()
        For each collector:
        1. Check if currently started (skip if not)
        2. Call collector.stop() <- new method in Base Collector class
            └─ Cancels all async collection tasks
            └─ Prevents further slurm calls
        3. Clear _active_collectors list
        4. Brief sleep to allow clean task cancellation
```
```
collect() method:
    will now only export from _active_collectors list
```

**Full flow for backup controller:**

```
STARTUP backup controller:
  └─ Collectors initialized but NOT started
  └─ _monitor_role_transitions() launched
       ↓
       Polling every 30s...
       ↓
FAILOVER EVENT:
  └─ PRIMARY crashes
  └─ _monitor_role_transitions() detects: previous=False, current=True
  └─ Calls _start_all_collectors()
       ├─ Sacct loads state (counters at 1234)
       ├─ All collectors start
       └─ Metric collection begins
       ↓
NORMAL OPERATION (active):
  └─ All collectors running
  └─ _monitor_role_transitions() keeps polling (no change detected)
       ↓
FAILBACK EVENT:
  └─ Original PRIMARY recovers
  └─ _monitor_role_transitions() detects: previous=True, current=False
  └─ Calls _stop_all_collectors()
       ├─ All async tasks cancelled
       ├─ Collection stops
```


**Full flow for primary controller:**

```
STARTUP primary controller:
  └─ Collectors initialized and started
  └─ _monitor_role_transitions() launched
       ↓
       Polling every 30s...
       ↓
FAILOVER EVENT:
  └─ PRIMARY crashes
    └─ _monitor_role_transitions() detects: previous=True, current=False
    └─ Calls _stop_all_collectors()
        ├─ All async tasks cancelled
        ├─ Collection stops

       ↓
NORMAL OPERATION (Idle):
  └─ no collectors running or exporting
  └─ _monitor_role_transitions() keeps polling (no change detected)
       ↓
FAILBACK EVENT:
  └─ Original PRIMARY recovers
  └─ _monitor_role_transitions() detects: previous=False, current=True
    └─ Calls _start_all_collectors()
        ├─ Sacct loads state (counters at 1234)
        ├─ All collectors start
        └─ Metric collection begins
```


