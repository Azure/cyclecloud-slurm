#!/bin/bash

down_and_off=$(sinfo -O nodelist:500,statelong -h | grep down~ | cut -d" " -f1)

if [ "$down_and_off" != "" ]; then
  echo $(date): found nodes in 'down~' state, returning to 'idle~' - $down_and_off
  scontrol update nodename=$down_and_off state=idle
fi