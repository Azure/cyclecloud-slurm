#!/bin/bash
set -e
CWD=$( realpath $(dirname $0) )
SOURCE_ROOT=$(dirname $CWD)
WORKDIR=$SOURCE_ROOT/slurm/install
cd $WORKDIR

if [ ! -e slurm-pkgs ]; then
  mkdir slurm-pkgs
fi

SLURM_VERSIONS=$(python3 slurm_supported_version.py)

TMP_BINS=slurm-pkgs-tmp
if [ -e $TMP_BINS ]; then
	rm -rf $TMP_BINS
fi
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

$runtime run -v $SOURCE_ROOT:/source -v $WORKDIR/$TMP_BINS:/root/rpmbuild/RPMS/x86_64 $extra_args -ti almalinux:8.5 /bin/bash /source/util/build-slurm.sh centos "$SLURM_VERSIONS"
$runtime run -v $SOURCE_ROOT:/source -v $WORKDIR/$TMP_BINS:/root/rpmbuild/RPMS/x86_64 $extra_args -ti centos:7 /bin/bash /source/util/build-slurm.sh centos "$SLURM_VERSIONS"
$runtime run -v $SOURCE_ROOT:/source -v $WORKDIR/$TMP_BINS:/root/rpmbuild/RPMS/x86_64 $extra_args -ti ubuntu:20.04 /bin/bash /source/util/build-debs.sh "$SLURM_VERSIONS"

mv $TMP_BINS/* slurm-pkgs/
rm -rf $TMP_BINS

