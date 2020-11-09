#!/bin/bash -e
cd ~/


function build_slurm() {
    SLURM_VERSION=$1
    SLURM_FOLDER="slurm-${SLURM_VERSION}"
    SLURM_PKG="slurm-${SLURM_VERSION}.tar.bz2"
    DOWNLOAD_URL="https://download.schedmd.com/slurm"

    # munge is in EPEL
    yum -y install epel-release && yum -q makecache

    # Install other build deps
    yum install -y rpm-build munge-devel munge-libs readline-devel openssl openssl-devel pam-devel perl-ExtUtils-MakeMaker gcc mysql mysql-devel wget gtk2-devel.x86_64 glib2-devel.x86_64 libtool-2.4.2 m4 automake rsync
    wget "${DOWNLOAD_URL}/${SLURM_PKG}"
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


    LD_LIBRARY_PATH=/root/job_submit/${SLURM_FOLDER}/src/api/.libs/ JOB_SUBMIT_CYCLECLOUD=1 python job_submit_cyclecloud_test.py
    rsync .libs/job_submit_cyclecloud.so  /root/rpmbuild/RPMS/x86_64/job_submit_cyclecloud_centos_${SLURM_VERSION}-1.so
    rsync .libs/job_submit_cyclecloud.so  /root/rpmbuild/RPMS/x86_64/job_submit_cyclecloud_ubuntu_${SLURM_VERSION}-1.so
}

build_slurm 19.05.5