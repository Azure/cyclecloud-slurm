#!/bin/bash
# Library of functions to be used across scripts
read_os()
{
    os_release=$(cat /etc/os-release | grep "^ID\=" | cut -d'=' -f 2 | xargs)
    os_version=$(cat /etc/os-release | grep "^VERSION_ID\=" | cut -d'=' -f 2 | xargs)
}

function is_scheduler() {
    jetpack config slurm.role | grep -q 'scheduler'
}

function is_login() {
    jetpack config slurm.role | grep -q 'login'
}

function is_compute() {
    jetpack config slurm.role | grep -q 'execute'
}

function is_arm64() {
   uname -m | grep -q 'aarch64\|arm64' 
}



function install_yq() {
    # Install yq
    YQ_VERSION="v4.44.2"
    YQ_PACKAGE="yq_linux_amd64"
    if is_arm64 ; then
        YQ_PACKAGE="yq_linux_arm64"
    fi
    
    if ! command -v yq &> /dev/null; then
        wget -q "https://github.com/mikefarah/yq/releases/download/${YQ_VERSION}/${YQ_PACKAGE}" -O /usr/bin/yq
        chmod 0755 /usr/bin/yq
    fi
}

function is_monitoring_enabled() {
    monitoring_enabled=$(jetpack config monitoring.enabled False)
    echo "$monitoring_enabled" | tr '[:upper:]' '[:lower:]' | grep -q 'true'
}