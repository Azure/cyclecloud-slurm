#!/bin/bash

down_and_off=$(sinfo -O nodelist:500,statelong -h | grep down~ | cut -d" " -f1)
echo exited with $?
if [ $? != 0 ]; then
  echo $(date): Could not run sinfo. Command was 'sinfo -O nodelist:500,statelong -h | grep down~ | cut -d" " -f1'
  exit 1
fi

echo $(date) down and off is '"'$down_and_off'"'

if [ "$down_and_off" != "" ]; then
  echo $(date): Setting the following down~ nodes to idle~
  scontrol update nodename=$down_and_off state=idle
  if [ $? != 0 ]; then
    echo $(date): Updating nodes failed! Command was "scontrol update nodename=$down_and_off state=idle"
    exit 1
  fi
fi

drained_and_off=$(sinfo -O nodelist:500,statelong -h | grep drained~ | cut -d" " -f1)

if [ "$down_and_off" != "" ]; then
  echo $(date): Setting the following drained~ nodes to idle~
  scontrol update nodename=$drained_and_off state=idle
  if [ $? != 0 ]; then
    echo $(date): Updating nodes failed! Command was "scontrol update nodename=$drained_and_off state=idle"
    exit 1
  fi
fi