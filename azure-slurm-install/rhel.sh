#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
set -e
INSTALLED_FILE=/etc/azslurm-bins.installed
SLURM_ROLE=$1
SLURM_VERSION=$2
OS_VERSION=$(cat /etc/os-release  | grep VERSION_ID | cut -d= -f2 | cut -d\" -f2 | cut -d. -f1)
OS_ID=$(cat /etc/os-release  | grep ^ID= | cut -d= -f2 | cut -d\" -f2 | cut -d. -f1)

if [ "$OS_VERSION" -lt "8" ]; then
    echo "RHEL versions < 8 no longer supported"
    exit 1
fi

is_package_installed() {
    local pkg_name=$1
    rpm -qa | grep -q "^${pkg_name}-"
}

system_packages=""

# Handle EPEL and perl-Switch
if [ "${OS_ID,,}" == "rhel" ]; then
    if ! is_package_installed "epel-release"; then
        echo "Installing EPEL repository for RHEL"
        dnf -y install https://dl.fedoraproject.org/pub/epel/epel-release-latest-8.noarch.rpm
    else
        echo "EPEL repository is already installed"
    fi
    if ! is_package_installed "perl-Switch"; then
        echo "perl-Switch needs to be installed"
        dnf -y install perl-Switch
    else
        echo "perl-Switch is already installed"
    fi
else
    if ! is_package_installed "epel-release"; then
        echo "epel-release needs to be installed"
        yum install -y epel-release
    else
        echo "epel-release is already installed"
    fi
    if ! is_package_installed "perl-Switch"; then
        echo "perl-Switch needs to be installed"
        dnf -y --enablerepo=powertools install perl-Switch
    else
        echo "perl-Switch is already installed"
    fi
    
fi

# Handle munge and jq
for pkg in munge jq; do
    if ! is_package_installed "$pkg"; then
        echo "$pkg needs to be installed"
        system_packages="$system_packages $pkg"
    else
        echo "$pkg is already installed"
    fi
done

slurm_packages="slurm slurm-libpmi slurm-devel slurm-pam_slurm slurm-perlapi slurm-torque slurm-openlava slurm-example-configs slurm-contribs"
sched_packages="slurm-slurmctld slurm-slurmdbd slurm-slurmrestd"
execute_packages="slurm-slurmd"

INSIDERS=$(/opt/cycle/jetpack/bin/jetpack config slurm.insiders False)

if [[ "$OS_VERSION" == "9" ]]; then
    if [[ "$INSIDERS" == "True" ]]; then
        cp slurmel9insiders.repo /etc/yum.repos.d/slurm.repo
    else
        cp slurmel9.repo /etc/yum.repos.d/slurm.repo
    fi
elif [[ "$OS_VERSION" == "8" ]]; then
    if [[ "$INSIDERS" == "True" ]]; then
        cp slurmel8insiders.repo /etc/yum.repos.d/slurm.repo
    else
        cp slurmel8.repo /etc/yum.repos.d/slurm.repo
    fi
else
    echo "Unsupported OS version: $OS_VERSION"
    exit 1
fi

# Collect all SLURM packages based on role
all_packages="$slurm_packages"

if [ "${SLURM_ROLE}" == "scheduler" ]; then
    all_packages="$all_packages $sched_packages"
fi

if [ "${SLURM_ROLE}" == "execute" ]; then
    all_packages="$all_packages $execute_packages"
fi

## This package is pre-installed in all hpc images used by cyclecloud, but if customer wants to
## build an image from generic marketplace images then this package sets up the right gpg keys for PMC.
if [ ! -e /etc/yum.repos.d/microsoft-prod.repo ]; then
    curl -sSL -O https://packages.microsoft.com/config/rhel/$OS_VERSION/packages-microsoft-prod.rpm
    rpm -i packages-microsoft-prod.rpm
    rm packages-microsoft-prod.rpm
fi

packages_to_install="$system_packages"

# Add SLURM packages that aren't installed
for pkg in $all_packages; do
    if is_package_installed "${pkg}-${SLURM_VERSION}*"; then
        echo "Package $pkg with version ${SLURM_VERSION} is already installed"
    else
        echo "Package $pkg with version ${SLURM_VERSION}* needs to be installed"
        packages_to_install="$packages_to_install ${pkg}-${SLURM_VERSION}*"
    fi
done

# Install all packages in one command (system packages first, then SLURM packages)
if [ -n "$packages_to_install" ]; then
    echo "Installing all packages: $packages_to_install"
    yum -y install $packages_to_install --disableexcludes slurm
    echo "Successfully installed all required packages"
else
    echo "All required packages are already installed"
fi

touch $INSTALLED_FILE
exit