#!/usr/bin/env bash
set -e
# 1) run ./docker-rpmbuild.sh so that you have all necessary RPMs / debs
# 2) if you are developing a local version of cyclecloud-scalelib, invoke this script like 
#    ./build.sh PATH/TO/SCALELIB

LOCAL_SCALELIB=$1

cd slurm/install
rm -f dist/*
python3 package.py
mv dist/* ../../blobs/

cd ../../
rm -f dist/*

if [ "$LOCAL_SCALELIB" == "" ]; then
    # we are using released versions of scalelib
    python3 package.py
else
    pushd $LOCAL_SCALELIB
    rm -f dist/*.gz
    python3 setup.py swagger
    python3 setup.py sdist
    popd
    swagger=`ls $LOCAL_SCALELIB/dist/swagger*.gz`
    scalelib=`ls $LOCAL_SCALELIB/dist/cyclecloud-scalelib*.gz`
    python3 package.py --scalelib $scalelib --swagger $swagger
fi
mv dist/* blobs/
