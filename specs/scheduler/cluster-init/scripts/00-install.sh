#!/usr/bin/env bash
set -e

do_install=$(jetpack config slurm.do_install True)
install_pkg=$(jetpack config slurm.install_pkg azure-slurm-install-pkg-3.0.0.tar.gz)
autoscale_pkg=$(jetpack config slurm.autoscale_pkg azure-slurm-pkg-3.0.0.tar.gz)
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

slurmctld start

attempts=3
delay=5
for i in $( seq 1 $attempts ); do
    echo $i/$attempts sleeping $delay seconds before running scontrol ping
    sleep $delay
    scontrol ping && exit 0
done
