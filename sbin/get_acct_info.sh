#!/usr/bin/env bash
source /opt/azurehpc/slurm/venv/bin/activate

azslurm accounting_info --node-name $1
