#!/bin/bash
local_azslurm=/source/azure-slurm
if [ "$1" != "" ]; then
  scalelib=$(realpath $1)
  local_scalelib=/source/cyclecloud-scalelib
  extra_args="-v ${scalelib}:${local_scalelib}"
fi

if command -v docker; then
  docker run -v $(pwd):${local_azslurm} $extra_args -ti almalinux:8.5 /bin/bash ${local_azslurm}/docker-package-internal.sh
else
  echo "`docker` binary not found. Install docker to build RPMs with this script"
fi
