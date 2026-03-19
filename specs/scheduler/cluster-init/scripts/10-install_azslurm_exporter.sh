#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
set -e

monitoring_enabled=$(jetpack config cyclecloud.monitoring.enabled False)
exporter_pkg=azure_slurm_exporter-0.1.0.tar.gz
slurm_project_name=$(jetpack config slurm.project_name slurm)

find_python3() {
    export PATH=$(echo $PATH | sed -e 's/\/opt\/cycle\/jetpack\/system\/embedded\/bin://g' | sed -e 's/:\/opt\/cycle\/jetpack\/system\/embedded\/bin//g')
    for version in $( seq 11 20 ); do
        which python3.$version > /dev/null 2>/dev/null
        if [ $? == 0 ]; then
            python3.$version -c "import venv"
            if [ $? == 0 ]; then
                # write to stdout the validated path
                which python3.$version
                return 0
            else
                echo Warning: Found python3.$version but venv not installed. 1>&2
            fi
        fi
    done
    # Quietly return nothing
    return 0
}

setup_exporter_venv() {

    set -e
    VENV=/opt/azurehpc/azslurm-exporter/venv
    $PYTHON_PATH -c "import sys; sys.exit(0)" || (echo "$PYTHON_PATH is not a valid python3 executable. Please install python3.11 or higher." && exit 1)
    $PYTHON_PATH -m pip --version > /dev/null || $PYTHON_PATH -m ensurepip

    if [ ! -d "$VENV" ]; then
        echo "Creating virtual environment at $VENV..."
        $PYTHON_PATH -m venv "$VENV"
    else
        echo "Virtual environment already exists at $VENV"
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
    cd $CYCLECLOUD_HOME/system/bootstrap
    rm -f -- "$exporter_pkg"
    jetpack download --project "$slurm_project_name" "$exporter_pkg"
    PYTHON_PATH=$(find_python3)
    setup_exporter_venv
    echo "Azslurm Exporter installation complete. Run start-services scheduler to start the azslurm-exporter and slurm services."
else
    echo "Monitoring disabled, skipping azslurm-exporter install."
    exit 0
fi