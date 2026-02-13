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
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARTIFACTS_DIR="$SCRIPT_DIR/artifacts"

rpm_check_pkg() {
    local packages_to_install=""
    local pkg_names=$1
    for pkg_name in $pkg_names; do
        base_pkg=$pkg_name
        if [[ "$pkg_name" == *.rpm ]]; then
            # Extract package name from .rpm filename
            base_pkg=$(basename "$pkg_name" | sed 's/-[0-9]*\.el.*$//')
        fi
        if ! rpm -qa | grep -q "^${base_pkg}-"; then
            packages_to_install="$packages_to_install $pkg_name"
        fi
    done
    if [ -n "$packages_to_install" ]; then
        echo "The following packages need to be installed: $packages_to_install"
        exit 1
    else
        echo "All required packages are already installed"
    fi
}

dependency_packages="perl-Switch munge jq jansson-devel libjwt-devel binutils make wget gcc"
slurm_packages="slurm slurm-libpmi slurm-devel slurm-pam_slurm slurm-perlapi slurm-torque slurm-openlava slurm-example-configs slurm-contribs"
sched_packages="slurm-slurmctld slurm-slurmdbd slurm-slurmrestd"
execute_packages="slurm-slurmd"


# Collect all SLURM packages based on role
all_slurm_packages="$slurm_packages"

if [ "${SLURM_ROLE}" == "scheduler" ]; then
    all_slurm_packages="$all_slurm_packages $sched_packages"
fi

if [ "${SLURM_ROLE}" == "execute" ]; then
    all_slurm_packages="$all_slurm_packages $execute_packages"
fi
versioned_slurm_packages=""
#add version suffix to all slurm packages
for pkg in $all_slurm_packages; do
    versioned_slurm_packages="$versioned_slurm_packages ${pkg}-${SLURM_VERSION}*"
done
all_packages="$dependency_packages $versioned_slurm_packages"
rpm_check_pkg "$all_packages"

# Install slurm_exporter container (will refactor this later)
monitoring_enabled=$(/opt/cycle/jetpack/bin/jetpack config cyclecloud.monitoring.enabled False)
if [ "${SLURM_ROLE}" == "scheduler" ] && [ "$monitoring_enabled" == "True" ]; then
    SLURM_EXPORTER_IMAGE_NAME="ghcr.io/slinkyproject/slurm-exporter:0.3.0"
    docker pull $SLURM_EXPORTER_IMAGE_NAME
fi


touch $INSTALLED_FILE
exit