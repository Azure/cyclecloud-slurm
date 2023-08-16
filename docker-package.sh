#!/bin/bash

local_azslurm=/source/azure-slurm
if [ "$1" != "" ]; then
  scalelib=$(realpath $1)
  local_scalelib=/source/cyclecloud-scalelib
  extra_args="-v ${scalelib}:${local_scalelib}"
fi

if command -v docker; then
  runtime=docker
  runtime_args=
elif command -v podman; then
  runtime=podman
  runtime_args="--privileged"
else
  echo "`docker` or `podman` binary not found. Install docker or podman to build RPMs with this script"
  exit 1
fi

# allows caching
$runtime build -t azslurm_build:latest -f util/Dockerfile .
$runtime run -v $(pwd):${local_azslurm} $runtime_args $extra_args -ti azslurm_build:latest /bin/bash ${local_azslurm}/util/build.sh $local_scalelib
