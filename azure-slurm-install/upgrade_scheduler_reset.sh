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
    cp -p start-services.sh /opt/azurehpc/slurm/
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

update_slurm_conf() {
    BACKUP_SLURM_CONF="/sched/$CLUSTERNAME-bak-$TIMESTAMP/slurm.conf"
    NEW_SLURM_CONF="/sched/$CLUSTERNAME/slurm.conf"

    SITE_SPECIFIC_CONF="/sched/$CLUSTERNAME/site_specific.conf"

    echo "Analyzing slurm.conf differences..."

    # Check if backup file exists
    if [ ! -f "$BACKUP_SLURM_CONF" ]; then
        echo "Warning: Backup slurm.conf not found at $BACKUP_SLURM_CONF"
        return 0
    fi

    # Check if new file exists
    if [ ! -f "$NEW_SLURM_CONF" ]; then
        echo "Warning: New slurm.conf not found at $NEW_SLURM_CONF"
        return 0
    fi

    # Create temporary files for processing
    TEMP_BACKUP=$(mktemp)
    TEMP_NEW=$(mktemp)
    TEMP_DIFF=$(mktemp)

    # Clean up function for temp files
    cleanup_temp() {
        rm -f "$TEMP_BACKUP" "$TEMP_NEW" "$TEMP_DIFF"
    }
    trap cleanup_temp RETURN

    # Normalize files by removing comments and empty lines, then sort
    grep -v '^#' "$BACKUP_SLURM_CONF" | grep -v '^[[:space:]]*$' | sort > "$TEMP_BACKUP"
    grep -v '^#' "$NEW_SLURM_CONF" | grep -v '^[[:space:]]*$' | sort > "$TEMP_NEW"

    # Find lines that exist in backup but not in new config
    comm -23 "$TEMP_BACKUP" "$TEMP_NEW" > "$TEMP_DIFF"

    # Check if there are any differences
    if [ -s "$TEMP_DIFF" ]; then
        echo "Found site-specific configuration differences, creating $SITE_SPECIFIC_CONF"

        # Create site-specific.conf with header
        cat > "$SITE_SPECIFIC_CONF" << EOF
# Site-specific Slurm configuration
# Generated during upgrade on $(date)
# These are configuration lines that were present in the previous slurm.conf
# but are not in the new default configuration

EOF

        # Add the differences
        cat "$TEMP_DIFF" >> "$SITE_SPECIFIC_CONF"

        echo "Site-specific configuration saved to $SITE_SPECIFIC_CONF"

    else
        echo "No site-specific configuration differences found"
        # Create empty file to indicate it was checked
        cat > "$SITE_SPECIFIC_CONF" << EOF
# Site-specific Slurm configuration. Add additional slurm config or overrrides to default config here.
EOF
        if command -v chown >/dev/null 2>&1; then
            chown slurm:slurm "$SITE_SPECIFIC_CONF" 2>/dev/null || true
        fi
    fi

    # Add include directive to slurm.conf if not already present
    if ! grep -q "^include site_specific.conf" "$NEW_SLURM_CONF"; then
        echo "" >> "$NEW_SLURM_CONF"
        echo "# Include site-specific configuration" >> "$NEW_SLURM_CONF"
        echo "Include site_specific.conf" >> "$NEW_SLURM_CONF"
        echo "Added 'include site_specific.conf' to $NEW_SLURM_CONF"
    else
        echo "Include directive already exists in $NEW_SLURM_CONF"
    fi

    ln -s $SITE_SPECIFIC_CONF /etc/slurm/site_specific.conf
}

update_prolog_epilog() {
    BACKUP_PROLOG_DIR="/sched/$CLUSTERNAME-bak-$TIMESTAMP/prolog.d"
    BACKUP_EPILOG_DIR="/sched/$CLUSTERNAME-bak-$TIMESTAMP/epilog.d"
    CURRENT_PROLOG_DIR="/sched/$CLUSTERNAME/prolog.d"
    CURRENT_EPILOG_DIR="/sched/$CLUSTERNAME/epilog.d"

    # Process prolog.d directory
    if [ -d "$BACKUP_PROLOG_DIR" ]; then
        echo "Checking prolog.d scripts..."
        for script in "$BACKUP_PROLOG_DIR"/*; do
            # Skip if no files match the glob pattern
            [ -e "$script" ] || continue

            script_name=$(basename "$script")
            current_script="$CURRENT_PROLOG_DIR/$script_name"

            # Only copy if the script doesn't exist in current directory
            if [ ! -e "$current_script" ]; then
                echo "Copying prolog script: $script_name"
                cp -p "$script" "$current_script"
                echo "Copied $script_name with preserved permissions"
            fi
        done
    else
        echo "No backup prolog.d directory found at $BACKUP_PROLOG_DIR"
    fi

    # Process epilog.d directory
    if [ -d "$BACKUP_EPILOG_DIR" ]; then
        echo "Checking epilog.d scripts..."
        for script in "$BACKUP_EPILOG_DIR"/*; do
            # Skip if no files match the glob pattern
            [ -e "$script" ] || continue

            script_name=$(basename "$script")
            current_script="$CURRENT_EPILOG_DIR/$script_name"

            # Only copy if the script doesn't exist in current directory
            if [ ! -e "$current_script" ]; then
                echo "Copying epilog script: $script_name"
                cp -p "$script" "$current_script"
                echo "Copied $script_name with preserved permissions"
            fi
        done
    else
        echo "No backup epilog.d directory found at $BACKUP_EPILOG_DIR"
    fi
}

start_services() {
    if [ -x "/opt/azurehpc/slurm/start-services.sh" ]; then
        /opt/azurehpc/slurm/start-services.sh scheduler
    else
        echo "ERROR: /opt/azurehpc/slurm/start-services.sh not found or not executable" >&2
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
    update_slurm_conf
    update_prolog_epilog
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