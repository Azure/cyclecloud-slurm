#!/usr/bin/env bash
set -e

mode=$1
echo $mode | grep -Eqw "login|execute" || (echo "Usage: $0 [login|execute]" && exit 1)

do_install=$(jetpack config slurm.do_install True)
install_pkg=$(jetpack config slurm.install_pkg azure-slurm-install-pkg-3.0.1.tar.gz)
slurm_project_name=$(jetpack config slurm.project_name slurm)
platform=$(jetpack config platform_family rhel)
dynamic_config=$(jetpack config slurm.dynamic_config _none_)


cd $CYCLECLOUD_HOME/system/bootstrap
if [ $do_install == "True" ]; then
    
    jetpack download --project $slurm_project_name $install_pkg
    tar xzf $install_pkg
    cd azure-slurm-install
    python3 install.py --platform $platform --mode $mode --bootstrap-config /opt/cycle/jetpack/config/node.json
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

if [ "$mode" == "execute" ]; then
    if [ "$dynamic_config" != "_none_" ]; then
        delete_dynamic_node=$(jetpack config slurm.delete_dynamic_node True)
        if [ "$delete_dynamic_node" == "True" ]; then
            node_name=$(jetpack config cyclecloud.node.name)
            echo "Deleting dynamic node $node_name"
            
            scontrol delete nodename=$node_name
        fi
    fi

    systemctl start slurmd
fi