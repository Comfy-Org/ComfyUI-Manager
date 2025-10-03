#!/bin/bash

# Test Environment Setup Script for pip_util.py
# Creates isolated venv to prevent environment corruption

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VENV_DIR="${SCRIPT_DIR}/test_venv"

echo "=================================================="
echo "pip_util.py Test Environment Setup"
echo "=================================================="
echo ""

# Check Python version
PYTHON_CMD=""
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo "❌ Error: Python not found. Please install Python 3.8 or higher."
    exit 1
fi

PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
echo "✓ Found Python: $PYTHON_VERSION"

# Remove existing venv if present
if [ -d "$VENV_DIR" ]; then
    echo ""
    read -p "⚠️  Existing test venv found. Remove and recreate? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "🗑️  Removing existing venv..."
        rm -rf "$VENV_DIR"
    else
        echo "Keeping existing venv. Skipping creation."
        exit 0
    fi
fi

# Create venv
echo ""
echo "📦 Creating virtual environment..."
$PYTHON_CMD -m venv "$VENV_DIR"

# Activate venv
echo "🔌 Activating virtual environment..."
source "${VENV_DIR}/bin/activate"

# Upgrade pip
echo "⬆️  Upgrading pip..."
pip install --upgrade pip

# Install test dependencies
echo ""
echo "📚 Installing test dependencies..."
pip install -r "${SCRIPT_DIR}/requirements.txt"

echo ""
echo "=================================================="
echo "✅ Test environment setup complete!"
echo "=================================================="
echo ""
echo "To activate the test environment:"
echo "  source ${VENV_DIR}/bin/activate"
echo ""
echo "To run tests:"
echo "  pytest"
echo ""
echo "To deactivate:"
echo "  deactivate"
echo ""
