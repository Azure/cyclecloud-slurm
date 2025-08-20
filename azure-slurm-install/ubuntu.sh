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
if [[ $UBUNTU_VERSION > "19" ]]; then
    apt -y install python3-venv
fi

apt -y install munge
 
apt -y install libmysqlclient-dev libssl-dev jq
arch=$(dpkg --print-architecture)
if [[ $UBUNTU_VERSION =~ ^24\.* ]]; then
    REPO=slurm-ubuntu-noble
elif [ $UBUNTU_VERSION == 22.04 ]; then
    REPO=slurm-ubuntu-jammy
else
    REPO=slurm-ubuntu-focal
fi

REPO_GROUP="stable"
INSIDERS=$(/opt/cycle/jetpack/bin/jetpack config slurm.insiders False)
if [[ "$INSIDERS" == "True" ]]; then
    REPO_GROUP="insiders"
fi

if [[ $UBUNTU_VERSION =~ ^24\.* ]]; then
    # microsoft-prod no longer installs GPG key in /etc/apt/trusted.gpg.d
    # so we need to use signed-by instead to specify the key for Ubuntu 24.04 onwards
    echo "deb [arch=$arch signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/repos/$REPO/ $REPO_GROUP main" > /etc/apt/sources.list.d/slurm.list
else
    if [ "$arch" == "arm64" ]; then
        echo "Slurm is not supported on arm64 architecture for Ubuntu versions < 24.04"
        exit 1
    fi
    echo "deb [arch=$arch] https://packages.microsoft.com/repos/$REPO/ $REPO_GROUP main" > /etc/apt/sources.list.d/slurm.list
fi
echo "\
Package: slurm, slurm-*
Pin:  origin \"packages.microsoft.com\"
Pin-Priority: 990

Package: slurm, slurm-*
Pin: origin *ubuntu.com*
Pin-Priority: -1" > /etc/apt/preferences.d/slurm-repository-pin-990

## This package is pre-installed in all hpc images used by cyclecloud, but if customer wants to
## use generic ubuntu marketplace image then this package sets up the right gpg keys for PMC.
if [ ! -e /etc/apt/sources.list.d/microsoft-prod.list ]; then
    curl -sSL -O https://packages.microsoft.com/config/ubuntu/$UBUNTU_VERSION/packages-microsoft-prod.deb
    dpkg -i packages-microsoft-prod.deb
    rm packages-microsoft-prod.deb
fi
apt update
slurm_packages="slurm-smd slurm-smd-client slurm-smd-dev slurm-smd-libnss-slurm slurm-smd-libpam-slurm-adopt slurm-smd-sview"
for pkg in $slurm_packages; do
    apt install -y $pkg=$SLURM_VERSION
    apt-mark hold $pkg
done

if [ ${SLURM_ROLE} == "scheduler" ]; then
    apt install -y slurm-smd-slurmctld=$SLURM_VERSION slurm-smd-slurmdbd=$SLURM_VERSION slurm-smd-slurmrestd=$SLURM_VERSION
    apt-mark hold slurm-smd-slurmctld slurm-smd-slurmdbd slurm-smd-slurmrestd
fi
if [ ${SLURM_ROLE} == "execute" ]; then
    apt install -y slurm-smd-slurmd=$SLURM_VERSION
    apt-mark hold slurm-smd-slurmd
fi

touch $INSALLED_FILE
exit

if [[ $UBUNTU_VERSION > "19" ]]; then
    apt install -y libhwloc15

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
