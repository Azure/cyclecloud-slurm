#!/bin/bash
yum -y install epel-release
yum -y install munge
dnf -y --enablerepo=powertools install -y perl-Switch
yum -y install blobs/*
