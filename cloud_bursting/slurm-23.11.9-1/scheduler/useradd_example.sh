#!/bin/bash
# -----------------------------------------------------------------------------
# Script: Create Shared Home Directory for a Test User in Slurm Scheduler
#
# This script creates a new user in a Slurm scheduler environment, setting up a 
# shared home directory. The user is configured with a specific username, GID, 
# and UID. It is primarily designed for environments like CycleCloud where 
# consistent user IDs are important (starting with 20001 for the first user).
#
# CycleCloud Convention:
# - For the first user, the UID and GID default to 20001 in CycleCloud. Modify 
#   these values as needed for additional users.
#
# Prerequisites:
# - Script must be run with root privileges.
# - The desired UID, GID, and username should be set before execution.
# -----------------------------------------------------------------------------

set -e
if [ $(whoami) != root ]; then
  echo "Please run as root"
  exit 1
fi

# test user details
username="user1"
gid=20001
uid=20001

mkdir -p /shared/home/$username
chmod 755 /shared/home/

# Create group if not exists
if ! getent group $gid >/dev/null; then
    groupadd -g $gid $username
fi

# Create user with specified uid, gid, home directory, and shell
useradd -g $gid -u $uid -d /shared/home/$username -s /bin/bash $username
chown -R $username:$username /shared/home/$username
# Switch to user to perform directory and file operations
su - $username -c "mkdir -p /shared/home/$username/.ssh"
su - $username -c "ssh-keygen -t rsa -N '' -f /shared/home/$username/.ssh/id_rsa"
su - $username -c "cat /shared/home/$username/.ssh/id_rsa.pub >> /shared/home/$username/.ssh/authorized_keys"
su - $username -c "chmod 600 /shared/home/$username/.ssh/authorized_keys"
su - $username -c "chmod 700 /shared/home/$username/.ssh"