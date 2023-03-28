#!/usr/env/bin bash
## Called inside the container
set -e

yum install -y python36 wget
if [ -e /source/cyclecloud-scalelib ]; then
    /source/azure-slurm/build.sh /source/cyclecloud-scalelib
else
    /source/azure-slurm/build.sh
fi