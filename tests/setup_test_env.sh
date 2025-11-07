#!/bin/bash
# ComfyUI Manager Test Environment Setup
# Sets up virtual environment and ComfyUI for testing

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}ComfyUI Manager Environment Setup${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Configuration
VENV_PATH="${VENV_PATH:-$HOME/venv}"
COMFYUI_PATH="${COMFYUI_PATH:-tests/env/ComfyUI}"
COMFYUI_BRANCH="${COMFYUI_BRANCH:-master}"
COMFYUI_REPO="${COMFYUI_REPO:-https://github.com/comfyanonymous/ComfyUI.git}"
PIP="${VENV_PATH}/bin/pip"

echo -e "${CYAN}Configuration:${NC}"
echo -e "  VENV_PATH: ${VENV_PATH}"
echo -e "  COMFYUI_PATH: ${COMFYUI_PATH}"
echo -e "  COMFYUI_BRANCH: ${COMFYUI_BRANCH}"
echo -e "  COMFYUI_REPO: ${COMFYUI_REPO}"
echo ""

# Step 1: Check/Create virtual environment
echo -e "${YELLOW}📦 Step 1: Setting up virtual environment...${NC}"

if [ ! -f "${VENV_PATH}/bin/activate" ]; then
    echo -e "${CYAN}Creating virtual environment at: ${VENV_PATH}${NC}"
    python3 -m venv "${VENV_PATH}"
    echo -e "${GREEN}✓ Virtual environment created${NC}"

    # Activate and install uv
    source "${VENV_PATH}/bin/activate"
    echo -e "${CYAN}Installing uv package manager...${NC}"
    "${PIP}" install uv
    echo -e "${GREEN}✓ uv installed${NC}"
else
    echo -e "${GREEN}✓ Virtual environment already exists${NC}"
    source "${VENV_PATH}/bin/activate"
fi

# Validate virtual environment is activated
if [ -z "$VIRTUAL_ENV" ]; then
    echo -e "${RED}✗ FATAL: Virtual environment activation failed${NC}"
    echo -e "${RED}  Expected path: ${VENV_PATH}${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Virtual environment activated: ${VIRTUAL_ENV}${NC}"
echo ""

# Step 2: Setup ComfyUI
echo -e "${YELLOW}🔧 Step 2: Setting up ComfyUI...${NC}"

# Create environment directory if it doesn't exist
env_dir=$(dirname "${COMFYUI_PATH}")
if [ ! -d "${env_dir}" ]; then
    echo -e "${CYAN}Creating environment directory: ${env_dir}${NC}"
    mkdir -p "${env_dir}"
fi

# Check if ComfyUI exists
if [ ! -d "${COMFYUI_PATH}" ]; then
    echo -e "${CYAN}Cloning ComfyUI repository...${NC}"
    echo -e "  Repository: ${COMFYUI_REPO}"
    echo -e "  Branch: ${COMFYUI_BRANCH}"

    git clone --branch "${COMFYUI_BRANCH}" "${COMFYUI_REPO}" "${COMFYUI_PATH}"

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ ComfyUI cloned successfully${NC}"
    else
        echo -e "${RED}✗ Failed to clone ComfyUI${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓ ComfyUI already exists at: ${COMFYUI_PATH}${NC}"

    # Check if it's a git repository and handle branch switching
    if [ -d "${COMFYUI_PATH}/.git" ]; then
        cd "${COMFYUI_PATH}"
        current_branch=$(git branch --show-current)
        echo -e "  Current branch: ${current_branch}"

        # Switch branch if requested and different
        if [ "${current_branch}" != "${COMFYUI_BRANCH}" ]; then
            echo -e "${YELLOW}⚠ Requested branch '${COMFYUI_BRANCH}' differs from current '${current_branch}'${NC}"
            echo -e "${CYAN}Switching to branch: ${COMFYUI_BRANCH}${NC}"
            git fetch origin
            git checkout "${COMFYUI_BRANCH}"
            git pull origin "${COMFYUI_BRANCH}"
            echo -e "${GREEN}✓ Switched to branch: ${COMFYUI_BRANCH}${NC}"
        fi
        cd - > /dev/null
    fi
fi
echo ""

# Step 3: Install ComfyUI dependencies
echo -e "${YELLOW}📦 Step 3: Installing ComfyUI dependencies...${NC}"

if [ ! -f "${COMFYUI_PATH}/requirements.txt" ]; then
    echo -e "${RED}✗ ComfyUI requirements.txt not found${NC}"
    echo -e "${RED}  Expected: ${COMFYUI_PATH}/requirements.txt${NC}"
    exit 1
fi

"${PIP}" install -r "${COMFYUI_PATH}/requirements.txt" > /dev/null 2>&1 || {
    echo -e "${YELLOW}⚠ Some ComfyUI dependencies may have failed to install${NC}"
    echo -e "${YELLOW}  This is usually OK for testing${NC}"
}
echo -e "${GREEN}✓ ComfyUI dependencies installed${NC}"
echo ""

# Step 4: Create required directories
echo -e "${YELLOW}📁 Step 4: Creating required directories...${NC}"

if [ ! -d "${COMFYUI_PATH}/custom_nodes" ]; then
    mkdir -p "${COMFYUI_PATH}/custom_nodes"
    echo -e "${GREEN}✓ Created custom_nodes directory${NC}"
else
    echo -e "${GREEN}✓ custom_nodes directory exists${NC}"
fi
echo ""

# Step 5: Validate environment
echo -e "${YELLOW}✅ Step 5: Validating environment...${NC}"

# Check frontend directory (support both old 'front' and new 'app' structures)
if [ ! -d "${COMFYUI_PATH}/front" ] && [ ! -d "${COMFYUI_PATH}/app" ]; then
    echo -e "${RED}✗ FATAL: ComfyUI frontend directory not found${NC}"
    echo -e "${RED}  Expected: ${COMFYUI_PATH}/front or ${COMFYUI_PATH}/app${NC}"
    echo -e "${RED}  This directory is required for ComfyUI to run${NC}"
    echo -e "${YELLOW}  Possible causes:${NC}"
    echo -e "${YELLOW}    - Incomplete ComfyUI clone${NC}"
    echo -e "${YELLOW}    - Wrong branch checked out${NC}"
    echo -e "${YELLOW}    - ComfyUI repository structure changed${NC}"
    echo -e "${YELLOW}  Try:${NC}"
    echo -e "${YELLOW}    rm -rf ${COMFYUI_PATH}${NC}"
    echo -e "${YELLOW}    ./setup_test_env.sh  # Will re-clone ComfyUI${NC}"
    exit 1
fi
if [ -d "${COMFYUI_PATH}/front" ]; then
    echo -e "${GREEN}✓ ComfyUI frontend directory exists (old structure)${NC}"
else
    echo -e "${GREEN}✓ ComfyUI frontend directory exists (new structure)${NC}"
fi

# Check main.py
if [ ! -f "${COMFYUI_PATH}/main.py" ]; then
    echo -e "${RED}✗ FATAL: ComfyUI main.py not found${NC}"
    echo -e "${RED}  Expected: ${COMFYUI_PATH}/main.py${NC}"
    exit 1
fi
echo -e "${GREEN}✓ ComfyUI main.py exists${NC}"
echo ""

# Final summary
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✅ Environment Setup Complete!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "Environment is ready for testing."
echo -e ""
echo -e "To run tests:"
echo -e "  ${CYAN}./run_tests.sh${NC}"
echo ""
echo -e "Configuration:"
echo -e "  Virtual Environment: ${GREEN}${VENV_PATH}${NC}"
echo -e "  ComfyUI Path: ${GREEN}${COMFYUI_PATH}${NC}"
echo -e "  ComfyUI Branch: ${GREEN}${COMFYUI_BRANCH}${NC}"
echo ""
