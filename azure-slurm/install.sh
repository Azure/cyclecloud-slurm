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
VENV=/opt/azurehpc/slurm/venv
INSTALL_DIR=$(dirname $VENV)
NO_JETPACK=0

export PATH=$PATH:/root/bin

while (( "$#" )); do
    case "$1" in
        --no-jetpack)
            NO_JETPACK=1
            shift
            ;;
        --help)
            echo "Usage: $0 [--no-jetpack]"
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

find_python3() {
    export PATH=$(echo $PATH | sed -e 's/\/opt\/cycle\/jetpack\/system\/embedded\/bin://g' | sed -e 's/:\/opt\/cycle\/jetpack\/system\/embedded\/bin//g')
    if [ ! -z $AZSLURM_PYTHON_PATH]; then
        echo $AZSLURM_PYTHON_PATH
        return 0
    fi
    for version in $( seq 11 20 ); do
        which python3.$version
        if [ $? == 0 ]; then
            return 0
        fi
    done
    echo Could not find python3 version 3.11 >&2
    return 1
}

setup_venv() {
    
    set -e

    $PYTHON_PATH -c "import sys; sys.exit(0)" || (echo "$PYTHON_PATH is not a valid python3 executable. Please install python3.11 or higher." && exit 1)
    $PYTHON_PATH -m pip --version > /dev/null || $PYTHON_PATH -m ensurepip
    $PYTHON_PATH -m venv $VENV

    set +e
    source $VENV/bin/activate
    set -e

    # ensure wheel is installed
    python3 -m pip install wheel
    # upgrade venv with packages from intallation
    python3 -m pip install --upgrade --no-deps packages/*

    SCALELIB_LOG_USER=$(jetpack config slurm.user.name 2> /dev/null || echo slurm)
    SCALELIB_LOG_GROUP=$(jetpack config slurm.group.name 2>/dev/null || echo slurm)

    # Create azslurm and azslurmd executables
    # NOTE: dynamically generated due to the SCALELIB_LOG_USER and SCALELIB_LOG_GROUP
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
    if [ ! -e ~/bin ]; then
        mkdir ~/bin
    fi

    ln -sf $VENV/bin/azslurm ~/bin/

    # setup autocomplete of azslurm
    if [ -e /etc/profile.d ]; then
        cat > /etc/profile.d/azslurm_autocomplete.sh<<EOF
which azslurm > /dev/null 2>&1 || export PATH=$PATH:/root/bin
eval "\$(/opt/azurehpc/slurm/venv/bin/register-python-argcomplete azslurm)" || echo "Warning: Autocomplete is disabled" 1>&2
EOF
    fi

    azslurm -h 2>&1 > /dev/null || exit 1
}

setup_install_dir() {
    mkdir -p $INSTALL_DIR/logs
    cp logging.conf $INSTALL_DIR/
    cp sbin/*.sh $INSTALL_DIR/
    chown slurm:slurm $INSTALL_DIR/*.sh
    chmod +x $INSTALL_DIR/*.sh
}

# TODO implement more functions to replace what comes after.
PYTHON_PATH=$(find_python3)
setup_venv
setup_install_dir


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

chown $SCALELIB_LOG_USER:$SCALELIB_LOG_GROUP $VENV/../logs/*.log