#!/usr/bin/env bash
set -e

find_python3() {
    export PATH=$(echo $PATH | sed -e 's/\/opt\/cycle\/jetpack\/system\/embedded\/bin://g' | sed -e 's/:\/opt\/cycle\/jetpack\/system\/embedded\/bin//g')
    if [ -n "$AZSLURM_PYTHON_PATH" ]; then
        echo $AZSLURM_PYTHON_PATH
        return 0
    fi
    for version in $( seq 11 20 ); do
        which python3.$version > /dev/null 2>/dev/null
        if [ $? == 0 ]; then
            python3.$version -c "import venv"
            if [ $? == 0 ]; then
                # write to stdout the validated path
                which python3.$version
                return 0
            else
                echo Warning: Found python3.$version but venv is not installed. 1>&2
            fi
        fi
    done
    # Quietly return nothing
    return 0
}

install_python3() {
    PYTHON_BIN=$(find_python3)
    if [ -n "$PYTHON_BIN" ]; then
        echo "Found Python at $PYTHON_BIN" >&2
        export PYTHON_BIN
        return 0
    fi
    echo "No suitable python3 installation found, beginning installation." >&2
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
        yum install -y python3.12
        PYTHON_BIN="/usr/bin/python3.12"

    elif [ "$OS" == "ubuntu" ] && [ "$VERSION_ID" == "22.04" ]; then
        echo "Detected Ubuntu 22.04. Installing Python 3.11..." >&2
        apt update
        # We need python dev headers and systemd dev headers for same reaosn mentioned above.
        apt install -y python3.11 python3.11-venv
        PYTHON_BIN="/usr/bin/python3.11"

    elif [ "$OS" == "ubuntu" ] && [[ $VERSION =~ ^24\.* ]]; then
        echo "Detected Ubuntu 24. Installing Python 3.12..." >&2
        apt update
        apt install -y python3.12 python3.12-venv
        PYTHON_BIN="/usr/bin/python3.12"

    elif [ "$OS" == "rhel" ]; then
        echo "Detected RHEL, using system python3..." >&2
        PYTHON_BIN="/usr/bin/python3"

    elif [ "$OS" == "azurelinux" ]; then
        echo "Detected AzureLinux. Installing Python 3.12..." >&2
        tdnf install -y python3
        PYTHON_BIN="/usr/bin/python3"

    elif [ "$OS" == "sle_hpc" ]; then
        echo "Detected SUSE, installing Python 3.11..." >&2
        zypper install -y python311 python311-virtualenv
        PYTHON_BIN="/usr/bin/python3.11"

    elif [ "$OS" == "rocky" ]; then
        echo "Detected RockyLinux, Installing Python 3.12..." >&2
        yum install -y python3.12
        PYTHON_BIN="/usr/bin/python3.12"
    else
        echo "Unsupported operating system: $OS $VERSION_ID" >&2
        exit 1
    fi
    export PYTHON_BIN
}

verify_python3_version() {
    python_bin=$1
    actual_version=$($python_bin --version | awk '{print $2}')
    minor_version=$(echo "$actual_version" | cut -d. -f2)
    if [ -z "$minor_version" ] || [ "$minor_version" -lt 11 ]; then
        echo "ERROR: Python >= 3.11 is required, but $python_bin is version $actual_version" >&2
        exit 1
    fi
    echo "Verified $python_bin is >= 3.11 (found $actual_version)" >&2
}