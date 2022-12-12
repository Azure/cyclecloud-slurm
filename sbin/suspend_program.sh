#!/usr/bin/env bash
node_list=$(echo $@ | sed "s/ /,/g")
source /opt/azurehpc/slurm/venv/bin/activate
azslurm suspend --node-list $node_list
exit $?