#!/bin/bash
set -e

TMP_BLOBS=blobs-tmp
rm -rf $TMP_BLOBS
mkdir $TMP_BLOBS

if command -v docker; then
  extra_args=
  if command -v podman; then
    extra_args="--privileged"
  fi

  docker run -v $(pwd)/specs/default/cluster-init/files:/source -v $(pwd)/$TMP_BLOBS:/root/rpmbuild/RPMS/x86_64 $extra_args -ti almalinux:8.5 /bin/bash /source/00-build-slurm.sh centos
  docker run -v $(pwd)/specs/default/cluster-init/files:/source -v $(pwd)/$TMP_BLOBS:/root/rpmbuild/RPMS/x86_64 -ti centos:7 /bin/bash /source/00-build-slurm.sh centos
  docker run -v $(pwd)/specs/default/cluster-init/files:/source -v $(pwd)/$TMP_BLOBS:/root/rpmbuild/RPMS/x86_64 $extra_args -ti ubuntu:18.04 /bin/bash /source/01-build-debs.sh
  
  mv $TMP_BLOBS/* blobs/
  rm -rf $TMP_BLOBS
else
  echo "`docker` binary not found. Install docker to build RPMs with this script"
fi


