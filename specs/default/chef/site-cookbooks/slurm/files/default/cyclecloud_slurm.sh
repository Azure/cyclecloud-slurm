#!/usr/bin/env bash
export PATH=$PATH:/usr/bin
bootstrap=/opt/cycle/slurm
# Slurm used to start processes in /var/log/slurmctld
# As backup, just kick off the process in the bootstrap dir
cd /var/log/slurmctld || cd $bootstrap
source $bootstrap/venv/bin/activate
export PYTHONPATH=$PYTHONPATH:$bootstrap
python3 -m cyclecloud_slurm "$@"
exit $?
