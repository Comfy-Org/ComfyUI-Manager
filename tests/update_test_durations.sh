#!/bin/bash
# Update test durations for optimal parallel distribution
# Run this when tests are added/modified/removed

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Test Duration Update${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if virtual environment is activated
if [ -z "$VIRTUAL_ENV" ]; then
    echo -e "${YELLOW}Activating virtual environment...${NC}"
    source ~/venv/bin/activate
fi

# Project root
cd /mnt/teratera/git/comfyui-manager

# Clean up
echo -e "${YELLOW}Cleaning up processes and cache...${NC}"
pkill -f "ComfyUI/main.py" 2>/dev/null || true
sleep 2

find comfyui_manager -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find tests -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# Reinstall package
echo -e "${YELLOW}Reinstalling package...${NC}"
if command -v uv &> /dev/null; then
    uv pip install . > /dev/null
else
    pip install . > /dev/null
fi

# Start test server
echo -e "${YELLOW}Starting test server...${NC}"
cd tests/env/ComfyUI_1

nohup python main.py \
    --enable-manager \
    --enable-compress-response-body \
    --front-end-root front \
    --port 8188 \
    > /tmp/duration-update-server.log 2>&1 &

SERVER_PID=$!
cd - > /dev/null

# Wait for server
echo -e "${YELLOW}Waiting for server to be ready...${NC}"
for i in {1..30}; do
    if curl -s "http://127.0.0.1:8188/system_stats" > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Server ready${NC}"
        break
    fi
    sleep 2
    echo -ne "."
done
echo ""

# Run tests to collect durations
echo -e "${YELLOW}Running tests to collect duration data...${NC}"
echo -e "${YELLOW}This may take 15-20 minutes...${NC}"

pytest tests/glob/ tests/test_case_sensitivity_integration.py \
    --store-durations \
    --durations-path=tests/.test_durations \
    -v \
    --tb=short \
    > /tmp/duration-update.log 2>&1

EXIT_CODE=$?

# Stop server
pkill -f "ComfyUI/main.py" 2>/dev/null || true
sleep 2

if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}✓ Duration data updated successfully${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo -e "Updated file: ${BLUE}tests/.test_durations${NC}"
    echo -e "Test count: $(jq 'length' tests/.test_durations 2>/dev/null || echo 'N/A')"
    echo ""
    echo -e "${YELLOW}Commit the updated .test_durations file:${NC}"
    echo -e "  git add tests/.test_durations"
    echo -e "  git commit -m 'chore: update test duration data'"
else
    echo -e "${RED}✗ Failed to update duration data${NC}"
    echo -e "${YELLOW}Check log: /tmp/duration-update.log${NC}"
    exit 1
fi
