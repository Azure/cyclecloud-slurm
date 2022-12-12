cat >~/demo_vars.sh<<EOF

## Enter your creds
export DEMO_SUBSCRIPTION_ID=""
export DEMO_TENANT_ID=""
export DEMO_CLIENT_ID=""
export DEMO_CLIENT_SECRET=""

## preferably use your ms username. 
export DEMO_USER=changeme
export DEMO_USER_SSH_PUB_KEY=""

## this will be created in 00-demo.sh
export DEMO_RESOURCE_GROUP=${DEMO_USER}-cs-demo-live

## pick your region and subnet id
export DEMO_REGION=southcentralus
export DEMO_SUBNET_ID="/subscriptions/$DEMO_SUBSCRIPTION_ID/resourceGroups/{}/providers/Microsoft.Network/virtualNetworks/{}/subnets/default"


## Note - this should be unique per region, if you are starting more than one.
export DEMO_SERVER_VM_NAME=cs-slurm-demo

#############################################
## The defaults for the below are likely fine
export DEMO_CLUSTER_NAME=csdemo
export DEMO_VM_SIZE=Standard_F2
export DEMO_SERVER_VM_SIZE=Standard_D4_v2

# Leave as default unless you have a reason to try a different branch.
export DEMO_ROOT=~/csdemo
export DEMO_BRANCH=feature/csdemo

EOF

chmod +x ~/demo_vars.sh

. ~/./demo_vars.sh