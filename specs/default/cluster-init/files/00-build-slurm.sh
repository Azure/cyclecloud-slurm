#!/bin/bash

SLURM_VERSION="17.11.12"
SLURM_PKG="slurm-${SLURM_VERSION}.tar.bz2"
DOWNLOAD_URL="https://download.schedmd.com/slurm"

# munge is in EPEL
yum -y install epel-release && yum -q makecache

# Install other build deps
yum install -y rpm-build munge-devel munge-libs readline-devel openssl openssl-devel pam-devel perl-ExtUtils-MakeMaker gcc mysql mysql-devel wget
wget "${DOWNLOAD_URL}/${SLURM_PKG}"

rpmbuild -ta ${SLURM_PKG}

