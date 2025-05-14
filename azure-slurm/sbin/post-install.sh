#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
set -e
cd $(dirname $0)
azslurm scale
chown -R slurm:slurm logs/