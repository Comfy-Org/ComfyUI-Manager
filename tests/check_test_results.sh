#!/bin/bash
# Simple test result checker
# Usage: ./tests/check_test_results.sh [logfile]

LOGFILE=${1:-/tmp/test-param-fix-final.log}

if [ ! -f "$LOGFILE" ]; then
    echo "Log file not found: $LOGFILE"
    exit 1
fi

# Check if tests are complete
if grep -q "Test Results Summary" "$LOGFILE"; then
    echo "========================================="
    echo "Test Results"
    echo "========================================="
    echo ""

    # Show summary
    grep -A 30 "Test Results Summary" "$LOGFILE" | head -40

    echo ""
    echo "========================================="

    # Count passed/failed
    PASSED=$(grep -c "✅.*PASSED" "$LOGFILE")
    FAILED=$(grep -c "❌.*FAILED" "$LOGFILE")

    echo "Environments: Passed=$PASSED, Failed=$FAILED"

else
    echo "Tests still running..."
    echo "Last 10 lines:"
    tail -10 "$LOGFILE"
fi
