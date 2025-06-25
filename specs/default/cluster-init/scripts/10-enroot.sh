#!/bin/bash
set -e
set -x
script_dir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BLOB_FILE=pyxis-artifacts.tar.gz
slurm_project_name=$(jetpack config slurm.project_name slurm)

function install_enroot() {
	cd /tmp

    jetpack download --project $slurm_project_name $BLOB_FILE
    tar -xvf $BLOB_FILE
    cd pyxis-artifacts
	./install.sh
}

function configure_enroot() 
{
    # enroot default scratch dir to /mnt/enroot
    # If NVMe disks exists link /mnt/enroot to /mnt/nvme/enroot
    ENROOT_SCRATCH_DIR=/mnt/enroot
    if [ -d /mnt/nvme ]; then
        # If /mnt/nvme exists, use it as the default scratch dir
        mkdir -pv /mnt/nvme/enroot
        ln -sfn /mnt/nvme/enroot $ENROOT_SCRATCH_DIR
   else
        mkdir -pv /mnt/scratch/enroot
        ln -sfn /mnt/scratch/enroot $ENROOT_SCRATCH_DIR
    fi

    logger -s "Creating enroot scratch directories in $ENROOT_SCRATCH_DIR"
    mkdir -pv $ENROOT_SCRATCH_DIR/{enroot-cache,enroot-data,enroot-temp,enroot-runtime,enroot-run}
    chmod -v 777 $ENROOT_SCRATCH_DIR/{enroot-cache,enroot-data,enroot-temp,enroot-runtime,enroot-run}

    # Configure enroot
    # https://github.com/NVIDIA/pyxis/wiki/Setup
    logger -s "Configure /etc/enroot/enroot.conf"
    cat <<EOF > /etc/enroot/enroot.conf
ENROOT_RUNTIME_PATH $ENROOT_SCRATCH_DIR/enroot-run/user-\$(id -u)
ENROOT_CACHE_PATH $ENROOT_SCRATCH_DIR/enroot-cache/group-\$(id -g)
ENROOT_DATA_PATH $ENROOT_SCRATCH_DIR/enroot-data/user-\$(id -u)
ENROOT_TEMP_PATH $ENROOT_SCRATCH_DIR/enroot-temp
ENROOT_SQUASH_OPTIONS -noI -noD -noF -noX -no-duplicates
ENROOT_MOUNT_HOME y
ENROOT_RESTRICT_DEV y
ENROOT_ROOTFS_WRITABLE y
MELLANOX_VISIBLE_DEVICES all
EOF

    logger -s "Install extra hooks for PMIx on compute nodes"
    cp -fv /usr/share/enroot/hooks.d/50-slurm-pmi.sh /usr/share/enroot/hooks.d/50-slurm-pytorch.sh /etc/enroot/hooks.d
}


install_enroot
configure_enroot

