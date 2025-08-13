#!/bin/bash

set -eo pipefail
# Get cluster name
CLUSTERNAME=$(scontrol show config | grep -i '^ClusterName' | awk -F= '{print $2}' | xargs)
if [ -z "$CLUSTERNAME" ]; then
    echo "ERROR: Could not determine cluster name" >&2
    exit 1
fi

source /opt/healthagent/.venv/bin/activate
healthagent-install > /dev/null
install -o root -g root -m 0755 /etc/healthagent/health.sh.example /sched/$CLUSTERNAME/health.sh.tmp
mv /sched/$CLUSTERNAME/health.sh.tmp /sched/$CLUSTERNAME/health.sh