#!/bin/bash -e
apt-get update
apt-get install -y alien
cd ~/rpmbuild/RPMS/x86_64/
alien *.rpm --bump 0