#!/bin/bash
# ============================================================================
# Test Monitoring Script
# ============================================================================
# Monitors background test execution and reports status/failures
# Usage: ./monitor_test.sh <log_file> <timeout_seconds>
# ============================================================================

set -e

LOG_FILE="${1:-/tmp/test-param-fix.log}"
TIMEOUT="${2:-600}"  # Default 10 minutes
CHECK_INTERVAL=10    # Check every 10 seconds
STALL_THRESHOLD=60   # Consider stalled if no new output for 60 seconds

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Test Monitor Started${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Log File: ${LOG_FILE}${NC}"
echo -e "${BLUE}Timeout: ${TIMEOUT}s${NC}"
echo -e "${BLUE}Stall Threshold: ${STALL_THRESHOLD}s${NC}"
echo ""

START_TIME=$(date +%s)
LAST_SIZE=0
LAST_CHANGE_TIME=$START_TIME
STATUS="running"

while true; do
    CURRENT_TIME=$(date +%s)
    ELAPSED=$((CURRENT_TIME - START_TIME))

    # Check if log file exists
    if [ ! -f "$LOG_FILE" ]; then
        echo -e "${YELLOW}[$(date '+%H:%M:%S')] Waiting for log file...${NC}"
        sleep $CHECK_INTERVAL
        continue
    fi

    # Check file size
    CURRENT_SIZE=$(wc -c < "$LOG_FILE" 2>/dev/null || echo "0")
    TIME_SINCE_CHANGE=$((CURRENT_TIME - LAST_CHANGE_TIME))

    # Check if file size changed (progress)
    if [ "$CURRENT_SIZE" -gt "$LAST_SIZE" ]; then
        LAST_SIZE=$CURRENT_SIZE
        LAST_CHANGE_TIME=$CURRENT_TIME

        # Show latest lines
        echo -e "${GREEN}[$(date '+%H:%M:%S')] Progress detected (${CURRENT_SIZE} bytes, +${ELAPSED}s)${NC}"
        tail -3 "$LOG_FILE" | sed 's/\x1b\[[0-9;]*m//g'  # Remove color codes
        echo ""
    else
        # No progress
        echo -e "${YELLOW}[$(date '+%H:%M:%S')] No change (stalled ${TIME_SINCE_CHANGE}s)${NC}"
    fi

    # Check for completion markers
    if grep -q "✅ ComfyUI_.*: PASSED" "$LOG_FILE" 2>/dev/null || \
       grep -q "❌ ComfyUI_.*: FAILED" "$LOG_FILE" 2>/dev/null || \
       grep -q "Test Suite Complete" "$LOG_FILE" 2>/dev/null; then

        echo -e "${GREEN}========================================${NC}"
        echo -e "${GREEN}Tests Completed!${NC}"
        echo -e "${GREEN}========================================${NC}"

        # Show summary
        grep -E "passed|failed|PASSED|FAILED" "$LOG_FILE" | tail -20

        # Check if tests passed
        if grep -q "❌.*FAILED" "$LOG_FILE" 2>/dev/null; then
            echo -e "${RED}❌ Some tests FAILED${NC}"
            STATUS="failed"
        else
            echo -e "${GREEN}✅ All tests PASSED${NC}"
            STATUS="success"
        fi

        break
    fi

    # Check for errors
    if grep -qi "error\|exception\|traceback" "$LOG_FILE" 2>/dev/null; then
        LAST_ERROR=$(grep -i "error\|exception" "$LOG_FILE" | tail -1)
        echo -e "${RED}[$(date '+%H:%M:%S')] Error detected: ${LAST_ERROR}${NC}"
    fi

    # Check for stall (no progress for STALL_THRESHOLD seconds)
    if [ "$TIME_SINCE_CHANGE" -gt "$STALL_THRESHOLD" ]; then
        echo -e "${RED}========================================${NC}"
        echo -e "${RED}⚠️  Test Execution STALLED${NC}"
        echo -e "${RED}========================================${NC}"
        echo -e "${RED}No progress for ${TIME_SINCE_CHANGE} seconds${NC}"
        echo -e "${RED}Last output:${NC}"
        tail -10 "$LOG_FILE" | sed 's/\x1b\[[0-9;]*m//g'

        STATUS="stalled"
        break
    fi

    # Check for timeout
    if [ "$ELAPSED" -gt "$TIMEOUT" ]; then
        echo -e "${RED}========================================${NC}"
        echo -e "${RED}⏰ Test Execution TIMEOUT${NC}"
        echo -e "${RED}========================================${NC}"
        echo -e "${RED}Exceeded ${TIMEOUT}s timeout${NC}"

        STATUS="timeout"
        break
    fi

    # Wait before next check
    sleep $CHECK_INTERVAL
done

# Final status
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Final Status: ${STATUS}${NC}"
echo -e "${BLUE}Total Time: ${ELAPSED}s${NC}"
echo -e "${BLUE}========================================${NC}"

# Exit with appropriate code
case "$STATUS" in
    "success") exit 0 ;;
    "failed") exit 1 ;;
    "stalled") exit 2 ;;
    "timeout") exit 3 ;;
    *) exit 99 ;;
esac
