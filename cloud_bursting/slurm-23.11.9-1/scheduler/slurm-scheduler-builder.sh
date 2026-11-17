#!/bin/sh
# -----------------------------------------------------------------------------
# Script: Install and Configure Slurm Scheduler
#
# This script automates the installation and configuration of the Slurm scheduler 
# on your VM or machine. It sets up the Slurm software to manage and schedule 
# workloads efficiently across the available resources in your environment.
#
# Key Features:
# - Installs and configures Slurm software on your VM or machine.
# - Sets up the Slurm configuration to manage compute resources.
#
# Prerequisites:
# - Root or sudo privileges are required to run the script.
#
# Usage:
# # sh slurm-scheduler-builder.sh
# -----------------------------------------------------------------------------


set -e
if [ $(whoami) != root ]; then
  echo "Please run as root"
  exit 1
fi

# Check if the script is running on a supported OS with the required version of almaLinux 8.7 or Ubuntu 22.04

# Check if /etc/os-release exists
if [ ! -e /etc/os-release ]; then
  echo "This script only supports AlmaLinux 8.7 or Ubuntu 22.04"
  exit 1
fi

# Source /etc/os-release to get OS information
. /etc/os-release

# Check OS name and version
if { [ "$ID" = "almalinux" ] && [ "$VERSION_ID" = "8.7" ]; } || \
   { [ "$ID" = "ubuntu" ] && [ "$VERSION_ID" = "22.04" ]; }; then
  echo "OS version is supported."
else
  echo "This script only supports AlmaLinux 8.7 or Ubuntu 22.04"
  exit 1
fi

echo "------------------------------------------------------------------------------------------------------------------------------"
echo "Building Slurm scheduler for cloud bursting with Azure CycleCloud"
echo "------------------------------------------------------------------------------------------------------------------------------"
echo " "
# Prompt for Cluster Name
read -p "Enter Cluster Name: " cluster_name

ip_address=$(hostname -I | awk '{print $1}')
echo "------------------------------------------------------------------------------------------------------------------------------"
echo " "
echo "Summary of entered details:"
echo "Cluster Name: $cluster_name"
echo "Scheduler Hostname: $(hostname)"
echo "NFSServer IP Address: $ip_address"
echo " "
echo "------------------------------------------------------------------------------------------------------------------------------"

