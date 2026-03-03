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
    python3 -m pip install aiohttp

    # upgrade venv with packages from intallation
    python3 -m pip install --upgrade --no-deps packages/*

    # Create exporter executable
    cat > $VENV/bin/azslurm-exporter <<EOF
#!$VENV/bin/python

from exporter import main
import asyncio
asyncio.run(main())
EOF


    chmod +x $VENV/bin/azslurm-exporter
    if [ ! -e ~/bin ]; then
        mkdir ~/bin
    fi

    ln -sf $VENV/bin/azslurm-exporter ~/bin/
}

setup_install_dir() {
    cp exporter_logging.conf $INSTALL_DIR/
}

setup_azslurm_exporter() {
    cat > /etc/systemd/system/azslurm-exporter.service <<EOF
[Unit]
Description=AzSlurm Exporter Daemon
After=network.target

[Service]
ExecStart=$VENV/bin/azslurm-exporter
Restart=on-failure
User=root
Group=root
Environment="PATH=/$VENV/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable azslurm-exporter
}

require_root() {
    if [ $(whoami) != root ]; then
    echo "Please run as root"
    exit 1
    fi
}

parse_args_set_variables() {
    export SCHEDULER=slurm
    export VENV=/opt/azurehpc/azslurm-exporter/venv
    export INSTALL_DIR=$(dirname $VENV)
    # Set this globally before running main.
    export PYTHON_PATH=$(find_python3)
    export PATH=$PATH:/root/bin

    while (( "$#" )); do
        case "$1" in
            --help)
                echo "Usage: $0"
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
    # create the venv and make sure azslurm-exporter is in the path
    setup_venv
    setup_install_dir
    # setup the azslurm-exporter but do not start it.
    setup_azslurm_exporter
}

require_root() {
    if [ $(whoami) != root ]; then
    echo "Please run as root"
    exit 1
    fi
}

require_root
parse_args_set_variables $@
main
echo Installation complete.
