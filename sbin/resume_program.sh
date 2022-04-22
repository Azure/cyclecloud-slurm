#!/usr/bin/env bash
source /opt/azurehpc/slurm/venv/bin/activate
azslurm resume --node-list $1
exit $?