#!/bin/bash
set -e
set -x

function install_plugstack() {

   echo 'required /opt/pyxis/spank_pyxis.so runtime_path=/mnt/enroot/enroot-runtime' > /etc/slurm/plugstack.conf.d/pyxis.conf
   chown slurm:slurm /etc/slurm/plugstack.conf.d/pyxis.conf
}

function install_pyxis_library() {
   build_pyxis
   install_plugstack
}

function build_pyxis() {

    BLOB_FILE=pyxis-artifacts.tar.gz

    if [[ -d /tmp/pyxis-artifacts ]]; then
        cd /tmp/pyxis-artifacts && ./install.sh
    else
        cd /tmp
        project_name=$(jetpack config slurm.project_name slurm)
        jetpack download --project $project_name $BLOB_FILE
        tar -xvf $BLOB_FILE
        cd /tmp/pyxis-artifacts && ./install.sh
    fi

}

logger -s "Install Pyxis library"
install_pyxis_library

logger -s "Pyxis installation complete"

