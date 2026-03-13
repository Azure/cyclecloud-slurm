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

    if ! pip install --force-reinstall $PACKAGE; then
        echo "ERROR: Failed to install $PACKAGE"
        deactivate || true
        exit 1
    fi

     if ! azslurm-exporter-install; then
        echo "ERROR: Failed to run azslurm-exporter-install"
        deactivate || true
        exit 1
    fi

}

main() {
    VERSION=0.1.0
    PACKAGE=azure_slurm_exporter-$VERSION.tar.gz
    VENV=/opt/azurehpc/azslurm-exporter/venv

    # create the venv and install azslurm-exporter
    setup_venv

}

require_root() {
    if [ $(whoami) != root ]; then
    echo "Please run as root"
    exit 1
    fi
}

# Set this globally before running main.
PYTHON_PATH=$(find_python3)
require_root
main
echo Installation complete.
