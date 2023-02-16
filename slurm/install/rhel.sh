#!/bin/bash
SLURM_ROLE=$1
SLURM_VERSION=$2

yum -y install epel-release
yum -y install munge
dnf -y --enablerepo=powertools install -y perl-Switch

if [ ${SLURM_ROLE} == "scheduler" ]; then
    yum  -y install $(ls slurm-pkgs/*${SLURM_VERSION}*.rpm)
else
    yum  -y install $(ls slurm-pkgs/*${SLURM_VERSION}*.rpm | grep -v slurmdbd)
fi