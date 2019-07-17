
Slurm
========

This project sets up an auto-scaling Slurm cluster
Slurm is a highly configurable open source workload manager. See the [Slurm project site](https://www.schedmd.com/) for an overview.

## Autoscale in CycleCloud 7.8
### Making Cluster Changes
The new autoscale functionality in CycleCloud 7.8 and version 2.0.0 of the Slurm project allows Slurm to work with multiple nodearrays and partitions. In order to facilitate this functionality with Slurm, CycleCloud pre-populates the execute nodes in the cluster. Because of this, you need to run a command on the Slurm master node after making any changes to the cluster, such as autoscale limits or VM types.

After making any changes to the cluster, run the following command as root on the Slurm master node to rebuild the slurm.conf and update the nodes in the cluster:

```
      $ sudo -i
      # cd /opt/cycle/jetpack/system/bootstrap/slurm
      # ./cyclecloud_slurm.sh scale
```

### Removing all execute nodes
Because CycleCloud pre-creates all of the compute nodes, it's often desirable to completely remove all nodes from the cluster when making big changes, such as VM type or Image. It is possible to remove all nodes via the UI, the `cyclecloud_slurm.sh` script has a `remove_nodes` option that will remove any nodes that aren't currently running jobs.

### Creating additional partitions
While the default template that ships with Azure CycleCloud has two partitions (`hpc` and `htc`), you can define custom nodearrays that map directly to Slurm partitions. For example, to create a GPU partition, add the following section to your cluster template:

```
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

      [[[cluster-init cyclecloud/slurm:execute:2.0.1]]]
      [[[network-interface eth0]]]
      AssociatePublicIpAddress = $ExecuteNodesPublic
```

## Troubleshooting

### UID conflicts for Slurm and Munge users

By default, this project uses a UID and GID of 11100 for the Slurm user and 11101 for the Munge user. If this causes a conflict with another user or group, these defaults may be overridden.

To override the UID and GID, click the edit button for both the `master` node:

![Alt](/images/masternodeedit.png "Edit Master")

And the `execute` nodearray:
![Alt](/images/nodearraytab.png "Edit nodearray")

 and add the following attributes to the `Configuration` section:


![Alt](/images/nodearrayedit.png "Edit configuration")


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

