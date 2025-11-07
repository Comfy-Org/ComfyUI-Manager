#!/bin/bash
# ComfyUI Manager Parallel Test Environment Setup
# Sets up multiple test environments for parallel testing

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}ComfyUI Manager Parallel Environment Setup${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Configuration
VENV_PATH="${VENV_PATH:-$HOME/venv}"
BASE_COMFYUI_PATH="${BASE_COMFYUI_PATH:-tests/env}"
COMFYUI_BRANCH="${COMFYUI_BRANCH:-master}"
COMFYUI_REPO="${COMFYUI_REPO:-https://github.com/comfyanonymous/ComfyUI.git}"
NUM_ENVS="${NUM_ENVS:-3}"  # Number of parallel environments
BASE_PORT="${BASE_PORT:-8188}"  # Starting port number

PIP="${VENV_PATH}/bin/pip"

echo -e "${CYAN}Configuration:${NC}"
echo -e "  VENV_PATH: ${VENV_PATH}"
echo -e "  BASE_COMFYUI_PATH: ${BASE_COMFYUI_PATH}"
echo -e "  COMFYUI_BRANCH: ${COMFYUI_BRANCH}"
echo -e "  COMFYUI_REPO: ${COMFYUI_REPO}"
echo -e "  NUM_ENVS: ${NUM_ENVS}"
echo -e "  BASE_PORT: ${BASE_PORT}"
echo ""

# Validate NUM_ENVS
if [ "$NUM_ENVS" -lt 1 ] || [ "$NUM_ENVS" -gt 10 ]; then
    echo -e "${RED}✗ FATAL: NUM_ENVS must be between 1 and 10${NC}"
    echo -e "${RED}  Current value: ${NUM_ENVS}${NC}"
    exit 1
fi

# Step 1: Setup shared virtual environment
echo -e "${YELLOW}📦 Step 1: Setting up shared virtual environment...${NC}"

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

# Step 2: Setup first ComfyUI environment (reference)
echo -e "${YELLOW}🔧 Step 2: Setting up reference ComfyUI environment...${NC}"

REFERENCE_PATH="${BASE_COMFYUI_PATH}/ComfyUI"

# Create base directory
if [ ! -d "${BASE_COMFYUI_PATH}" ]; then
    mkdir -p "${BASE_COMFYUI_PATH}"
fi

# Clone or update reference ComfyUI
if [ ! -d "${REFERENCE_PATH}" ]; then
    echo -e "${CYAN}Cloning ComfyUI repository...${NC}"
    echo -e "  Repository: ${COMFYUI_REPO}"
    echo -e "  Branch: ${COMFYUI_BRANCH}"

    git clone --branch "${COMFYUI_BRANCH}" "${COMFYUI_REPO}" "${REFERENCE_PATH}"

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ ComfyUI cloned successfully${NC}"
    else
        echo -e "${RED}✗ Failed to clone ComfyUI${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓ Reference ComfyUI already exists${NC}"

    # Check branch and switch if needed
    if [ -d "${REFERENCE_PATH}/.git" ]; then
        cd "${REFERENCE_PATH}"
        current_branch=$(git branch --show-current)
        echo -e "  Current branch: ${current_branch}"

        if [ "${current_branch}" != "${COMFYUI_BRANCH}" ]; then
            echo -e "${YELLOW}⚠ Switching to branch: ${COMFYUI_BRANCH}${NC}"
            git fetch origin || true
            git checkout "${COMFYUI_BRANCH}"
            # Only pull if it's a tracking branch
            if git rev-parse --abbrev-ref --symbolic-full-name @{u} >/dev/null 2>&1; then
                git pull origin "${COMFYUI_BRANCH}" || true
            fi
            echo -e "${GREEN}✓ Switched to branch: ${COMFYUI_BRANCH}${NC}"
        fi
        cd - > /dev/null
    fi
fi

# Get current commit hash for consistency
cd "${REFERENCE_PATH}"
REFERENCE_COMMIT=$(git rev-parse HEAD)
REFERENCE_BRANCH=$(git branch --show-current)
echo -e "${CYAN}  Reference commit: ${REFERENCE_COMMIT:0:8}${NC}"
echo -e "${CYAN}  Reference branch: ${REFERENCE_BRANCH}${NC}"
cd - > /dev/null

# Install ComfyUI dependencies
echo -e "${CYAN}Installing ComfyUI dependencies...${NC}"
if [ -f "${REFERENCE_PATH}/requirements.txt" ]; then
    "${PIP}" install -r "${REFERENCE_PATH}/requirements.txt" > /dev/null 2>&1 || {
        echo -e "${YELLOW}⚠ Some ComfyUI dependencies may have failed to install${NC}"
    }
    echo -e "${GREEN}✓ ComfyUI dependencies installed${NC}"
fi

# Validate reference environment (support both old 'front' and new 'app' structures)
if [ ! -d "${REFERENCE_PATH}/front" ] && [ ! -d "${REFERENCE_PATH}/app" ]; then
    echo -e "${RED}✗ FATAL: Reference ComfyUI frontend directory not found (neither 'front' nor 'app')${NC}"
    exit 1
fi
if [ -d "${REFERENCE_PATH}/front" ]; then
    echo -e "${GREEN}✓ Reference ComfyUI validated (old structure with 'front')${NC}"
else
    echo -e "${GREEN}✓ Reference ComfyUI validated (new structure with 'app')${NC}"
fi
echo ""

# Step 3: Create parallel environments
echo -e "${YELLOW}🔀 Step 3: Creating ${NUM_ENVS} parallel environments...${NC}"

for i in $(seq 1 $NUM_ENVS); do
    ENV_NAME="ComfyUI_${i}"
    ENV_PATH="${BASE_COMFYUI_PATH}/${ENV_NAME}"
    PORT=$((BASE_PORT + i - 1))

    echo -e "${CYAN}Creating environment ${i}/${NUM_ENVS}: ${ENV_NAME} (port: ${PORT})${NC}"

    # Remove existing environment if exists
    if [ -d "${ENV_PATH}" ]; then
        echo -e "${YELLOW}  Removing existing environment...${NC}"
        rm -rf "${ENV_PATH}"
    fi

    # Create new environment by copying reference (excluding .git for efficiency)
    echo -e "  Copying from reference (excluding .git)..."
    mkdir -p "${ENV_PATH}"
    rsync -a --exclude='.git' "${REFERENCE_PATH}/" "${ENV_PATH}/"

    if [ $? -ne 0 ]; then
        echo -e "${RED}✗ Failed to copy reference environment${NC}"
        exit 1
    fi

    # Create custom_nodes directory
    mkdir -p "${ENV_PATH}/custom_nodes"

    # Validate environment (support both old 'front' and new 'app' structures)
    if [ ! -d "${ENV_PATH}/front" ] && [ ! -d "${ENV_PATH}/app" ]; then
        echo -e "${RED}✗ Environment ${i} validation failed: missing frontend directory${NC}"
        exit 1
    fi

    if [ ! -f "${ENV_PATH}/main.py" ]; then
        echo -e "${RED}✗ Environment ${i} validation failed: missing main.py${NC}"
        exit 1
    fi

    echo -e "${GREEN}✓ Environment ${i} created and validated${NC}"
    echo ""
done

# Step 4: Create environment info file
echo -e "${YELLOW}📝 Step 4: Creating environment configuration file...${NC}"

ENV_INFO_FILE="${BASE_COMFYUI_PATH}/parallel_envs.conf"

cat > "${ENV_INFO_FILE}" << EOF
# Parallel Test Environments Configuration
# Generated: $(date)

VENV_PATH="${VENV_PATH}"
BASE_COMFYUI_PATH="${BASE_COMFYUI_PATH}"
COMFYUI_BRANCH="${COMFYUI_BRANCH}"
COMFYUI_COMMIT="${REFERENCE_COMMIT}"
NUM_ENVS=${NUM_ENVS}
BASE_PORT=${BASE_PORT}

# Environment details
EOF

for i in $(seq 1 $NUM_ENVS); do
    ENV_NAME="ComfyUI_${i}"
    ENV_PATH="${BASE_COMFYUI_PATH}/${ENV_NAME}"
    PORT=$((BASE_PORT + i - 1))

    cat >> "${ENV_INFO_FILE}" << EOF
ENV_${i}_NAME="${ENV_NAME}"
ENV_${i}_PATH="${ENV_PATH}"
ENV_${i}_PORT=${PORT}
EOF
done

echo -e "${GREEN}✓ Configuration saved to: ${ENV_INFO_FILE}${NC}"
echo ""

# Final summary
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✅ Parallel Environments Setup Complete!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "Setup Summary:"
echo -e "  Virtual Environment: ${GREEN}${VENV_PATH}${NC}"
echo -e "  Reference ComfyUI: ${GREEN}${REFERENCE_PATH}${NC}"
echo -e "  Branch: ${GREEN}${REFERENCE_BRANCH}${NC}"
echo -e "  Commit: ${GREEN}${REFERENCE_COMMIT:0:8}${NC}"
echo -e "  Number of Environments: ${GREEN}${NUM_ENVS}${NC}"
echo -e "  Port Range: ${GREEN}${BASE_PORT}-$((BASE_PORT + NUM_ENVS - 1))${NC}"
echo ""
echo -e "Parallel Environments:"
for i in $(seq 1 $NUM_ENVS); do
    ENV_NAME="ComfyUI_${i}"
    ENV_PATH="${BASE_COMFYUI_PATH}/${ENV_NAME}"
    PORT=$((BASE_PORT + i - 1))
    echo -e "  ${i}. ${CYAN}${ENV_NAME}${NC} → Port ${GREEN}${PORT}${NC} → ${ENV_PATH}"
done
echo ""
echo -e "Configuration file: ${GREEN}${ENV_INFO_FILE}${NC}"
echo ""
echo -e "To run parallel tests:"
echo -e "  ${CYAN}./run_parallel_tests.sh${NC}"
echo ""
