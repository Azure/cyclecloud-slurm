#!/bin/bash -e

DEBIAN_FRONTEND="noninteractive" TZ="Etc/UTC" apt-get update
DEBIAN_FRONTEND="noninteractive" TZ="Etc/UTC" apt-get install -y alien
# perform these separately to avoid conflicting UUID issue.

for r in $( ls ~/rpmbuild/RPMS/x86_64/*.rpm ); do
    alien --bump 0 --scripts $r
done
mv *.deb ~/rpmbuild/RPMS/x86_64/
