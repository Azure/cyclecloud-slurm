#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
set -e
cd $(dirname $0)

if [ $(whoami) != root ]; then
  echo "Please run as root"
  exit 1
fi

if [ -e /etc/centos-release ]; then
    python3 install.py --platform rhel $@ --mode execute
else
    python3 install.py --platform ubuntu $@ --mode execute
fi
