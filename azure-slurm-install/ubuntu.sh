#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
set -e
set -x

SLURM_ROLE=$1
SLURM_VERSION=$2

UBUNTU_VERSION=$(cat /etc/os-release | grep VERSION_ID | cut -d= -f2 | cut -d\" -f2)
if [[ $UBUNTU_VERSION > "19" ]]; then
    apt -y install python3-venv
fi

arch=$(dpkg --print-architecture)
if [[ $UBUNTU_VERSION =~ ^24\.* ]]; then
    REPO=slurm-ubuntu-noble
elif [ $UBUNTU_VERSION == 22.04 ]; then
    REPO=slurm-ubuntu-jammy
else
    REPO=slurm-ubuntu-focal
fi

if [[ $UBUNTU_VERSION =~ ^24\.* ]]; then
    # microsoft-prod no longer installs GPG key in /etc/apt/trusted.gpg.d
    # so we need to use signed-by instead to specify the key for Ubuntu 24.04 onwards
    echo "deb [arch=$arch signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/repos/$REPO/ insiders main" > /etc/apt/sources.list.d/slurm.list
else
    if [ "$arch" == "arm64" ]; then
        echo "Slurm is not supported on arm64 architecture for Ubuntu versions < 24.04"
        exit 1
    fi
    echo "deb [arch=$arch] https://packages.microsoft.com/repos/$REPO/ insiders main" > /etc/apt/sources.list.d/slurm.list
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
apt -y install munge libmysqlclient-dev libssl-dev jq
slurm_packages="slurm-smd slurm-smd-client slurm-smd-dev slurm-smd-libnss-slurm slurm-smd-libpam-slurm-adopt slurm-smd-slurmrestd slurm-smd-sview"

if [[ ${SLURM_ROLE} == "scheduler" || ${SLURM_ROLE} == "install-only" ]]; then
    slurm_packages+=" slurm-smd-slurmctld slurm-smd-slurmdbd"
fi

if [[ ${SLURM_ROLE} == "execute" || ${SLURM_ROLE} == "install-only" ]]; then
    slurm_packages+=" slurm-smd-slurmd"
fi

for pkg in $slurm_packages; do
    apt-mark unhold $pkg
    apt install -y $pkg=$SLURM_VERSION
    apt-mark hold $pkg
done

exit