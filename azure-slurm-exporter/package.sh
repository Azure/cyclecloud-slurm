#!/usr/bin/env bash
set -e

PROJECT_DIR=$(dirname "$0")
VENV_DIR="$PROJECT_DIR/.venv"
# Create a virtual environment if it does not exist
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
else
    echo "Virtual environment already exists at $VENV_DIR"
fi
# Activate the virtual environment
source "$VENV_DIR/bin/activate"
# Ensure setuptools and wheel are installed
pip install --upgrade setuptools wheel build
# Build the distribution
python3 -m build
# Deactivate the virtual environment
deactivate
