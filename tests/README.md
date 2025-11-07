# ComfyUI Manager Test Suite

Comprehensive test suite for ComfyUI Manager with parallel execution support.

## Quick Start

### Fastest Way: Automated Testing

```bash
./tests/run_automated_tests.sh
```

**What it does**:
- Cleans environment and stops old processes
- Sets up 10 parallel test environments
- Runs all 43 tests in ~2 minutes
- Generates comprehensive report

**Expected**: 100% pass rate, ~140-160s execution time, 9x+ speedup

### For Claude Code Users

Load the testing prompt:
```
@tests/TESTING_PROMPT.md
```

Claude Code will automatically execute tests and provide intelligent analysis.

## Test Suite Overview

### Coverage (54 Tests)
- **Queue Task API** (8 tests) - Install, uninstall, version switching
- **Version Switching** (19 tests) - CNR↔Nightly, upgrades, downgrades
- **Enable/Disable API** (5 tests) - Package activation
- **Update API** (4 tests) - Package updates
- **Installed API** (4 tests) - Package listing, original case preservation
- **Case Sensitivity** (2 tests) - Case-insensitive lookup, full workflow
- **Complex Scenarios** (12 tests) - Multi-version state, automatic switching

### Performance
- **Execution**: ~140-160s (2.3-2.7 minutes)
- **Parallel**: 10 environments
- **Speedup**: 9x+ vs sequential
- **Load Balance**: 1.2x variance (excellent)

## Manual Execution

### Parallel Testing (Recommended)

```bash
# Setup (one-time)
export NUM_ENVS=10
./tests/setup_parallel_test_envs.sh

# Run tests
./tests/run_parallel_tests.sh
```

### Single Environment Testing

```bash
# Setup
./tests/setup_test_env.sh

# Run tests
cd tests/env
python ComfyUI/main.py --enable-manager &
sleep 20
pytest ../glob/
```

## Adding New Tests

When adding 3+ new tests or modifying test execution time significantly:

```bash
# 1. Write your tests in tests/glob/

# 2. Run tests and check load balance
./tests/run_automated_tests.sh
# Look for "Load Balance: X.XXx variance" in report

# 3. If variance > 2.0x, update durations
./tests/update_test_durations.sh  # Takes ~15-20 min

# 4. Commit duration data
git add .test_durations
git commit -m "chore: update test duration data"
```

**See**: `glob/TESTING_GUIDE.md` for detailed workflow

## Files

- `run_automated_tests.sh` - One-command test execution
- `run_parallel_tests.sh` - Parallel test runner
- `setup_parallel_test_envs.sh` - Environment setup
- `update_test_durations.sh` - Update load balancing data
- `TESTING_PROMPT.md` - Claude Code automation
- `glob/` - Test implementations
- `glob/TESTING_GUIDE.md` - Development workflow guide

## Requirements

- Python 3.12+
- Virtual environment: `/home/rho/venv`
- ComfyUI branch: `ltdrdata/dr-support-pip-cm`
- Ports: 8188-8197 available

## Troubleshooting

### Tests Fail to Start

```bash
# Stop existing processes
pkill -f "ComfyUI/main.py"
sleep 2

# Re-run
./tests/run_automated_tests.sh
```

### Slow Execution

If tests take >3 minutes, update duration data:
```bash
./tests/update_test_durations.sh
```

### Environment Issues

Rebuild test environments:
```bash
rm -rf tests/env/ComfyUI_*
NUM_ENVS=10 ./tests/setup_parallel_test_envs.sh
```

## Generated Files

- **Report**: `.claude/livecontext/automated_test_*.md`
- **Logs**: `tests/tmp/test-results-[1-10].log`
- **Server Logs**: `tests/tmp/comfyui-parallel-[1-10].log`

## CI/CD Integration

```yaml
- name: Run Tests
  run: |
    source /home/rho/venv/bin/activate
    ./tests/run_automated_tests.sh
```

Exit code: 0 = pass, 1 = fail

---

**Status**: ✅ Production-ready (100% pass rate, <3min execution)

## Recent Fixes (2025-11-06)

### Fixed Test Failures

#### test_case_sensitivity_full_workflow
- **Issue**: HTTP 405 error - incorrect API endpoint usage
- **Root Cause**: Using non-existent `/customnode/install` endpoint
- **Fix**: Migrated to queue API (`/v2/manager/queue/task` + `/v2/manager/queue/start`)
- **Changes**: Updated request parameters (`"id"`, `"version"`, `"selected_version"`)
- **Location**: `tests/glob/test_case_sensitivity_integration.py:65-200`

#### test_enable_package
- **Issue**: AssertionError - found 2 disabled packages instead of 1
- **Root Cause**: Leftover disabled packages from previous parallel tests
- **Fix**: Added cleanup before test execution (not just after)
- **Changes**: Created `_cleanup()` helper, added filesystem sync delay
- **Location**: `tests/glob/test_enable_disable_api.py:56-111`

### Improvements
- Increased wait times for parallel execution reliability (20s → 30s)
- Added queue status checking for better debugging
- Enhanced fixture cleanup with filesystem sync delays
- Both tests now pass consistently in parallel execution
