#!/bin/bash
set -e
cd $(dirname $0)/install
if [ -e pkg ]; then 
  mkdir pkg
fi

TMP_BINS=slurm-pkgs-tmp
rm -rf $TMP_BINS
mkdir $TMP_BINS

if command -v docker; then
  extra_args=
  if command -v podman; then
    extra_args="--privileged"
  fi

  docker run -v $(pwd)/specs/default/cluster-init/files:/source -v $(pwd)/$TMP_BINS:/root/rpmbuild/RPMS/x86_64 $extra_args -ti almalinux:8.5 /bin/bash /source/00-build-slurm.sh centos
  docker run -v $(pwd)/specs/default/cluster-init/files:/source -v $(pwd)/$TMP_BINS:/root/rpmbuild/RPMS/x86_64 -ti centos:7 /bin/bash /source/00-build-slurm.sh centos
  docker run -v $(pwd)/specs/default/cluster-init/files:/source -v $(pwd)/$TMP_BINS:/root/rpmbuild/RPMS/x86_64 $extra_args -ti ubuntu:18.04 /bin/bash /source/01-build-debs.sh
  
  mv $TMP_BINS/* slurm-pkgs/
  rm -rf $TMP_BINS
else
  echo "`docker` binary not found. Install docker to build RPMs with this script"
fi


