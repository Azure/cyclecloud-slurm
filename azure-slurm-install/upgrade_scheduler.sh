#!/bin/bash

set -eo pipefail

TIMESTAMP=$(date +%Y_%m_%d_%H_%M)
WORKDIR=/tmp/upgrade-$TIMESTAMP

find_python3() {
    export PATH=$(echo $PATH | sed -e 's/\/opt\/cycle\/jetpack\/system\/embedded\/bin://g' | sed -e 's/:\/opt\/cycle\/jetpack\/system\/embedded\/bin//g')
    if [ ! -z "$AZSLURM_PYTHON_PATH" ]; then
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

install_python3() {
    PYTHON_BIN=$(find_python3)
    if [ -z "$PYTHON_BIN" ]; then
        return 0
    fi
    # NOTE: based off of healthagent 00-install.sh, but we have different needs - we don't need the devel/systemd paths.
    # most likely if healthagent is already installed, this won't be an issue.
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$ID
        VERSION_ID=$VERSION_ID
    else
        echo "Cannot detect the operating system."
        exit 1
    fi

    if [ "$OS" == "almalinux" ]; then
        echo "Detected AlmaLinux. Installing Python 3.12..." >&2
        yum install -y python3.12
        PYTHON_BIN="/usr/bin/python3.12"

    elif [ "$OS" == "ubuntu" ] && [ "$VERSION_ID" == "22.04" ]; then
        echo "Detected Ubuntu 22.04. Installing Python 3.11..." >&2
        apt update
        # We need python dev headers and systemd dev headers for same reaosn mentioned above.
        apt install -y python3.11 python3.11-venv
        PYTHON_BIN="/usr/bin/python3.11"

    elif [ "$OS" == "ubuntu" ] && [[ $VERSION_ID =~ ^24\.* ]]; then
        echo "Detected Ubuntu 24. Installing Python 3.12..." >&2
        apt update
        apt install -y python3.12 python3.12-venv
        PYTHON_BIN="/usr/bin/python3.12"
    else
        echo "Unsupported operating system: $OS $VERSION_ID" >&2
        exit 1
    fi
    export PYTHON_BIN
}
upgrade_azslurm_install() {

    echo "Running azslurm install upgrade"
    cd $WORKDIR
    PACKAGE="azure-slurm-install-pkg-4.0.2.tar.gz"
    curl --retry 10 --retry-delay 5 --retry-all-errors -fsSL -O  https://github.com/Azure/cyclecloud-slurm/releases/download/4.0.2/$PACKAGE
    tar -xf $PACKAGE
    cd azure-slurm-install
    install -o root -g root -m 0755 start-services.sh /opt/azurehpc/slurm/
    install -o root -g root -m 0755 capture_logs.sh /opt/cycle/
    install -o root -g root -m 0755 imex_epilog.sh /sched/$CLUSTERNAME/epilog.d/
    install -o root -g root -m 0755 imex_prolog.sh /sched/$CLUSTERNAME/prolog.d/
}

upgrade_azslurmd() {

    echo "Running azslurmd upgrade"
    cd $WORKDIR
    PACKAGE="azure-slurm-pkg-4.0.2.tar.gz"
    curl --retry 10 --retry-delay 5 --retry-all-errors -fsSL -O https://github.com/Azure/cyclecloud-slurm/releases/download/4.0.2/$PACKAGE
    tar -xf $PACKAGE
    cd azure-slurm
    AZSLURM_PYTHON_PATH=$PYTHON_BIN ./install.sh
    echo "Success"
}

upgrade_healthagent() {
    cd $WORKDIR
    systemctl stop healthagent || true
    PACKAGE="healthagent-1.0.3.tar.gz"
    curl --retry 10 --retry-delay 5 --retry-all-errors -fsSL -O https://github.com/Azure/cyclecloud-healthagent/releases/download/1.0.3/$PACKAGE
    source /opt/healthagent/.venv/bin/activate
    pip install --force-reinstall $PACKAGE
    healthagent-install
    sed -i '/^\[Service\]/a WatchdogSec=600s' /etc/systemd/system/healthagent.service
    systemctl daemon-reload
    systemctl restart healthagent || true
    cp $PACKAGE /opt/healthagent/
    install -o root -g root -m 0755 /etc/healthagent/health.sh.example /sched/$CLUSTERNAME/health.sh
    install -o root -g root -m 0755 /etc/healthagent/epilog.sh.example /sched/$CLUSTERNAME/epilog.d/99-health_epilog.sh
    echo "Healthagent upgrade complete"

}


main(){
    mkdir -p "$WORKDIR"

    echo "Starting upgrade of scheduler node, workdir: $WORKDIR"

    # Get cluster name
    CLUSTERNAME=$(scontrol show config | grep -i '^ClusterName' | awk -F= '{print $2}' | xargs)
    if [ -z "$CLUSTERNAME" ]; then
        echo "ERROR: Could not determine cluster name" >&2
        exit 1
    fi

    echo "Cluster: $CLUSTERNAME"

    # Perform upgrade
    install_python3
    ### Feel free to remove this function if we don't need to upgrade healthagent.
    upgrade_healthagent
    upgrade_azslurm_install
    upgrade_azslurmd

    echo "Scheduler upgrade completed successfully!"
}

main "$@"