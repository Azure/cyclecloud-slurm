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

**Sacct state saving**
    - Save initial starttime if save state file doesnt exist
        - Pros:
            - If exporter stops/crashes next time it starts it will take in the initial starttime in the first collection and pull in all the data.
            - No data lost
        - Cons:
            - First collection interval could become very big and then having all that data becomes useless because then it looks like that x amount of jobs finished in a short time frame.



**Failover Detection**:
- SlurmctldPrimaryOnProg, SlurmctldPrimaryOffProg
    - Pros:
        - Slurm handles failover detection:
        - can send a signal to exporter to inidicate that it is primary or backup now (controller has to be up for these programs to work)
        - can be used to save state of active controller to state save file for exporter to read to determine which is active controller
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

- strigger
    - Start exporter with these
    ```
    --backup_slurmctld_assumed_control
    --primary_slurmctld_resumed_control
    ```

    - Stop Exporter with these

    ```
    --primary_slurmctld_failure
    --backup_slurmctld_failure
    ```
    - Pros:
        - Slurm handles failover detection, we only start/stop exporter
    - Cons:
        - No flag to stop exporter on backup if primary resumes control

- Combination of strigger AND SlurmctldPrimaryOnProg, SlurmctldPrimaryOffProg
    - Start exporter with strigger
    - Stop exporter with strigger failure flags AND SlurmctldPrimaryOffProg.

    - Pros:
        - Slurm handles transitions
        - Exporter starts only for one controller so no
        - Combination allows for both fail over as well as fail back
        - No code changes as we use all slurm hooks
    - Cons:
        - Would still need to save state of job history somehow.




## Design Decisions

### Proposal #2:
Exporter runs on only one node at a time
    - Set striggers to stop exporter when slurmctld fails on either backup or primary
    - Set striggers to start exporter when backup assumes control or primary resumes control
    - Use SlurmctldPrimaryOffProg to stop exporter when backup goes back to standby

We save starttime of first sacct collection so that when backup starts we use that starttime to pull in all finished jobs in that window. If primary resumes control again we use that starttime again for the first collection.



### Proposal #1:
Exporter Runs on both nodes:
 - When exporter detects it is not the active controller it will run in idle mode -- no collecting or exporting
 - When exporter detects it is the active controller it will run in active mode -- collecting and exporting

~~Scontrol ping to detect failover:~~
 ~~- gives us most accurate active controller at a given time~~

Use SlurmctldPrimaryOnProg to save hostname of active controller to state save file
    - exporter periodically checks this file for transitions, if another controller becomes the active controller then we stop collecting and exporting

Exporter in either active or idle mode will first initialize all collectors.

Only exporter in active mode will start controllers.

Exporter will save initial start_time to state save file if doesnt exist when Sacct collector initializes so that if azslurm crashes we can query from inital starttime when exporter starts again so data persists.

Since we are initializing all collectors for both controllers (active and inactive) starttime will be accurate when inactive controller becomes active and starts collecting. (bigger window for first query). When we stop the sacct collector the current starttime will be the last endtime of the window of the last successful query so when the collector starts again it will resume with the last successful query endtime as the starttime and the new endtime will be now (bigger window again for first query)

 - All other collectors are gauges and stateless so they can just start when exporter goes in active mode

Create a background role transition handling task method in CompositeCollector to continuosly check the role of the controller (if it is active or not) every 30s because SlurmCtldTimeout is 30s
- if transitions from not active to active  start all collectors
- if transitions from active to not active stop all collectors
- no transition = no op
- save all active collectors in a list

collect function will now export metrics only from active collectors list

Prometheus is configured on both nodes and will ingest from both exporters but exporters will be the one limiting metrics

## Abstract Proposal #2
```
class Sacct(Base Collector):
    Update initalize() method for sacct:
    → Set starttime from state save file during initialization if exists, if not set it as now - 1 hour
    → If state save doesnt exist save current startttime to state save
    → Use atomic write (temp file + rename)
    File location:
    /sched/{cluster_name}/spool/slurmctld/sacct_exporter_starttime
        "starttime": "2026-04-14T16:47:00"
```
Hooks:
- /etc/slurm/hooks/controller_lost_control.sh #systemctl stop azslurm-exporter
- /etc/slurm/hooks/controller_assume_control.sh #systemctl start azslurm-exporter

Primary loses control (failover)
```
strigger --set --flags=PERM \
  --primary_slurmctld_failure \
  --program=/etc/slurm/hooks/controller_lost_control.sh

strigger --set --flags=PERM \
  --backup_slurmctld_assumed_control \
  --program=/etc/slurm/hooks/controller_assume_control.sh

SlurmctldPrimaryOffProg=/etc/slurm/hooks/controller_lost_control.sh
SlurmctldPrimaryOnProg=/etc/slurm/hooks/controller_assume_control.sh
```

Backup loses control (failback)
```
strigger --set --flags=PERM \
  --primary_slurmctld_resumed_control \
  --program=/etc/slurm/hooks/controller_assume_control.sh

SlurmctldPrimaryOffProg=/etc/slurm/hooks/controller_lost_control.sh
SlurmctldPrimaryOnProg=/etc/slurm/hooks/controller_assume_control.sh
```
**Full flow for primary controller:**

```
STARTUP primary controller:
  └─ azslurm-exporter started
  └─ Save initial starttime to state save file
       ↓
FAILOVER EVENT:
  └─ PRIMARY crashes
  └─ strigger will stop azslurm-exporter
       ↓
NORMAL OPERATION (inactive):
  └─ azslurm-exporter is stopped
       ↓
FAILBACK EVENT:
  └─ Original PRIMARY recovers
  └─ strigger + SlurmctldPrimaryOnProg will start azslurm-exporter
  └─ starttime will be loaded in and first sacct collection will start from there

```

**Full flow for backup controller:**

```
STARTUP backup controller:
  └─ azslurm-exporter not started
       ↓
FAILOVER EVENT:
  └─ PRIMARY crashes
  └─ strigger + SlurmctldPrimaryOnProg will start azslurm-exporter
  └─ starttime will be loaded in and first sacct collection will start from there
       ↓
NORMAL OPERATION (active):
  └─ All collectors running and exporting
       ↓
FAILBACK EVENT:
  └─ Original PRIMARY recovers
  └─ SlurmctldPrimaryOffProg will stop azslurm-exporter
```

## Abstract Proposal #1:

```
class ControllerRoleChecker():
    Methods:
    - initialize()         → Detect if HA is enabled using jetpack config slurm.ha_enabled
    - check_role()        → check state save file to determine active controller
    - is_ha_enabled()      → Return if cluster is in HA mode
```
```
class Sacct(Base Collector):
    Update initalize() method for sacct:
    → Set starttime from state save file during initialization if exists, if not set it as now - 1 hour
    → If state save doesnt exist save current startttime to state save
    → Use atomic write (temp file + rename)
    File location:
    /sched/{cluster_name}/spool/slurmctld/sacct_exporter_starttime
        "starttime": "2026-04-14T16:47:00"
```
```
class BaseCollector(ABC):
    Update launch_task() method:
    → return task from asyncio.create_task()
    New Methods:
    stop()
    → Cancel collection task

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

