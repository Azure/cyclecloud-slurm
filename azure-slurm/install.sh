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
pip install parallel-ssh
pip install --upgrade --no-deps packages/*

# Without jetpack, slurm should still be able to be installed, so we echo the defaults
SCALELIB_LOG_USER=$(jetpack config slurm.user.name 2> /dev/null || echo slurm)
SCALELIB_LOG_GROUP=$(jetpack config slurm.group.name 2>/dev/null || echo slurm)

cat > $VENV/bin/azslurm <<EOF
#!$VENV/bin/python

import os

if "SCALELIB_LOG_USER" not in os.environ:
    os.environ["SCALELIB_LOG_USER"] = "$SCALELIB_LOG_USER"
if "SCALELIB_LOG_GROUP" not in os.environ:
    os.environ["SCALELIB_LOG_GROUP"] = "$SCALELIB_LOG_GROUP"

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
which azslurm > /dev/null 2>&1 || export PATH=$PATH:/root/bin
eval "\$(/opt/azurehpc/slurm/venv/bin/register-python-argcomplete azslurm)" || echo "Warning: Autocomplete is disabled" 1>&2
EOF
fi

if [ $NO_JETPACK == 1 ]; then
    echo "--no-jetpack is set. Please run azslurm initconfig and azslurm scale manually, as well as chown slurm:slurm $VENV/../logs/*.log."
    exit 0
fi

which jetpack || (echo "Jetpack is not installed. Please run this from a CycleCloud node, or pass in --no-jetpack if you intend to install this outside of CycleCloud provisioned nodes." && exit 1)

connection_json_path=/opt/cycle/jetpack/config/connection.json
cluster_name=$(jq -r '.cluster' $connection_json_path)
escaped_cluster_name=$(python3 -c "import re; print(re.sub('[^a-zA-Z0-9-]', '-', '$cluster_name').lower())")

config_dir=/sched/$escaped_cluster_name
azslurm initconfig --username $(jq -r '.username' $connection_json_path) \
                   --password $(jq -r '.password' $connection_json_path) \
                   --url      $(jq -r '.url' $connection_json_path) \
                   --cluster-name "$(jq -r '.cluster' $connection_json_path)" \
                   --config-dir $config_dir \
                   --accounting-subscription-id $(jetpack props get azure.subscription_id) \
                   --default-resource '{"select": {}, "name": "slurm_gpus", "value": "node.gpu_count"}' \
                   --cost-cache-root $INSTALL_DIR/.cache \
                   > $INSTALL_DIR/autoscale.json


azslurm scale --no-restart

chown $SCALELIB_LOG_USER:$SCALELIB_LOG_GROUP $VENV/../logs/*.log