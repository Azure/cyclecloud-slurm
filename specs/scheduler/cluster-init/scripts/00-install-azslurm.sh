#!/usr/bin/env bash
set -e
set -x

autoscale_pkg=$(jetpack config slurm.autoscale_pkg azure-slurm-pkg-4.0.0.tar.gz)
slurm_project_name=$(jetpack config slurm.project_name slurm)


cd $CYCLECLOUD_HOME/system/bootstrap
rm -rf azure-slurm
jetpack download --project $slurm_project_name $autoscale_pkg
tar xzf $autoscale_pkg
cd azure-slurm
./install.sh

echo "installation complete. Run start-services scheduler|execute|login to start the slurm services."
