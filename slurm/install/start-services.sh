#!/usr/bin/env bash
set -e

if [ "$1" == "" ]; then
    echo "Usage: $0 [scheduler|execute|login]"
    exit 1
fi

role=$1

# all nodes need to have munge running
echo restarting munge...
systemctl restart munge
# wait up to 60 seconds for munge to start
iters=60
while [ $iters -ge 0 ]; do
    echo test | munge > /dev/null 2>&1
    if [ $? == 0 ]; then
        break
    fi
    sleep 1
    iters=$(( $iters - 1 ))
done

# login nodes explicitly should _not_ have slurmd running.
if [ $role == "login" ]; then
    exit 0
fi

# execute nodes just need slurmd
if [ $role == "execute" ]; then
    systemctl start slurmd
    exit 0
fi

# sanity check - make sure a valid role was actually passed in.
# note they are defined in the slurm_*_role.rb
if [ $role != "scheduler" ]; then
    echo  unknown role! $role 1>&2
    exit 2
fi

# lastly - the scheduler

systemctl show slurmdbd 2>&1 > /dev/null && systemctl start slurmdbd
# there is no obvious way to check slurmdbd status _before_ starting slurmctld
sleep 10
systemctl start slurmctld
attempts=3
delay=5
set +e
for i in $( seq 1 $attempts ); do
    echo $i/$attempts sleeping $delay seconds before running scontrol ping
    sleep $delay
    scontrol ping
    if [ $? == 0 ]; then
        systemctl start slurmd || exit 1
        exit 0
    fi;
done

echo FATAL: slurmctld has not started! 1>&2
echo Here are the last 100 lines of slurmctld.log
tail -n 100 /var/log/slurmctld/slurmctld.log 1>&2
exit 2
