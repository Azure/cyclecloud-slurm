#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
set -e
INSALLED_FILE=/etc/azslurm-bins.installed
if [ -e $INSALLED_FILE ]; then
    exit 0
fi

SLURM_ROLE=$1
SLURM_VERSION=$2

apt update
UBUNTU_VERSION=$(cat /etc/os-release | grep VERSION_ID | cut -d= -f2 | cut -d\" -f2)
if [ $UBUNTU_VERSION > "19" ]; then
    apt -y install python3.8-venv
fi

apt -y install munge
 
apt -y install libmariadbclient-dev-compat libssl-dev

if [ $UBUNTU_VERSION > "19" ]; then
    ln -sf /lib/x86_64-linux-gnu/libreadline.so.8 /usr/lib/x86_64-linux-gnu/libreadline.so.7
    ln -sf /lib/x86_64-linux-gnu/libhistory.so.8 /usr/lib/x86_64-linux-gnu/libhistory.so.7
    ln -sf /lib/x86_64-linux-gnu/libncurses.so.6 /usr/lib/x86_64-linux-gnu/libncurses.so.6
    ln -sf /lib/x86_64-linux-gnu/libtinfo.so.6.2 /usr/lib/x86_64-linux-gnu/libtinfo.so.6
    # part of what is needed for perl support, but libperl.so.5.26 is not available on ubuntu via public
    # repos, so for this release we will need to have support use cloud-init to install perl
    ln -sf /usr/lib64/libslurm.so.38 /usr/lib/x86_64-linux-gnu/

else
    ln -sf /usr/lib/x86_64-linux-gnu/libssl.so /usr/lib/x86_64-linux-gnu/libssl.so.10 
    ln -sf /usr/lib/x86_64-linux-gnu/libcrypto.so /usr/lib/x86_64-linux-gnu/libcrypto.so.10
    ln -sf /usr/lib/x86_64-linux-gnu/libmysqlclient.so /usr/lib/x86_64-linux-gnu/libmysqlclient.so.18
    # Need to manually create links for libraries the RPMs are linked to (we use alien to create the debs)

    ln -sf /lib/x86_64-linux-gnu/libreadline.so.7 /usr/lib/x86_64-linux-gnu/libreadline.so.6 
    ln -sf /lib/x86_64-linux-gnu/libhistory.so.7 /usr/lib/x86_64-linux-gnu/libhistory.so.6
    ln -sf /lib/x86_64-linux-gnu/libncurses.so.5 /usr/lib/x86_64-linux-gnu/libncurses.so.5
    ln -sf /lib/x86_64-linux-gnu/libtinfo.so.5 /usr/lib/x86_64-linux-gnu/libtinfo.so.5
fi

dpkg -i --force-all $(ls slurm-pkgs/*${SLURM_VERSION}*.deb | grep -v slurmdbd)
if [ ${SLURM_ROLE} == "scheduler" ]; then
    # slurmdbd transpilation from rpm to deb fails due to a clashing build uuid
    # e.g. /usr/lib/.build-id/XX/XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
    dpkg -i --force-all slurm-pkgs/*slurmdbd*${SLURM_VERSION}*.deb
fi

touch $INSALLED_FILE