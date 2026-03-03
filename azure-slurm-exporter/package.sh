#!/usr/bin/env bash
set -e

if [ ! -e libs ]; then
    mkdir libs
fi

rm -f dist/*

python3.11 package.py
