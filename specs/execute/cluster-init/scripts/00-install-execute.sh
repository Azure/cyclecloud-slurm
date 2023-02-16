#!/usr/bin/env bash
set -e
do_install=$(jetpack config slurm.do_install True)
install_pkg=$(jetpack config slurm.install_pkg azure-slurm-install-pkg-3.0.1.tar.gz)
slurm_project_name=$(jetpack config slurm.project_name slurm)
platform=$(jetpack config platform_family rhel)

cd $CYCLECLOUD_HOME/system/bootstrap
if [ $do_install == "True" ]; then
    
    jetpack download --project $slurm_project_name $install_pkg
    tar xzf $install_pkg
    cd azure-slurm-install
    python3 install.py --platform $platform --mode execute --bootstrap-config /opt/cycle/jetpack/config/node.json
fi

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

systemctl start slurmd