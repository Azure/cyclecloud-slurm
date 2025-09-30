#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
set -e
INSTALLED_FILE=/etc/azslurm-bins.installed
SLURM_ROLE=$1
SLURM_VERSION=$2

UBUNTU_VERSION=$(cat /etc/os-release | grep VERSION_ID | cut -d= -f2 | cut -d\" -f2)

dpkg_pkg_install() {
    local packages_to_install=""
    local packages_to_hold=""
    local pkg_names=$1
    
    for pkg_name in $pkg_names; do
        # Check if it's a versioned SLURM package
        if [[ "$pkg_name" == *"=${SLURM_VERSION}"* ]]; then
            local base_pkg=$(echo "$pkg_name" | sed "s/=${SLURM_VERSION}.*//")
            if ! dpkg -l | grep "^[hi]i  ${base_pkg}" | grep -q "${SLURM_VERSION}"; then
                packages_to_install="$packages_to_install $pkg_name"
                packages_to_hold="$packages_to_hold $base_pkg"
            fi
        else
            # Regular package check
            if ! dpkg -l | grep -q "^[hi]i  ${pkg_name}"; then
                packages_to_install="$packages_to_install $pkg_name"
            fi
        fi
    done
    
    if [ -n "$packages_to_install" ]; then
        echo "The following packages need to be installed: $packages_to_install"
        apt update
        # Install all packages in one command
        apt install -y --allow-downgrades --allow-change-held-packages $packages_to_install
        # Hold SLURM packages to prevent automatic updates
        if [ -n "$packages_to_hold" ]; then
            apt-mark hold $packages_to_hold
        fi
        echo "Successfully installed all required packages"
    else
        echo "All required packages are already installed"
    fi
}

dependency_packages=""

# Handle python3-venv for Ubuntu > 19
if [[ $UBUNTU_VERSION > "19" ]]; then
    dependency_packages="$dependency_packages python3-venv"
fi

dependency_packages="$dependency_packages munge libmysqlclient-dev libssl-dev jq libjansson-dev libjwt-dev binutils"

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
all_slurm_packages="$slurm_packages"

if [ "${SLURM_ROLE}" == "scheduler" ]; then
    all_slurm_packages="$all_slurm_packages $sched_packages"
fi

if [ "${SLURM_ROLE}" == "execute" ]; then
    all_slurm_packages="$all_slurm_packages $execute_packages"
fi

# Combine dependency packages and versioned SLURM packages
all_packages="$dependency_packages"

# Add version suffix to all slurm packages
for pkg in $all_slurm_packages; do
    all_packages="$all_packages ${pkg}=${SLURM_VERSION}*"
done

# Install all packages using the unified function
dpkg_pkg_install "$all_packages"

# Install yq for slurm_exporter (will refactor this later)
if [ "${SLURM_ROLE}" == "scheduler" ]; then
    YQ_VERSION="v4.44.2"
    YQ_PACKAGE="yq_linux_${arch}"
    if ! command -v yq &> /dev/null; then
        wget -q "https://github.com/mikefarah/yq/releases/download/${YQ_VERSION}/${YQ_PACKAGE}" -O /usr/bin/yq
        chmod 0755 /usr/bin/yq
    fi
fi
touch $INSTALLED_FILE
exit
