#!/bin/bash
set -e
script_dir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$script_dir/../files/common.sh" 
read_os

ENROOT_VERSION=3.5.0

function install_enroot() {
    # Install or update enroot if necessary
    if [ "$(enroot version)" != "$ENROOT_VERSION" ] ; then
        logger -s  Updating enroot to $ENROOT_VERSION
        # RDH otherwise we are writing to cluster-init dir, which causes strange behaviour on retries
	pushd /tmp
	case $os_release in
            almalinux)
                yum remove -y enroot enroot+caps
                # Enroot requires user namespaces to be enabled
                echo "user.max_user_namespaces=32" > /etc/sysctl.d/userns.conf
                sysctl -p /etc/sysctl.d/userns.conf

                arch=$(uname -m)
                curl -fSsL -O https://github.com/NVIDIA/enroot/releases/download/v${ENROOT_VERSION}/enroot-check_${ENROOT_VERSION}_$(uname -m).run
                chmod 755 enroot-check_*.run
                ./enroot-check_*.run --verify

                yum install -y https://github.com/NVIDIA/enroot/releases/download/v${ENROOT_VERSION}/enroot-${ENROOT_VERSION}-1.el8.${arch}.rpm
                yum install -y https://github.com/NVIDIA/enroot/releases/download/v${ENROOT_VERSION}/enroot+caps-${ENROOT_VERSION}-1.el8.${arch}.rpm
                ;;
            ubuntu)
                arch=$(dpkg --print-architecture)
                curl -fSsL -O https://github.com/NVIDIA/enroot/releases/download/v${ENROOT_VERSION}/enroot-check_${ENROOT_VERSION}_$(uname -m).run
                chmod 755 enroot-check_*.run
                ./enroot-check_*.run --verify

                curl -fSsL -O https://github.com/NVIDIA/enroot/releases/download/v${ENROOT_VERSION}/enroot_${ENROOT_VERSION}-1_${arch}.deb
                curl -fSsL -O https://github.com/NVIDIA/enroot/releases/download/v${ENROOT_VERSION}/enroot+caps_${ENROOT_VERSION}-1_${arch}.deb
                apt install -y ./*.deb
                ;;
            *)
                logger -s "OS $os_release not tested"
                exit 0
            ;;
        esac
	popd
    else
        logger -s  Enroot is already at version $ENROOT_VERSION
    fi
}

function configure_enroot() 
{
    # enroot default scratch dir to /mnt/enroot
    # If NVMe disks exists link /mnt/enroot to /mnt/nvme/enroot
    ENROOT_SCRATCH_DIR=/mnt/enroot
    if [ -d /mnt/nvme ]; then
        # If /mnt/nvme exists, use it as the default scratch dir
        mkdir -pv /mnt/nvme/enroot
        ln -s /mnt/nvme/enroot $ENROOT_SCRATCH_DIR
   else
        mkdir -pv /mnt/scratch/enroot
        ln -s /mnt/scratch/enroot $ENROOT_SCRATCH_DIR
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

