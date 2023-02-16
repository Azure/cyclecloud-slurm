#!/bin/bash

if [ "$1" == "" ]; then
  echo Usage: $0 path/to/scalelib-repo
  exit 1
fi

scalelib=$(realpath $1)
local_scalelib=/source/cyclecloud-scalelib
local_azslurm=/source/azure-slurm

if command -v docker; then
  docker run -v $(pwd):${local_azslurm} -v ${scalelib}:${local_scalelib} -ti almalinux:8.5 /bin/bash ${local_azslurm}/docker-package-internal.sh
else
  echo "`docker` binary not found. Install docker to build RPMs with this script"
fi
