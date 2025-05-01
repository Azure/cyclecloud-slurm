#!/bin/bash
set -ex
if ! systemctl list-units --full --all | grep -Fq "nvidia-imex.service"; then 
  exit 0 
fi
# Clean the config file in case the service gets started by accident
# clean up connection
> /etc/nvidia-imex/nodes_config.cfg
NVIDIA_IMEX_STOP_TIMEOUT=15
set +e
sudo timeout $NVIDIA_IMEX_STOP_TIMEOUT systemctl stop nvidia-imex
pkill -9 nvidia-imex
set -e