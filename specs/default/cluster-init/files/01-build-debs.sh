#!/bin/bash -e
apt-get update
apt-get install -y alien

alien --bump 0 --scripts ~/rpmbuild/RPMS/x86_64/*.rpm 
mv *.deb ~/rpmbuild/RPMS/x86_64/
