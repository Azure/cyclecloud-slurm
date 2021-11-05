#!/bin/bash

down_and_off=$(sinfo -O nodelist:500,statelong -h | grep down~ | cut -d" " -f1)

if [ "$down_and_off" != "" ]; then
  echo $(date): Setting the following down~ nodes to idle~: $down_and_off
  scontrol update nodename=$down_and_off state=idle
  if [ $? != 0 ]; then
    echo $(date): Updating nodes failed! Command was "scontrol update nodename=$down_and_off state=idle"
    exit 1
  fi
fi

drained_and_off=$(sinfo -O nodelist:500,statelong -h | grep drained~ | cut -d" " -f1)

if [ "$drained_and_off" != "" ]; then
  echo $(date): Setting the following drained~ nodes to idle~: $drained_and_off
  scontrol update nodename=$drained_and_off state=idle
  if [ $? != 0 ]; then
    echo $(date): Updating nodes failed! Command was "scontrol update nodename=$drained_and_off state=idle"
    exit 1
  fi
fi
