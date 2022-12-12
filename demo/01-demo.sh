#!/usr/bin/env bash
set -e

LOG=/tmp/01-demo.log
. ~/./demo_vars.sh

echo Running 01-demo.sh at $date > $LOG

echo see $LOG for more detail

##############################################
## Install dotnet
echo Downloading dotnet-sdk 6.0.402 and installing to $HOME/dotnet
wget https://download.visualstudio.microsoft.com/download/pr/d3e46476-4494-41b7-a628-c517794c5a6a/6066215f6c0a18b070e8e6e8b715de0b/dotnet-sdk-6.0.402-linux-x64.tar.gz 2>> $LOG
mkdir -p $HOME/dotnet
tar zxf dotnet-sdk-6.0.402-linux-x64.tar.gz -C $HOME/dotnet 2>> $LOG

echo Installing cred provider from Microsoft helpers.
# install cred provider
wget -O - https://raw.githubusercontent.com/microsoft/artifacts-credprovider/master/helpers/installcredprovider.sh | bash - 2>> $LOG


echo Creating ~/ClusterService/src/clusters/roles/StandaloneHost/appsettings.local.json with MasterAppClient credentials.
##############################################
## setup ClusterService
. ~/./demo_vars.sh

cat >~/ClusterService/src/clusters/roles/StandaloneHost/appsettings.local.json <<EOF
{
  "Azure": {
    "CoreCredentials": {
      "MasterAppClient": {
        "TenantId": "$DEMO_TENANT_ID",
        "ClientId": "$DEMO_CLIENT_ID",
        "ClientSecret": "$DEMO_CLIENT_SECRET"
      }
    }
  }
}
EOF

echo complete! >> $LOG
echo complete!