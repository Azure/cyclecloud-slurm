#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
set -e
CLUSTER_NAME=
USERNAME=
PASSWORD=
ACCOUNTING_SUBSCRIPTION_ID=unused
URL=
INSTALL_DIR=/opt/azurehpc/slurm

usage() {
    echo "Usage: $0 [--url <URL>] [--cluster-name <CLUSTER_NAME>] [--username <USERNAME>] [--password <PASSWORD>] [--accounting-subscription-id <ACCOUNTING_SUBSCRIPTION_ID>] [--accounting-tag-value <ACCOUNTING_TAG_VALUE>]"
    echo "  --url <URL>                        The URL of the CycleCloud instance"
    echo "  --cluster-name <CLUSTER_NAME>      The name of the cluster"
    echo "  --username <USERNAME>              The username for CycleCloud"
    echo "  --password <PASSWORD>              The password for CycleCloud"
    echo "  --accounting-subscription-id <ID>  The subscription ID for accounting (optional)"
}


while (( "$#" )); do
    case "$1" in
        --url)
            URL=$2
            shift 2
            ;;
        --cluster-name)
            CLUSTER_NAME=$2
            shift 2
            ;;
        --username)
            USERNAME=$2
            shift 2
            ;;
        --password)
            PASSWORD=$2
            shift 2
            ;;
        --accounting-subscription-id)
            ACCOUNTING_SUBSCRIPTION_ID=$2
            shift 2
            ;;
        --help)
            usage
            exit 0
            ;;
        -*|--*=)
            echo "Unknown option $1" >&2
            exit 1
            ;;
        *)
            echo "Unknown option  $1" >&2
            exit 1
            ;;
    esac
done

if [ -z "$CLUSTER_NAME" ] || [ -z "$USERNAME" ] || [ -z "$PASSWORD" ] || [ -z "$URL" ]; then
    echo "Error: Missing required arguments."
    echo "Please provide --url, --cluster-name, --username, and --password."
    usage
    exit 1
fi

escaped_cluster_name=$(python3 -c "import re; print(re.sub('[^a-zA-Z0-9-]', '-', '$CLUSTER_NAME').lower())")

config_dir=/sched/$escaped_cluster_name
azslurm initconfig --username $USERNAME \
                --password $PASSWORD \
                --url      $URL \
                --cluster-name $CLUSTER_NAME\
                --config-dir $config_dir \
                --accounting-subscription-id $ACCOUNTING_SUBSCRIPTION_ID \
                --default-resource '{"select": {}, "name": "slurm_gpus", "value": "node.gpu_count"}' \
                --cost-cache-root $INSTALL_DIR/.cache \
                > $INSTALL_DIR/autoscale.json