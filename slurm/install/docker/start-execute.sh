#!/bin/bash
docker run -v $(pwd)/../..:/source -v $(pwd)/../../../blobs:/blobs  -ti almalinux:8.5 /bin/bash /source/install/docker/setup-execute.sh