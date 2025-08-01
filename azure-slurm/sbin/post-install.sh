#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
set -e
cd $(dirname $0)
azslurm scale --no-restart
SLURM_GROUP=${1:-slurm}
SLURM_USER=${2:-slurm}
chown -R $SLURM_GROUP:$SLURM_USER logs/
systemctl restart azslurmd
