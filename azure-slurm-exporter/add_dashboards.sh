#!/bin/bash
EXPORTER_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
echo "Exporter directory: $EXPORTER_DIR"
source "$EXPORTER_DIR/util.sh"
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
LIBRARY_PANEL_FOLDER=$DASHBOARD_FOLDER/library-panels
# Create Grafana dashboards folders
az grafana folder show -n $GRAFANA_NAME -g $RESOURCE_GROUP_NAME --folder "$FOLDER_NAME" > /dev/null 2>&1
if [ $? -ne 0 ]; then
  echo "$FOLDER_NAME folder does not exist. Creating it."
  az grafana folder create --name $GRAFANA_NAME --resource-group $RESOURCE_GROUP_NAME --title "$FOLDER_NAME"
fi

# Library panels (must exist before importing dashboards that reference them).
if [ -d "$LIBRARY_PANEL_FOLDER" ] && ls "$LIBRARY_PANEL_FOLDER"/*.json > /dev/null 2>&1; then
  GRAFANA_ENDPOINT=$(az grafana show -n $GRAFANA_NAME -g $RESOURCE_GROUP_NAME --query properties.endpoint -o tsv | tr -d '\r\n')
  for panel_file in "$LIBRARY_PANEL_FOLDER"/*.json; do
    if ! import_library_panel "$panel_file"; then
      echo "Failed to import library panel: $panel_file" >&2
      exit 1
    fi
  done
fi

# Slurm dashboards
for dashboard_file in "$DASHBOARD_FOLDER"/*.json; do
  if [ ! -f "$dashboard_file" ]; then
    continue
  fi
  echo "Importing dashboard: $(basename "$dashboard_file")"
  az grafana dashboard import --name $GRAFANA_NAME --resource-group $RESOURCE_GROUP_NAME --folder "$FOLDER_NAME" --overwrite true --definition "$dashboard_file"
done