#!/bin/bash
set -e
script_dir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$script_dir/../files/common.sh" 

PYXIS_VERSION=0.20.0
PYXIS_DIR=/opt/pyxis



function install_plugstack() {

   echo 'required /opt/pyxis/spank_pyxis.so runtime_path=/mnt/enroot/enroot-runtime' > /etc/slurm/plugstack.conf.d/pyxis.conf
   chown slurm:slurm /etc/slurm/plugstack.conf.d/pyxis.conf
}

function install_pyxis_library() {
   build_pyxis
   install_plugstack
}

function build_pyxis() {

   # Check and install 'make' based on the OS
   if [[ -f /etc/os-release ]]; then
       . /etc/os-release
       if [[ "$ID" == "ubuntu" ]]; then
           logger -s "Installing 'make' on Ubuntu"
           apt update && apt install -y make gcc wget
       else
           logger -s "Installing 'make' on non-Ubuntu system (assuming RHEL/CentOS)"
           yum install -y make gcc wget
       fi
   else
       logger -s "Unable to detect OS. Please ensure 'make' is installed."
       exit 1
   fi

   logger -s "Downloading Pyxis source code $PYXIS_VERSION"

   cd /tmp
   wget -q https://github.com/NVIDIA/pyxis/archive/refs/tags/v$PYXIS_VERSION.tar.gz
   tar -xzf v$PYXIS_VERSION.tar.gz
   cd pyxis-$PYXIS_VERSION
   logger -s "Building Pyxis"
   make

   # Copy pyxis library to /opt/pyxis
   logger -s "Copying Pyxis library to $PYXIS_DIR"
   mkdir -p $PYXIS_DIR
   cp -fv spank_pyxis.so $PYXIS_DIR
   chmod +x $PYXIS_DIR/spank_pyxis.so
}

logger -s "Install Pyxis library"
install_pyxis_library

logger -s "Pyxis installation complete"

