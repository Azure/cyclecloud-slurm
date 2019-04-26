#!/bin/bash -e

SLURM_VERSION="18.08.7"
SLURM_FOLDER="slurm-${SLURM_VERSION}"
SLURM_PKG="slurm-${SLURM_VERSION}.tar.bz2"
DOWNLOAD_URL="https://download.schedmd.com/slurm"

# munge is in EPEL
yum -y install epel-release && yum -q makecache

# Install other build deps
yum install -y rpm-build munge-devel munge-libs readline-devel openssl openssl-devel pam-devel perl-ExtUtils-MakeMaker gcc mysql mysql-devel wget gtk2-devel.x86_64 glib2-devel.x86_64 libtool-2.4.2 m4 automake
wget "${DOWNLOAD_URL}/${SLURM_PKG}"
rpmbuild -ta ${SLURM_PKG}

