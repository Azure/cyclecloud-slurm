#!/bin/bash
set -e
SOURCE_ROOT=$( realpath $(dirname $0) )
cd $(dirname $0)/slurm/install

if [ ! -e slurm-pkgs ]; then 
  mkdir slurm-pkgs
fi

SLURM_VERSIONS=$(python3 slurm_supported_version.py | cut -d- -f1)

TMP_BINS=slurm-pkgs-tmp
rm -rf $TMP_BINS
mkdir $TMP_BINS

if command -v docker; then
  runtime=docker
  extra_args=
elif command -v podman; then
  runtime=podman
  extra_args="--privileged"
else
  echo "docker binary not found. Install docker to build RPMs with this script"
  exit 1
fi

$runtime run -v $SOURCE_ROOT/specs/default/cluster-init/files:/source -v $SOURCE_ROOT/$TMP_BINS:/root/rpmbuild/RPMS/x86_64 $extra_args -ti almalinux:8.5 /bin/bash /source/00-build-slurm.sh centos "$SLURM_VERSIONS"
$runtime run -v $SOURCE_ROOT/specs/default/cluster-init/files:/source -v $SOURCE_ROOT/$TMP_BINS:/root/rpmbuild/RPMS/x86_64 -ti centos:7 /bin/bash /source/00-build-slurm.sh centos "$SLURM_VERSIONS"
$runtime run -v $SOURCE_ROOT/specs/default/cluster-init/files:/source -v $SOURCE_ROOT/$TMP_BINS:/root/rpmbuild/RPMS/x86_64 $extra_args -ti ubuntu:20.04 /bin/bash /source/01-build-debs.sh "$SLURM_VERSIONS"

mv $TMP_BINS/* $SOURCE_ROOT/slurm/install/slurm-pkgs/
rm -rf $TMP_BINS

S