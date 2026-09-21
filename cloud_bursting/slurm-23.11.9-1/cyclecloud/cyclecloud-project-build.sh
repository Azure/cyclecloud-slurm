#!/bin/sh
# This script need to run on cyclecloud VM.
# This script will fetch the CycleCloud project and upload it to the locker.
# Author : Vinil Vadakkepurakkal
# Date : 01/10/2024
set -e
read -p "Enter Cluster Name: " cluster_name
echo "Cluster Name: $cluster_name"
echo "Use the same cluster name: $cluster_name in building the scheduler"

echo "Importing Cluster"
cyclecloud import_cluster $cluster_name -c Slurm_HL -f slurm.txt

# creating custom project and upload it to the locker

CCLOCKERNAME=$(cyclecloud locker list | sed 's/(.*)//; s/[[:space:]]*$//')
echo "Locker Name: $CCLOCKERNAME"
echo "Fetching CycleCloud project"
SLURM_PROJ_VERSION="3.0.9"
cyclecloud project fetch https://github.com/Azure/cyclecloud-slurm/releases/$SLURM_PROJ_VERSION slurm-$SLURM_PROJ_VERSION
cd slurm-$SLURM_PROJ_VERSION
echo "Uploading CycleCloud project to the locker"
cyclecloud project upload "$CCLOCKERNAME"