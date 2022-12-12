# Batch Clusters And Slurm - A Demo

We are going to create a basic VM via the Portal and setup Batch Clusters on it.

## Create variables needed for this demo
Download [demo_vars.sh](https://raw.githubusercontent.com/Azure/cyclecloud-slurm/feature/csdemo/demo/demo_vars.sh) onto your computer and edit the relevant DEMO_* variables to be used to both start the server VM and to start new VMs via Batch Clusters.

__Note:__ _You need to use these variables in two places - both the Azure Portal and on the actual server created in the following step._
```bash
# Linux/Unix etc
wget https://raw.githubusercontent.com/Azure/cyclecloud-slurm/feature/csdemo/demo/demo_vars.sh
```

<details>
<summary><b>Or expand to see <code>demo_vars.sh</code></b></summary>

```bash
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
```

</details>


## Start the Server VM
We need to allocate a VM that will be our NFS server, our Batch Clusters/StandaloneHost and our Slurm head node.

Go to the Azure Portal and open an Azure Shell. Please switch the shell type to bash.

```bash
# paste in demo_vars.sh from first step. 
```

```bash
wget -O - https://raw.githubusercontent.com/Azure/cyclecloud-slurm/feature/csdemo/demo/00-demo.sh | bash -
```

<details>
<summary> <b>Expand to see <code>00-demo.sh</code></b> </summary>

```bash
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
```

</details>

It will take a few minutes for the VM to start. You can get the IP address using this command.
```bash
. ~/demo_vars.sh && az vm list-ip-addresses --resource-group $DEMO_RESOURCE_GROUP --name $DEMO_SERVER_VM_NAME | jq -r '.[0].virtualMachine.network.privateIpAddresses[]'
```


## Setup dotnet and Git Clone Batch Clusters
Ssh into the VM created in the previous step. __Paste in the demo_vars.sh from the first step__.

```bash
# paste in demo_vars.sh from first step. 
```

Clone Batch Clusters to `~/code/ClusterService` and setup the proper dotnet and cred provider.

__Note__ _You will be prompted for your PAT._
```bash
sudo yum -y install git
git clone https://msazure@dev.azure.com/msazure/AzureBatch/_git/ClusterService ~/ClusterService -b integration/slurm
```

Install dotnet and the Cred Provider helper.
```bash
wget -O - https://raw.githubusercontent.com/Azure/cyclecloud-slurm/feature/csdemo/demo/01-demo.sh | bash -
```

<details>
<summary><b>Expand to see <code>01-demo.sh</code></b></summary>

```bash
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
```

</details>

## Build and Run Batch Clusters
We are already on the appropriate branch, and have created master credentials for Batch Clusters via _appsettings.local.json_ in the previous step.

Finally, we can build and run ClusterService
```bash
cd ~/ClusterService/src/clusters/roles/StandaloneHost/
~/dotnet/dotnet run --environment Development --os linux --interactive
```

__Note__ You will have to open browser to [devicelogin](https://microsoft.com/devicelogin) and enter the code like below
```bash
# 
#
#      **********************************************************************
#  
#      To sign in, use a web browser to open the page https://microsoft.com/devicelogin and enter the code XXYYZZAA12 to authenticate.
#  
#      **********************************************************************
```

Congratulations! Batch Clusters is now running. __Leave this terminal open for the remainder of the demo.__

## Register Subscription via grpcurl

Start a new ssh session to the same VM and the following. 

_This step is required so that Batch Clusters knows which user subscription to use._
```bash
wget -O - https://raw.githubusercontent.com/Azure/cyclecloud-slurm/feature/csdemo/demo/activate_sub.sh | bash -
```

<details>
<summary><b>Expand to see <code>activate_sub.sh</code></b></summary>

```bash
#!/usr/bin/env
set -e
. ~/./demo_vars.sh
cd
wget https://github.com/fullstorydev/grpcurl/releases/download/v1.8.7/grpcurl_1.8.7_linux_x86_64.tar.gz
tar xzf grpcurl_1.8.7_linux_x86_64.tar.gz
~/grpcurl -insecure -d '{"id": "'${DEMO_SUBSCRIPTION_ID}'", "properties": {"tenant_id": "5678", "registration_state": "Registered", "registration_date": "2021-02-01T14:01:01Z"}}' localhost:5679 microsoft.batchclusters.Service/CreateOrUpdateSubscription
```

</details>

__At this point, Batch Clusters is now ready to start new nodes for this sub.__



.
# Setup Slurm/Azure-Slurm with Batch Clusters
The following steps will build Slurm, Azure-Slurm, and setup an autoscaling Slurm cluster that integrates with Batch Clusters.

__Note:__ If you simply want to use Batch Clusters directly, then the following is not required. 

## Create and stage Slurm/Azure-Slurm binaries

The below script will install NFS, build Slurm, build azure-slurm and copy the packages to `/sched`. 

__Note:__ It may take several minutes, due to compilation speeds of Slurm.
```bash
wget -O - https://raw.githubusercontent.com/Azure/cyclecloud-slurm/feature/csdemo/demo/02-demo.sh | bash -
```

## Install Slurm and Azure-Slurm
```bash
wget -O - https://raw.githubusercontent.com/Azure/cyclecloud-slurm/feature/csdemo/demo/03-demo.sh | bash -
```
__`azslurm` is now installed!__

## Create Batch Cluster
`azslurm` provides a convenience method for creating the Batch Cluster. 
```bash
sudo -i
azslurm create_cluster
```

<details>
<summary><b>Expand to example REST request and response</b></summary>

```
PUT /subscriptions/XXXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX/resourceGroups/ryhamel-cs-demo-live-pre/providers/Microsoft.AzureHPC/clusters/csdemo HTTP/1.1
Host: localhost:5677
Accept-Encoding: identity
Content-Length: 152
Accept: application/json
Content-Type: application/json
User-Agent: Swagger-Codegen/1.0.0/python
```



```javascript
{
  "tags": {
    "Owner": "ryhamel"
  },
  "networkProfile": {
    "publicNetworkAccess": "Disabled",
    "nodeManagementAccess": {
      "defaultAction": "Allow",
      "ipRules": []
    }
  }
}
```

```bash
curl -H "Content-Type: application/json"  https://localhost:5677/subscriptions/$DEMO_SUBSCRIPTION_ID/resourceGroups/$DEMO_RESOURCE_GROP/providers/Microsoft.AzureHPC/clusters/$DEMO_CLUSTER_NAME -d '{
  "tags": {
    "Owner": "'$DEMO_USER'"
  },
  "networkProfile": {
    "publicNetworkAccess": "Disabled",
    "nodeManagementAccess": {
      "defaultAction": "Allow",
      "ipRules": []
    }
  }
}'
```
</details>

## Submit a job as $DEMO_USER!
```bash
sbatch --wrap "sleep 90"

# monitor the node status
sinfo
# monitor the job status
squeue
```

## Explore azslurm
Here we will explore manually starting and stopping nodes in Slurm - or resume and suspend, in Slurm terms.

Note the example request and responses below, showing the Batch Clusters API in action.
```bash
sudo -i
azslurm resume --node-list htc-100
```
<details>
<summary><b>Expand to see REST request and response</b></summary>

```
PUT /subscriptions/XXXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX/resourceGroups/ryhamel-cs-demo-live-pre/providers/Microsoft.AzureHPC/clusters/csdemo/nodes/htc-100 HTTP/1.1
Host: localhost:5677
Accept-Encoding: identity
Content-Length: 1529
Accept: application/json
Content-Type: application/json
User-Agent: Swagger-Codegen/1.0.0/python
```


The JSON body
```javascript
{
  "virtualMachineProfile": {
    "scalesetType": "Flex",
    "subnetId": "/subscriptions/XXXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX/resourceGroups/ryhamel-persistent/providers/Microsoft.Network/virtualNetworks/ryhamelgoddardvnet/subnets/default",
    "vmSize": "Standard_F2",
    "region": "southcentralus",
    "imageReference": {
      "publisher": "Canonical",
      "offer": "UbuntuServer",
      "sku": "18.04-LTS",
      "version": "latest"
    },
    "adminAccess": {
      "userName": "ryhamel",
      "publicKey": "ssh-rsa AAAAB..."
    },
    "cloudInit": "#!/bin/bash\nNFS_SRV=10.1.0.25\napt install -y nfs-common\nCLUSTER_NAME=csdemo\nmkdir -p /sched\nmkdir -p /shared\nmount -t nfs $NFS_SRV:/mnt/exports/sched /sched\nmount -t nfs $NFS_SRV:/mnt/exports/shared /shared\ncd \ntar xzf /sched/azure-slurm-install-pkg-3.0.0.tar.gz\ncd azure-slurm-install\ncat > bootstrap.json<<EOF\n{\n    \"cluster_name\": \"\",\n    \"node_name\": \"scheduler\",\n    \"slurm\": {\n        \"version\": \"20.05.3\",\n        \"accounting\": {\"enabled\": false}\n    },\n    \"hostname\": \"localhost\"\n}\nEOF\n./install.sh --bootstrap-config bootstrap.json --mode execute",
    "tags": {
      "Owner": "ryhamel"
    }
  }
}
```



The cloud-init script.
```bash
#!/bin/bash
NFS_SRV=10.1.0.25
apt install -y nfs-common
CLUSTER_NAME=csdemo
mkdir -p /sched
mkdir -p /shared
mount -t nfs $NFS_SRV:/mnt/exports/sched /sched
mount -t nfs $NFS_SRV:/mnt/exports/shared /shared
cd 
tar xzf /sched/azure-slurm-install-pkg-3.0.0.tar.gz
cd azure-slurm-install
cat > bootstrap.json<<EOF
{
    "cluster_name": "",
    "node_name": "scheduler",
    "slurm": {
        "version": "20.05.3",
        "accounting": {"enabled": false}
    },
    "hostname": "localhost"
}
EOF
./install.sh --bootstrap-config bootstrap.json --mode execute
```

And the response
```javascript
{
    "name": "htc-100",
    "clusterName": null,
    "resourceGroup": null,
    "subscriptionId": null,
    "properties": {
        "virtualMachineProfile": {
            "scalesetType": 1,
            "subnetId": "/subscriptions/XXXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX/resourceGroups/ryhamel-persistent/providers/Microsoft.Network/virtualNetworks/ryhamelgoddardvnet/subnets/default",
            "vmSize": "Standard_F2",
            "region": "southcentralus",
            "imageReference": {
                "publisher": "Canonical",
                "offer": "UbuntuServer",
                "sku": "18.04-LTS",
                "version": "latest"
            },
            "adminAccess": {
                "userName": "ryhamel",
                "publicKey": "ssh-rsa AAAA..."
            },
            "cloudInit": "#!/bin/bash\\nNFS_SRV=10.1.0.25\\napt install -y nfs-common\\nCLUSTER_NAME=csdemo\\nmkdir -p /sched\\nmkdir -p /shared\\nmount -t nfs $NFS_SRV:/mnt/exports/sched /sched\\nmount -t nfs $NFS_SRV:/mnt/exports/shared /shared\\ncd \\ntar xzf /sched/azure-slurm-install-pkg-3.0.0.tar.gz\\ncd azure-slurm-install\\ncat > bootstrap.json<<EOF\\n{\\n    \\"cluster_name\\": \\"\\",\\n    \\"node_name\\": \\"scheduler\\",\\n    \\"slurm\\": {\\n        \\"version\\": \\"20.05.3\\",\\n        \\"accounting\\": {\\"enabled\\": false}\\n    },\\n    \\"hostname\\": \\"localhost\\"\\n}\\nEOF\\n./install.sh --bootstrap-config bootstrap.json --mode execute",
            "tags": {
                "Owner": "ryhamel"
            }
        }
    }
}
```

```bash
curl -X PUT -H "Content-Type: application/json"  https://localhost:5677/subscriptions/$DEMO_SUBSCRIPTION_ID/resourceGroups/$DEMO_RESOURCE_GROP/providers/Microsoft.AzureHPC/clusters/$DEMO_CLUSTER_NAME/nodes/htc-100 -d '{(INSERT JSON HERE)}'
```

</details>

```bash
sudo -i
azslurm suspend --node-list htc-100
```

<details>
<summary><b>Expand to see REST request and response</b></summary>

```
DELETE /subscriptions/XXXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX/resourceGroups/ryhamel-cs-demo-live-pre/providers/Microsoft.AzureHPC/clusters/csdemo/nodes/htc-100 HTTP/1.1
Host: localhost:5677
Accept-Encoding: identity
Content-Length: 2
Accept: application/json
User-Agent: Swagger-Codegen/1.0.0/python
Content-Type: application/json
```

```bash
curl -X DELETE https://localhost:5677/subscriptions/$DEMO_SUBSCRIPTION_ID/resourceGroups/$DEMO_RESOURCE_GROP/providers/Microsoft.AzureHPC/clusters/$DEMO_CLUSTER_NAME/nodes/htc-100
```

The json body and response are empty.

</details>

