#!/bin/bash

# yes, nodehost is the ip address and nodeaddr is the hostname. 
/bin/sinfo -N -O nodehost,nodelist --noheader > /sched/nodeaddrs