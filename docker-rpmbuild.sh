#!/bin/bash

if command -v docker; then
  docker run -v $(pwd)/specs/default/cluster-init/files:/source -v $(pwd)/blobs:/root/rpmbuild/RPMS/x86_64 -ti centos:7 /bin/bash /source/00-build-slurm.sh
  docker run -v $(pwd)/specs/default/cluster-init/files:/source -v $(pwd)/blobs:/root/rpmbuild/RPMS/x86_64 -ti ubuntu:18.04 /bin/bash /source/01-build-debs.sh
else
  echo "`docker` binary not found. Install docker to build RPMs with this script"
fi
