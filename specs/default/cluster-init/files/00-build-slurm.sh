#!/bin/bash -e
set +x
cd ~/

CENTOS_VERSION=8.5
CENTOS_MAJOR=8

function build_slurm() {
    set -e
    cd ~/
    SLURM_VERSION=$1
    SLURM_FOLDER="slurm-${SLURM_VERSION}"
    SLURM_PKG="slurm-${SLURM_VERSION}.tar.bz2"
    DOWNLOAD_URL="https://download.schedmd.com/slurm"
    
    # munge is in EPEL
    yum -y install epel-release && yum -q makecache
    rpm -ivh http://repo.okay.com.mx/centos/8/x86_64/release/okay-release-1-5.el8.noarch.rpm
    yum -y install http-parser-devel json-c-devel wget

    wget "${DOWNLOAD_URL}/${SLURM_PKG}"
    ls ${SLURM_PKG}
    

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
        dnf config-manager --set-enabled powertools
        yum install -y make
    fi

    yum install -y make $PYTHON which rpm-build munge-devel munge-libs readline-devel openssl openssl-devel pam-devel perl-ExtUtils-MakeMaker gcc mysql mysql-devel wget gtk2-devel.x86_64 glib2-devel.x86_64 $LIBTOOL m4 automake rsync lua-devel.x86_64
    if [ ! -e ~/bin ]; then
        mkdir -p ~/bin
    fi
    
    install_pmix

    
    ln -s `which $PYTHON` ~/bin/python
    export PATH=$PATH:~/bin
    cd ~/
    rpmbuild --define '_with_pmix --with-pmix=/opt/pmix/v3' --with=hwlocs --with=lua -ta ${SLURM_PKG}

    # make the plugin
    rm -rf ~/job_submit
    mkdir -p ~/job_submit
    cd ~/
    
}

function install_pmix() {
    yum -y install autoconf flex
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

build_slurm 22.05.3