sched_dir="/sched/$cluster_name"
slurm_conf="$sched_dir/slurm.conf"
munge_key="/etc/munge/munge.key"
slurm_script_dir="/opt/azurehpc/slurm"
OS_ID=$(cat /etc/os-release  | grep ^ID= | cut -d= -f2 | cut -d\" -f2 | cut -d. -f1)
OS_VERSION=$(cat /etc/os-release  | grep VERSION_ID | cut -d= -f2 | cut -d\" -f2)
SLURM_VERSION="23.11.9-1"

# Create directories
mkdir -p "$sched_dir"

# Create Munge and Slurm users
echo "------------------------------------------------------------------------------------------------------------------------------"
echo "Creating Munge and Slurm users"
echo "------------------------------------------------------------------------------------------------------------------------------"

#check if the users already exist
#uid 11100 is used for slurm and 11101 is used for munge in cyclecloud

# Function to check and create a user and group
create_user_and_group() {
    username=$1
    uid=$2
    gid=$3

    if id "$username" >/dev/null 2>&1; then
        echo "$username user already exists"
    else
        echo "Creating $username user and group..."
        groupadd -g "$gid" "$username"
        useradd -u "$uid" -g "$gid" -s /bin/false -M "$username"
        echo "$username user and group created"
    fi
}

# Check and create 'munge' user and group if necessary
create_user_and_group "munge" 11101 11101

# Check and create 'slurm' user and group if necessary
create_user_and_group "slurm" 11100 11100

# Set up NFS server
echo "------------------------------------------------------------------------------------------------------------------------------"
echo "Setting up NFS server"
echo "------------------------------------------------------------------------------------------------------------------------------"
if [ "$OS_ID" = "almalinux" ]; then
   dnf install -y nfs-utils
elif [ "$OS_ID" = "ubuntu" ]; then
   apt-get install -y nfs-kernel-server
fi
mkdir -p /sched /shared
echo "/sched *(rw,sync,no_root_squash)" >> /etc/exports
echo "/shared *(rw,sync,no_root_squash)" >> /etc/exports
systemctl restart nfs-server.service
systemctl enable nfs-server.service
echo "NFS server setup complete"
showmount -e localhost

# setting up Microsoft repo
# Set up Microsoft repository based on the OS
echo "Setting up Microsoft repo"

# Check if OS is AlmaLinux
if [ "$OS_ID" = "almalinux" ]; then
    echo "Detected AlmaLinux"
    if [ ! -e /etc/yum.repos.d/microsoft-prod.repo ]; then
        echo "Downloading and installing Microsoft repo for AlmaLinux..."
        curl -sSL -O https://packages.microsoft.com/config/rhel/$(echo "$OS_VERSION" | cut -d. -f1)/packages-microsoft-prod.rpm
        rpm -i packages-microsoft-prod.rpm
        rm -f packages-microsoft-prod.rpm
        echo "Microsoft repo setup complete for AlmaLinux"
    else
        echo "Microsoft repo already exists on AlmaLinux"
    fi

# Check if OS is Ubuntu
elif [ "$OS_ID" = "ubuntu" ]; then
    echo "Detected Ubuntu"
    if [ ! -e /etc/apt/sources.list.d/microsoft-prod.list ]; then
        echo "Downloading and installing Microsoft repo for Ubuntu..."
        curl -sSL -O https://packages.microsoft.com/config/ubuntu/$OS_VERSION/packages-microsoft-prod.deb
        dpkg -i packages-microsoft-prod.deb
        rm -f packages-microsoft-prod.deb
        echo "Microsoft repo setup complete for Ubuntu"
    else
        echo "Microsoft repo already exists on Ubuntu"
    fi

# If OS is neither AlmaLinux nor Ubuntu
else
    echo "Unsupported OS: $OS_ID"
    exit 1
fi

# Install and configure Munge
echo "------------------------------------------------------------------------------------------------------------------------------"
echo "Installing and configuring Munge"
echo "------------------------------------------------------------------------------------------------------------------------------"
if [ "$OS_ID" = "almalinux" ]; then
   dnf install -y epel-release
   dnf install -y munge munge-libs
elif [ "$OS_ID" = "ubuntu" ]; then
   apt-get update
   apt-get install -y munge
else
   echo "Unsupported OS: $OS_ID"
   exit 1
fi

# Generate the munge key and set proper permissions
dd if=/dev/urandom bs=1 count=1024 of="$munge_key"
chown munge:munge "$munge_key"
chmod 400 "$munge_key"

# Start and enable the munge service
systemctl start munge
systemctl enable munge

# Copy the munge key to the sched directory
cp "$munge_key" "$sched_dir/munge.key"
chown munge: "$sched_dir/munge.key"
chmod 400 "$sched_dir/munge.key"

echo "------------------------------------------------------------------------------------------------------------------------------"
echo "Munge installed and configured"
echo "------------------------------------------------------------------------------------------------------------------------------"

# Install and configure Slurm
echo "------------------------------------------------------------------------------------------------------------------------------"
echo "Installing Slurm"
echo "------------------------------------------------------------------------------------------------------------------------------"

# Installing Slurm on AlmaLinux
if [ "$OS_ID" = "almalinux" ]; then
    echo "Installing Slurm on AlmaLinux"
    echo "Setting up Slurm repository..."

    # Create Slurm repository file for AlmaLinux
    cat <<EOF > /etc/yum.repos.d/slurm.repo
[slurm]
name=Slurm Workload Manager
baseurl=https://packages.microsoft.com/yumrepos/slurm-el8-insiders
enabled=1
gpgcheck=1
gpgkey=https://packages.microsoft.com/keys/microsoft.asc
priority=10
EOF

    echo "Slurm repository setup complete."
    echo "------------------------------------------------------------------------------------------------------------------------------"
    echo "Installing Slurm packages"
    echo "------------------------------------------------------------------------------------------------------------------------------"

    # List of Slurm packages to install
    slurm_packages="slurm slurm-slurmrestd slurm-libpmi slurm-devel slurm-pam_slurm slurm-perlapi slurm-torque slurm-openlava slurm-example-configs"
    sched_packages="slurm-slurmctld slurm-slurmdbd"

    # Install Slurm packages on AlmaLinux
    OS_MAJOR_VERSION=$(echo "$OS_VERSION" | cut -d. -f1)
    for pkg in $slurm_packages; do
        yum -y install $pkg-${SLURM_VERSION}.el${OS_MAJOR_VERSION} --disableexcludes=slurm
    done
    for pkg in $sched_packages; do
        yum -y install $pkg-${SLURM_VERSION}.el${OS_MAJOR_VERSION} --disableexcludes=slurm
    done

# Installing Slurm on Ubuntu
elif [ "$OS_ID" = "ubuntu" ]; then
    echo "Installing Slurm on Ubuntu"
    REPO="slurm-ubuntu-jammy"

    echo "Setting up Slurm repository for Ubuntu..."
    # Add Slurm repository
    echo "deb [arch=amd64] https://packages.microsoft.com/repos/$REPO/ insiders main" > /etc/apt/sources.list.d/slurm.list

    # Set package pinning preferences
    echo "\
Package: slurm, slurm-*
Pin:  origin \"packages.microsoft.com\"
Pin-Priority: 990

Package: slurm, slurm-*
Pin: origin *ubuntu.com*
Pin-Priority: -1" > /etc/apt/preferences.d/slurm-repository-pin-990

    echo "Slurm repository setup completed."
    echo "------------------------------------------------------------------------------------------------------------------------------"
    echo "Installing Slurm packages"
    echo "------------------------------------------------------------------------------------------------------------------------------"

    # Update package lists and install Slurm
    # remove the need restart prompt for outdated libraries
    grep -qxF "\$nrconf{restart} = 'a';" /etc/needrestart/conf.d/no-prompt.conf || echo "\$nrconf{restart} = 'a';" | sudo tee -a /etc/needrestart/conf.d/no-prompt.conf > /dev/null
    apt-get update
    apt install -y libhwloc15 libmysqlclient-dev libssl-dev jq python3-venv chrony
    systemctl enable chrony
    systemctl start chrony
    slurm_packages="slurm-smd slurm-smd-client slurm-smd-dev slurm-smd-libnss-slurm slurm-smd-libpam-slurm-adopt slurm-smd-slurmrestd slurm-smd-sview slurm-smd-slurmctld slurm-smd-slurmdbd"
    for pkg in $slurm_packages; do
        apt-get update
        DEBIAN_FRONTEND=noninteractive apt install -y $pkg=$SLURM_VERSION
        DEBIAN_FRONTEND=noninteractive apt-mark hold $pkg   
    done
       
  # Unsupported OS

else
    echo "Unsupported OS: $OS_ID"
    exit 1
fi

echo "------------------------------------------------------------------------------------------------------------------------------"
echo "Slurm installation completed."
echo "------------------------------------------------------------------------------------------------------------------------------"

# Configure Slurm
echo "------------------------------------------------------------------------------------------------------------------------------"
echo "Configuring Slurm"
echo "------------------------------------------------------------------------------------------------------------------------------"

cat <<EOF > "$slurm_conf"
MpiDefault=none
ProctrackType=proctrack/cgroup
ReturnToService=2
PropagateResourceLimits=ALL
SlurmctldPidFile=/var/run/slurmctld.pid
SlurmdPidFile=/var/run/slurmd.pid
SlurmdSpoolDir=/var/spool/slurmd
SlurmUser=slurm
StateSaveLocation=/var/spool/slurmctld
SwitchType=switch/none
TaskPlugin=task/affinity,task/cgroup
SchedulerType=sched/backfill
SelectType=select/cons_tres
GresTypes=gpu
SelectTypeParameters=CR_Core_Memory
# We use a "safe" form of the CycleCloud cluster_name throughout slurm.
# First we lowercase the cluster name, then replace anything
# that is not letters, digits and '-' with a '-'
# eg My Cluster == my-cluster
ClusterName=$cluster_name
JobAcctGatherType=jobacct_gather/none
SlurmctldDebug=debug
SlurmctldLogFile=/var/log/slurmctld/slurmctld.log
SlurmctldParameters=idle_on_node_suspend
SlurmdDebug=debug
SlurmdLogFile=/var/log/slurmd/slurmd.log
# TopologyPlugin=topology/tree
# If you use the TopologyPlugin you likely also want to use our
# job submit plugin so that your jobs run on a single switch
# or just add --switches 1 to your submission scripts
# JobSubmitPlugins=lua
PrivateData=cloud
PrologSlurmctld=/opt/azurehpc/slurm/prolog.sh
TreeWidth=65533
ResumeTimeout=1800
SuspendTimeout=600
SuspendTime=300
ResumeProgram=/opt/azurehpc/slurm/resume_program.sh
ResumeFailProgram=/opt/azurehpc/slurm/resume_fail_program.sh
SuspendProgram=/opt/azurehpc/slurm/suspend_program.sh
SchedulerParameters=max_switch_wait=24:00:00
# Only used with dynamic node partitions.
MaxNodeCount=10000
# This as the partition definitions managed by azslurm partitions > /sched/azure.conf
Include azure.conf
# If slurm.accounting.enabled=true this will setup slurmdbd
# otherwise it will just define accounting_storage/none as the plugin
Include accounting.conf
# SuspendExcNodes is managed in /etc/slurm/keep_alive.conf
# see azslurm keep_alive for more information.
# you can also remove this import to remove support for azslurm keep_alive
Include keep_alive.conf
EOF

# Configure Hostname in slurmd.conf
echo "SlurmctldHost=$(hostname -s)" >> "$slurm_conf"

# Create cgroup.conf
cat <<EOF > "$sched_dir/cgroup.conf"
CgroupAutomount=no
ConstrainCores=yes
ConstrainRamSpace=yes
ConstrainDevices=yes
EOF

echo "# Do not edit this file. It is managed by azslurm" >> "$sched_dir/keep_alive.conf"

# Set limits for Slurm
cat <<EOF > /etc/security/limits.d/slurm-limits.conf
* soft memlock unlimited
* hard memlock unlimited
EOF

# Add accounting configuration
echo "AccountingStorageType=accounting_storage/none" >> "$sched_dir/accounting.conf"

# Set permissions and create symlinks

ln -s "$slurm_conf" /etc/slurm/slurm.conf
ln -s "$sched_dir/keep_alive.conf" /etc/slurm/keep_alive.conf
ln -s "$sched_dir/cgroup.conf" /etc/slurm/cgroup.conf
ln -s "$sched_dir/accounting.conf" /etc/slurm/accounting.conf
ln -s "$sched_dir/azure.conf" /etc/slurm/azure.conf
ln -s "$sched_dir/gres.conf" /etc/slurm/gres.conf 
touch "$sched_dir"/gres.conf "$sched_dir"/azure.conf
chown  slurm:slurm "$sched_dir"/*.conf
chmod 644 "$sched_dir"/*.conf
chown slurm:slurm /etc/slurm/*.conf

# Set up log and spool directories
mkdir -p /var/spool/slurmd /var/spool/slurmctld /var/log/slurmd /var/log/slurmctld
chown slurm:slurm /var/spool/slurmd /var/spool/slurmctld /var/log/slurmd /var/log/slurmctld
echo " "
echo "------------------------------------------------------------------------------------------------------------------------------"
echo "Slurm configured"
echo "------------------------------------------------------------------------------------------------------------------------------"
echo " "
echo "------------------------------------------------------------------------------------------------------------------------------"
echo " Go to CycleCloud Portal and edit the $cluster_name cluster configuration to use the external scheduler and start the cluster."
echo " Use $ip_address IP Address for File-system Mount for /sched and /shared in Network Attached Storage section in CycleCloud GUI "
echo " Once the cluster is started, proceed to run  cyclecloud-integrator.sh script to complete the integration with CycleCloud."
echo "------------------------------------------------------------------------------------------------------------------------------"
echo " "