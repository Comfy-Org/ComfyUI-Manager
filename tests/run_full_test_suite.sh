#!/bin/bash
# Standalone Test Execution Script for ComfyUI Manager
# Can be run outside Claude Code in any session
# Usage: ./tests/run_full_test_suite.sh [OPTIONS]

set -e  # Exit on error

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}ComfyUI Manager Test Suite${NC}"
echo -e "${BLUE}Standalone Execution Script${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Default configuration
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PATH="${VENV_PATH:-$HOME/venv}"
COMFYUI_BRANCH="${COMFYUI_BRANCH:-ltdrdata/dr-support-pip-cm}"
NUM_ENVS="${NUM_ENVS:-10}"
TEST_MODE="${TEST_MODE:-parallel}"  # single or parallel
TEST_TIMEOUT="${TEST_TIMEOUT:-7200}"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --single)
            TEST_MODE="single"
            shift
            ;;
        --parallel)
            TEST_MODE="parallel"
            shift
            ;;
        --envs)
            NUM_ENVS="$2"
            shift 2
            ;;
        --branch)
            COMFYUI_BRANCH="$2"
            shift 2
            ;;
        --venv)
            VENV_PATH="$2"
            shift 2
            ;;
        --timeout)
            TEST_TIMEOUT="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --single              Run tests in single environment (default: parallel)"
            echo "  --parallel            Run tests in parallel across multiple environments"
            echo "  --envs N              Number of parallel environments (default: 10)"
            echo "  --branch BRANCH       ComfyUI branch to use (default: ltdrdata/dr-support-pip-cm)"
            echo "  --venv PATH           Virtual environment path (default: ~/venv)"
            echo "  --timeout SECONDS     Test timeout in seconds (default: 7200)"
            echo "  --help                Show this help message"
            echo ""
            echo "Environment Variables:"
            echo "  PROJECT_ROOT          Project root directory (auto-detected)"
            echo "  VENV_PATH             Virtual environment path"
            echo "  COMFYUI_BRANCH        ComfyUI branch name"
            echo "  NUM_ENVS              Number of parallel environments"
            echo "  TEST_MODE             Test mode (single or parallel)"
            echo "  TEST_TIMEOUT          Test timeout in seconds"
            echo ""
            echo "Examples:"
            echo "  $0                            # Run parallel tests with defaults"
            echo "  $0 --single                   # Run in single environment"
            echo "  $0 --parallel --envs 5        # Run with 5 parallel environments"
            echo "  $0 --branch master            # Use master branch (requires --enable-manager support)"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

echo -e "${CYAN}Configuration:${NC}"
echo -e "  Project Root: ${PROJECT_ROOT}"
echo -e "  Virtual Environment: ${VENV_PATH}"
echo -e "  ComfyUI Branch: ${COMFYUI_BRANCH}"
echo -e "  Test Mode: ${TEST_MODE}"
if [ "$TEST_MODE" = "parallel" ]; then
    echo -e "  Number of Environments: ${NUM_ENVS}"
fi
echo -e "  Test Timeout: ${TEST_TIMEOUT}s"
echo ""

# Change to project root
cd "$PROJECT_ROOT"

# Step 1: Validate virtual environment
echo -e "${YELLOW}Step 1: Validating virtual environment...${NC}"
if [ ! -f "${VENV_PATH}/bin/activate" ]; then
    echo -e "${RED}✗ FATAL: Virtual environment not found at: ${VENV_PATH}${NC}"
    echo -e "${YELLOW}  Create it with: python3 -m venv ${VENV_PATH}${NC}"
    exit 1
fi

source "${VENV_PATH}/bin/activate"
if [ -z "$VIRTUAL_ENV" ]; then
    echo -e "${RED}✗ FATAL: Virtual environment activation failed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Virtual environment activated: ${VIRTUAL_ENV}${NC}"
echo ""

# Step 2: Check prerequisites
echo -e "${YELLOW}Step 2: Checking prerequisites...${NC}"

# Check uv
if ! command -v uv &> /dev/null; then
    echo -e "${YELLOW}⚠ uv not found, installing...${NC}"
    pip install uv
