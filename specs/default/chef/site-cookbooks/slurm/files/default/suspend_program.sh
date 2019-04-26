#!/usr/bin/env bash
$(dirname $0)/./cyclecloud_slurm.sh suspend --node-list $1
exit $?