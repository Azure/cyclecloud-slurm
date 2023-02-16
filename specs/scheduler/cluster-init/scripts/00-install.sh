#!/usr/bin/env bash
set -e

do_install=$(jetpack config slurm.do_install True)
install_pkg=$(jetpack config slurm.install_pkg azure-slurm-install-pkg-3.0.1.tar.gz)
autoscale_pkg=$(jetpack config slurm.autoscale_pkg azure-slurm-pkg-3.0.1.tar.gz)
slurm_project_name=$(jetpack config slurm.project_name slurm)
platform=$(jetpack config platform_family rhel)

cd $CYCLECLOUD_HOME/system/bootstrap
if [ $do_install == "True" ]; then
    rm -rf azure-slurm-install
    jetpack download --project $slurm_project_name $install_pkg
    tar xzf $install_pkg
    cd azure-slurm-install
    python3 install.py --platform $platform --mode scheduler --bootstrap-config $CYCLECLOUD_HOME/config/node.json
    cd ..
fi

rm -rf azure-slurm
jetpack download --project $slurm_project_name $autoscale_pkg
tar xzf $autoscale_pkg
cd azure-slurm
./install.sh

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