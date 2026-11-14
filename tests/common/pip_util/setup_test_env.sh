#!/bin/bash
# Setup script for pip_util integration tests
# Creates a test venv and installs base packages

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/test_venv"

echo "Setting up test environment for pip_util integration tests..."

# Remove existing venv if present
if [ -d "$VENV_DIR" ]; then
    echo "Removing existing test venv..."
    rm -rf "$VENV_DIR"
fi

# Create new venv
echo "Creating test venv at $VENV_DIR..."
python3 -m venv "$VENV_DIR"

# Activate venv
source "$VENV_DIR/bin/activate"

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install pytest
echo "Installing pytest..."
pip install pytest

# Install base test packages
echo "Installing base test packages..."
pip install -r "$SCRIPT_DIR/requirements-test-base.txt"

echo ""
echo "Test environment setup complete!"
echo "Installed packages:"
pip freeze

echo ""
echo "To activate the test venv, run:"
echo "  source $VENV_DIR/bin/activate"
echo ""
echo "To run tests:"
echo "  pytest -v"
