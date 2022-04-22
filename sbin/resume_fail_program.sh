#!/usr/bin/env bash
source /opt/azurehpc/slurm/venv/bin/activate
azslurm suspend --node-list $1
exit $?