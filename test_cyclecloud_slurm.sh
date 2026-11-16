#!/usr/bin/env bash
set -eu

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TEST_PYTHON="$REPO_DIR/.venv-tests/bin/python"

if ! command -v uv >/dev/null 2>&1; then
    echo "Error: uv must be installed and available on PATH." >&2
    exit 1
fi

if [ ! -x "$TEST_PYTHON" ]; then
    echo "Creating test virtual environment..."
    uv venv --python 3.11 "$REPO_DIR/.venv-tests"
fi

echo "Installing test dependencies..."
# The legacy setup.py files import setuptools.command.test.
uv pip install --python "$TEST_PYTHON" 'setuptools<72' wheel
uv pip install --python "$TEST_PYTHON" --no-build-isolation \
    "$REPO_DIR/azure-slurm" \
    'https://github.com/Azure/cyclecloud-scalelib/archive/refs/tags/1.0.10.tar.gz' \
    'https://github.com/Azure/cyclecloud-scalelib/releases/download/1.0.10/cyclecloud_api-8.8.3-py2.py3-none-any.whl' \
    parallel-ssh \
    --requirements "$REPO_DIR/azure-slurm-exporter/pyproject.toml" --extra test

status=0
for project in azure-slurm azure-slurm-exporter azure-slurm-install; do
    echo "=== Testing $project ==="
    if (
        cd "$REPO_DIR/$project" &&
        PYTHONPATH=.:test "$TEST_PYTHON" -m pytest test -v
    ); then
        echo "=== PASSED: $project ==="
    else
        echo "=== FAILED: $project ===" >&2
        status=1
    fi
done

exit "$status"
