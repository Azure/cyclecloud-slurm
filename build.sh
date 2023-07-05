#!/usr/bin/env bash
set -e

if [ "$1" == "-h" ] || [ "$1" == "--help" ] || [ "$1" == "-help" ]; then
    echo "Usage: $0 [path/to/scalelib repo]"
    echo "If no path to scalelib is passed in, one will be downloaded from GitHub based on"
    echo "the version specified in package.py:SCALELIB_VERSION"
    exit 1
fi

LOCAL_SCALELIB=$1

if [ "$LOCAL_SCALELIB" != "" ]; then
    LOCAL_SCALELIB=$(realpath $LOCAL_SCALELIB)
fi

cd $(dirname $0)
if [ ! -e blobs ]; then
    mkdir blobs
fi

wget -k -O slurm/install/AzureCA.pem  https://github.com/Azure/cyclecloud-slurm/releases/download/2.7.3/AzureCA.pem
# ls slurm/install/slurm-pkgs/*.rpm > /dev/null || (echo you need to run docker-rpmbuild.sh first; exit 1)
# ls slurm/install/slurm-pkgs/*.deb > /dev/null || (echo you need to run docker-rpmbuild.sh first; exit 1)


cd slurm/install
rm -f dist/*
./package.sh
mv dist/* ../../blobs/

cd ../../
rm -f dist/*
./package.sh $LOCAL_SCALELIB
mv dist/* blobs/
