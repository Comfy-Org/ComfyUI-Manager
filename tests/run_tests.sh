#!/bin/bash
# ComfyUI Manager Test Suite Runner
# Runs the complete test suite with environment validation

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}ComfyUI Manager Test Suite${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Configuration
VENV_PATH="${VENV_PATH:-$HOME/venv}"
COMFYUI_PATH="${COMFYUI_PATH:-tests/env/ComfyUI}"
TEST_SERVER_PORT="${TEST_SERVER_PORT:-8188}"
TEST_TIMEOUT="${TEST_TIMEOUT:-3600}"  # 60 minutes
PYTHON="${VENV_PATH}/bin/python"
PYTEST="${VENV_PATH}/bin/pytest"
PIP="${VENV_PATH}/bin/pip"

# Export environment variables for pytest
export COMFYUI_PATH
export COMFYUI_CUSTOM_NODES_PATH="${COMFYUI_PATH}/custom_nodes"
export TEST_SERVER_PORT

# Function to check if server is running
check_server() {
    curl -s "http://127.0.0.1:${TEST_SERVER_PORT}/system_stats" > /dev/null 2>&1
}

# Function to wait for server to be ready
wait_for_server() {
    local max_wait=60
    local count=0

    echo -e "${YELLOW}⏳ Waiting for ComfyUI server to be ready...${NC}"

    while [ $count -lt $max_wait ]; do
        if check_server; then
            echo -e "${GREEN}✓ Server is ready${NC}"
            return 0
        fi
        sleep 2
        count=$((count + 2))
        echo -n "."
    done

    echo ""
    echo -e "${RED}✗ Server failed to start within ${max_wait} seconds${NC}"
    return 1
}

# Step 0: Validate environment
echo -e "${YELLOW}🔍 Step 0: Validating environment...${NC}"

# Check if virtual environment exists
if [ ! -f "${VENV_PATH}/bin/activate" ]; then
    echo -e "${RED}✗ FATAL: Virtual environment not found${NC}"
    echo -e "${RED}  Expected: ${VENV_PATH}/bin/activate${NC}"
    echo -e "${YELLOW}  Please run setup first:${NC}"
    echo -e "${CYAN}    ./setup_test_env.sh${NC}"
    exit 1
fi

# Activate virtual environment
source "${VENV_PATH}/bin/activate"

# Validate virtual environment is activated
if [ -z "$VIRTUAL_ENV" ]; then
    echo -e "${RED}✗ FATAL: Virtual environment is not activated${NC}"
    echo -e "${RED}  Expected: ${VENV_PATH}${NC}"
    echo -e "${YELLOW}  Please check your virtual environment setup${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Virtual environment activated: ${VIRTUAL_ENV}${NC}"

# Check if ComfyUI exists
if [ ! -d "${COMFYUI_PATH}" ]; then
    echo -e "${RED}✗ FATAL: ComfyUI not found${NC}"
    echo -e "${RED}  Expected: ${COMFYUI_PATH}${NC}"
    echo -e "${YELLOW}  Please run setup first:${NC}"
    echo -e "${CYAN}    ./setup_test_env.sh${NC}"
    exit 1
fi
echo -e "${GREEN}✓ ComfyUI exists: ${COMFYUI_PATH}${NC}"

# Validate ComfyUI frontend directory (support both old 'front' and new 'app' structures)
if [ ! -d "${COMFYUI_PATH}/front" ] && [ ! -d "${COMFYUI_PATH}/app" ]; then
    echo -e "${RED}✗ FATAL: ComfyUI frontend directory not found${NC}"
    echo -e "${RED}  Expected: ${COMFYUI_PATH}/front or ${COMFYUI_PATH}/app${NC}"
    echo -e "${RED}  This directory is required for ComfyUI to run${NC}"
    echo -e "${YELLOW}  Please re-run setup:${NC}"
    echo -e "${CYAN}    rm -rf ${COMFYUI_PATH}${NC}"
    echo -e "${CYAN}    ./setup_test_env.sh${NC}"
    exit 1
fi
if [ -d "${COMFYUI_PATH}/front" ]; then
    echo -e "${GREEN}✓ ComfyUI frontend directory exists (old structure)${NC}"
else
    echo -e "${GREEN}✓ ComfyUI frontend directory exists (new structure)${NC}"
fi

# Validate ComfyUI main.py
if [ ! -f "${COMFYUI_PATH}/main.py" ]; then
    echo -e "${RED}✗ FATAL: ComfyUI main.py not found${NC}"
    echo -e "${RED}  Expected: ${COMFYUI_PATH}/main.py${NC}"
    echo -e "${YELLOW}  Please re-run setup:${NC}"
    echo -e "${CYAN}    ./setup_test_env.sh${NC}"
    exit 1
fi
echo -e "${GREEN}✓ ComfyUI main.py exists${NC}"

# Check pytest availability
if [ ! -f "${PYTEST}" ]; then
    echo -e "${RED}✗ FATAL: pytest not found${NC}"
    echo -e "${RED}  Expected: ${PYTEST}${NC}"
    echo -e "${YELLOW}  Please install test dependencies:${NC}"
    echo -e "${CYAN}    source ${VENV_PATH}/bin/activate${NC}"
    echo -e "${CYAN}    pip install -e \".[dev]\"${NC}"
    exit 1
fi
echo -e "${GREEN}✓ pytest is available${NC}"
echo ""

# Step 1: Clean up old test packages
echo -e "${YELLOW}📦 Step 1: Cleaning up old test packages...${NC}"
rm -rf "${COMFYUI_PATH}/custom_nodes/ComfyUI_SigmoidOffsetScheduler" \
       "${COMFYUI_PATH}/custom_nodes/.disabled"/*[Ss]igmoid* 2>/dev/null || true
echo -e "${GREEN}✓ Cleanup complete${NC}"
echo ""

# Step 2: Clean Python cache
echo -e "${YELLOW}🗑️  Step 2: Cleaning Python cache...${NC}"
find comfyui_manager -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find tests -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
echo -e "${GREEN}✓ Cache cleaned${NC}"
echo ""

# Step 3: Install/reinstall package
echo -e "${YELLOW}📦 Step 3: Installing comfyui-manager package...${NC}"

# Check if uv is available
if command -v uv &> /dev/null; then
    uv pip install .
else
    echo -e "${YELLOW}⚠ uv not found, using pip${NC}"
    "${PIP}" install .
fi
echo -e "${GREEN}✓ Package installed${NC}"
echo ""

# Step 4: Check if server is already running
echo -e "${YELLOW}🔍 Step 4: Checking for running server...${NC}"
if check_server; then
    echo -e "${GREEN}✓ Server already running on port ${TEST_SERVER_PORT}${NC}"
    SERVER_STARTED_BY_SCRIPT=false
else
    echo -e "${YELLOW}Starting ComfyUI server...${NC}"

    # Kill any existing server processes
    pkill -f "ComfyUI/main.py" 2>/dev/null || true
    sleep 2

    # Detect frontend directory (old 'front' or new 'app')
    FRONTEND_ROOT="front"
    if [ ! -d "${COMFYUI_PATH}/front" ] && [ -d "${COMFYUI_PATH}/app" ]; then
        FRONTEND_ROOT="app"
    fi

    # Start server in background
    cd "${COMFYUI_PATH}"
    nohup "${PYTHON}" main.py \
        --enable-manager \
        --enable-compress-response-body \
        --front-end-root "${FRONTEND_ROOT}" \
        --port "${TEST_SERVER_PORT}" \
        > /tmp/comfyui-test-server.log 2>&1 &

    SERVER_PID=$!
    cd - > /dev/null
    SERVER_STARTED_BY_SCRIPT=true

    # Wait for server to be ready
    if ! wait_for_server; then
        echo -e "${RED}✗ Server failed to start${NC}"
        echo -e "${YELLOW}Check logs at: /tmp/comfyui-test-server.log${NC}"
        echo -e "${YELLOW}Last 20 lines of log:${NC}"
        tail -20 /tmp/comfyui-test-server.log
        exit 1
    fi
fi
echo ""

# Step 5: Run tests
echo -e "${YELLOW}🧪 Step 5: Running test suite...${NC}"
echo -e "${BLUE}Running: pytest tests/glob/ tests/test_case_sensitivity_integration.py${NC}"
echo ""

# Run pytest with timeout
TEST_START=$(date +%s)
if timeout "${TEST_TIMEOUT}" "${PYTEST}" \
    tests/glob/ \
    tests/test_case_sensitivity_integration.py \
    -v \
    --tb=short \
    --color=yes; then
    TEST_RESULT=0
else
    TEST_RESULT=$?
fi
TEST_END=$(date +%s)
TEST_DURATION=$((TEST_END - TEST_START))

echo ""
echo -e "${BLUE}========================================${NC}"

# Step 6: Report results
if [ $TEST_RESULT -eq 0 ]; then
    echo -e "${GREEN}✅ All tests PASSED${NC}"
    echo -e "${GREEN}Test duration: ${TEST_DURATION} seconds${NC}"
else
    echo -e "${RED}❌ Tests FAILED${NC}"
    echo -e "${RED}Exit code: ${TEST_RESULT}${NC}"
    echo -e "${YELLOW}Check output above for details${NC}"
fi

echo -e "${BLUE}========================================${NC}"
echo ""

# Step 7: Cleanup if we started the server
if [ "$SERVER_STARTED_BY_SCRIPT" = true ]; then
    echo -e "${YELLOW}🧹 Cleaning up test server...${NC}"
    if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
        kill "$SERVER_PID" 2>/dev/null || true
    fi
    pkill -f "ComfyUI/main.py" 2>/dev/null || true
    echo -e "${GREEN}✓ Server stopped${NC}"
fi

exit $TEST_RESULT
