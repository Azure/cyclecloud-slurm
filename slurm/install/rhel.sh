#!/bin/bash
yum -y install epel-release
yum -y install munge
dnf -y --enablerepo=powertools install -y perl-Switch
if [ $1 == "scheduler" ]; then
    yum -y install blobs/*
else
    yum  -y install $(ls blobs/* | grep -v slurmdbd)
fi