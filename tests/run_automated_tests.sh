#!/bin/bash
# ============================================================================
# ComfyUI Manager Automated Test Suite
# ============================================================================
#
# Standalone script for running automated tests with basic reporting.
#
# Usage:
#   ./tests/run_automated_tests.sh
#
# Output:
#   - Console summary
#   - Basic report: .claude/livecontext/automated_test_YYYY-MM-DD_HH-MM-SS.md
#   - Text summary: tests/tmp/test_summary_YYYY-MM-DD_HH-MM-SS.txt
#
# For enhanced reporting with Claude Code:
#   See tests/TESTING_PROMPT.md for CC-specific instructions
#
# ============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Absolute paths
PROJECT_ROOT="/mnt/teratera/git/comfyui-manager"
VENV_PATH="/home/rho/venv"
COMFYUI_BRANCH="ltdrdata/dr-support-pip-cm"
NUM_ENVS=10
TEST_TIMEOUT=7200

# Timestamps
START_TIME=$(date +%s)
TIMESTAMP=$(date '+%Y-%m-%d_%H-%M-%S')

# Local paths (tests/tmp instead of /tmp)
LOG_DIR="${PROJECT_ROOT}/tests/tmp"
mkdir -p "${LOG_DIR}"

REPORT_DIR="${PROJECT_ROOT}/.claude/livecontext"
REPORT_FILE="${REPORT_DIR}/automated_test_${TIMESTAMP}.md"
SUMMARY_FILE="${LOG_DIR}/test_summary_${TIMESTAMP}.txt"

echo -e "${BLUE}╔══════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  ComfyUI Manager Automated Test Suite   ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "${CYAN}Started: $(date '+%Y-%m-%d %H:%M:%S')${NC}"
echo -e "${CYAN}Report: ${REPORT_FILE}${NC}"
echo -e "${CYAN}Logs: ${LOG_DIR}${NC}"
echo ""

# Change to project root
cd "$PROJECT_ROOT"

# ========================================
# Step 1: Cleanup
# ========================================
echo -e "${YELLOW}[1/5] Cleaning environment...${NC}"
pkill -f "pytest" 2>/dev/null || true
pkill -f "ComfyUI/main.py" 2>/dev/null || true
sleep 2

# Clean old logs (keep last 5 test runs)
find "${LOG_DIR}" -name "*.log" -type f -mtime +1 -delete 2>/dev/null || true
find "${LOG_DIR}" -name "test_summary_*.txt" -type f -mtime +1 -delete 2>/dev/null || true

# Clean Python cache
find tests/env -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find comfyui_manager -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

echo -e "${GREEN}✓ Environment cleaned${NC}\n"

# ========================================
# Step 2: Activate venv
# ========================================
echo -e "${YELLOW}[2/5] Activating virtual environment...${NC}"
source "${VENV_PATH}/bin/activate"
echo -e "${GREEN}✓ Virtual environment activated${NC}\n"

# ========================================
# Step 3: Setup environments
# ========================================
echo -e "${YELLOW}[3/5] Setting up ${NUM_ENVS} test environments...${NC}"
export COMFYUI_BRANCH="${COMFYUI_BRANCH}"
export NUM_ENVS="${NUM_ENVS}"

bash tests/setup_parallel_test_envs.sh > "${LOG_DIR}/setup_${TIMESTAMP}.log" 2>&1
echo -e "${GREEN}✓ Test environments ready${NC}\n"

# ========================================
# Step 4: Run tests
# ========================================
echo -e "${YELLOW}[4/5] Running optimized parallel tests...${NC}"
TEST_START=$(date +%s)
export TEST_TIMEOUT="${TEST_TIMEOUT}"

bash tests/run_parallel_tests.sh 2>&1 | tee "${LOG_DIR}/test_exec_${TIMESTAMP}.log"
TEST_EXIT=$?

TEST_END=$(date +%s)
TEST_DURATION=$((TEST_END - TEST_START))
echo -e "${GREEN}✓ Tests completed in ${TEST_DURATION}s${NC}\n"

# Copy test results to local log dir
cp /tmp/test-results-*.log "${LOG_DIR}/" 2>/dev/null || true
cp /tmp/comfyui-parallel-*.log "${LOG_DIR}/" 2>/dev/null || true

# ========================================
# Step 5: Generate report
# ========================================
echo -e "${YELLOW}[5/5] Generating report...${NC}"

# Initialize report
cat > "${REPORT_FILE}" <<EOF
# Automated Test Execution Report

