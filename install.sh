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
NO_JETPACK=0

export PATH=$PATH:/root/bin

while (( "$#" )); do
    case "$1" in
        --install-python3)
            INSTALL_PYTHON3=1
            shift
            ;;
        --no-jetpack)
            NO_JETPACK=1
            shift
            ;;
        --venv)
            VENV=$2
            shift 2
            ;;
        --help)
            echo "Usage: $0 [--install-python3] [--venv <path>] [--no-jetpack]"
            exit 0
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
set -e

# ensure wheel is installed
pip install wheel
pip install --upgrade --no-deps packages/*

cat > $VENV/bin/azslurm <<EOF
#!$VENV/bin/python

from ${SCHEDULER}cc.cli import main
main()
EOF
chmod +x $VENV/bin/azslurm

azslurm -h 2>&1 > /dev/null || exit 1


if [ ! -e ~/bin ]; then
    mkdir ~/bin
fi

ln -sf $VENV/bin/azslurm ~/bin/

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

if [ $NO_JETPACK == 1 ]; then
    echo "--no-jetpack is set. Please run azslurm initconfig and azslurm scale manually, as well as chown slurm:slurm $VENV/../logs/*.log."
    exit 0
fi

which jetpack || (echo "Jetpack is not installed. Please run this from a CycleCloud node, or pass in --no-jetpack if you intend to install this outside of CycleCloud provisioned nodes." && exit 1)

# note: lower case the tag names, and use a sane default 'unknown'
tag=$(jetpack config azure.metadata.compute.tags | python3 -c "\
import sys;\
items = [x.split(':', 1) for x in sys.stdin.read().split(';')];\
tags = dict([tuple([i[0].lower(), i[-1]]) for i in items]);\
print(tags.get('clusterid', 'unknown'))")

cluster_name=$(jetpack config cyclecloud.cluster.name)
escaped_cluster_name=$(python3 -c "import re; print(re.sub('[^a-zA-Z0-9-]', '-', '$cluster_name').lower())")

config_dir=/sched/$escaped_cluster_name
azslurm initconfig --username $(jetpack config cyclecloud.config.username) \
                   --password $(jetpack config cyclecloud.config.password) \
                   --url      $(jetpack config cyclecloud.config.web_server) \
                   --cluster-name "$(jetpack config cyclecloud.cluster.name)" \
                   --config-dir $config_dir \
                   --accounting-tag-name ClusterId \
                   --accounting-tag-value "$tag" \
                   --accounting-subscription-id $(jetpack config azure.metadata.compute.subscriptionId) \
                   --default-resource '{"select": {}, "name": "slurm_gpus", "value": "node.gpu_count"}' \
                   --cost-cache-root $INSTALL_DIR/.cache \
                   > $INSTALL_DIR/autoscale.json


azslurm scale --no-restart

chown slurm:slurm $VENV/../logs/*.log