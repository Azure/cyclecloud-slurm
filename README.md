
Slurm
========

This project sets up an auto-scaling Slurm cluster
Slurm is a highly configurable open source workload manager. See the [Slurm project site](https://www.schedmd.com/) for an overview.

## Slurm Clusters in CycleCloud versions < 8.4.0
See [Transitioning from 2.7 to 3.0](#transitioning-from-27-to-30) for more information.

### Making Cluster Changes
The Slurm cluster deployed in CycleCloud contains a cli called `azslurm` which facilitates this. After making any changes to the cluster, run the following command as root on the Slurm scheduler node to rebuild the `azure.conf` and update the nodes in the cluster:

```
      $ sudo -i
      # azslurm scale
```

This should create the partitions with the correct number of nodes, the proper `gres.conf` and restart the `slurmctld`.

### No longer pre-creating execute nodes
As of 3.0.0, we are no longer pre-creating the nodes in CycleCloud. Nodes are created when `azslurm resume` is invoked, or by manually creating them in CycleCloud via CLI etc.

### Creating additional partitions
The default template that ships with Azure CycleCloud has three partitions (`hpc`, `htc` and `dynamic`), and you can define custom nodearrays that map directly to Slurm partitions. For example, to create a GPU partition, add the following section to your cluster template:

```ini
   [[nodearray gpu]]
   MachineType = $GPUMachineType
   ImageName = $GPUImageName
   MaxCoreCount = $MaxGPUExecuteCoreCount
   Interruptible = $GPUUseLowPrio
   AdditionalClusterInitSpecs = $ExecuteClusterInitSpecs

      [[[configuration]]]
      slurm.autoscale = true
      # Set to true if nodes are used for tightly-coupled multi-node jobs
      slurm.hpc = false

      [[[cluster-init cyclecloud/slurm:execute:3.0.7]]]
      [[[network-interface eth0]]]
      AssociatePublicIpAddress = $ExecuteNodesPublic
```

### Dynamic Partitions
As of `3.0.1`, we support dynamic partitions. You can make a `nodearray` map to a dynamic partition by adding the following.
Note that `mydyn` could be any valid Feature. It could also be more than one, separated by a comma.
```ini
      [[[configuration]]]
      slurm.autoscale = true
      # Set to true if nodes are used for tightly-coupled multi-node jobs
      slurm.hpc = false
      # This is the minimum, but see slurmd --help and [slurm.conf](https://slurm.schedmd.com/slurm.conf.html) for more information.
      slurm.dynamic_config := "-Z --conf \"Feature=mydyn\""
```

This will generate a dynamic partition like the following
```
# Creating dynamic nodeset and partition using slurm.dynamic_config=-Z --conf "Feature=mydyn"
Nodeset=mydynamicns Feature=mydyn
PartitionName=mydynamic Nodes=mydynamicns
```

### Using Dynamic Partitions to Autoscale
By default, we define no nodes in the dynamic partition. Instead, you can start nodes via CycleCloud or by manually invoking `azslurm resume` and they will join the cluster with whatever name you picked. However, Slurm does not know about these nodes so it can not autoscale them up.

Instead, you can also pre-create node records like so, which allows Slurm to autoscale them up.
```bash
scontrol create nodename=f4-[1-10] Feature=mydyn State=CLOUD
```

One other advantage of dynamic partitions is that you can support **multiple VM sizes in the same partition**.
Simply add the VM Size name as a feature, and then `azslurm` can distinguish which VM size you want to use.

**_Note_ The VM Size is added implicitly. You do not need to add it to `slurm.dynamic_config`**
```bash
scontrol create nodename=f4-[1-10] Feature=mydyn,Standard_F4 State=CLOUD
scontrol create nodename=f8-[1-10] Feature=mydyn,Standard_F8 State=CLOUD
```


Either way, once you have created these nodes in a `State=Cloud` they are now available to autoscale like other nodes.

To support **multiple VM sizes in a CycleCloud nodearray**, you can alter the template to allow multiple VM sizes by adding `Config.Mutiselect = true`.
```ini
        [[[parameter DynamicMachineType]]]
        Label = Dyn VM Type
        Description = The VM type for Dynamic nodes
        ParameterType = Cloud.MachineType
        DefaultValue = Standard_F2s_v2
        Config.Multiselect = true
```

### Dynamic Scaledown

By default, all nodes in the dynamic partition will scale down just like the other partitions. To disable this, see [SuspendExcParts](https://slurm.schedmd.com/slurm.conf.html).



### Manual scaling
If cyclecloud_slurm detects that autoscale is disabled (SuspendTime=-1), it will use the FUTURE state to denote nodes that are powered down instead of relying on the power state in Slurm. i.e. When autoscale is enabled, off nodes are denoted as `idle~` in sinfo. When autoscale is disabled, the off nodes will not appear in sinfo at all. You can still see their definition with `scontrol show nodes --future`.

To start new nodes, run `/opt/azurehpc/slurm/resume_program.sh node_list` (e.g. htc-[1-10]).

To shutdown nodes, run `/opt/azurehpc/slurm/suspend_program.sh node_list` (e.g. htc-[1-10]).

To start a cluster in this mode, simply add `SuspendTime=-1` to the additional slurm config in the template.

To switch a cluster to this mode, add `SuspendTime=-1` to the slurm.conf and run `scontrol reconfigure`. Then run `azslurm remove_nodes && azslurm scale`. 

### Accounting

To enable accounting in slurm, maria-db can now be started via cloud-init on the scheduler node and slurmdbd configured to enable db connection without a
password string. In the absense of database URL and password, slurmdbd configuration defaults to localhost.
One way of doing this is to add following lines in cluster-init:

```
#!/bin/bash
yum install -y mariadb-server
systemctl enable mariadb.service
systemctl start mariadb.service
```

#### AzureCA.pem and existing MariaDB/MySQL instances
In previous versions, we shipped with an embedded certificate to connect to Azure MariaDB and Azure MySQL instances. This is no longer required. However, if you wish to restore this behavior, select the 'AzureCA.pem' option from the dropdown for the _'Accounting Certificate URL'_ parameter in your your cluster settings.

### Cost Reporting

`azslurm` in slurm 3.0 project now comes with a new experimental feature `azslurm cost` to display costs of slurm jobs. This requires Cyclecloud 8.4 or newer, as well
as slurm accounting enabled.

```
usage: azslurm cost [-h] [--config CONFIG] [-s START] [-e END] -o OUT [-f FMT]

optional arguments:
  -h, --help            show this help message and exit
  --config CONFIG, -c CONFIG
  -s START, --start START
                        Start time period (yyyy-mm-dd), defaults to current
                        day.
  -e END, --end END     End time period (yyyy-mm-dd), defaults to current day.
  -o OUT, --out OUT     Directory name for output CSV
  -f FMT, --fmt FMT     Comma separated list of SLURM formatting options.
                        Otherwise defaults are applied
```

Cost reporting at the moment only works with retail azure pricing, and hence may not reflect actual customer invoices.

To generate cost reports for a given time period:

```
 azslurm cost -s 2023-03-01 -e 2023-03-31 -o march-2023
```

This will create a directory march-2023 and generate csv files containing costs for jobs and partitions.

```
[root@slurm301-2-scheduler ~]# ls march-2023/
jobs.csv  partition.csv  partition_hourly.csv
```

1. jobs.csv :  contains costs per job based on jobs runtime. Currently running jobs are included.
2. partition.csv: contains costs per partition, based total usage in each partition. For partitions, such
                  as dynamic partitions where multiple VM sizes can be included, it includes a row for each VM size.
3. partition_hourly.csv: contains csv report for each partition on an hourly basis.

Some basic formatting support includes customizing fields in the jobs report that are appended from `sacct` data. Cost
reporting fields such as `sku_name,region,spot,meter,meterid,metercat,rate,currency,cost` are always appended but slurm
fields from sacct can be customizable. Any field available in `sacct -e` is valid. To customize formatting:

```
azslurm cost -s 2023-03-01 -e 2023-03-31 -o march-2023 -f account,cluster,jobid,jobname,reqtres,start,end,state,qos,priority,container,constraints,user
```
This will append the supplied formatting options to cost reporting fields, and produce the jobs csv file with following
columns:
```
account,cluster,jobid,jobname,reqtres,start,end,state,qos,priority,container,constraints,user,sku_name,region,spot,meter,meterid,metercat,rate,currency,cost
```
Formatting is only available for jobs and not for partition and partition_hourly data.

Do note: `azslurm cost` relies on slurm's admincomment feature to associate specific vm_size and meter info for jobs.

## Troubleshooting

### UID conflicts for Slurm and Munge users

By default, this project uses a UID and GID of 11100 for the Slurm user and 11101 for the Munge user. If this causes a conflict with another user or group, these defaults may be overridden.

To override the UID and GID, click the edit button for both the `scheduler` node:

![Alt](/images/schedulernodeedit.png "Edit Scheduler Node")

And for each nodearray, for example the `htc` array:
![Alt](/images/nodearraytab.png "Edit nodearray")

 and add the following attributes at the end of the `Configuration` section:


![Alt](/images/nodearrayedit.png "Edit configuration")


### Incorrect number of GPUs

For some regions and VM sizes, some subscriptions may report an incorrect number of GPUs. This value is controlled in `/opt/azurehpc/slurm/autoscale.json`

The default definition looks like the following: 
```json
  "default_resources": [
    {
      "select": {},
      "name": "slurm_gpus",
      "value": "node.gpu_count"
    }
  ],
```
Note that here it is saying "For all VM sizes in all nodearrays, create a resource called `slurm_gpus` with the value of the `gpu_count` CycleCloud is reporting".

A common solution is to add a specific override for that VM size. In this case, `8` GPUs. Note the ordering here is critical - the blank `select` statement will set the default for all possible VM sizes and all other definitions will be ignored. For more information on how scalelib `default_resources` work, the underlying library used in all CycleCloud autoscalers, [see the ScaleLib documentation](https://github.com/Azure/cyclecloud-scalelib?tab=readme-ov-file#resources)

```json
  "default_resources": [
    {
      "select": {"node.vm_size": "Standard_XYZ"},
      "name": "slurm_gpus",
      "value": 8
    },
    {
      "select": {},
      "name": "slurm_gpus",
      "value": "node.gpu_count"
    }
  ],
```

Simply run `azslurm scale` again for the changes to take effect. Note that if you need to iterate on this, you may also run `azslurm partitions`, which will write the partition definition out to stdout. This output will match what is in `/etc/slurm/azure.conf` after `azslurm scale` is run.

### Dampening Memory

Slurm requires that you define the amount of free memory, after OS/Applications are considered, when reporting memory as a resource. If the reported memory is too low, then Slurm will reject this node. To overcome this, by default we dampen the memory by 5% or 1g, whichever is larger.

To change this dampening, there are two options.
1) You can define `slurm.dampen_memory=X` where X is an integer percentage (5 == 5%)
2) Create a default_resource definition in the /opt/azurehpc/slurm/autoscale.json file. 
  ```json
    "default_resources": [
    {
      "select": {},
      "name": "slurm_memory",
      "value": "node.memory"
    }
  ],
  ```

  Default resources are a powerful tool that the underlying library ScaleLib provides. [see the ScaleLib documentation](https://github.com/Azure/cyclecloud-scalelib?tab=readme-ov-file#resources)

  **Note:** `slurm.dampen_memory` takes precedence, so the default_resource `slurm_memory` will be ignored if `slurm.dampen_memory` is defined.


### KeepAlive set in CycleCloud and Zombie nodes
If you choose to set KeepAlive=true in CycleCloud, then Slurm will still change its internal power state to `powered_down`. At this point, that node is now a `zombie` node. A `zombie` node is one where it exists in CycleCloud but is in a powered_down state in Slurm.

Previous to 3.0.7, Slurm would try and fail to resume `zombie` nodes over and over again. As of 3.0.7, the `zombie` node will be left in a `down~` (or `drained~`). If you want the `zombie` node to rejoin the cluster, g=you must log into it and restart the `slurmd`, typically via `systemctl restart slurmd`. If you want these nodes to be terminated, you can either manually terminate them via the UI or `azslurm suspend`, or to do this automatically, you can add the following to the autoscale.json file found at `/opt/azurehpc/slurm/autoscale.json`

This will change the behavior of the `azslurm return_to_idle` command that is, by default, run as a cronjob every 5 minutes. You can also execute it manually, with the argument `--terminate-zombie-nodes`.

```json
{
  "return-to-idle": {
    "terminate-zombie-nodes": true
  }
}
```

### Transitioning from 2.7 to 3.0

1. The installation folder changed
      `/opt/cycle/slurm`
      ->
      `/opt/azurehpc/slurm`

2. Logs are now in `/opt/azurehpc/slurm/logs` instead of `/var/log/slurmctld`. Note, `slurmctld.log` will still be in this folder.

3. `cyclecloud_slurm.sh` no longer exists. Instead there is the azslurm cli, which can be run as root. `azslurm` uses autocomplete.
      ```bash
      [root@scheduler ~]# azslurm
      usage: 
      accounting_info      - 
      buckets              - Prints out autoscale bucket information, like limits etc
      config               - Writes the effective autoscale config, after any preprocessing, to stdout
      connect              - Tests connection to CycleCloud
      cost                 - Cost analysis and reporting tool that maps Azure costs to SLURM Job Accounting data. This is an experimental feature.
      default_output_columns - Output what are the default output columns for an optional command.
      generate_topology    - Generates topology plugin configuration
      initconfig           - Creates an initial autoscale config. Writes to stdout
      keep_alive           - Add, remeove or set which nodes should be prevented from being shutdown.
      limits               - 
      nodes                - Query nodes
      partitions           - Generates partition configuration
      refresh_autocomplete - Refreshes local autocomplete information for cluster specific resources and nodes.
      remove_nodes         - Removes the node from the scheduler without terminating the actual instance.
      resume               - Equivalent to ResumeProgram, starts and waits for a set of nodes.
      resume_fail          - Equivalent to SuspendFailProgram, shutsdown nodes
      retry_failed_nodes   - Retries all nodes in a failed state.
      scale                - 
      shell                - Interactive python shell with relevant objects in local scope. Use --script to run python scripts
      suspend              - Equivalent to SuspendProgram, shutsdown nodes
      wait_for_resume      - Wait for a set of nodes to converge.
      ```
4. Nodes are no longer pre-populated in CycleCloud. They are only created when needed.
5. All slurm binaries are inside the `azure-slurm-install-pkg*.tar.gz` file, under `slurm-pkgs`. They are pulled from a specific binary release. The current binary releases is [2023-08-07](https://github.com/Azure/cyclecloud-slurm/releases/tag/2023-08-07-bins)
6. For MPI jobs, the only network boundary that exists by default is the partition. There are not multiple "placement groups" per partition like 2.x. So you only have one colocated VMSS per partition. There is also no use of the topology plugin, which necessitated the use of a job submission plugin that is also no longer needed. Instead, submitting to multiple partitions is now the recommended option for use cases that require submitting jobs to multiple placement groups.

### Ubuntu 22 or greater and DNS hostname resolution
Due to an issue with the underlying DNS registration scheme that is used across Azure, our Slurm scripts use a mitigation that involves restarting `systemd-networkd` when changing the hostname of VMs deployed in a VMSS. This mitigation can be disabled by adding the following to your `Configuration` section.
```ini
      [[[configuration]]]
      slurm.ubuntu22_waagent_fix = false
```
In future releases, this mitigation will be disabled by default when the issue is resolved in `waagent`.

# Contributing

This project welcomes contributions and suggestions.  Most contributions require you to agree to a
Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us
the rights to use your contribution. For details, visit https://cla.microsoft.com.

When you submit a pull request, a CLA-bot will automatically determine whether you need to provide
a CLA and decorate the PR appropriately (e.g., label, comment). Simply follow the instructions
provided by the bot. You will only need to do this once across all repos using our CLA.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or
contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.

