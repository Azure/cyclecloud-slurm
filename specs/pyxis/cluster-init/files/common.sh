#!/bin/bash
# Library of functions to be used across scripts
JETPACK=/opt/cycle/jetpack/bin/jetpack

read_os()
{
    os_release=$(cat /etc/os-release | grep "^ID\=" | cut -d'=' -f 2 | xargs)
    os_version=$(cat /etc/os-release | grep "^VERSION_ID\=" | cut -d'=' -f 2 | xargs)
}

function is_scheduler() {
    $JETPACK config slurm.role | grep -q 'scheduler'
}

function is_login() {
    $JETPACK config slurm.role | grep -q 'login'
}

function is_compute() {
    $JETPACK config slurm.role | grep -q 'execute'
}

