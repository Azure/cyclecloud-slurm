#!/bin/bash

run_epilog(){
  if ! systemctl list-units --full --all | grep -Fq "nvidia-imex.service"; then 
    exit 0 
  fi
  # Clean the config file in case the service gets started by accident
  # clean up connection
  > /etc/nvidia-imex/nodes_config.cfg
  NVIDIA_IMEX_STOP_TIMEOUT=15
  set +e
  timeout $NVIDIA_IMEX_STOP_TIMEOUT systemctl stop nvidia-imex
  pkill -9 nvidia-imex
  set -e
}
# Get VM size from Jetpack
mkdir -p /var/log/slurm
{
  set -x
  set +e
  VM_SIZE=$(/opt/cycle/jetpack/bin/jetpack config azure.metadata.compute.vmSize)
  IMEX_ENABLED=$(/opt/cycle/jetpack/bin/jetpack config slurm.imex.enabled null)

  # Main logic
  set -e
  if [[ "$VM_SIZE" == *"GB200"* || "$VM_SIZE" == *"GB300"* ]]; then
      if [[ "$IMEX_ENABLED" == "False" ]]; then
          exit 0  # No-op
      else
          run_epilog  # Run epilog for GB200/GB300 by default
      fi
  elif [[ "$IMEX_ENABLED" == "True" ]]; then
      run_epilog  # Run epilog for non-GB200/GB300 VM if explicitly enabled
  else
      exit 0  # No-op
  fi
} > "/var/log/slurm/imex_epilog_$SLURM_JOB_ID.log" 2>&1