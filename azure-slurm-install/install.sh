#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
set -e
set -x

SLURM_VERSION=$1

python3 install.py --config-mode install-only -s $1