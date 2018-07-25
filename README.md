
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
     
  6. You need to either build the Slurm RPMs and put them in the `blobs/` directory 
     or get them from someone who has already built them. There is a script in the 
     cluster-init `scratch` directory to build the RPMs.

  7. Optional: To use the `cyclecloud project upload <locker>` command, you must
     have a Pogo configuration file set up with write-access to your locker.

     a. You may use your preferred tool to interact with your storage "Locker"
        instead.


  8. Centos 7 with Cyclecloud 6.7.0 has been tested and confirmed working.



Usage
=====

A. Configuring the Project
--------------------------

The first step is to configure the project for use with your storage locker:

  1. Open a terminal session with the CycleCloud CLI enabled.

  2. Switch to the Slurm sample directory.

  3. Run ``cyclecloud project add_target my_locker`` (assuming the locker is named "my_locker").
     The locker name will generally be the same as the cloud provider you created when configuring
     CycleCloud. The expected output looks like this:::

       $ cyclecloud project add_target my_locker
       Name: slurm
       Version: 1.0.0
       Targets:
          my_locker: {'default': 'true', 'is_locker': 'true'}

     NOTE: You may call add_target as many times as needed to add additional target lockers.

       
B. Deploying the Project
------------------------

To upload the project (including any local changes) to your target locker, run the
`cyclecloud project upload` command from the project directory.  The expected output looks like
this:::

    $ cyclecloud project upload
    Sync completed!

*IMPORTANT*

For the upload to succeed, you must have a valid Pogo configuration for your target Locker.


C. Importing the Cluster Template
---------------------------------

To import the cluster:

  1. Open a terminal session with the CycleCloud CLI enabled.

  2. Switch to the Slurm directory.

  3. Run ``cyclecloud import_template Slurm -f templates/slurm_template.txt``.  The
     expected output looks like this:::

       $ cyclecloud import_template Slurm -f templates/slurm_template.txt
       Importing template Slurm....
       ----------------------
       Slurm : *template*
       ----------------------
       Keypair: $keypair
       Cluster nodes:
           master: off
       Total nodes: 1


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

