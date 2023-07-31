#!/usr/bin/env bash
node_list=$(echo $@ | sed "s/ /,/g")
echo node list is $node_list
$(dirname $0)/./cyclecloud_slurm.sh resume_fail --node-list $node_list
exit $?