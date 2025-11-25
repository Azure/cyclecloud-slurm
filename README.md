
Cyclecloud Slurm
========

This project sets up an auto-scaling Slurm cluster
Slurm is a highly configurable open source workload manager. See the [Slurm project site](https://www.schedmd.com/) for an overview.
# Table of Contents:
1. [Managing Slurm Clusters in 4.0.3](#managing-slurm-clusters)
    1. [Making Cluster Changes](#making-cluster-changes)
    2. [No longer pre-creating execute nodes](#no-longer-pre-creating-execute-nodes)
    3. [Creating additional partitions](#creating-additional-partitions)
    4. [Dynamic Partitions](#dynamic-partitions)
    5. [Using Dynamic Partitions to Autoscale](#using-dynamic-partitions-to-autoscale)
    6. [Dynamic Scaledown](#dynamic-scaledown)
    7. [Manual scaling](#manual-scaling)
    8. [Accounting](#accounting)
        1. [AzureCA.pem and existing MariaDB/MySQL instances](#azurecapem-and-existing-mariadbmysql-instances)
    9. [Cost Reporting](#cost-reporting)
    10. [Topology](#topology)
    11. [GB200/GB300 IMEX Support](#gb200gb300-imex-support) 
    12. [Setting KeepAlive in CycleCloud](#setting-keepalive)
    13. [Slurmrestd](#slurmrestd)
    14. [Monitoring](#monitoring)
        1. [Example Dashboards](#example-dashboards)
2. [Supported Slurm and PMIX versions](#supported-slurm-and-pmix-versions)
3. [Packaging](#packaging)
    1. [Supported OS and PMC Repos](#supported-os-and-pmc-repos)
4. [Slurm Configuration Reference](#slurm-configuration-reference)
5. [Troubleshooting](#troubleshooting)
    1. [UID conflicts for Slurm and Munge users](#uid-conflicts-for-slurm-and-munge-users)
    2. [Incorrect number of GPUs](#incorrect-number-of-gpus)
    3. [Dampening Memory](#dampening-memory)
    4. [Pre:4.0.3: KeepAlive set in CycleCloud and Zombie nodes](#keepalive-set-in-cyclecloud-and-zombie-nodes)
    5. [Transitioning from 2.7 to 3.0](#transitioning-from-27-to-30)
    6. [Transitioning from 3.0 to 4.0](#transitioning-from-30-to-40)
    7. [Ubuntu 22 or greater and DNS hostname resolution](#ubuntu-22-or-greater-and-dns-hostname-resolution)
    8. [Capturing logs and configuration for troubleshooting](#capturing-logs-and-configuration-for-troubleshooting)
6. [Contributing](#contributing)
---
## Managing Slurm Clusters in 4.0.3

### Making Cluster Changes
In CycleCloud, cluster changes can be made using the "Edit" dialog from the cluster page in the GUI or from the CycleCloud CLI.   Cluster topology changes, such as new partitions, generally require editing and re-importing the cluster template.   This can be applied to live, running clusters as well as terminated clusters.   It is also possible to import changes as a new Template for future cluster creation via the GUI.
 
When updating a running cluster, some changes may need to be applied directly on the running nodes.  Slurm clusters deployed by CycleCloud include a cli, available on the scheduler node, called `azslurm` which facilitates applying cluster configuration and scaling changes for running clusters.
 
After making any changes to the running cluster, run the following command as root on the Slurm scheduler node to rebuild the `azure.conf` and update the nodes in the cluster:
 

```
      $ sudo -i
      # azslurm scale
```
This should create the partitions with the correct number of nodes, the proper `gres.conf` and restart the `slurmctld`.
 
For changes that are not available via the cluster's "Edit" dialog in the GUI,  the cluster template must be customized. First, download a copy of the [Slurm cluster template](#templates/slurm.txt), if you do not have it. Then, to make template changes for a cluster you can perform the following commands using the cyclecloud cli.
```
# First update a copy of the slurm template (shown as ./MODIFIED_SLURM.txt below)
 
cyclecloud export_parameters MY_CLUSTERNAME > ./MY_CLUSTERNAME.json
cyclecloud import_cluster MY_CLUSTERNAME -c slurm -f ./MODIFIED_slurm.txt -p ./MY_CLUSTERNAME.json
```
For a terminated cluster you can go ahead and start the cluster with all changes in effect.
 
**IMPORTANT: There is no need to terminate the cluster or scale down to apply changes.**

To apply changes to a running/started cluster perform the following steps after you have completed the previous steps:
```
cyclecloud start_cluster MY_CLUSTERNAME
ssh $SCHEDULER_IP
# azslurm scale will configure the partition and restart slurmctld
# - this generally has no impact on the running workload
sudo azslurm scale
```

### No longer pre-creating execute nodes
As of 3.0.0, we are no longer pre-creating the nodes in CycleCloud. Nodes are created when `azslurm resume` is invoked, or by manually creating them in CycleCloud via CLI etc.

### Creating additional partitions
The default template that ships with Azure CycleCloud has four partitions (`hpc`, `htc`, `gpu` and `dynamic`), and you can define custom nodearrays that map directly to Slurm partitions. For example, to create a second GPU partition, add the following section to your cluster template:

```ini
   [[nodearray specialgpu]]
   Extends = gpu

   MachineType = $SpecialGPUMachineType

   MaxCoreCount = $MaxSpecialGPUCoreCount

...

# Any new parameters [SpecialGPUMachineType, MaxSpecialGPUCoreCount] should be added n the [[parameters]] section

```

### Dynamic Partitions
In cyclelcoud slurm projects >= `3.0.1`, we support dynamic partitions. You can make a `nodearray` map to a dynamic partition by adding the following.
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
By default, we define no nodes in the dynamic partition. 

You can pre-create node records like so, which allows Slurm to autoscale them up.
```bash
scontrol create nodename=f4-[1-10] Feature=mydyn,Standard_F2s_V2 cpus=2 State=CLOUD
```

One other advantage of dynamic partitions is that you can support **multiple VM sizes in the same partition**.
Simply add the VM Size name as a feature, and then `azslurm` can distinguish which VM size you want to use.

**_Note_ The VM Size is added implicitly. You do not need to add it to `slurm.dynamic_config`**
```bash
scontrol create nodename=f4-[1-10] Feature=mydyn,Standard_F4 State=CLOUD
scontrol create nodename=f8-[1-10] Feature=mydyn,Standard_F8 State=CLOUD
```


Either way, once you have created these nodes in a `State=Cloud` they are now available to autoscale like other nodes.

Multiple VM_Sizes are supported by default for dynamic partitions, and that is configured via `Config.Multiselect` field in slurm template as shown here:

```ini
        [[[parameter DynamicMachineType]]]
        Label = Dyn VM Type
        Description = The VM type for Dynamic nodes
        ParameterType = Cloud.MachineType
        DefaultValue = Standard_F2s_v2
        Config.Multiselect = true
```

### Note for slurm 23.11.7 users:

Dynamic partition behaviour has changed in new version of Slurm 23.11.7. When adding dynamic nodes containing GRES such as gpu's, the `/etc/slurm/gres.conf` file needs to be modified **first** before
running `scontrol create nodename` command. If this is not done, slurm will report invalid nodename like shown here:

```bash
root@s3072-scheduler:~# scontrol create NodeName=e1 CPUs=24 Gres=gpu:4 Feature=dyn,nv24 State=cloud
scontrol: error: Invalid argument (e1)
Error creating node(s): Invalid argument
```
Simply add the node `e1` in `/etc/slurm/gres.conf` and then the command will work.


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
mysql --connect-timeout=120 -u root -e "ALTER USER root@localhost IDENTIFIED VIA mysql_native_password ; FLUSH privileges;"
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

### Topology
`azslurm` in slurm 4.0 project upgrades `azslurm generate_topology` to `azslurm topology` to generate the [topology plugin configuration](https://slurm.schedmd.com/topology.html) for slurm either using VMSS topology, a fabric manager that has SHARP enabled, or the NVLink Domain. `azslurm topology` can generate both tree and block topology plugin configurations for Slurm. Users may use `azslurm topology` to generate the topology file but must manually add it to `/etc/slurm/topology.conf` either by giving that as the output file or copying the file over. Additionally, users must specify `topologyType=tree|block` in `slurm.conf` for full functionality.

Note: `azslurm topology` is only useful in manually scaled clusters or clusters of fixed size. Autoscaling does not take topology into account and topology is not updated on autoscale.

```
usage: azslurm topology [-h] [--config CONFIG] [-p, PARTITION] [-o OUTPUT]
                        [-v | -f | -n] [-b | -t] [-s BLOCK_SIZE]

optional arguments:
  -h, --help            show this help message and exit
  --config CONFIG, -c CONFIG
  -p, PARTITION, --partition PARTITION
                        Specify the parititon
  -o OUTPUT, --output OUTPUT
                        Specify slurm topology file output
  -v, --use_vmss        Use VMSS to map Tree or Block topology along VMSS
                        boundaries without special network consideration
                        (default: True)
  -f, --use_fabric_manager
                        Use Fabric Manager to map Tree topology (Block
                        topology not allowed) according to SHARP network
                        topology tool(default: False)
  -n, --use_nvlink_domain
                        Use NVlink domain to map Block topology (Tree topology
                        not allowed) according to NVLink Domain and Partition
                        for multi-node NVLink (default: False)
  -b, --block           Generate Block Topology output to use Block topology
                        plugin (default: False)
  -t, --tree            Generate Tree Topology output to use Tree topology
                        plugin(default: False)
  -s BLOCK_SIZE, --block_size BLOCK_SIZE
                        Minimum block size required for each block (use with
                        --block or --use_nvlink_domain, default: 1)
```
To generate slurm topology using VMSS you may optionally specify the type of topology which is defaulted as tree:
```
azslurm topology
azslurm topology -v -t
azslurm topology -o topology.conf
```
This will print out a the topology in the tree plugin format slurm wants for topology.conf or create a file based on the output file given in the cli

```
SwitchName=htc Nodes=cluster-htc-1,cluster-htc-2,cluster-htc-3,cluster-htc-4,cluster-htc-5,cluster-htc-6,cluster-htc-7,cluster-htc-8,cluster-htc-9,cluster-htc-10,cluster-htc-11,cluster-htc-12,cluster-htc-13,cluster-htc-14,cluster-htc-15,cluster-htc-16,cluster-htc-17,cluster-htc-18,cluster-htc-19,cluster-htc-20,cluster-htc-21,cluster-htc-22,cluster-htc-23,cluster-htc-24,cluster-htc-25,cluster-htc-26,cluster-htc-27,cluster-htc-28,cluster-htc-29,cluster-htc-30,cluster-htc-31,cluster-htc-32,cluster-htc-33,cluster-htc-34,cluster-htc-35,cluster-htc-36,cluster-htc-37,cluster-htc-38,cluster-htc-39,cluster-htc-40,cluster-htc-41,cluster-htc-42,cluster-htc-43,cluster-htc-44,cluster-htc-45,cluster-htc-46,cluster-htc-47,cluster-htc-48,cluster-htc-49,cluster-htc-50
SwitchName=Standard_F2s_v2_pg0 Nodes=cluster-hpc-1,cluster-hpc-10,cluster-hpc-11,cluster-hpc-12,cluster-hpc-13,cluster-hpc-14,cluster-hpc-15,cluster-hpc-16,cluster-hpc-2,cluster-hpc-3,cluster-hpc-4,cluster-hpc-5,cluster-hpc-6,cluster-hpc-7,cluster-hpc-8,cluster-hpc-9
```
To generate slurm topology using Fabric Manager you need a SHARP enabled cluster and it is required you specify a partition and you may optionally specify tree plugin which is the default:
```
azslurm topology -f -p gpu
azslurm topology -f -p gpu -t
azslurm topology -f -p gpu -o topology.conf
```
```
# Number of Nodes in sw00: 6

SwitchName=sw00 Nodes=ccw-gpu-7,ccw-gpu-99,ccw-gpu-151,ccw-gpu-140,ccw-gpu-167,ccw-gpu-194

# Number of Nodes in sw01: 12

SwitchName=sw01 Nodes=ccw-gpu-30,ccw-gpu-29,ccw-gpu-32,ccw-gpu-87,ccw-gpu-85,ccw-gpu-149,ccw-gpu-150,ccw-gpu-166,ccw-gpu-141,ccw-gpu-162,ccw-gpu-112,ccw-gpu-183

# Number of Nodes in sw02: 1

SwitchName=sw02 Nodes=ccw-gpu-192

# Number of Nodes in sw03: 8

SwitchName=sw03 Nodes=ccw-gpu-13,ccw-gpu-142,ccw-gpu-26,ccw-gpu-136,ccw-gpu-163,ccw-gpu-138,ccw-gpu-187,ccw-gpu-88
```
This either prints out the topology in slurm topology format or creates an output file with the topology.

To generate slurm topology using NVLink Domain, you need to specifiy a partition and optionally specify a minimum block size (Default 1) as well as the block option which is the default :
```
azslurm topology -n -p gpu
azslurm topology -n -p gpu -b -s 5
azslurm topology -n -p gpu -b -s 5 -o topology.conf
```
```
# Number of Nodes in block1: 18
# ClusterUUID and CliqueID: b78ed242-7b98-426f-b194-b76b8899f4ec 32766
BlockName=block1 Nodes=ccw-1-3-gpu-21,ccw-1-3-gpu-407,ccw-1-3-gpu-333,ccw-1-3-gpu-60,ccw-1-3-gpu-387,ccw-1-3-gpu-145,ccw-1-3-gpu-190,ccw-1-3-gpu-205,ccw-1-3-gpu-115,ccw-1-3-gpu-236,ccw-1-3-gpu-164,ccw-1-3-gpu-180,ccw-1-3-gpu-195,ccw-1-3-gpu-438,ccw-1-3-gpu-305,ccw-1-3-gpu-255,ccw-1-3-gpu-14,ccw-1-3-gpu-400
# Number of Nodes in block2: 16
# ClusterUUID and CliqueID: cc79d754-915f-408b-b1c3-b8c3aa6668ab 32766
BlockName=block2 Nodes=ccw-1-3-gpu-464,ccw-1-3-gpu-7,ccw-1-3-gpu-454,ccw-1-3-gpu-344,ccw-1-3-gpu-91,ccw-1-3-gpu-217,ccw-1-3-gpu-324,ccw-1-3-gpu-43,ccw-1-3-gpu-188,ccw-1-3-gpu-97,ccw-1-3-gpu-434,ccw-1-3-gpu-172,ccw-1-3-gpu-153,ccw-1-3-gpu-277,ccw-1-3-gpu-147,ccw-1-3-gpu-354
# Number of Nodes in block3: 8
# ClusterUUID and CliqueID: 0e568355-d588-4a53-8166-8200c2c1ef55 32766
BlockName=block3 Nodes=ccw-1-3-gpu-31,ccw-1-3-gpu-52,ccw-1-3-gpu-297,ccw-1-3-gpu-319,ccw-1-3-gpu-349,ccw-1-3-gpu-62,ccw-1-3-gpu-394,ccw-1-3-gpu-122
# Number of Nodes in block4: 9
# ClusterUUID and CliqueID: e3656d04-00db-4ad6-9a42-5df790994e41 32766
BlockName=block4 Nodes=ccw-1-3-gpu-5,ccw-1-3-gpu-17,ccw-1-3-gpu-254,ccw-1-3-gpu-284,ccw-1-3-gpu-249,ccw-1-3-gpu-37,ccw-1-3-gpu-229,ccw-1-3-gpu-109,ccw-1-3-gpu-294
BlockSizes=5
```
This either prints out the topology in slurm topology format or creates an output file with the topology.


### GB200/GB300 IMEX Support
Cyclecloud Slurm clusters now include prolog and epilog scripts to enable and cleanup IMEX service on a per-job basis. The prolog script will attempt to kill an existing IMEX service before configuring a new instance that will be specific to the new, submitted job. The epilog script terminates the IMEX service. By default, these scripts will run for GB200/GB300 nodes and not run for non-GB200/GB300 nodes. A configurable parameter `slurm.imex.enabled` has been added to the slurm cluster configuration template to allow non-GB200/GB300 nodes to enable IMEX support for their jobs or allow GB200/GB300 nodes to disable IMEX support for their jobs.
```
#Parameter to enable or disable IMEX service on a per-job basis
        slurm.imex.enabled=True
                or
        slurm.imex.enabled=False
``` 


### Setting KeepAlive
Added in 4.0.3: If the KeepAlive attribute is set in the CycleCloud UI, then the azslurmd will add that node's name to the `SuspendExcNodes` attribute via scontrol. Note that it is required that `ReconfigFlags=KeepPowerSaveSettings` is set in the slurm.conf, as is the default as of 4.0.3. Once KeepALive is set back to false, `azslurmd` will then remove this node from `SuspendExcNodes`.

If a node is added to `SuspendExcNodes` either via `azslurm keep_alive` or via the scontrol command, then `azslurmd` will not remove this node from the `SuspendExcNodes` if KeepAlive is false in CycleCloud. However, if the node is later set to KeepAlive as true in the UI then `azslurmd` will then remove it from `SuspendExcNodes` when the node is set back to KeepAlive is false.  

### Slurmrestd
As of version 4.0.3, `slurmrestd` is automatically configured and started on the scheduler node and scheduler-ha node for all Slurm clusters. This REST API service provides programmatic access to Slurm functionality, allowing external applications and tools to interact with the cluster. For more information on the Slurm REST API, see the [official Slurm REST API documentation](https://slurm.schedmd.com/rest_api.html).

### Monitoring
As of version 4.0.3, users have the option of enabling the [cyclecloud-monitoring project](https://github.com/Azure/cyclecloud-monitoring) in their slurm clusters via the Monitoring tab in the cluster creation UI.
![Alt](/images/monitoringui.png "Monitoring Page in Slurm Cluster Creation/Edit UI")

 To enable monitoring, users must create the Azure Managed Monitoring Infrastructure following the cyclecloud-monitoring project instructions under the [Build Managed Monitoring Infrastructure section](https://github.com/Azure/cyclecloud-monitoring?tab=readme-ov-file#build-the-managed-monitoring-infrastructure) and the [Grant the Monitoring Metrics Publisher role to the User Assigned Managed Identity section](https://github.com/Azure/cyclecloud-monitoring?tab=readme-ov-file#grant-the-monitoring-metrics-publisher-role-to-the-user-assigned-managed-identity). After deploying the Azure Managed Monitoring Infrastructure, input the Client ID of the Managed Identity with Monitoring Metrics Publisher role as well as the Ingestion Endpoint of the Azure Monitor Workspace in which to push metrics in the fields under the monitoring tab. These fields can be retrieved following the commands listed under the [Monitoring Configuration Parameters section](https://github.com/Azure/cyclecloud-monitoring?tab=readme-ov-file#monitoring-configuration-parameters) of the cyclecloud-monitoring project. Enabling monitoring will include the installation and configuration of:
- Prometheus Node Exporter (for all nodes)
- NVidia DCGM exporter (for Nvidia GPU nodes)
- SchedMD Slurm exporter (for Slurm scheduler node).

Once the cluster is started, you can access the Grafana dashboards by browsing to the Azure Managed Grafana instance created by the deployment script from the cyclecloud-monitoring project. The URL can be retrieved by browsing the Endpoint of the Azure Managed Grafana instance in the Azure portal, and when connected, access the pre-built dashboards under the Dashboards/Azure CycleCloud folder.

To check if the configured exporters are exposing metrics, connect to a node and execute these `curls` commands :
- For the Node Exporter : `curl -s http://localhost:9100/metrics` - available on all nodes
- For the DCGM Exporter : `curl -s http://localhost:9400/metrics` - only available on VM type with NVidia GPU
- For the Slurm Exporter : `curl -s http://localhost:9200/metrics` - only available on the Slurm scheduler VM

#### Example Dashboards

**Slurm Dashboard**
![Alt](/images/slurmexporterdash.png "Example Slurm Exporter Grafana Dashboard")
*Note: this dashboard is not published with cyclecloud-monitoring project and is used here as an example*

**GPU Device View Dashboard**
![Alt](/images/dcgmdash.png "Example DCGM Exporter Grafana Dashboard")

**Node View Dashboard**
![Alt](/images/nodeexporterdash.png "Example Node Exporter Grafana Dashboard")


## Supported Slurm and PMIX versions
The current slurm version supported is `25.05.2` which is compiled with PMIX version `4.2.9`.
## Packaging
Slurm and PMIX packages are fetched and downloaded exclusively from packages.microsoft.com.
### Supported OS and PMC Repos

| OS                    | PMC Repo                                      |
|-----------------------|-----------------------------------------------|
| Ubuntu 22.04 [amd64]  | `https://packages.microsoft.com/repos/slurm-ubuntu-jammy/` |
| Ubuntu 24.04 [amd64]  | `https://packages.microsoft.com/repos/slurm-ubuntu-noble/` |
| Ubuntu 24.04 [arm64]  | `https://packages.microsoft.com/repos/slurm-ubuntu-noble/` |
| AlmaLinux 8 [amd64]   | `https://packages.microsoft.com/yumrepos/slurm-el8/`       |
| Almalinux 9 [amd64]   | `https://packages.microsoft.com/yumrepos/slurm-el9/`       |
| RHEL 8 [amd64]        | `https://packages.microsoft.com/yumrepos/slurm-el8/`       |
| RHEL 9 [amd64]        | `https://packages.microsoft.com/yumrepos/slurm-el9/`       |

**Note: CycleCloud also supports SLES 15 HPC, however we can only install the version supported by SLES HPC's zypper repos. At the time of this release, that is 23.02.7. Due to limited support, slurmrestd, monitoring, and background healthchecks are disabled for SUSE operting systems.**

## Slurm configuration reference

The following table describes the Slurm-specific configuration options you can toggle/define in the [slurm template](templates/slurm.txt) to customize functionality:

| Slurm specific configuration options | Description |
| ------------------------------------ | ----------- |
| slurm.version                        | Default: `25.05.2`. Sets the version of Slurm to install and run.  |
| slurm.insiders                        | Default: `false`. Setting that controls whethere slurm is installed from pmc stable repo or pmc insiders repo. Set to `true` to install from insiders repo.  |
| slurm.autoscale                      | Default: `false`. A per-nodearray setting that controls whether Slurm automatically stops and starts nodes in this node array. |
| slurm.hpc                            | Default: `true`. A per-nodearray setting that controls whether nodes in the node array are in the same placement group. Primarily used for node arrays that use VM families with InfiniBand. It only applies when `slurm.autoscale` is set to `true`. |
| slurm.default_partition              | Default: `false`. A per-nodearray setting that controls whether the nodearray should be the default partition for jobs that don't request a partition explicitly. |
| slurm.dampen_memory                  | Default: `5`. The percentage of memory to hold back for OS/VM overhead. |
| slurm.suspend_timeout                | Default: `600`. The amount of time in seconds between a suspend call and when that node can be used again. |
| slurm.resume_timeout                 | Default: `1800`. The amount of time in seconds to wait for a node to successfully boot. |
| slurm.use_pcpu                       | Default: `true`. A per-nodearray setting to control scheduling with hyperthreaded vCPUs. Set to `false` to set `CPUs=vcpus` in `cyclecloud.conf`. |
| slurm.enable_healthchecks                       | Default: `false`. Setting to enable healthagent background healthchecks every minute|
| slurm.accounting.enabled                       | Default: `false`. Setting to enable Slurm job accounting.  |
| slurm.accounting.url                       | Required when `slurm.accounting.enabled = true`. URL of the database to use for Slurm job accounting  |
| slurm.accounting.storageloc                       | Optional when `slurm.accounting.enabled = true`. Database name to store slurm accounting records  |
| slurm.accounting.user                       | Required when `slurm.accounting.enabled = true`. User for Slurm DBD admin  |
| slurm.accounting.password                       | Required when `slurm.accounting.enabled = true`. Password for Slurm DBD admin  |
| slurm.accounting.certificate_url                       | Required when `slurm.accounting.enabled = true`. Url to fetch SSL Certificate for authentication to DB. Use AzureCA.pem (embedded) for use with deprecated MariaDB instances. |
| slurm.additional.config                      | Any additional lines to add to slurm.conf |
| slurm.ha_enabled                       | Default: `false`. Setting to deploy with an additional HA node |
| slurm.launch_parameters                       | Default: `use_interactive_step`. Deploy Slurm with Launch Parameters (comma delimited) |
| slurm.user.name                      | Default: `slurm`. The user name for the Slurm service to use. |
| slurm.user.uid                       | Default: `11100`. The user ID to use for the Slurm user. |
| slurm.user.gid                       | Default: `11100`. The group ID to use for the Slurm user. |
| munge.user.name                      | Default: `munge`. The user name for the MUNGE authentication service to use. |
| munge.user.uid                       | Default: `11101`. The user ID to use for the MUNGE user. |
| munge.user.gid                       | Default: `11101`. The group ID for the MUNGE user. |
| slurm.slurmrestd.user.name                      | Default: `slurmrestd`. The user name for the Slurmrestd service to use. |
| slurm.slurmrestd.user.uid                       | Default: `11102`. The user ID to use for the Slurmrestd user. |
| slurm.slurmrestd.user.gid                       | Default: `11102`. The group ID for the Slurmrestd user. |
| slurm.imex.enabled                      | Default: `true` for GB200/GB300 nodes,`false` for all other skus.  A per-nodearray setting that controls whether to enable IMEX support for jobs. |

## Troubleshooting

### UID conflicts for Slurm, Munge, and Slurmrestd users

By default, this project uses a UID and GID of 11100 for the Slurm user, 11101 for the Munge user and 11102 for the Slurmrestd user. If this causes a conflict with another user or group, these defaults may be overridden.

To override the UID and GID, first terminate the cluster and then for each nodearray click the edit button, for example the `scheduler-ha` array:

![Alt](/images/nodearraytab.png "Edit nodearray")

 For each nodearray, edit the following attributes in the `Configuration` section:
```
munge.user.uid
munge.user.gid
slurm.slurmrestd.user.uid
slurm.slurmrestd.user.gid
slurm.user.uid
slurm.user.gid
```


![Alt](/images/nodearrayedit.png "Edit configuration")

After saving the attributes, you may restart the cluster.

**Note: slurm requires UID/GID to be consistent across the cluster so you must edit all nodearray (including scheduler and scheduler-ha) configurations to override the defaults successfully. If you fail to do so you will see the following error in slurmd:**
```
Nov 18 17:50:18 rc403-hpc-1 slurmd[8046]: [2025-11-18T17:50:18.003] error: Security violation, ping RPC from uid 11100
Nov 18 17:50:26 rc403-hpc-1 slurmd[8046]: [2025-11-18T17:50:26.011] error: Security violation, health check RPC from uid 11100
Nov 18 17:51:32 rc403-hpc-1 slurmd[8046]: [2025-11-18T17:51:32.767] debug:  _rpc_terminate_job: uid = 11100 JobId=2
Nov 18 17:51:32 rc403-hpc-1 slurmd[8046]: [2025-11-18T17:51:32.767] error: Security violation: kill_job(2) from uid 11100
Nov 18 17:51:58 rc403-hpc-1 slurmd[8046]: [2025-11-18T17:51:58.002] error: Security violation, ping RPC from uid 11100
```


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
      topology             - Generates topology plugin configuration
      wait_for_resume      - Wait for a set of nodes to converge.
      ```
4. Nodes are no longer pre-populated in CycleCloud. They are only created when needed.
5. All slurm binaries are inside the `azure-slurm-install-pkg*.tar.gz` file, under `slurm-pkgs`. They are pulled from a specific binary release. The current binary releases is [2023-08-07](https://github.com/Azure/cyclecloud-slurm/releases/tag/2023-08-07-bins)
6. For MPI jobs, the only network boundary that exists by default is the partition. There are not multiple "placement groups" per partition like 2.x. So you only have one colocated VMSS per partition. There is also no use of the topology plugin, which necessitated the use of a job submission plugin that is also no longer needed. Instead, submitting to multiple partitions is now the recommended option for use cases that require submitting jobs to multiple placement groups.
### Transitioning from 3.0 to 4.0
1. Disable PMC is no longer supported and all slurm downloads will come from packages.microsoft.com. All blobs from github have been removed.
2. Slurmrestd is now automatically configured and started for scheduler nodes and scheduler-ha nodes.

### Ubuntu 22 or greater and DNS hostname resolution
Due to an issue with the underlying DNS registration scheme that is used across Azure, our Slurm scripts use a mitigation that involves restarting `systemd-networkd` when changing the hostname of VMs deployed in a VMSS. This mitigation can be disabled by adding the following to your `Configuration` section.
```ini
      [[[configuration]]]
      slurm.ubuntu22_waagent_fix = false
```
In future releases, this mitigation will be disabled by default when the issue is resolved in `waagent`.

### Capturing logs and configuration data for troubleshooting

When diagnosing/troubleshooting issues in Slurm clusters orchestrated by CycleCloud, Please use the following convenience script provided for capturing logs and configuration data from any node that needs to be examined by Microsoft engineers.
This script can be run on any scheduler/login/execute node. But it must be run on all the nodes whose logs/data needs to be captured.

```bash
/opt/cycle/capture_logs.sh
```

This should produce a tarball file which should be sent over in support cases.

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

