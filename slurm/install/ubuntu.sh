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
DISABLE_PMC=$3

apt update
UBUNTU_VERSION=$(cat /etc/os-release | grep VERSION_ID | cut -d= -f2 | cut -d\" -f2)
if [[ $UBUNTU_VERSION > "19" ]]; then
    apt -y install python3-venv
fi

apt -y install munge
 
apt -y install libmariadbclient-dev-compat libssl-dev

if [ $UBUNTU_VERSION == 22.04 ]; then
    REPO=slurm-ubuntu-jammy
else
    REPO=slurm-ubuntu-focal
fi

if [ "$DISABLE_PMC" = "False" ]; then
    echo "deb [arch=amd64] https://packages.microsoft.com/repos/$REPO/ insiders main" > /etc/apt/sources.list.d/slurm.list
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
    slurm_packages="slurm slurm-slurmrestd slurm-libpmi slurm-devel slurm-pam-slurm slurm-perlapi slurm-torque slurm-openlava slurm-example-configs"
    for pkg in $slurm_packages; do
        apt install -y $pkg=$SLURM_VERSION
        apt-mark hold $pkg
    done

    if [ ${SLURM_ROLE} == "scheduler" ]; then
        apt install -y slurm-slurmctld=$SLURM_VERSION slurm-slurmdbd=$SLURM_VERSION
        apt-mark hold slurm-slurmctld slurm-slurmdbd
    fi
    if [ ${SLURM_ROLE} == "execute" ]; then
        apt install -y slurm-slurmd=$SLURM_VERSION
        apt-mark hold slurm-slurmd
    fi

    touch $INSALLED_FILE
    exit
fi

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

if [ $UBUNTU_VERSION == 22.04 ]; then
    PACKAGE_DIR=slurm-pkgs-ubuntu22
else
    PACKAGE_DIR=slurm-pkgs-ubuntu20
fi

dpkg -i --force-all $(ls $PACKAGE_DIR/debs/*${SLURM_VERSION}*.deb | grep -v -e slurmdbd -e slurmctld)

if [ ${SLURM_ROLE} == "scheduler" ]; then
    dpkg -i --force-all $PACKAGE_DIR/debs/slurm-slurmctld_${SLURM_VERSION}*.deb
    dpkg -i --force-all $PACKAGE_DIR/debs/slurm-slurmdbd_${SLURM_VERSION}*.deb
fi

touch $INSALLED_FILE