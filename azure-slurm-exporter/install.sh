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

}
add_scraper() {
    # If az_exporter is already configured, do not add it again
    if grep -q "azslurm_exporter" $PROM_CONFIG; then
        echo "AzSlurm Exporter is already configured in Prometheus"
        return 0
    fi
    INSTANCE_NAME=$(hostname)

    cat > azslurm-exporter.yml <<-EOF
    scrape_configs:
    - job_name: azslurm_exporter
      static_configs:
      - targets: ["instance_name:9101"]
      relabel_configs:
      - source_labels: [__address__]
        target_label: instance
        regex: '([^:]+)(:[0-9]+)?'
        replacement: '\${1}'
EOF

    yq eval-all '. as $item ireduce ({}; . *+ $item)' $PROM_CONFIG azslurm-exporter.yml > tmp.yml
    mv -vf tmp.yml $PROM_CONFIG

    # update the configuration file
    sed -i "s/instance_name/$INSTANCE_NAME/g" $PROM_CONFIG
}


setup_azslurm_exporter() {
    cat > /etc/systemd/system/azslurm-exporter.service <<EOF
[Unit]
Description=AzSlurm Exporter Daemon
After=network.target

[Service]
ExecStart=$VENV/bin/azslurm-exporter
Restart=always
User=root
Group=root
Environment="PATH=/$VENV/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable azslurm-exporter
}

main() {
    VERSION=0.1.0
    PACKAGE=azure_slurm_exporter-$VERSION.tar.gz
    SCHEDULER=slurm
    VENV=/opt/azurehpc/azslurm-exporter/venv
    INSTALL_DIR=$(dirname $VENV)
    PATH=$PATH:/root/bin
    PROM_CONFIG=/opt/prometheus/prometheus.yml

    # create the venv and install azslurm-exporter
    setup_venv
    add_scraper
    # setup the azslurm-exporter systemd but do not start it.
    setup_azslurm_exporter
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
