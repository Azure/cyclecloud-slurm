#!/usr/bin/env bash
cyclecloud_slurm_python=/opt/cycle/jetpack/system/embedded/bin/python
export PYTHONPATH=$(dirname $0)
$cyclecloud_slurm_python -m cyclecloud_slurm $@
exit $?
