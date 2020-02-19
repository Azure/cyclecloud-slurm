# Bursting CycleCloud Slurm clusters from a dedicated on-prem scheduler

It is possible to configure a Slurm scheduler not provisioned by CycleCloud to autoscale an execute Nodearray/partition defined in CycleCloud. There are some manual steps to install.

## In CycleCloud/Initializing a headless cluster

1) Download the latest slurm project and upload it to your storage locker

```bash
wget https://ahowardinternal.blob.core.windows.net/releases/cyclecloud-slurm-204.tgz
tar xvzf cyclecloud-slurm-204.tgz
cd cyclecloud-slurm
cyclecloud project upload
```

2) Import the headless cluster template:

```bash
cyclecloud import_template slurm-headless -f templates/slurm-headless.txt -c slurm
```

3) Create a cluster in CycleCloud using the slurm-headless template and start it. No execute nodes will be created yet; that will happen after the cluster is joined to the on-prem scheduler.

## On the scheduler

1) Ensure that the Slurm scheduler is installed and configured properly for a basic on-prem setup

2) Copy the slurm_bootstrap tarball (https://ahowardinternal.blob.core.windows.net/releases/slurm_bootstrap.tgz) tarball contents to /opt/cycle/jetpack/system/bootstrap/slurm:

```bash
mkdir -p /opt/cycle/jetpack/system/bootstrap/slurm
cd !$
tar xvzf /tmp/bootstrap_slurm.tgz
```

3) Install python and python-pip if they aren't already installed

4) Install the cyclecloud-api Python package using pip:
    
```bash
    sudo pip install cyclecloud-api-7.9.2.tar.gz
```

5) Copy job_submit_cyclecloud.so  to /usr/lib64/slurm/

    sudo cp /opt/cycle/jetpack/system/bootstrap/job_submit_cyclecloud.so /usr/lib64/slurm/
6) mkdir /opt/cycle/jetpack/config

7) Initialize the connection to CycleCloud with the cyclecloud_slurm.sh script. Note: You may want to use a special API user since this password will be stored on the cluster:

    cd /opt/cycle/jetpack/system/bootstrap/slurm
    ./cyclecloud_slurm.sh initialize --cluster-name slurmmpi --username myuser --password mypass --url https://cyclecloudiq4tz4.eastus.cloudapp.azure.com 

8) Create /etc/slurm/{topology,cyclecloud,cgroups}.conf if they don't already exist (and link to /sched)

9) Update /etc/slurm/slurm.conf to have the following settings:

```
TopologyPlugin=topology/tree
JobSubmitPlugins=job_submit/cyclecloud
ResumeTimeout=1800
SuspendTimeout=600
SuspendTime=300
ResumeProgram=/opt/cycle/jetpack/system/bootstrap/slurm/resume_program.sh
ResumeFailProgram=/opt/cycle/jetpack/system/bootstrap/slurm/resume_fail_program.sh
SuspendProgram=/opt/cycle/jetpack/system/bootstrap/slurm/suspend_program.sh
SchedulerParameters=max_switch_wait=24:00:00
Include cyclecloud.conf
SlurmctldHost=ljhvr50kzwv
```


## Additional notes:

Mount the /shared and /sched filers to appropriate places on the scheduler
