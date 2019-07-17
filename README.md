
Slurm
========

This project sets up an auto-scaling Slurm cluster


Pre-Requisites
--------------

This sample requires the following:

  1. CycleCloud must be installed and running.

     a. If this is not the case, see the CycleCloud QuickStart Guide for
        assistance.

  2. The CycleCloud CLI must be installed and configured for use.

  3. You must have access to log in to CycleCloud.

  4. You must have access to upload data and launch instances in your chosen
     Azure subscription

  5. You must have access to a configured CycleCloud "Locker" for Project Storage
     (Cluster-Init and Chef).

  6. You need to build the Slurm RPMs and put them in the `blobs/` directory.
     There is a script in the cluster-init `scratch` directory to build the RPMs on a cloud node.
     Alternatively, you can run the included `./docker-rpmbuild.sh` on a development machine with
     `docker` installed.  This `docker-rpmbuild.sh` script will generate the rpm files for
     CentOS 7.x compatible nodes and place them in the `blobs/` directory.

  7. Optional: To use the `cyclecloud project upload <locker>` command, you must
     have a Pogo configuration file set up with write-access to your locker.

     a. You may use your preferred tool to interact with your storage "Locker"
        instead.


  8. Centos 7 with Cyclecloud 6.7.0 has been tested and confirmed working.



Usage
=====

A. Deploying the Project
--------------------------

The first step is to configure the project for use with your storage locker:

  1. Open a terminal session with the CycleCloud CLI enabled.

  2. Switch to the Slurm sample directory.

  3. Upload the project (including any local changes) to your target locker, run the
`cyclecloud project upload` command from the project directory.  The expected output looks like this:

```
    $ cyclecloud project upload
    Sync completed!
```

*IMPORTANT*

For the upload to succeed, you must have a valid Pogo configuration for your target Locker.


B. Importing the Cluster Template
---------------------------------

To import the cluster:

  1. Open a terminal session with the CycleCloud CLI enabled.

  2. Switch to the Slurm directory.

  3. Run ``cyclecloud import_template Slurm -f templates/slurm_template.txt``.  The
     expected output looks like this:::

```
       $ cyclecloud import_template Slurm -f templates/slurm_template.txt
       Importing template Slurm....
       ----------------------
       Slurm : *template*
       ----------------------
       Keypair: $keypair
       Cluster nodes:
           master: off
       Total nodes: 1
```

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

