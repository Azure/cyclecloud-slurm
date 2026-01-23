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

# Add this after the azslurmd executable creation (around line 77)

    cat > $VENV/bin/azslurm-exporter <<EOF
#!$VENV/bin/python

import os
import sys

# Add the exporter path to sys.path
sys.path.insert(0, "/opt/azurehpc/slurm/exporter")

if "SCALELIB_LOG_USER" not in os.environ:
    os.environ["SCALELIB_LOG_USER"] = "$SCALELIB_LOG_USER"
if "SCALELIB_LOG_GROUP" not in os.environ:
    os.environ["SCALELIB_LOG_GROUP"] = "$SCALELIB_LOG_GROUP"

from exporter import main
main()
EOF

    chmod +x $VENV/bin/azslurm-exporter
    ln -sf $VENV/bin/azslurm-exporter ~/bin/
    
    # setup autocomplete of azslurm
    if [ -e /etc/profile.d ]; then
        cat > /etc/profile.d/azslurm_autocomplete.sh<<EOF
if [ "\$(whoami)" == "root" ]; then 
  which azslurm > /dev/null 2>&1 || export PATH=\$PATH:/root/bin
  eval "\$(/opt/azurehpc/slurm/venv/bin/register-python-argcomplete azslurm)" || echo "Warning: Autocomplete is disabled" 1>&2
fi
EOF
    fi

    azslurm -h 2>&1 > /dev/null || exit 1
}

setup_install_dir() {
    mkdir -p $INSTALL_DIR/logs
    mkdir -p $INSTALL_DIR/exporter
    cp logging.conf $INSTALL_DIR/
    cp sbin/*.sh $INSTALL_DIR/
    if [ -d "exporter" ]; then
        cp exporter/*.py $INSTALL_DIR/exporter/
    fi
    chown slurm:slurm $INSTALL_DIR/*.sh
    chmod +x $INSTALL_DIR/*.sh
    chown -R slurm:slurm $INSTALL_DIR/exporter
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

create_deployment_timestamp() {
    TIMESTAMP_FILE="$INSTALL_DIR/cluster_deploy_time"
    
    # Only create if it doesn't exist (preserve original deployment time)
    if [ ! -f "$TIMESTAMP_FILE" ]; then
        # Store as ISO 8601 format that sacct accepts
        date -u +"%Y-%m-%dT%H:%M:%S" > "$TIMESTAMP_FILE"
        chown slurm:slurm "$TIMESTAMP_FILE"
        chmod 644 "$TIMESTAMP_FILE"
        echo "Cluster deployment timestamp created: $(cat $TIMESTAMP_FILE)"
    else
        echo "Using existing deployment timestamp: $(cat $TIMESTAMP_FILE)"
    fi
}

setup_azslurm_exporter() {
    # Create exporter directory
    mkdir -p /opt/azurehpc/slurm/exporter
    
    # Copy exporter files if they exist in the installation package
    if [ -d "exporter" ]; then
        cp exporter/*.py /opt/azurehpc/slurm/exporter/
        chown -R slurm:slurm /opt/azurehpc/slurm/exporter
    fi
    
    # Get the deployment timestamp
    TIMESTAMP_FILE="$INSTALL_DIR/cluster_deploy_time"
    if [ ! -f "$TIMESTAMP_FILE" ]; then
        echo "Error: Deployment timestamp not found at $TIMESTAMP_FILE" >&2
        exit 1
    fi
    DEPLOY_TIME=$(cat "$TIMESTAMP_FILE")
    
    cat > /etc/systemd/system/azslurm-exporter.service <<EOF
[Unit]
Description=Azure Slurm Prometheus Exporter
After=network.target slurmd.service
Wants=slurmd.service

[Service]
Type=simple
ExecStart=$VENV/bin/azslurm-exporter --port 9500 --reset-time "$DEPLOY_TIME"
Restart=on-failure
RestartSec=5s
User=slurm
Group=slurm
WorkingDirectory=/opt/azurehpc/slurm/exporter
Environment="PATH=$VENV/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="PYTHONUNBUFFERED=1"

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=azslurm-exporter

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable azslurm-exporter
    
    echo "azslurm-exporter service created and enabled"
    echo "Deployment time set to: $DEPLOY_TIME"
    echo "To start: systemctl start azslurm-exporter"
    echo "To check status: systemctl status azslurm-exporter"
    echo "Metrics will be available at http://localhost:9500/metrics"
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
    # Create deployment timestamp (only on first deployment)
    create_deployment_timestamp
    # setup the azslurmd but do not start it.
    setup_azslurmd
    # setup the azslurm-exporter but do not start it.
    setup_azslurm_exporter
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
