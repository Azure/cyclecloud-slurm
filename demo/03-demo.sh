#!/usr/bin/env bash
set -e

. ~/./demo_vars.sh

# bootstrap.json, passed into azure-slurm-install/install.sh --bootstrap-config
tar xzf /sched/azure-slurm-install*.tar.gz
cd azure-slurm-install

cat >bootstrap.json<<EOF
{
    "cluster_name": "$DEMO_CLUSTER_NAME",
    "node_name": "scheduler",
    "slurm": {
        "version": "20.05.3",
        "accounting": {"enabled": false}
    },
    "hostname": "$(hostname)"
}
EOF
sudo ./install.sh --bootstrap-config bootstrap.json --mode scheduler
ipv4=$(curl -s -H Metadata:true --noproxy "*" "http://169.254.169.254/metadata/instance?api-version=2021-02-01" | jq -r .network.interface[0].ipv4.ipAddress[0].privateIpAddress)
cat >/sched/demo.json<<EOF
{
    "cluster_name": "$DEMO_CLUSTER_NAME",
    "url": "https://localhost:5677",
    "nodearrays": {
      "htc": {
        "generated_placement_group_buffer": 0
      }
    },
    "subscription_id": "$DEMO_SUBSCRIPTION_ID",
    "resource_group": "$DEMO_RESOURCE_GROUP",
"demo": {
    "vm_size": "$DEMO_VM_SIZE",
    "region": "$DEMO_REGION",
    "scaleset_type": "Flex",
    "subnet_id": "$DEMO_SUBNET_ID",
    "admin_access": {
      "user_name": "$DEMO_USER",
      "public_key": "$DEMO_USER_SSH_PUB_KEY"
    },
  "cloud_init": "#!/bin/bash\nNFS_SRV=$ipv4\napt install -y nfs-common\nCLUSTER_NAME=$DEMO_CLUSTER_NAME\nmkdir -p /sched\nmkdir -p /shared\nmount -t nfs \$NFS_SRV:/mnt/exports/sched /sched\nmount -t nfs \$NFS_SRV:/mnt/exports/shared /shared\ncd \ntar xzf /sched/azure-slurm-install-pkg-3.0.0.tar.gz\ncd azure-slurm-install\ncat > bootstrap.json<<EOF\n{\n    \"cluster_name\": \"$CLUSTER_NAME\",\n    \"node_name\": \"scheduler\",\n    \"slurm\": {\n        \"version\": \"20.05.3\",\n        \"accounting\": {\"enabled\": false}\n    },\n    \"hostname\": \"localhost\"\n}\nEOF\n./install.sh --bootstrap-config bootstrap.json --mode execute",
    "image_reference": {
      "publisher": "Canonical",
      "offer": "UbuntuServer",
      "sku": "18.04-LTS",
      "version": "latest"
    },
    "tags": {
      "Owner": "$DEMO_USER"
    }
  }
}
EOF


cd ~
tar xzf /sched/azure-slurm-pkg*.tar.gz
cd azure-slurm
sudo ./install.sh

# in theory not necessary, but if you rerun this step it is.
sudo systemctl restart slurmctld