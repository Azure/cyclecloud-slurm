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
    python3 install.py --platform rhel $@
else
    set +e
    which zypper 2>/dev/null 1>&2
    result=$1
    set -e
    if [ $result -eq 0 ]; then
      python3 install.py --platform suse $@
    else
      python3 install.py --platform ubuntu $@
    fi
fi
