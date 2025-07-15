#!/usr/bin/env bash
set -e

mode=$1
echo $mode | grep -Eqw "login|execute" || (echo "Usage: $0 [login|execute]" && exit 1)

do_install=$(jetpack config slurm.do_install True)
install_pkg=$(jetpack config slurm.install_pkg azure-slurm-install-pkg-4.0.1.tar.gz)
slurm_project_name=$(jetpack config slurm.project_name slurm)
platform=$(jetpack config platform_family rhel)


cd $CYCLECLOUD_HOME/system/bootstrap
if [ $do_install == "True" ]; then

    jetpack download --project $slurm_project_name $install_pkg
    tar xzf $install_pkg
    cd azure-slurm-install
    python3 install.py --platform $platform --mode $mode --bootstrap-config /opt/cycle/jetpack/config/node.json
fi

echo "installation complete. Run start-services scheduler|execute|login to start the slurm services."
