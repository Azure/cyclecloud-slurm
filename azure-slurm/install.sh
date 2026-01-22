#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
set -e

find_python3() {
    export PATH=$(echo $PATH | sed -e 's/\/opt\/cycle\/jetpack\/system\/embedded\/bin://g' | sed -e 's/:\/opt\/cycle\/jetpack\/system\/embedded\/bin//g')
    if [ ! -z $AZSLURM_PYTHON_PATH ]; then
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
    python3 -m pip install parallel-ssh
    # upgrade venv with packages from intallation
    python3 -m pip install --upgrade --no-deps packages/*

    # Create azslurm executable
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

    cat > $VENV/bin/azslurmd <<EOF
#!$VENV/bin/python

import os

if "SCALELIB_LOG_USER" not in os.environ:
    os.environ["SCALELIB_LOG_USER"] = "$SCALELIB_LOG_USER"
if "SCALELIB_LOG_GROUP" not in os.environ:
    os.environ["SCALELIB_LOG_GROUP"] = "$SCALELIB_LOG_GROUP"

from ${SCHEDULER}cc.azslurmdwrapper import main
main()
EOF

    chmod +x $VENV/bin/azslurm
    chmod +x $VENV/bin/azslurmd
    if [ ! -e ~/bin ]; then
        mkdir ~/bin
    fi

    ln -sf $VENV/bin/azslurm ~/bin/

    # setup autocomplete of azslurm
    if [ -e /etc/profile.d ]; then
        cat > /etc/profile.d/azslurm_autocomplete.sh<<EOF
which azslurm > /dev/null 2>&1 || export PATH=\$PATH:/root/bin
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

init_azslurm_config() {
    which jetpack || (echo "Jetpack is not installed. Please run this from a CycleCloud node, or pass in --no-jetpack if you intend to install this outside of CycleCloud provisioned nodes." && exit 1)

    $INSTALL_DIR/init-config.sh \
        --url "$(jetpack config cyclecloud.config.web_server)" \
        --cluster-name "$(jetpack config cyclecloud.cluster.name)" \
        --username $(jetpack config cyclecloud.config.username) \
        --password $(jetpack config cyclecloud.config.password) \
        --accounting-subscription-id $(jetpack config azure.metadata.compute.subscriptionId)
}

setup_azslurmd() {
    cat > /etc/systemd/system/azslurmd.service <<EOF
[Unit]
Description=AzSlurm Daemon
After=network.target

[Service]
ExecStart=$VENV/bin/azslurmd
Restart=always
User=root
Group=root
WorkingDirectory=/tmp/
Environment="PATH=/$VENV/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable azslurmd
}

no_jetpack() {
    echo "--no-jetpack is set. Please run $INSTALL_DIR/init-config.sh then $INSTALL_DIR/post-install.sh."
}

require_root() {
    if [ $(whoami) != root ]; then
    echo "Please run as root"
    exit 1
    fi
}

parse_args_set_variables() {
    export SCHEDULER=slurm
    export VENV=/opt/azurehpc/slurm/venv
    export INSTALL_DIR=$(dirname $VENV)
    export NO_JETPACK=0
    # if jetpack doesn't exist or this is not defined, it will silently use slurm as default 
    export SCALELIB_LOG_USER=$(jetpack config slurm.user.name 2> /dev/null || echo slurm)
    export SCALELIB_LOG_GROUP=$(jetpack config slurm.group.name 2>/dev/null || echo slurm)
    # Set this globally before running main.
    export PYTHON_PATH=$(find_python3)
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
}

main() {
    # create the venv and make sure azslurm is in the path
    setup_venv
    # setup the install dir - logs and logging.conf, some permissions.
    setup_install_dir
    # setup the azslurmd but do not start it.
    setup_azslurmd
    # If there is no jetpack, we have to stop here.
    # The user has to run $INSTALL_DIR/init-config.sh with the appropriate arguments, and then $INSTALL_DIR/post-install.sh
    if [ $NO_JETPACK == 1 ]; then
        no_jetpack
        exit 0
    fi

    # we have jetpack, so let's automate init-config.sh and post-install.sh
    init_azslurm_config
    echo Running $INSTALL_DIR/post-install.sh
    $INSTALL_DIR/post-install.sh $SCALELIB_LOG_GROUP $SCALELIB_LOG_USER
}

require_root() {
    if [ $(whoami) != root ]; then
    echo "Please run as root"
    exit 1
    fi
}


parse_args_set_variables() {
    export SCHEDULER=slurm
    export VENV=/opt/azurehpc/slurm/venv
    export INSTALL_DIR=$(dirname $VENV)
    export NO_JETPACK=0
    # if jetpack doesn't exist or this is not defined, it will silently use slurm as default 
    export SCALELIB_LOG_USER=$(jetpack config slurm.user.name 2> /dev/null || echo slurm)
    export SCALELIB_LOG_GROUP=$(jetpack config slurm.group.name 2>/dev/null || echo slurm)
    # Set this globally before running main.
    export PYTHON_PATH=$(find_python3)
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
}

require_root
parse_args_set_variables $@
main
echo Installation complete.
