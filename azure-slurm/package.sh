#!/bin/bash
set -e
cd $(dirname $0)/


if [ ! -e libs ]; then
    mkdir libs
fi

LOCAL_SCALELIB=$1

rm -f dist/*

if [ "$LOCAL_SCALELIB" == "" ]; then
    # we are using released versions of scalelib
    python3.11 package.py
else
    pushd $LOCAL_SCALELIB
    rm -f dist/*.gz
    # python3 setup.py swagger
    python3.11 setup.py sdist
    popd
    # swagger=`ls $LOCAL_SCALELIB/dist/swagger*.gz`
    scalelib=`ls $LOCAL_SCALELIB/dist/cyclecloud-scalelib*.gz`
    # python3 package.py --scalelib $scalelib --swagger $swagger
    python3.11 package.py --scalelib $scalelib
fi