fi
echo -e "${GREEN}✓ uv is available${NC}"

# Check pytest
if ! command -v pytest &> /dev/null; then
    echo -e "${YELLOW}⚠ pytest not found, installing...${NC}"
    uv pip install pytest
fi
echo -e "${GREEN}✓ pytest is available${NC}"
echo ""

# Step 3: Set up test environments
echo -e "${YELLOW}Step 3: Setting up test environment(s)...${NC}"
export COMFYUI_BRANCH="$COMFYUI_BRANCH"

if [ "$TEST_MODE" = "parallel" ]; then
    export NUM_ENVS="$NUM_ENVS"
    if [ ! -f "tests/setup_parallel_test_envs.sh" ]; then
        echo -e "${RED}✗ FATAL: setup_parallel_test_envs.sh not found${NC}"
        exit 1
    fi
    ./tests/setup_parallel_test_envs.sh
else
    if [ ! -f "tests/setup_test_env.sh" ]; then
        echo -e "${RED}✗ FATAL: setup_test_env.sh not found${NC}"
        exit 1
    fi
    ./tests/setup_test_env.sh
fi
echo ""

# Step 4: Run tests
echo -e "${YELLOW}Step 4: Running tests...${NC}"
export TEST_TIMEOUT="$TEST_TIMEOUT"

if [ "$TEST_MODE" = "parallel" ]; then
    if [ ! -f "tests/run_parallel_tests.sh" ]; then
        echo -e "${RED}✗ FATAL: run_parallel_tests.sh not found${NC}"
        exit 1
    fi
    echo -e "${CYAN}Running distributed parallel tests across ${NUM_ENVS} environments...${NC}"
    ./tests/run_parallel_tests.sh
else
    if [ ! -f "tests/run_tests.sh" ]; then
        echo -e "${RED}✗ FATAL: run_tests.sh not found${NC}"
        exit 1
    fi
    echo -e "${CYAN}Running tests in single environment...${NC}"
    ./tests/run_tests.sh
fi

# Step 5: Show results location
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✅ Test Execution Complete!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${CYAN}Test Results Location:${NC}"
if [ "$TEST_MODE" = "parallel" ]; then
    echo -e "  Individual environment logs: ${YELLOW}/tmp/test-results-*.log${NC}"
    echo -e "  Server logs: ${YELLOW}/tmp/comfyui-parallel-*.log${NC}"
    echo -e "  Main execution log: ${YELLOW}/tmp/parallel_test_final.log${NC}"
    echo ""
    echo -e "${CYAN}Quick Result Summary:${NC}"
    if ls /tmp/test-results-*.log 1> /dev/null 2>&1; then
        total_passed=0
        total_failed=0
        for log in /tmp/test-results-*.log; do
            if grep -q "passed" "$log"; then
                passed=$(grep "passed" "$log" | tail -1 | grep -oP '\d+(?= passed)' || echo "0")
                total_passed=$((total_passed + passed))
            fi
            if grep -q "failed" "$log"; then
                failed=$(grep "failed" "$log" | tail -1 | grep -oP '\d+(?= failed)' || echo "0")
                total_failed=$((total_failed + failed))
            fi
        done
        echo -e "  ${GREEN}Passed: ${total_passed}${NC}"
        echo -e "  ${RED}Failed: ${total_failed}${NC}"
    fi
else
    echo -e "  Test results: ${YELLOW}/tmp/comfyui-test-results.log${NC}"
    echo -e "  Server log: ${YELLOW}/tmp/comfyui-server.log${NC}"
fi

echo ""
echo -e "${CYAN}View detailed results:${NC}"
if [ "$TEST_MODE" = "parallel" ]; then
    echo -e "  ${YELLOW}tail -100 /tmp/test-results-1.log${NC}  # View environment 1 results"
    echo -e "  ${YELLOW}grep -E 'passed|failed|ERROR' /tmp/test-results-*.log${NC}  # View all results"
else
    echo -e "  ${YELLOW}tail -100 /tmp/comfyui-test-results.log${NC}"
fi
echo ""
