#!/bin/bash -e
set -e
apt-get update
apt install -y alien liblua5.1 liblua5.1-dev

for rpm in $(ls ~/rpmbuild/RPMS/x86_64/*.rpm ); do
    alien --bump 0 --scripts $rpm
done
mv *.deb ~/rpmbuild/RPMS/x86_64/
