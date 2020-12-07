#!/bin/bash

if command -v docker; then
  docker run -v $(pwd)/specs/default/cluster-init/files:/source -v $(pwd)/blobs:/root/rpmbuild/RPMS/x86_64 -ti centos:7 /bin/bash /source/00-build-slurm.sh
  docker run -v $(pwd)/specs/default/cluster-init/files:/source -v $(pwd)/blobs:/root/rpmbuild/RPMS/x86_64 -ti centos:8 /bin/bash /source/00-build-slurm.sh
  docker run -v $(pwd)/specs/default/cluster-init/files:/source -v $(pwd)/blobs:/root/rpmbuild/RPMS/x86_64 -ti ubuntu:18.04 /bin/bash /source/01-build-debs.sh
  cat > /tmp/check_mising_files.py <<EOF
from configparser import ConfigParser
import os
parser = ConfigParser()
parser.read("project.ini")
expected_files = set([x.strip() for x in parser.get("blobs", "Files").split(",")])
actual = set(os.listdir("blobs"))
missing = expected_files - actual
assert not missing, "Missing the following blobs: %s" % ",".join(missing)
EOF
  python3 /tmp/check_mising_files.py
else
  echo "`docker` binary not found. Install docker to build RPMs with this script"
fi
