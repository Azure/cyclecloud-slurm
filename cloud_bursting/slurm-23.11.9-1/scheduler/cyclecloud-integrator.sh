#!/bin/bash
# -----------------------------------------------------------------------------
# Script: Install CycleCloud Autoscaler and Integrate with Slurm Scheduler
#
# This script automates the installation of the CycleCloud Autoscaler package, 
# a key component used to dynamically scale compute resources in a cluster managed 
# by the CycleCloud environment. It integrates with the Slurm scheduler to ensure 
# efficient scaling based on workload demands.
#
# Key Features:
# - Installs the CycleCloud Autoscaler package.
# - Configures integration with the Slurm workload manager for automated scaling.
# - Ensures that the compute resources in the cluster can scale up or down based 
#   on the job queue and resource usage, optimizing both performance and cost.
#
# Prerequisites:
# - Root or sudo privileges are required to execute the installation steps.
# - Slurm scheduler should already be set up in the environment.
#
# Usage:
# sh cyclecloud-integrator.sh
# -----------------------------------------------------------------------------
set -e
if [ $(whoami) != root ]; then
  echo "Please run as root"
  exit 1
fi


# Prompt user to enter CycleCloud details for Slurm scheduler integration
echo "Please enter the CycleCloud details to integrate with the Slurm scheduler"
echo " "
# Prompt for Cluster Name
read -p "Enter Cluster Name: " cluster_name

# Prompt for Username
read -p "Enter CycleCloud Username: " username

# Prompt for Password (masked input)
echo -n "Enter CycleCloud password: "
stty -echo   # Turn off echo
read password
stty echo    # Turn echo back on
echo
echo "Password entered."
# Prompt for URL
read -p "Enter CycleCloud IP (e.g.,10.222.1.19): " ip
url="https://$ip"

# Display summary of entered details
echo "------------------------------------------------------------------------------------------------------------------------------"
echo " "
echo "Summary of entered details:"
echo "Cluster Name: $cluster_name"
echo "CycleCloud Username: $username"
echo "CycleCloud URL: $url"
echo " "
echo "------------------------------------------------------------------------------------------------------------------------------"

# Define variables

slurm_autoscale_pkg_version="3.0.9"
slurm_autoscale_pkg="azure-slurm-pkg-$slurm_autoscale_pkg_version.tar.gz"
slurm_script_dir="/opt/azurehpc/slurm"
config_dir="/sched/$cluster_name"

# Create necessary directories
mkdir -p "$slurm_script_dir"

# Activate Python virtual environment for Slurm integration
echo "------------------------------------------------------------------------------------------------------------------------------"
echo "Configuring virtual enviornment and Activating Python virtual environment"
echo "------------------------------------------------------------------------------------------------------------------------------"
python3 -m venv "$slurm_script_dir/venv"
. "$slurm_script_dir/venv/bin/activate"

# Download and install CycleCloud Slurm integration package
echo "------------------------------------------------------------------------------------------------------------------------------"
echo "Downloading and installing CycleCloud Slurm integration package"
echo "------------------------------------------------------------------------------------------------------------------------------"

wget https://github.com/Azure/cyclecloud-slurm/releases/download/$slurm_autoscale_pkg_version/$slurm_autoscale_pkg -P "$slurm_script_dir"
tar -xvf "$slurm_script_dir/$slurm_autoscale_pkg" -C "$slurm_script_dir"
cd "$slurm_script_dir/azure-slurm"
head -n -30 install.sh > integrate-cc.sh
chmod +x integrate-cc.sh
./integrate-cc.sh
#cleanup
rm -rf azure-slurm*

# Initialize autoscaler configuration
echo "------------------------------------------------------------------------------------------------------------------------------"
echo "Initializing autoscaler configuration"
echo "------------------------------------------------------------------------------------------------------------------------------"

azslurm initconfig --username "$username" --password "$password" --url "$url" --cluster-name "$cluster_name" --config-dir "$config_dir" --default-resource '{"select": {}, "name": "slurm_gpus", "value": "node.gpu_count"}' > "$slurm_script_dir/autoscale.json"
chown slurm:slurm "$slurm_script_dir/autoscale.json"
chown -R slurm:slurm "$slurm_script_dir"
# Connect and scale
echo "------------------------------------------------------------------------------------------------------------------------------"
echo "Connecting to CycleCloud and scaling resources"
echo "------------------------------------------------------------------------------------------------------------------------------"

azslurm connect
azslurm scale --no-restart
chown -R slurm:slurm "$slurm_script_dir"/logs/*.log

systemctl restart munge
systemctl restart slurmctld
echo " "
echo "------------------------------------------------------------------------------------------------------------------------------"
echo "Slurm scheduler integration with CycleCloud completed successfully"
echo " Create User and Group for job submission. Make sure that GID and UID is consistent across all nodes and home directory is shared"
echo "------------------------------------------------------------------------------------------------------------------------------"
echo " "