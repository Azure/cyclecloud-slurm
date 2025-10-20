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
ENROOT_VERSION="4.0.1"
PYXIS_VERSION="0.21.0"
PYXIS_DIR="/opt/pyxis"
if [ "$OS_VERSION" -lt "8" ]; then
    echo "RHEL versions < 8 no longer supported"
    exit 1
fi

#Almalinux 8/9 and RHEL 8/9 both need epel-release to install libjwt for slurm packages 
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
        # Install all packages in one yum command
        yum install -y $packages_to_install $extra_flags
        echo "Successfully installed all required packages"
    else
        echo "All required packages are already installed"
    fi
}

dependency_packages="perl-Switch munge jq jansson-devel libjwt-devel binutils make wget gcc"
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
monitoring_enabled=$(/opt/cycle/jetpack/bin/jetpack config cyclecloud.monitoring.enabled False)
if [ "${SLURM_ROLE}" == "scheduler" ] && [ "$monitoring_enabled" == "True" ]; then
    SLURM_EXPORTER_IMAGE_NAME="ghcr.io/slinkyproject/slurm-exporter:0.3.0"
    docker pull $SLURM_EXPORTER_IMAGE_NAME
fi

# Install enroot package
if [[ "$OS_VERSION" == "8" ]]; then
    yum remove -y enroot enroot+caps
    # Enroot requires user namespaces to be enabled
    echo "user.max_user_namespaces=32" > /etc/sysctl.d/userns.conf
    sysctl -p /etc/sysctl.d/userns.conf

    arch=$(uname -m)
    run_file=artifacts/enroot-check_${ENROOT_VERSION}_$(uname -m).run
    chmod 755 $run_file
    $run_file --verify
    rpm_pkg_install "artifacts/enroot-${ENROOT_VERSION}-1.el8.${arch}.rpm artifacts/enroot+caps-${ENROOT_VERSION}-1.el8.${arch}.rpm"
fi

# Install pyxis
if [[ ! -f $PYXIS_DIR/spank_pyxis.so ]]; then
    tar -xzf artifacts/pyxis-${PYXIS_VERSION}.tar.gz
    cd pyxis-${PYXIS_VERSION}
    make
    mkdir -p $PYXIS_DIR
    cp -fv spank_pyxis.so $PYXIS_DIR
    chmod +x $PYXIS_DIR/spank_pyxis.so
fi

touch $INSTALLED_FILE
exit