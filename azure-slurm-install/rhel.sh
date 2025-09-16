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

rpm_pkg_install() {
    local packages_to_install=""
    local pkg_names=$1
    for pkg_name in $pkg_names; do
        if ! rpm -qa | grep -q "^${pkg_name}-"; then
            packages_to_install="$packages_to_install $pkg_name"
        fi
    done
    if [ -n "$packages_to_install" ]; then
        echo "The following packages need to be installed: $packages_to_install"
        dependent_pkgs=""
        slurm_pkgs=""

        for pkg in $packages_to_install; do
            case "$pkg" in
                epel-release|perl-Switch|munge|jq)
                    dependent_pkgs="$dependent_pkgs $pkg"
                    ;;
                *)
                    slurm_pkgs="$slurm_pkgs $pkg"
                    ;;
            esac
        done

        # Install dependent packages individually
        for pkg in $dependent_pkgs; do
            if [[ "$pkg" == "epel-release" ]] &&  [ "${OS_ID,,}" == "rhel" ]; then
                dnf -y install https://dl.fedoraproject.org/pub/epel/epel-release-latest-8.noarch.rpm
            elif [[ "$pkg" == "perl-Switch" ]] && [ "${OS_ID,,}" != "rhel" ]; then
                dnf -y --enablerepo=powertools install perl-Switch
            else
                echo "Installing $pkg"
                yum install -y $pkg 
            fi  
        done

        # Install slurm packages in one yum command
        if [ -n "$slurm_pkgs" ]; then
            echo "Installing slurm packages: $slurm_pkgs"
            yum install -y $slurm_pkgs --disableexcludes slurm
        fi
        echo "Successfully installed all required packages"
    else
        echo "All required packages are already installed"
    fi
}

dependency_packages="epel-release perl-Switch munge jq"
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

all_packages="$dependency_packages"

#add version suffix to all slurm packages
for pkg in $all_slurm_packages; do
    all_packages="$all_packages ${pkg}-${SLURM_VERSION}*"
done

rpm_pkg_install "$all_packages"

touch $INSTALLED_FILE
exit