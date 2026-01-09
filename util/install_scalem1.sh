#!/bin/bash

curl https://raw.githubusercontent.com/Azure/cyclecloud-slurm/tags/slurm_m1-1.0.1/scale_m1/scale_to_n_nodes.py > ~/bin/scale_m1
chmod +x ~/bin/scale_m1

# only run resume for non-gpu nodes
printf '#!/usr/bin/env bash
node_list=$(echo $@ | sed "s/ /,/g")
source /opt/azurehpc/slurm/venv/bin/activate
non_gpu=$(scontrol show hostnames $node_list | grep -v gpu)
if [ "$non_gpu" == "" ]; then
    exit 0
fi
azslurm resume --node-list $non_gpu
exit $?
' > /opt/azurehpc/slurm/resume_program.sh