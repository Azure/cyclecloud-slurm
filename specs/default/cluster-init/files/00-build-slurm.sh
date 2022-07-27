#!/bin/bash -e
set +x

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

cd ~/

function build_slurm() {
    set -e

    DISTRO_FAMILY=${1}
    SLURM_VERSION=${2}

    SLURM_FOLDER="slurm-${SLURM_VERSION}"
    SLURM_PKG="slurm-${SLURM_VERSION}.tar.bz2"
    DOWNLOAD_URL="https://download.schedmd.com/slurm"

    if [ "$SLURM_VERSION" \> "20" ]; then
        PYTHON=python3
    else
        PYTHON=python2
    fi

    case ${DISTRO_FAMILY} in
        suse)
            zypper install --no-confirm bzip2 rpmbuild munge-devel pam-devel mysql-devel autoconf
            ;;
        centos)
            CENTOS_VERSION=8.5
            CENTOS_MAJOR=8

            if [ $CENTOS_VERSION \< "8." ]; then
                LIBTOOL=libtool-2.4.2
            else
                LIBTOOL=libtool
                yum install -y dnf-plugins-core
                dnf config-manager --set-enabled powertools
                yum install -y make
            fi

             # munge is in EPEL
            yum -y install epel-release && yum -q makecache
            yum install -y make $PYTHON which rpm-build munge-devel munge-libs readline-devel openssl openssl-devel pam-devel perl-ExtUtils-MakeMaker gcc mysql mysql-devel wget gtk2-devel.x86_64 glib2-devel.x86_64 $LIBTOOL m4 automake rsync
            ;;
    esac

    if [ ! -e ~/bin ]; then
        mkdir -p ~/bin
    fi
    
    # install_pmix ${DISTRO_FAMILY}
    
    WHICH_PYTHON=$(which ${PYTHON})
    if ! [[ ${WHICH_PYTHON} ]]; then
        ln -s ${WHICH_PYTHON} ~/bin/python
        export PATH=$PATH:~/bin
    fi

    if [[ ! -f ${SLURM_PKG} ]]; then
        wget "${DOWNLOAD_URL}/${SLURM_PKG}"
    fi

    rpmbuild --with mysql -ta ${SLURM_PKG}

    # make the plugin
    rm -rf ~/job_submit
    mkdir -p ~/job_submit
    cd ~/
    cd ~/job_submit
    tar xjf ~/${SLURM_PKG}
    mkdir -p ${SLURM_FOLDER}/src/plugins/job_submit/cyclecloud/
    cd ${SLURM_FOLDER}/src/plugins/job_submit/cyclecloud/
    rsync -a ${SCRIPT_DIR}/JobSubmitPlugin/ .

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
    cp .libs/job_submit_cyclecloud.so job_submit_cyclecloud_${DISTRO_FAMILY}${CENTOS_MAJOR}_${SLURM_VERSION}-1.so
}

function install_pmix() {
    case ${1} in
        suse)
            zypper install --no-confirm libtool git autoconf flex
            ;;
        centos)
            yum -y install autoconf flex libevent-devel git
    esac
   
    cd ~/
    mkdir -p /opt/pmix/v3
    mkdir -p pmix/build/v3 pmix/install/v3
    cd pmix

    if ! [[ -d source ]]; then
        git clone https://github.com/openpmix/openpmix.git source
    fi

    cd source/
    # git branch -a
    git checkout v3.1
    git pull
    ./autogen.sh
    cd ../build/v3/
    ../../source/configure --prefix=/opt/pmix/v3
    make -j install >/dev/null
    cd ../../install/v3/
}

build_slurm ${1} 20.11.9