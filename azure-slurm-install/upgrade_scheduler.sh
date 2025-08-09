#!/bin/bash

set -eo pipefail

TIMESTAMP=$(date +%Y_%m_%d_%H_%M)
WORKDIR=/tmp/upgrade-$TIMESTAMP

# Cleanup function for error handling
cleanup() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        echo "ERROR: Upgrade failed! Attempting rollback..." >&2
        rollback_on_failure
    fi

}
trap cleanup EXIT


rollback_on_failure() {
    echo "Rolling back changes..." >&2
    systemctl stop slurmctld slurmdbd || true

    if [ -d "/etc/slurm-bak-$TIMESTAMP" ]; then
        rm -rf /etc/slurm
        mv /etc/slurm-bak-$TIMESTAMP /etc/slurm
    fi

    if [ -d "/sched/$CLUSTERNAME-bak-$TIMESTAMP" ]; then
        rm -rf "/sched/$CLUSTERNAME"
        mv "/sched/$CLUSTERNAME-bak-$TIMESTAMP" "/sched/$CLUSTERNAME"
    fi

    systemctl restart munge slurmdbd slurmctld || true

    # Restore partitions
    for part in $(sinfo -o "%R" --noheader 2>/dev/null || true); do 
        scontrol update partition="$part" state=up || true
    done
}


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
    curl --retry 3 --retry-delay 2 --retry-all-errors -fsSL -O  https://github.com/Azure/cyclecloud-slurm/releases/download/4.0.2/$PACKAGE
    tar -xf $PACKAGE
    cd azure-slurm-install
    $PYTHON_BIN install.py --mode=scheduler --platform=$OS
    echo "Success"
}

upgrade_azslurmd() {

    echo "Running azslurmd upgrade"
    cd $WORKDIR
    PACKAGE="azure-slurm-pkg-4.0.2.tar.gz"
    curl --retry 3 --retry-delay 2 --retry-all-errors -fsSL -O https://github.com/Azure/cyclecloud-slurm/releases/download/4.0.2/$PACKAGE
    tar -xf $PACKAGE
    cd azure-slurm
    AZSLURM_PYTHON_PATH=$PYTHON_BIN ./install.sh
    echo "Success"
}

upgrade_healthagent() {
    cd $WORKDIR
    systemctl stop healthagent || true
    PACKAGE="healthagent-1.0.3.tar.gz"
    curl --retry 3 --retry-delay 2 --retry-all-errors -fsSL -O https://github.com/Azure/cyclecloud-healthagent/releases/download/1.0.3/$PACKAGE
    source /opt/healthagent/.venv/bin/activate
    pip install --force-reinstall $PACKAGE
    sed -i '/^\[Service\]/a WatchdogSec=600s' /etc/systemd/system/healthagent.service
    systemctl daemon-reload
    systemctl restart healthagent || true
    cp $PACKAGE /opt/healthagent/
    echo "Healthagent upgrade complete"

}

start_services() {
    if [ -x "$WORKDIR/azure-slurm-install/start-services.sh" ]; then
        $WORKDIR/azure-slurm-install/start-services.sh scheduler
    else
        echo "ERROR: $WORKDIR/azure-slurm-install/start-services.sh not found or not executable" >&2
        exit 1
    fi
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
    echo "Preparing scheduler node for upgrade, marking partitions down..."

    # Mark partitions down
    for part in $(sinfo -o "%R" --noheader); do 
        echo "Marking partition $part down"
        scontrol update partition="$part" state=down
    done

    # Stop services
    echo "Stopping Slurm services..."
    systemctl stop slurmdbd
    systemctl stop slurmctld

    # Backup existing configuration
    echo "Backing up existing configuration..."
    if [ -d "/etc/slurm" ]; then
        mv "/etc/slurm" "/etc/slurm-bak-$TIMESTAMP"
        mkdir /etc/slurm
    fi
    if [ -d "/sched/$CLUSTERNAME" ]; then
        mv "/sched/$CLUSTERNAME" "/sched/$CLUSTERNAME-bak-$TIMESTAMP"
    fi

    if [ -f /etc/azslurm-bins.installed ]; then
        rm /etc/azslurm-bins.installed
    fi

    # Perform upgrade
    install_python3
    ### Feel free to remove this function if we don't need to upgrade healthagent.
    upgrade_healthagent
    upgrade_azslurm_install
    upgrade_azslurmd
    start_services

    echo "Upgrade complete, marking partitions back up..."
    for part in $(sinfo -o "%R" --noheader); do 
        echo "Marking partition $part up"
        scontrol update partition="$part" state=up
    done

    echo "Scheduler upgrade completed successfully!"
}

main "$@"