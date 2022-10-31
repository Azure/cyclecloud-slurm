#!/bin/bash

SLURM22="22.05.3"
SLURM20="20.11.9"

rm -rf blobs-build-tmp
mkdir blobs-build-tmp
if command -v docker; then

  docker run -v $(pwd)/specs/default/cluster-init/files:/source -v $(pwd)/blobs-debian-tmp:/root/rpmbuild/RPMS/x86_64 -ti almalinux:8.5 /bin/bash /source/00-build-slurm.sh centos $SLURM22
  docker run -v $(pwd)/specs/default/cluster-init/files:/source -v $(pwd)/blobs-debian-tmp:/root/rpmbuild/RPMS/x86_64 -ti centos:7 /bin/bash /source/00-build-slurm.sh centos $SLURM20
  docker run -v $(pwd)/specs/default/cluster-init/files:/source -v $(pwd)/blobs-debian-tmp:/root/rpmbuild/RPMS/x86_64 -ti ubuntu:18.04 /bin/bash /source/01-build-debs.sh
  # we only want the rpms for almalinux8 (i.e. slurm22) but we want all of the debs
  mv blobs-debian-tmp/*.deb blobs/
  mv blobs-debian-tmp/*$SLURM22*.rpm blobs/
  rm -rf blobs-debian-tmp
else
  echo "`docker` binary not found. Install docker to build RPMs with this script"
fi
