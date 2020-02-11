#!/usr/bin/env bash
$(dirname $0)/./cyclecloud_slurm.sh terminate_nodes --node-list $1
exit $?
