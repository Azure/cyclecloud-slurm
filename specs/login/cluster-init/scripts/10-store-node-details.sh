#!/usr/bin/env bash
set -e

CLUSTER_NAME=$(jetpack config cyclecloud.cluster.name)
NODE_NAME=$(jetpack config cyclecloud.node.name)
PRIVATE_IP=$(hostname -i)

mkdir -p "/shared/${CLUSTER_NAME}"
cat << EOF > "/shared/${CLUSTER_NAME}/${NODE_NAME}.json"
{
  "cluster_name": "${CLUSTER_NAME}",
  "name": "${NODE_NAME}",
  "ip": "${PRIVATE_IP}"
}

EOF
