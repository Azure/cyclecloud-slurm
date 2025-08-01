#!/bin/bash
# Generic log and configuration capture script for slurm project. Can be used on Scheduler/login/Execute nodes.
set -euo pipefail

LOG_LOCATIONS=(
    "/etc/slurm"
    "/opt/azurehpc/slurm/logs"
    "/opt/cycle/jetpack/logs"
    "/opt/healthagent/healthagent.log"
    "/opt/healthagent/healthagent_install.log"
    "/var/log/slurmctld/"
    "/var/log/slurmd"
    "/var/log/syslog"
    "/var/log/waagent.log"
    "/var/log/cloud-init.log"
    "/var/log/azure-slurm-install.log"
)
HOSTNAME=$(hostname)
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
ARCHIVE_NAME="${HOSTNAME}-${TIMESTAMP}.log.tar.gz"
ARCHIVE_BASENAME="${HOSTNAME}-${TIMESTAMP}.log"
ARCHIVE_PATH="$(pwd)/$ARCHIVE_NAME"
OUTPUT_DIR="/tmp/logbundle/$ARCHIVE_BASENAME"

echo "Creating output directory..."
rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"

# === Copy Logs ===
echo "Copying log files..."
for path in "${LOG_LOCATIONS[@]}"; do
    if [ -e "$path" ]; then
        echo " - Copying $path"
        dest="$OUTPUT_DIR${path%/*}"
        mkdir -p "$dest"
        cp -r "$path" "$dest/"
    else
        echo " - Skipping missing path: $path"
    fi
done

echo "Creating tar archive..."
tar -czf "$ARCHIVE_PATH" -C "/tmp/logbundle" "$ARCHIVE_BASENAME"

echo "Log archive created at: $ARCHIVE_PATH"
rm -rf $OUTPUT_DIR