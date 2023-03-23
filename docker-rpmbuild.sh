#!/bin/bash
set -e
SOURCE_ROOT=$( realpath $(dirname $0) )
cd $(dirname $0)/slurm/install

if [ ! -e slurm-pkgs ]; then 
  mkdir slurm-pkgs
fi

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

$runtime run -v $SOURCE_ROOT/specs/default/cluster-init/files:/source -v $SOURCE_ROOT/$TMP_BINS:/root/rpmbuild/RPMS/x86_64 $extra_args -ti almalinux:8.5 /bin/bash /source/00-build-slurm.sh centos
$runtime run -v $SOURCE_ROOT/specs/default/cluster-init/files:/source -v $SOURCE_ROOT/$TMP_BINS:/root/rpmbuild/RPMS/x86_64 -ti centos:7 /bin/bash /source/00-build-slurm.sh centos
$runtime run -v $SOURCE_ROOT/specs/default/cluster-init/files:/source -v $SOURCE_ROOT/$TMP_BINS:/root/rpmbuild/RPMS/x86_64 $extra_args -ti ubuntu:18.04 /bin/bash /source/01-build-debs.sh

mv $TMP_BINS/* slurm-pkgs/
rm -rf $TMP_BINS

