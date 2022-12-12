#!/usr/bin/env bash
set -e
. ~/./demo_vars.sh
LOG=/tmp/00-demo.log
echo Begin 00-demo.sh 2>$LOG

# create the RG
echo Creating resource group $DEMO_REGION $DEMO_RESOURCE_GROUP...
az group create --location $DEMO_REGION --resource-group $DEMO_RESOURCE_GROUP 2>>$LOG
echo Done!

# download the template and parameters
echo Downloading server-arm.json, used to create the all purpose demo VM 
wget https://raw.githubusercontent.com/Azure/cyclecloud-slurm/feature/csdemo/demo/server-arm.json >>$LOG 2>&1 

echo Deploying server VM...
az deployment group create --resource-group $DEMO_RESOURCE_GROUP --template-file server-arm.json \
    --parameters "adminPublicKey=$DEMO_USER_SSH_PUB_KEY" \
    --parameters "adminUsername=$DEMO_USER" \
    --parameters "virtualNetworkId=$(echo $DEMO_SUBNET_ID | rev | cut -d/ -f3- | rev)" \
    --parameters "subnetName=$(echo $DEMO_SUBNET_ID | rev | cut -d/ -f-1 | rev)" \
    --parameters "location=$DEMO_REGION" \
    --parameters "virtualMachineName=$DEMO_SERVER_VM_NAME" \
    --parameters "virtualMachineComputerName1=$DEMO_SERVER_VM_NAME" \
    --parameters "virtualMachineRG=$DEMO_RESOURCE_GROUP" \
    --parameters "osDiskType=Premium_LRS" \
    --parameters "osDiskDeleteOption=DELETE" \
    --parameters "virtualMachineSize=Standard_D4s_v3" \
    --parameters "enableAcceleratedNetworking=true" \
    --parameters "nicDeleteOption=Detach" \
    --parameters "zone=1" \
    --parameters "networkInterfaceName1=$DEMO_SERVER_VM_NAME-299z1" 1>&2 2>>$LOG
echo done!