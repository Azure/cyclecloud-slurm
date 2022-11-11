#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
set -e
if [ $(whoami) != root ]; then
  echo "Please run as root"
  exit 1
fi

SCHEDULER=slurm
INSTALL_PYTHON3=0
VENV=/opt/azurehpc/slurm/venv
export PATH=$PATH:/root/bin

while (( "$#" )); do
    case "$1" in
        --install-python3)
            INSTALL_PYTHON3=1
            shift
            ;;
        --venv)
            VENV=$2
            shift 2
            ;;
        -*|--*=)
            echo "Unknown option $1" >&2
            exit 1
            ;;
        *)
            echo "Unknown option  $1" >&2
            exit 1
            ;;
    esac
done

echo INSTALL_PYTHON3=$INSTALL_PYTHON3
echo VENV=$VENV

# remove jetpack's python3 from the path
export PATH=$(echo $PATH | sed -e 's/\/opt\/cycle\/jetpack\/system\/embedded\/bin://g' | sed -e 's/:\/opt\/cycle\/jetpack\/system\/embedded\/bin//g')
set +e
which python3 > /dev/null;
if [ $? != 0 ]; then
    if [ $INSTALL_PYTHON3 == 1 ]; then
        yum install -y python3 || exit 1
    else
        echo Please install python3 >&2;
        exit 1
    fi
fi
set -e


python3 -m venv $VENV
mkdir -p $VENV/../logs
source $VENV/bin/activate
# not sure why but pip gets confused installing frozendict locally
# if you don't install it first. It has no dependencies so this is safe.
pip install --upgrade packages/*

cat > $VENV/bin/azslurm <<EOF
#!$VENV/bin/python

from ${SCHEDULER}cc.cli import main
main()
EOF
chmod +x $VENV/bin/azslurm

azslurm -h 2>&1 > /dev/null || exit 1


if [ ! -e /root/bin ]; then
    mkdir /root/bin
fi

ln -sf $VENV/bin/azslurm /root/bin/

INSTALL_DIR=$(dirname $VENV)

cp logging.conf $INSTALL_DIR/
cp sbin/*.sh $INSTALL_DIR/
chown slurm:slurm $INSTALL_DIR/*.sh
chmod +x $INSTALL_DIR/*.sh

if [ -e /etc/profile.d ]; then
    cat > /etc/profile.d/azslurm_autocomplete.sh<<EOF
which azslurm 2>/dev/null || export PATH=\$PATH:/root/bin
eval "\$(/opt/azurehpc/slurm/venv/bin/register-python-argcomplete azslurm)" || echo "Warning: Autocomplete is disabled" 1>&2
EOF
fi

which jetpack || exit 0
tag=$(jetpack config azure.metadata.compute.tags | python3 -c "import sys; print(dict([tuple(x.split(':', 1)) for x in sys.stdin.read().split(';')])['ClusterId'])")
azslurm initconfig --username $(jetpack config cyclecloud.config.username) \
                   --password $(jetpack config cyclecloud.config.password) \
                   --url      $(jetpack config cyclecloud.config.web_server) \
                   --cluster-name $(jetpack config cyclecloud.cluster.name) \
                   --accounting-tag-name ClusterId \
                   --accounting-tag-value $tag \
                   --accounting-subscription-id $(jetpack config azure.metadata.compute.subscriptionId) \
                   > $INSTALL_DIR/autoscale.json


azslurm partitions > /sched/azure.conf

chown slurm:slurm $VENV/../logs/*.log