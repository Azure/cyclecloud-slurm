#!/bin/bash
set -x

log=/var/log/slurmctld/prolog_slurmctld.log
script=/opt/azurehpc/slurm/get_acct_info.sh
scontrol=/bin/scontrol
JQ=/bin/jq
job=$SLURM_JOBID

nodename=$($scontrol show hostnames $SLURM_JOB_NODELIST | head -n 1)

ret=0
count=0

while [ $ret -eq 0 ] && [ $count -lt 5 ]
do
	sleep 2
	output=$($script $nodename 2>>$log)
	ret=$(echo $output | $JQ '. | length')
	echo "DEBUG: json: " $output "ret: " $ret "job: " $SLURM_JOBID "nodename: " $nodename >> $log
	count=$((count+1))
done

if [ $ret -eq 0 ]; then
	echo "ERROR: Could not process get node info for admincomment" >> $log
else
	$scontrol update job=$job admincomment="$output"
fi
