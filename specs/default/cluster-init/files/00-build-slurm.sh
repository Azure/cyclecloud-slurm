#!/bin/bash -e
cd ~/
set -e
set -x

CENTOS_VERSION=$( cat /etc/centos-release | cut -d" " -f4 )

function build_slurm() {
    SLURM_VERSION=$1
    SLURM_FOLDER="slurm-${SLURM_VERSION}"
    SLURM_PKG="slurm-${SLURM_VERSION}.tar.bz2"
    DOWNLOAD_URL="https://download.schedmd.com/slurm"
    yum install -y wget which
    wget "${DOWNLOAD_URL}/${SLURM_PKG}"
    # munge is in EPEL7 or PowerTools in epel8
    yum -y install epel-release && yum -q makecache

    # Install other build deps
    # centos8 defaults
    YUM_REPO_ARGS=--enablerepo=PowerTools
    LIBTOOL_VERSION=2.4.6

    # tweaks for centos7
    if [ $CENTOS_VERSION \< "8." ]; then
        YUM_REPO_ARGS=
        LIBTOOL_VERSION=2.4.2
    fi
    yum $YUM_REPO_ARGS install -y python3 libtool-$LIBTOOL_VERSION make rsync rpm-build munge-devel munge-libs readline-devel openssl openssl-devel pam-devel perl-ExtUtils-MakeMaker gcc mysql mysql-devel wget gtk2-devel.x86_64 glib2-devel.x86_64 m4 automake rsync
    
    rpmbuild -ta ${SLURM_PKG} 

    # make the plugin
    rm -rf ~/job_submit
    mkdir -p ~/job_submit
    cd ~/job_submit
    tar xjf ~/${SLURM_PKG}
    mkdir -p ${SLURM_FOLDER}/src/plugins/job_submit/cyclecloud/
    cd ${SLURM_FOLDER}/src/plugins/job_submit/cyclecloud/
    rsync -a /source/JobSubmitPlugin/ .
    if [ "$SLURM_VERSION" \> "19" ]; then
        mv Makefile.in.v19 Makefile.in
    fi
    cd ~/job_submit
    sed -i 's/src\/plugins\/job_submit\/Makefile/src\/plugins\/job_submit\/Makefile\n                 src\/plugins\/job_submit\/cyclecloud\/Makefile/g'  ${SLURM_FOLDER}/configure.ac
    cd ~/job_submit/${SLURM_FOLDER}

    if [ "$SLURM_VERSION" \> "19" ]; then
        autoconf
    else
        ./autogen.sh
    fi
    ./configure
    make
    cd ~/job_submit/${SLURM_FOLDER}/src/plugins/job_submit/cyclecloud/
    make


    # LD_LIBRARY_PATH=/root/job_submit/${SLURM_FOLDER}/src/api/.libs/ JOB_SUBMIT_CYCLECLOUD=1 python job_submit_cyclecloud_test.py
    rsync .libs/job_submit_cyclecloud.so  /root/rpmbuild/RPMS/x86_64/job_submit_cyclecloud_centos8_${SLURM_VERSION}-1.so
    rsync .libs/job_submit_cyclecloud.so  /root/rpmbuild/RPMS/x86_64/job_submit_cyclecloud_ubuntu8_${SLURM_VERSION}-1.so
}

if [ $CENTOS_VERSION \< "8." ]; then
    build_slurm 19.05.8
fi
build_slurm 20.11.0
