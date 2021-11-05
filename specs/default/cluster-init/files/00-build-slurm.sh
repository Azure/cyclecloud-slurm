#!/bin/bash -e
cd ~/

CENTOS_VERSION=$(cat /etc/centos-release | cut -d" " -f4)
CENTOS_MAJOR=$(echo $CENTOS_VERSION | cut -d. -f1)

function build_slurm() {
    set -e
    
    install_pmix

    SLURM_VERSION=$1
    SLURM_FOLDER="slurm-${SLURM_VERSION}"
    SLURM_PKG="slurm-${SLURM_VERSION}.tar.bz2"
    DOWNLOAD_URL="https://download.schedmd.com/slurm"

    # munge is in EPEL
    yum -y install epel-release && yum -q makecache

    if [ "$SLURM_VERSION" \> "20" ]; then
        PYTHON=python3
    else
        PYTHON=python2
    fi

    if [ $CENTOS_VERSION \< "8." ]; then
        LIBTOOL=libtool-2.4.2
    else
        LIBTOOL=libtool
        yum install -y dnf-plugins-core
        yum config-manager --set-enabled PowerTools
        yum install -y make
    fi

    yum install -y make $PYTHON which rpm-build munge-devel munge-libs readline-devel openssl openssl-devel pam-devel perl-ExtUtils-MakeMaker gcc mysql mysql-devel wget gtk2-devel.x86_64 glib2-devel.x86_64 $LIBTOOL m4 automake rsync
    if [ ! -e ~/bin ]; then
        mkdir -p ~/bin
    fi
    
    ln -s `which $PYTHON` ~/bin/python
    export PATH=$PATH:~/bin
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


    LD_LIBRARY_PATH=/root/job_submit/${SLURM_FOLDER}/src/api/.libs/ JOB_SUBMIT_CYCLECLOUD=1 python3 job_submit_cyclecloud_test.py
    rsync .libs/job_submit_cyclecloud.so  /root/rpmbuild/RPMS/x86_64/job_submit_cyclecloud_centos${CENTOS_MAJOR}_${SLURM_VERSION}-1.so
    rsync .libs/job_submit_cyclecloud.so  /root/rpmbuild/RPMS/x86_64/job_submit_cyclecloud_ubuntu_${SLURM_VERSION}-1.so
}

function install_pmix() {
    cd ~/
    mkdir -p /opt/pmix/v3
    yum install -y libevent-devel git
    mkdir -p pmix/build/v3 pmix/install/v3
    cd pmix
    git clone https://github.com/openpmix/openpmix.git source
    cd source/
    git branch -a
    git checkout v3.1
    git pull
    ./autogen.sh
    cd ../build/v3/
    ../../source/configure --prefix=/opt/pmix/v3
    make -j install >/dev/null
    cd ../../install/v3/
}

build_slurm 20.11.7