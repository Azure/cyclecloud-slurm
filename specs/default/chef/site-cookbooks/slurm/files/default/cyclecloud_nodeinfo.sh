#!/usr/bin/env bash
source $bootstrap/venv/bin/activate
export PYTHONPATH=$PYTHONPATH:$(dirname $0)
python3 -m cyclecloud_slurm nodeinfo "$@"
exit $?