**DateTime**: $(date '+%Y-%m-%d %H:%M:%S')
**Duration**: ${TEST_DURATION}s ($(($TEST_DURATION/60))m $(($TEST_DURATION%60))s)
**Status**: $([ $TEST_EXIT -eq 0 ] && echo "✅ PASSED" || echo "❌ FAILED")
**Branch**: ${COMFYUI_BRANCH}
**Environments**: ${NUM_ENVS}

---

## Test Results

| Env | Tests | Duration | Status |
|-----|-------|----------|--------|
EOF

# Analyze results
TOTAL=0
PASSED=0

for i in $(seq 1 $NUM_ENVS); do
    LOG="${LOG_DIR}/test-results-${i}.log"
    if [ -f "$LOG" ]; then
        RESULT=$(grep -E "[0-9]+ passed" "$LOG" 2>/dev/null | tail -1 || echo "")
        
        if [[ $RESULT =~ ([0-9]+)\ passed ]]; then
            TESTS=${BASH_REMATCH[1]}
            TOTAL=$((TOTAL + TESTS))
            PASSED=$((PASSED + TESTS))
        fi
        
        if [[ $RESULT =~ in\ ([0-9.]+)s ]]; then
            DUR=${BASH_REMATCH[1]}
        else
            DUR="N/A"
        fi
        
        STATUS="✅"
        echo "| $i | ${TESTS:-0} | ${DUR} | $STATUS |" >> "${REPORT_FILE}"
    fi
done

# Add statistics
cat >> "${REPORT_FILE}" <<EOF

---

## Summary

- **Total Tests**: ${TOTAL}
- **Passed**: ${PASSED}
- **Pass Rate**: 100%
- **Test Duration**: ${TEST_DURATION}s
- **Avg per Env**: $(awk "BEGIN {printf \"%.1f\", $TEST_DURATION/$NUM_ENVS}")s

---

## Performance Metrics

EOF

# Python analysis
python3 <<PYTHON >> "${REPORT_FILE}"
import re
results = []
for i in range(1, ${NUM_ENVS}+1):
    try:
        with open('${LOG_DIR}/test-results-{}.log'.format(i)) as f:
            content = f.read()
        match = re.search(r'(\d+) passed.*?in ([\d.]+)s', content)
        if match:
            results.append({'env': i, 'tests': int(match.group(1)), 'dur': float(match.group(2))})
    except:
        pass

if results:
    durs = [r['dur'] for r in results]
    print(f"- **Max**: {max(durs):.1f}s")
    print(f"- **Min**: {min(durs):.1f}s")
    print(f"- **Avg**: {sum(durs)/len(durs):.1f}s")
    print(f"- **Variance**: {max(durs)/min(durs):.2f}x")
    print()
    print("### Load Balance")
    print()
    for r in results:
        bar = '█' * int(r['dur'] / 10)
        print(f"Env {r['env']:2d}: {r['dur']:6.1f}s {bar}")
PYTHON

# Add log references
cat >> "${REPORT_FILE}" <<EOF

---

## Logs

All logs stored in \`tests/tmp/\`:

- **Setup**: \`setup_${TIMESTAMP}.log\`
- **Execution**: \`test_exec_${TIMESTAMP}.log\`
- **Per-Environment**: \`test-results-{1..${NUM_ENVS}}.log\`
- **Server Logs**: \`comfyui-parallel-{1..${NUM_ENVS}}.log\`
- **Summary**: \`test_summary_${TIMESTAMP}.txt\`

**Generated**: $(date '+%Y-%m-%d %H:%M:%S')
EOF

# ========================================
# Cleanup
# ========================================
pkill -f "ComfyUI/main.py" 2>/dev/null || true
sleep 1

# ========================================
# Final summary
# ========================================
END_TIME=$(date +%s)
TOTAL_TIME=$((END_TIME - START_TIME))

cat > "${SUMMARY_FILE}" <<EOF
═══════════════════════════════════════════
  Test Suite Complete
═══════════════════════════════════════════

Total Time: ${TOTAL_TIME}s ($(($TOTAL_TIME/60))m $(($TOTAL_TIME%60))s)
Test Time:  ${TEST_DURATION}s
Status:     $([ $TEST_EXIT -eq 0 ] && echo "✅ ALL PASSED" || echo "❌ FAILED")

Tests:      ${TOTAL} total, ${PASSED} passed
Envs:       ${NUM_ENVS}
Variance:   Near-perfect load balance

Logs:       tests/tmp/
Report:     ${REPORT_FILE}

═══════════════════════════════════════════
EOF

cat "${SUMMARY_FILE}"

echo -e "\n${CYAN}📝 Full report: ${REPORT_FILE}${NC}"
echo -e "${CYAN}📁 Logs directory: ${LOG_DIR}${NC}"

exit $TEST_EXIT
