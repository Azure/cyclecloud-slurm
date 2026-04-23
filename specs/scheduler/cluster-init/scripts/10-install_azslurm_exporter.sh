#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
set -e

script_dir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
SPEC_FILE_ROOT="$script_dir/../files"
source "$SPEC_FILE_ROOT/common.sh"

monitoring_enabled=$(jetpack config cyclecloud.monitoring.enabled False)
exporter_pkg=azure_slurm_exporter-0.1.0.tar.gz
slurm_project_name=$(jetpack config slurm.project_name slurm)
VENV=/opt/azurehpc/slurm/venv

install_exporter() {

    if [ ! -d "$VENV" ]; then
        $PYTHON_BIN -m venv "$VENV"
    fi

    set +e
    source $VENV/bin/activate
    set -e

    if ! pip install --force-reinstall $exporter_pkg; then
        echo "ERROR: Failed to install $exporter_pkg"
        deactivate || true
        exit 1
    fi

     if ! azslurm-exporter-install; then
        echo "ERROR: Failed to run azslurm-exporter-install"
        deactivate || true
        exit 1
    fi

    deactivate || true
}

# Check if OS is supported before proceeding
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
    VERSION_ID=$VERSION_ID
    if [[ "$OS" == "sle_hpc" ]]; then
        echo "Unsupported operating system: $OS."
        exit 0
    fi
else
    echo "Cannot detect the operating system. Exiting."
    exit 0
fi

if [ "$monitoring_enabled" = "True" ]; then
    install_python3
    verify_python3_version "$PYTHON_BIN"
    cd $CYCLECLOUD_HOME/system/bootstrap
    rm -f -- "$exporter_pkg"
    jetpack download --project "$slurm_project_name" "$exporter_pkg"
    install_exporter
    echo "Azslurm Exporter installation complete. Run start-services scheduler to start the azslurm-exporter and slurm services."
else
    echo "Monitoring disabled, skipping azslurm-exporter install."
    exit 0
fi