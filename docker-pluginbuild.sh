#!/bin/bash

if command -v docker; then
  docker run -v $(pwd)/specs/default/cluster-init/files:/source -v $(pwd)/blobs:/root/rpmbuild/RPMS/x86_64 -ti centos:7 /bin/bash /source/02-develop-submit-plugin.sh
else
  echo "`docker` binary not found. Install docker to build plugin with this script"
fi
