#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v uv >/dev/null 2>&1; then
    echo "Error: uv must be installed and available on PATH." >&2
    exit 1
fi

test_project() (
    cd "$REPO_DIR/$1" || exit 1
    TEST_PYTHON="$PWD/.venv/bin/python"
    if [ ! -x "$TEST_PYTHON" ]; then
        uv venv --python 3.11 .venv || exit 1
    fi

    echo "Installing test dependencies for $1..."
    if [ -f pyproject.toml ]; then
        uv pip install --python "$TEST_PYTHON" \
            --requirements pyproject.toml --extra test || exit 1
    elif [ -f setup.py ]; then
        # Legacy metadata includes tests_require, which pip does not install.
        uv pip install --python "$TEST_PYTHON" 'setuptools<72' wheel || exit 1
        "$TEST_PYTHON" -c '
import setuptools
from distutils.core import run_setup

metadata = run_setup("setup.py", stop_after="config")
print("\n".join(metadata.install_requires + metadata.tests_require))
' | uv pip install --python "$TEST_PYTHON" --requirements - || exit 1
    else
        echo "Error: no setup.py or pyproject.toml in $PWD." >&2
        exit 1
    fi

    if [ "$1" = azure-slurm ]; then
        # These runtime dependencies are not declared in setup.py.
        uv pip install --python "$TEST_PYTHON" --no-build-isolation \
            'https://github.com/Azure/cyclecloud-scalelib/archive/refs/tags/1.0.10.tar.gz' \
            'https://github.com/Azure/cyclecloud-scalelib/releases/download/1.0.10/cyclecloud_api-8.8.3-py2.py3-none-any.whl' \
            parallel-ssh || exit 1
    fi

    PYTHONPATH=.:test "$TEST_PYTHON" -m pytest test -v
)

status=0
for project in azure-slurm azure-slurm-exporter azure-slurm-install; do
    echo "=== Testing $project ==="
    if test_project "$project"; then
        echo "=== PASSED: $project ==="
    else
        echo "=== FAILED: $project ===" >&2
        status=1
    fi
done

exit "$status"
