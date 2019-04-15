#!/bin/bash -e

SLURM_VERSION="17.11.12"
SLURM_FOLDER="slurm-${SLURM_VERSION}"
SLURM_PKG="slurm-${SLURM_VERSION}.tar.bz2"
DOWNLOAD_URL="https://download.schedmd.com/slurm"

# munge is in EPEL
yum -y install epel-release && yum -q makecache

# Install other build deps
yum install -y rpm-build munge-devel munge-libs readline-devel openssl openssl-devel pam-devel perl-ExtUtils-MakeMaker gcc mysql mysql-devel wget gtk2-devel.x86_64 glib2-devel.x86_64 libtool-2.4.2 m4 automake
wget "${DOWNLOAD_URL}/${SLURM_PKG}"
tar xjf ${SLURM_PKG}
mkdir -p ${SLURM_FOLDER}/src/plugins/topology/cyclecloud/
cp /source/TopologyPlugin/topology_cyclecloud.c ${SLURM_FOLDER}/src/plugins/topology/cyclecloud/
cp /source/TopologyPlugin/Makefile.am ${SLURM_FOLDER}/src/plugins/topology/cyclecloud/
sed -i 's/src\/plugins\/topology\/Makefile/src\/plugins\/topology\/Makefile\n                 src\/plugins\/topology\/cyclecloud\/Makefile/g'  ${SLURM_FOLDER}/configure.ac
cd ${SLURM_FOLDER}
./autogen.sh
./configure
make
cd ..
rm -f ${SLURM_PKG}
tar cjf ${SLURM_PKG} ${SLURM_FOLDER}
rpmbuild -ta ${SLURM_PKG}

