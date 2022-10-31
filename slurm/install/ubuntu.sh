#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
set -e
apt -y install munge
apt -y install blobs/*

# Need to manually create links for libraries the RPMs are linked to (we use alien to create the debs)
ln -s /lib/x86_64-linux-gnu/libreadline.so.7 /usr/lib/x86_64-linux-gnu/libreadline.so.6 
ln -s /lib/x86_64-linux-gnu/libhistory.so.7 /usr/lib/x86_64-linux-gnu/libhistory.so.6
ln -s /lib/x86_64-linux-gnu/libncurses.so.5 /usr/lib/x86_64-linux-gnu/libncurses.so.5
ln -s /lib/x86_64-linux-gnu/libtinfo.so.5 /usr/lib/x86_64-linux-gnu/libtinfo.so.5
