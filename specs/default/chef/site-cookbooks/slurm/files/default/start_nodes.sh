#!/usr/bin/env bash
node_list=$(echo $@ | sed "s/ /,/g")
$(dirname $0)/./cyclecloud_slurm.sh resume --keep-alive --node-list $node_list
exit $?