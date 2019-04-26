#!/usr/bin/env bash
$(dirname $0)/./cyclecloud_slurm.sh resume --node-list $1
exit $?