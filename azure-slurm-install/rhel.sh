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

#Almalinux 8/9 and RockyLinux 8/9 both need epel-release to install libjwt for slurm packages 
enable_epel() {
    if ! rpm -qa | grep -q "^epel-release-"; then
        if [ "${OS_ID,,}" == "rhel" ]; then
            yum -y install artifacts/epel-release-latest-${OS_VERSION}.noarch.rpm
        else
            yum -y install epel-release
        fi
    fi
    if [ "${OS_ID}" == "almalinux" ]; then
        if [ "$OS_VERSION" == "8" ]; then
            # Enable powertools repo for AlmaLinux 8 (needed for perl-Switch package)
                yum config-manager --set-enabled powertools
        else
            # Enable crb repo for AlmaLinux 9 (needed for perl-Switch package)
                yum config-manager --set-enabled crb
        fi
    fi

}

rpm_pkg_install() {
    local packages_to_install=""
    local pkg_names=$1
    local extra_flags=$2
    for pkg_name in $pkg_names; do
        if ! rpm -qa | grep -q "^${pkg_name}-"; then
            packages_to_install="$packages_to_install $pkg_name"
        fi
    done
    if [ -n "$packages_to_install" ]; then
        echo "The following packages need to be installed: $packages_to_install"
        # Install all packages in one yum command
        yum install -y $packages_to_install $extra_flags
        echo "Successfully installed all required packages"
    else
        echo "All required packages are already installed"
    fi
}

dependency_packages="perl-Switch munge jq jansson-devel libjwt-devel binutils"
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
all_slurm_packages="$slurm_packages"

if [ "${SLURM_ROLE}" == "scheduler" ]; then
    all_slurm_packages="$all_slurm_packages $sched_packages"
fi

if [ "${SLURM_ROLE}" == "execute" ]; then
    all_slurm_packages="$all_slurm_packages $execute_packages"
fi

## This package is pre-installed in all hpc images used by cyclecloud, but if customer wants to
## build an image from generic marketplace images then this package sets up the right gpg keys for PMC.
if [ ! -e /etc/yum.repos.d/microsoft-prod.repo ]; then
    curl -sSL -O https://packages.microsoft.com/config/rhel/$OS_VERSION/packages-microsoft-prod.rpm
    rpm -i packages-microsoft-prod.rpm
    rm packages-microsoft-prod.rpm
fi

versioned_slurm_packages=""
#add version suffix to all slurm packages
for pkg in $all_slurm_packages; do
    versioned_slurm_packages="$versioned_slurm_packages ${pkg}-${SLURM_VERSION}*"
done

enable_epel
rpm_pkg_install "$dependency_packages"
rpm_pkg_install "$versioned_slurm_packages" "--disableexcludes slurm"

# Install slurm_exporter container (will refactor this later)
monitoring_enabled=$(/opt/cycle/jetpack/bin/jetpack config monitoring.enabled False)
if [ "${SLURM_ROLE}" == "scheduler" ] && [ "$monitoring_enabled" == "True" ]; then
    SLURM_EXPORTER_IMAGE_NAME="ghcr.io/slinkyproject/slurm-exporter:0.3.0"
    docker pull $SLURM_EXPORTER_IMAGE_NAME
fi

touch $INSTALLED_FILE
exit