#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
set -e
INSTALLED_FILE=/etc/azslurm-bins.installed
SLURM_ROLE=$1
SLURM_VERSION=$2

# Function to check if a package is installed (for any version)
is_package_installed() {
    local pkg_name=$1
    dpkg -l | grep -q "^[hi]i  ${pkg_name}"
}

# Function to check if a package is installed with specific version prefix
is_package_installed_with_version() {
    local pkg_name=$1
    local version_prefix=$2
    dpkg -l | grep "^[hi]i  ${pkg_name}" | grep -q "${version_prefix}"
}

UBUNTU_VERSION=$(cat /etc/os-release | grep VERSION_ID | cut -d= -f2 | cut -d\" -f2)

system_packages=""

# Handle python3-venv for Ubuntu > 19
if [[ $UBUNTU_VERSION > "19" ]]; then
    if ! is_package_installed "python3-venv"; then
        echo "python3-venv needs to be installed"
        system_packages="$system_packages python3-venv"
    else
        echo "python3-venv is already installed"
    fi
fi

# Handle system packages
for pkg in munge libmysqlclient-dev libssl-dev jq; do
    if ! is_package_installed "$pkg"; then
        echo "$pkg needs to be installed"
        system_packages="$system_packages $pkg"
    else
        echo "$pkg is already installed"
    fi
done

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

slurm_packages="slurm-smd slurm-smd-client slurm-smd-dev slurm-smd-libnss-slurm slurm-smd-libpam-slurm-adopt slurm-smd-sview"
sched_packages="slurm-smd-slurmctld slurm-smd-slurmdbd slurm-smd-slurmrestd"
execute_packages="slurm-smd-slurmd"

# Collect all SLURM packages based on role
all_packages="$slurm_packages"

if [ "${SLURM_ROLE}" == "scheduler" ]; then
    all_packages="$all_packages $sched_packages"
fi

if [ "${SLURM_ROLE}" == "execute" ]; then
    all_packages="$all_packages $execute_packages"
fi

packages_to_install="$system_packages"
packages_to_hold=""

# Add SLURM packages that aren't installed
for pkg in $all_packages; do
    if is_package_installed_with_version "$pkg" "$SLURM_VERSION"; then
        echo "Package $pkg with version ${SLURM_VERSION}* is already installed"
    else
        echo "Package $pkg with version ${SLURM_VERSION}* needs to be installed"
        packages_to_install="$packages_to_install ${pkg}=${SLURM_VERSION}*"
        packages_to_hold="$packages_to_hold $pkg"
    fi
done

# Install all packages in one command (system packages first, then SLURM packages)
if [ -n "$packages_to_install" ]; then
    apt update
    echo "Installing all packages: $packages_to_install"
    apt install -y --allow-downgrades --allow-change-held-packages $packages_to_install
    echo "Successfully installed all required packages"
    
    # Hold SLURM packages to prevent automatic updates
    if [ -n "$packages_to_hold" ]; then
        echo "Holding packages: $packages_to_hold"
        apt-mark hold $packages_to_hold
    fi
else
    echo "All required packages are already installed"
fi

touch $INSTALLED_FILE
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