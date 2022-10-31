#!/usr/bin/env bash
source /opt/azurehpc/slurm/venv/bin/activate

azslurm nodes -C '{"node.name": ["'$1'"]}' -o name,vm_size,location,spot -F json 
