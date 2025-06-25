#!/usr/bin/env bash
set -e
set -x

mode=$(jetpack config slurm.role install-only)
install_pkg=$(jetpack config slurm.install_pkg azure-slurm-install-pkg-4.0.0.tar.gz)
slurm_project_name=$(jetpack config slurm.project_name slurm)


cd $CYCLECLOUD_HOME/system/bootstrap

# Install Slurm
jetpack download --project $slurm_project_name $install_pkg
tar xzf $install_pkg
cd azure-slurm-install
python3 install.py --config-mode $mode

echo "installation complete. Run start-services scheduler|execute|login to start the slurm services."
