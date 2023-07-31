#!/bin/bash
set -e

cluster_name=suse-build
locker=$(cyclecloud locker list | cut -d" " -f1)
svm_template=$(cycle_server execute --format json 'select ClusterName from Cloud.Cluster where BaseName=="single-vm" && IsTemplate' | python3 -c "import json, sys; print(json.load(sys.stdin)[0]['ClusterName'])")
cat > $cluster_name.json<<EOF
{
    "ImageName": "suse:sle-hpc-15-sp4:gen2:latest",
    "ReturnProxy" : false,
    "UsePublicNetwork" : false,
    "MachineType" : "Standard_D2_v4"
}
EOF

cyclecloud create_cluster $svm_template $cluster_name -p $cluster_name.json --force
echo "Fill out the cluster parameters, then hit enter to continue"
read 
cyclecloud start_cluster $cluster_name
CycleCloudDevel=1 cyclecloud await_target_state $cluster_name -n instance

ip=$(cyclecloud show_nodes -c $cluster_name --format json | python3 -c "import sys, json; print(json.load(sys.stdin)[0]['Instance']['PrivateIp'])")

rsync -a -e "ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null" specs/default/cluster-init/files/JobSubmitPlugin $ip:~/
scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ./specs/default/cluster-init/files/00-build-slurm.sh $ip:~/
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null $ip sudo bash 00-build-slurm.sh suse
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null $ip ln -s /usr/src/packages/RPMS/x86_64/ blobs
rsync -a -e "ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"  $ip:~/blobs/*suse* blobs/
