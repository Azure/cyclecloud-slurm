#!/bin/bash
set -e
cd "$(dirname "$0")"

VERSION=8.9.0-3579
# Identify cyclecloud8 build version
INITIAL_CC_BUILD_VERSION=$(cat /opt/cycle_server/system/version)

# Update cyclecloud yum repo to insiders-fast 
sed -i 's|^\(baseurl=.*\)/cyclecloud$|\1/cyclecloud-insiders-fast|' /etc/yum.repos.d/cyclecloud.repo

# Clean and rebuild yum cache
yum clean all
yum makecache

# Update cyclecloud8 to latest version
yum -y install cyclecloud8-$VERSION

# Check if the update was successful
UPDATED_CC_BUILD_VERSION=$(cat /opt/cycle_server/system/version)
if [ "$UPDATED_CC_BUILD_VERSION" != "$INITIAL_CC_BUILD_VERSION" ]; then
    echo "CycleCloud updated successfully from version $INITIAL_CC_BUILD_VERSION to $UPDATED_CC_BUILD_VERSION."
else
    echo "CycleCloud update failed or no new version available."
    exit 1
fi

# # Update cyclecloud-monitoring project to latest release 
# /usr/local/bin/cyclecloud project fetch https://github.com/Azure/cyclecloud-monitoring/releases/1.0.2 /tmp/cyclecloud-monitoring
# pushd /tmp/cyclecloud-monitoring
# /usr/local/bin/cyclecloud project upload azure-storage
# popd
# rm -rf /tmp/cyclecloud-monitoring