#!/bin/bash
# Shared helper functions for the infra scripts.

# Audience used to request a token for the Azure Managed Grafana REST API
GRAFANA_AAD_RESOURCE="ce34e7e5-485f-4d76-964f-b3d2b16d1e4f"

# az grafana has no library-panel command, so call the Grafana REST API directly.
# Upsert a single Grafana library panel.
# Usage: import_library_panel <library-panel-json>
# Requires the following variables to be set in the environment:
#   GRAFANA_ENDPOINT      - Grafana instance endpoint URL
import_library_panel() {
  local panel_file="$1"

  if [ -z "$panel_file" ]; then
    echo "import_library_panel: missing library panel json argument" >&2
    return 1
  fi
  if [ ! -f "$panel_file" ]; then
    echo "import_library_panel: file not found: $panel_file" >&2
    return 1
  fi

  if ! command -v jq >/dev/null 2>&1; then
    echo "import_library_panel: jq is required but was not found in PATH" >&2
    return 1
  fi

  local panel_uid panel_name existing_version payload
  panel_uid=$(jq -r '.uid // empty' "$panel_file")
  panel_name=$(jq -r '.name // empty' "$panel_file")

  if [ -z "$panel_uid" ] || [ -z "$panel_name" ]; then
    echo "import_library_panel: panel JSON must include non-empty .uid and .name: $panel_file" >&2
    return 1
  fi

  echo "Upserting library panel: $panel_name ($panel_uid)"

  if [ -z "${GRAFANA_ENDPOINT:-}" ]; then
    echo "import_library_panel: GRAFANA_ENDPOINT is not set" >&2
    return 1
  fi

  local existing_json
  existing_version=""
  if existing_json=$(az rest --method get \
    --url "$GRAFANA_ENDPOINT/api/library-elements/$panel_uid" \
    --resource "$GRAFANA_AAD_RESOURCE" 2>/dev/null); then
    existing_version=$(jq -r '.result.version // empty' <<<"$existing_json")
  fi

  if [ -z "$existing_version" ]; then
    # Create new library panel
    if az rest --method post \
      --url "$GRAFANA_ENDPOINT/api/library-elements" \
      --resource "$GRAFANA_AAD_RESOURCE" \
      --headers "Content-Type=application/json" \
      --body @"$panel_file" > /dev/null; then
      echo "  created"
    else
      echo "  failed to create $panel_uid" >&2
      return 1
    fi
  else
    # Update existing library panel (PATCH requires the current version)
    payload=$(jq --argjson v "$existing_version" '{name, kind, model, version: $v}' "$panel_file") || return 1
    if az rest --method patch \
      --url "$GRAFANA_ENDPOINT/api/library-elements/$panel_uid" \
      --resource "$GRAFANA_AAD_RESOURCE" \
      --headers "Content-Type=application/json" \
      --body "$payload" > /dev/null; then
      echo "  updated"
    else
      echo "  failed to update $panel_uid" >&2
      return 1
    fi
  fi
}
