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
            zypper install --no-confirm bzip2 rpmbuild munge-devel pam-devel mysql-devel autoconf readline-devel
            ;;
        centos)
            CENTOS_VERSION=$(cat /etc/centos-release | sed 's/ /\n/g' | grep -E '[0-9.]+')
            CENTOS_MAJOR=$(echo $CENTOS_VERSION | cut -d. -f1)

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
            yum install -y make $PYTHON which rpm-build munge-devel munge-libs readline-devel openssl openssl-devel pam-devel perl-ExtUtils-MakeMaker gcc mysql mysql-devel wget gtk2-devel.x86_64 glib2-devel.x86_64 $LIBTOOL m4 automake rsync lua-devel
            yum install -y http-parser-devel json-c-devel
            ;;
            
    esac

    if [ ! -e ~/bin ]; then
        mkdir -p ~/bin
    fi
    
    install_pmix ${DISTRO_FAMILY}

    cd ~/
    
    WHICH_PYTHON=$(which ${PYTHON})
    if ! [[ ${WHICH_PYTHON} ]]; then
        ln -s ${WHICH_PYTHON} ~/bin/python
        export PATH=$PATH:~/bin
    fi

    if [[ ! -f ${SLURM_PKG} ]]; then
        wget "${DOWNLOAD_URL}/${SLURM_PKG}"
    fi

    rpmbuild --with mysql --define '_with_pmix --with-pmix=/opt/pmix/v3' --with=hwlocs --with=lua -ta ${SLURM_PKG}
}

function install_pmix() {
    case ${1} in
        suse)
            zypper install --no-confirm libtool git autoconf flex libevent-devel
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

for version in $(echo $2); do 
    build_slurm ${1} $version
done
