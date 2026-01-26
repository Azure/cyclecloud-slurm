#!/usr/bin/env bash
set -e

do_install=$(jetpack config slurm.do_install True)
install_pkg=$(jetpack config slurm.install_pkg azure-slurm-install-pkg-4.0.5.tar.gz)
autoscale_pkg=$(jetpack config slurm.autoscale_pkg azure-slurm-pkg-4.0.5.tar.gz)
slurm_project_name=$(jetpack config slurm.project_name slurm)

find_python3() {
    export PATH=$(echo $PATH | sed -e 's/\/opt\/cycle\/jetpack\/system\/embedded\/bin://g' | sed -e 's/:\/opt\/cycle\/jetpack\/system\/embedded\/bin//g')
    if [ -n "$AZSLURM_PYTHON_PATH" ]; then
        echo $AZSLURM_PYTHON_PATH
        return 0
    fi
    for version in $( seq 11 20 ); do
        which python3.$version
        if [ $? == 0 ]; then
            return 0
        fi
    done
    echo Could not find python3 version 3.11 >&2
    return 1
}

install_python3() {
    PYTHON_BIN=$(find_python3)
    if [ -n "$PYTHON_BIN" ]; then
        echo "Found Python at $PYTHON_BIN" >&2
        export PYTHON_BIN
        return 0
    fi
    # NOTE: based off of healthagent 00-install.sh, but we have different needs - we don't need the devel/systemd paths.
    # most likely if healthagent is already installed, this won't be an issue.
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$ID
        VERSION_ID=$VERSION_ID
    else
        echo "Cannot detect the operating system."
        exit 1
    fi

    if [ "$OS" == "almalinux" ]; then
        echo "Detected AlmaLinux. Installing Python 3.12..." >&2
        yum install -y python3.12 python3.12-pyyaml
        PYTHON_BIN="/usr/bin/python3.12"
        
    elif [ "$OS" == "ubuntu" ] && [ "$VERSION_ID" == "22.04" ]; then
        echo "Detected Ubuntu 22.04. Installing Python 3.11..." >&2
        apt update
        # We need python dev headers and systemd dev headers for same reaosn mentioned above.
        apt install -y python3.11 python3.11-venv python3-yaml
        PYTHON_BIN="/usr/bin/python3.11"
        
    elif [ "$OS" == "ubuntu" ] && [[ $VERSION =~ ^24\.* ]]; then
        echo "Detected Ubuntu 24. Installing Python 3.12..." >&2
        apt update
        apt install -y python3.12 python3.12-venv python3-yaml
        PYTHON_BIN="/usr/bin/python3.12"
    
    elif [ "$OS" == "rhel" ]; then
        echo "Detected RHEL, using system python3..." >&2
        PYTHON_BIN="/usr/bin/python3"
    
    elif [ "$OS" == "sle_hpc" ]; then
        echo "Detected SUSE, installing Python 3.11..." >&2
        zypper install -y python311 python311-virtualenv python311-PyYAML
        PYTHON_BIN="/usr/bin/python3.11"
    
    else
        echo "Unsupported operating system: $OS $VERSION_ID" >&2
        exit 1
    fi
    export PYTHON_BIN
}

cd $CYCLECLOUD_HOME/system/bootstrap

install_python3

if [ $do_install == "True" ]; then
    rm -rf azure-slurm-install
    jetpack download --project $slurm_project_name $install_pkg
    tar xzf $install_pkg
    cd azure-slurm-install
    $PYTHON_BIN install.py --mode scheduler --bootstrap-config $CYCLECLOUD_HOME/config/node.json
    cd ..
fi

rm -rf azure-slurm
jetpack download --project $slurm_project_name $autoscale_pkg
tar xzf $autoscale_pkg
cd azure-slurm
AZSLURM_PYTHON_PATH=$PYTHON_BIN ./install.sh

echo "installation complete. Run start-services scheduler|execute|login to start the slurm services."
