#!/bin/bash
# ComfyUI Manager Parallel Test Runner
# Runs tests in parallel across multiple environments

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}ComfyUI Manager Parallel Test Suite${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Configuration
BASE_COMFYUI_PATH="${BASE_COMFYUI_PATH:-tests/env}"
ENV_INFO_FILE="${BASE_COMFYUI_PATH}/parallel_envs.conf"
TEST_TIMEOUT="${TEST_TIMEOUT:-3600}"  # 60 minutes per environment

# Log directory (project-local instead of /tmp) - use absolute path
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOG_DIR="${PROJECT_ROOT}/tests/tmp"
mkdir -p "${LOG_DIR}"

# Clean old logs from previous runs (clean state guarantee)
rm -f "${LOG_DIR}"/test-results-*.log 2>/dev/null || true
rm -f "${LOG_DIR}"/comfyui-parallel-*.log 2>/dev/null || true
rm -f "${LOG_DIR}"/comfyui-parallel-*.pid 2>/dev/null || true

# Check if parallel environments are set up
if [ ! -f "${ENV_INFO_FILE}" ]; then
    echo -e "${RED}✗ FATAL: Parallel environments not found${NC}"
    echo -e "${RED}  Expected: ${ENV_INFO_FILE}${NC}"
    echo -e "${YELLOW}  Please run setup first:${NC}"
    echo -e "${CYAN}    ./setup_parallel_test_envs.sh${NC}"
    exit 1
fi

# Load configuration
source "${ENV_INFO_FILE}"

echo -e "${CYAN}Configuration:${NC}"
echo -e "  Virtual Environment: ${VENV_PATH}"
echo -e "  Base Path: ${BASE_COMFYUI_PATH}"
echo -e "  Branch: ${COMFYUI_BRANCH}"
echo -e "  Commit: ${COMFYUI_COMMIT:0:8}"
echo -e "  Number of Environments: ${NUM_ENVS}"
echo -e "  Port Range: ${BASE_PORT}-$((BASE_PORT + NUM_ENVS - 1))"
echo ""

# Validate virtual environment
if [ ! -f "${VENV_PATH}/bin/activate" ]; then
    echo -e "${RED}✗ FATAL: Virtual environment not found${NC}"
    echo -e "${RED}  Expected: ${VENV_PATH}${NC}"
    exit 1
fi

source "${VENV_PATH}/bin/activate"

if [ -z "$VIRTUAL_ENV" ]; then
    echo -e "${RED}✗ FATAL: Virtual environment activation failed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Virtual environment activated${NC}"

PYTHON="${VENV_PATH}/bin/python"
PYTEST="${VENV_PATH}/bin/pytest"
PIP="${VENV_PATH}/bin/pip"

# Validate pytest
if [ ! -f "${PYTEST}" ]; then
    echo -e "${RED}✗ FATAL: pytest not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓ pytest is available${NC}"
echo ""

# Step 1: Clean and reinstall package
echo -e "${YELLOW}📦 Step 1: Reinstalling comfyui-manager package and pytest-split...${NC}"

# Clean Python cache
find comfyui_manager -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find tests -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# Reinstall package and pytest-split
if command -v uv &> /dev/null; then
    uv pip install . > /dev/null
    uv pip install pytest-split > /dev/null 2>&1 || echo -e "${YELLOW}⚠ pytest-split installation skipped${NC}"
else
    "${PIP}" install . > /dev/null
    "${PIP}" install pytest-split > /dev/null 2>&1 || echo -e "${YELLOW}⚠ pytest-split installation skipped${NC}"
fi
echo -e "${GREEN}✓ Package installed${NC}"
echo ""

# Function to check if server is running
check_server() {
    local port=$1
    curl -s "http://127.0.0.1:${port}/system_stats" > /dev/null 2>&1
}

# Function to wait for server (2-second intervals with better feedback)
wait_for_server() {
    local port=$1
    local max_wait=60
    local count=0

    while [ $count -lt $max_wait ]; do
        if check_server $port; then
            return 0
        fi
        sleep 2
        count=$((count + 2))
        # Show progress every 6 seconds
        if [ $((count % 6)) -eq 0 ]; then
            echo -ne "."
        fi
    done
    echo ""  # New line after dots
    return 1
}

# Function to start server for an environment
start_server() {
    local env_num=$1
    local env_path_var="ENV_${env_num}_PATH"
    local env_port_var="ENV_${env_num}_PORT"
    local env_path="${!env_path_var}"
    local env_port="${!env_port_var}"

    echo -e "${CYAN}Starting server for environment ${env_num} on port ${env_port}...${NC}"

    # Clean up old test packages
    rm -rf "${env_path}/custom_nodes/ComfyUI_SigmoidOffsetScheduler" \
           "${env_path}/custom_nodes/.disabled"/*[Ss]igmoid* 2>/dev/null || true

    # Kill any existing process on this port
    pkill -f "main.py.*--port ${env_port}" 2>/dev/null || true
    sleep 1

    # Detect frontend directory (old 'front' or new 'app')
    local frontend_root="front"
    if [ ! -d "${env_path}/front" ] && [ -d "${env_path}/app" ]; then
        frontend_root="app"
    fi

    # Start server
    cd "${env_path}"
    nohup "${PYTHON}" main.py \
        --enable-manager \
        --enable-compress-response-body \
        --front-end-root "${frontend_root}" \
        --port "${env_port}" \
        > "${LOG_DIR}/comfyui-parallel-${env_num}.log" 2>&1 &

    local server_pid=$!
    cd - > /dev/null

    # Wait for server to be ready
    if wait_for_server $env_port; then
        echo -e "${GREEN}✓ Server ${env_num} ready on port ${env_port}${NC}"
        echo $server_pid > "${LOG_DIR}/comfyui-parallel-${env_num}.pid"
        return 0
    else
        echo -e "${RED}✗ Server ${env_num} failed to start${NC}"
        return 1
    fi
}

# Function to stop server
stop_server() {
    local env_num=$1
    local pid_file="${LOG_DIR}/comfyui-parallel-${env_num}.pid"
    local env_port_var="ENV_${env_num}_PORT"
    local env_port="${!env_port_var}"

    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
        rm -f "$pid_file"
    fi

    # Kill by port pattern as backup
    pkill -f "main.py.*--port ${env_port}" 2>/dev/null || true
}

# Function to run tests for an environment with test distribution
run_tests_for_env() {
    local env_num=$1
    local env_name_var="ENV_${env_num}_NAME"
    local env_path_var="ENV_${env_num}_PATH"
    local env_port_var="ENV_${env_num}_PORT"
    local env_name="${!env_name_var}"
    local env_path="${!env_path_var}"
    local env_port="${!env_port_var}"

    echo -e "${YELLOW}🧪 Running tests for ${env_name} (port ${env_port}) - Split ${env_num}/${NUM_ENVS}...${NC}"

    # Run tests with environment variables explicitly set
    # Use pytest-split to distribute tests across environments
    # With timing-based distribution for optimal load balancing
    local log_file="${LOG_DIR}/test-results-${env_num}.log"
    if timeout "${TEST_TIMEOUT}" env \
        COMFYUI_PATH="${env_path}" \
        COMFYUI_CUSTOM_NODES_PATH="${env_path}/custom_nodes" \
        TEST_SERVER_PORT="${env_port}" \
        "${PYTEST}" \
        tests/glob/ \
        --splits ${NUM_ENVS} \
        --group ${env_num} \
        --splitting-algorithm=least_duration \
        --durations-path=tests/.test_durations \
        -v \
        --tb=short \
        --color=yes \
        > "$log_file" 2>&1; then
        echo -e "${GREEN}✓ Tests passed for ${env_name} (split ${env_num})${NC}"
        return 0
    else
        local exit_code=$?
        echo -e "${RED}✗ Tests failed for ${env_name} (exit code: ${exit_code})${NC}"
        echo -e "${YELLOW}  See log: ${log_file}${NC}"
        return 1
    fi
}

# Step 2: Start all servers
echo -e "${YELLOW}🚀 Step 2: Starting all servers...${NC}"

declare -a server_pids
all_servers_started=true

for i in $(seq 1 $NUM_ENVS); do
    if ! start_server $i; then
        all_servers_started=false
        echo -e "${RED}✗ Failed to start server ${i}${NC}"
        break
    fi
    echo ""
done

if [ "$all_servers_started" = false ]; then
    echo -e "${RED}✗ Server startup failed, cleaning up...${NC}"
    for i in $(seq 1 $NUM_ENVS); do
        stop_server $i
    done
    exit 1
fi

echo -e "${GREEN}✓ All servers started successfully${NC}"
echo ""

# Step 3: Run tests in parallel
echo -e "${YELLOW}🧪 Step 3: Running tests in parallel...${NC}"
echo ""

declare -a test_pids
declare -a test_results

# Start all test runs in background
for i in $(seq 1 $NUM_ENVS); do
    run_tests_for_env $i &
    test_pids[$i]=$!
done

# Wait for all tests to complete and collect results
for i in $(seq 1 $NUM_ENVS); do
    if wait ${test_pids[$i]}; then
        test_results[$i]=0
    else
        test_results[$i]=1
    fi
done

echo ""

# Step 4: Stop all servers
echo -e "${YELLOW}🧹 Step 4: Stopping all servers...${NC}"

for i in $(seq 1 $NUM_ENVS); do
    stop_server $i
    echo -e "${GREEN}✓ Server ${i} stopped${NC}"
done

echo ""

# Step 5: Report results
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Test Results Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

passed_count=0
failed_count=0

for i in $(seq 1 $NUM_ENVS); do
    env_name_var="ENV_${i}_NAME"
    env_name="${!env_name_var}"
    env_port_var="ENV_${i}_PORT"
    env_port="${!env_port_var}"

    if [ ${test_results[$i]} -eq 0 ]; then
        echo -e "${GREEN}✅ ${env_name} (port ${env_port}): PASSED${NC}"
        passed_count=$((passed_count + 1))
    else
        echo -e "${RED}❌ ${env_name} (port ${env_port}): FAILED${NC}"
        echo -e "${YELLOW}   Log: ${LOG_DIR}/test-results-${i}.log${NC}"
        failed_count=$((failed_count + 1))
    fi
done

echo ""
echo -e "Summary:"
echo -e "  Total Environments: ${NUM_ENVS}"
echo -e "  Passed: ${GREEN}${passed_count}${NC}"
echo -e "  Failed: ${RED}${failed_count}${NC}"
echo ""

if [ $failed_count -eq 0 ]; then
    echo -e "${GREEN}✅ All parallel tests PASSED${NC}"
    exit 0
else
    echo -e "${RED}❌ Some parallel tests FAILED${NC}"
    exit 1
fi
