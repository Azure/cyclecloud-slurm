#!/bin/bash
EXPORTER_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
echo "Exporter directory: $EXPORTER_DIR"
RESOURCE_GROUP_NAME=$1
GRAFANA_NAME=$2 

if [ -z "$GRAFANA_NAME" ]; then
  echo "Usage: $0 <resource-group-name> <grafana-name>"
  exit 1
fi
if [ -z "$RESOURCE_GROUP_NAME" ]; then
  echo "Usage: $0 <resource-group-name> <grafana-name>"
  exit 1
fi

FOLDER_NAME="Azure CycleCloud"
DASHBOARD_FOLDER=$EXPORTER_DIR/dashboards
# Create Grafana dashboards folders
az grafana folder show -n $GRAFANA_NAME -g $RESOURCE_GROUP_NAME --folder "$FOLDER_NAME" > /dev/null 2>&1
if [ $? -ne 0 ]; then
  echo "$FOLDER_NAME folder does not exist. Creating it."
  az grafana folder create --name $GRAFANA_NAME --resource-group $RESOURCE_GROUP_NAME --title "$FOLDER_NAME"
fi

# Slurm Dashboard
az grafana dashboard import --name $GRAFANA_NAME --resource-group $RESOURCE_GROUP_NAME --folder "$FOLDER_NAME" --overwrite true --definition $DASHBOARD_FOLDER/slurm.json
az grafana dashboard import --name $GRAFANA_NAME --resource-group $RESOURCE_GROUP_NAME --folder "$FOLDER_NAME" --overwrite true --definition $DASHBOARD_FOLDER/failed-jobs.json
