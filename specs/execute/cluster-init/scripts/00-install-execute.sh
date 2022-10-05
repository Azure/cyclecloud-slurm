#!/usr/bin/env bash
set -e
do_install=$(jetpack config slurm.do_install True)
install_pkg=$(jetpack config slurm.install_pkg None)
autoscale_pkg=$(jetpack config slurm.autoscale_pkg None)
slurm_project_name=$(jetpack config slurm.project_name slurm)
platform=$(jetpack config platform_family rhel)

cd $CYCLECLOUD_HOME/system/bootstrap
if [ $do_install == "True" ]; then
    
    jetpack download --project $slurm_project_name $install_pkg
    tar xzf $install_pkg
    cd azure-slurm-install
    ./install.sh --platform $platform --mode scheduler
    cd ..
fi

slurmctld start
