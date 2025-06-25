#!/bin/bash

set -e
set -x

read_os()
{
    os_release=$(cat /etc/os-release | grep "^ID\=" | cut -d'=' -f 2 | xargs)
    os_version=$(cat /etc/os-release | grep "^VERSION_ID\=" | cut -d'=' -f 2 | xargs)
}
ENROOT_VERSION=3.5.0
PYXIS_DIR=/opt/pyxis
PYXIS_VERSION=0.20.0

function install_enroot() {
    # Install or update enroot if necessary
    if [ "$(enroot version)" != "$ENROOT_VERSION" ] ; then
        logger -s  Updating enroot to $ENROOT_VERSION
        read_os
        case $os_release in
            almalinux)
                yum remove -y enroot enroot+caps
                # Enroot requires user namespaces to be enabled
                echo "user.max_user_namespaces=32" > /etc/sysctl.d/userns.conf
                sysctl -p /etc/sysctl.d/userns.conf

                arch=$(uname -m)
                run_file=$(pwd)/enroot-check_${ENROOT_VERSION}_$(uname -m).run
                chmod 755 $run_file
                $run_file --verify

                yum install -y $(pwd)/enroot-${ENROOT_VERSION}-1.el8.${arch}.rpm
                yum install -y $(pwd)/enroot+caps-${ENROOT_VERSION}-1.el8.${arch}.rpm
                ;;
            ubuntu)
                arch=$(dpkg --print-architecture)
                run_file=$(pwd)/enroot-check_${ENROOT_VERSION}_$(uname -m).run
                chmod 755 $run_file
                $run_file --verify

                apt install -y $(pwd)/enroot_${ENROOT_VERSION}-1_${arch}.deb
                apt install -y $(pwd)/enroot+caps_${ENROOT_VERSION}-1_${arch}.deb
                ;;
            *)
                logger -s "OS $os_release not supported"
                exit 0
            ;;
        esac
    else
        logger -s  Enroot is already at version $ENROOT_VERSION
    fi
}

function install_pyxis() {

    if [[ ! -f $PYXIS_DIR/spank_pyxis.so ]]; then

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

        logger -s "Building Pyxis $PYXIS_VERSION"

        tar -xzf pyxis-$PYXIS_VERSION.tar.gz
        cd pyxis-$PYXIS_VERSION
        make

        # Copy pyxis library to /opt/pyxis
        logger -s "Copying Pyxis library to $PYXIS_DIR"
        mkdir -p $PYXIS_DIR
        cp -fv spank_pyxis.so $PYXIS_DIR
        chmod +x $PYXIS_DIR/spank_pyxis.so
    else
        echo "Pyxis already installed"
    fi
}

install_enroot
install_pyxis
