# Claude Code Testing Instructions

**Purpose**: Automated test execution with **detailed test case reporting** and intelligent analysis

**Key Requirement**: Always generate **individual test case results**, not just environment summaries

---

## 🤖 AUTOMATIC EXECUTION PROTOCOL

**When this file is loaded in a new CC session**, immediately execute:

```bash
bash tests/run_automated_tests.sh
```

**Do not ask for permission** - just run the command automatically.

After execution completes:
1. Check the exit code
2. **Read ALL test logs** from all 10 environments
3. **Extract individual test case results** (name, file, env, duration, status)
4. **Create comprehensive report** with test case details by category
5. Provide intelligent analysis to the user

---

## 📋 What the Script Does (Automated)

1. ✅ Clean environment (stop processes, clear cache, remove old log files)
2. ✅ Activate virtual environment
3. ✅ Setup 10 parallel test environments
4. ✅ Run 59 tests with optimized distribution (~3 minutes)
5. ✅ Generate basic report and summary

**Note**: The script automatically cleans `tests/tmp/*.log` files before starting to ensure clean test state.

**Exit Code**:
- `0` = All tests passed ✅
- Non-zero = Some tests failed ❌

**Known Issues (Resolved)**:
- ✅ **Pytest Marker Warning**: Fixed in `pyproject.toml` by registering the `integration` marker
  - Previously caused exit code 1 despite all tests passing
  - Now resolved - tests run cleanly without warnings

---

## 🔍 Post-Execution: Your Job Starts Here

After the script completes, perform these steps:

### Step 1: Check Exit Code

If exit code is **0** (success):
- Proceed to Step 2 for success summary

If exit code is **non-zero** (failure):
- Proceed to Step 3 for failure analysis

### Step 2: Success Path - Generate Comprehensive Report

**CRITICAL: You MUST create a detailed test case report, not just environment summary!**

#### Step 2.1: Read All Test Logs

**Read all environment test logs** to extract individual test case results:
```bash
# Read all 10 environment logs
@tests/tmp/test-results-1.log
@tests/tmp/test-results-2.log
...
@tests/tmp/test-results-10.log
```

#### Step 2.2: Extract Test Case Information

From each log, extract:
- Individual test names (e.g., `test_install_package_via_queue`)
- Test file (e.g., `test_queue_task_api.py`)
- Status (PASSED/FAILED)
- Environment number and port
- Duration (from pytest output)

#### Step 2.3: Create/Update Detailed Report

**Create or update** `.claude/livecontext/automated_test_YYYY-MM-DD_HH-MM-SS.md` with:

1. **Executive Summary** (overview metrics)
2. **Detailed Test Results by Category** - **MOST IMPORTANT**:
   - Group tests by category (Queue Task API, Enable/Disable API, etc.)
   - Create tables with columns: Test Case | Environment | Duration | Status
   - Include coverage description for each category
3. **Test Category Summary** (table with category stats)
4. **Load Balancing Analysis**
5. **Performance Insights**
6. **Configuration Details**

**Example structure**:
```markdown
## Detailed Test Results by Category

### 📦 Queue Task API Tests (8 tests) - All Passed ✅

| Test Case | Environment | Duration | Status |
|-----------|-------------|----------|--------|
| `test_install_package_via_queue` | Env 4 (8191) | ~28s | ✅ PASSED |
| `test_uninstall_package_via_queue` | Env 6 (8193) | ~28s | ✅ PASSED |
| `test_install_uninstall_cycle` | Env 7 (8194) | ~23s | ✅ PASSED |
...

**Coverage**: Package installation, uninstallation, version switching via queue

---

### 🔄 Version Switching Comprehensive Tests (19 tests) - All Passed ✅

| Test Case | Environment | Duration | Status |
|-----------|-------------|----------|--------|
| `test_cnr_to_nightly_switching` | Env 1 (8188) | ~38s | ✅ PASSED |
...
```

#### Step 2.4: Provide User Summary

**After creating the detailed report**, provide user with concise summary:

```markdown
✅ **All 59 tests passed successfully!**

### 📊 Category Breakdown
| Category | Tests | Status |
|----------|-------|--------|
| Version Switching Comprehensive | 19 | ✅ All Passed |
| Complex Scenarios | 12 | ✅ All Passed |
| Queue Task API | 8 | ✅ All Passed |
| Nightly Downgrade/Upgrade | 5 | ✅ All Passed |
| Enable/Disable API | 5 | ✅ All Passed |
| Update API | 4 | ✅ All Passed |
| Installed API (Original Case) | 4 | ✅ All Passed |
| Case Sensitivity Integration | 2 | ✅ All Passed |

### ⚡ Performance
- **Execution time**: 118s (1m 58s)
- **Speedup**: 9.76x vs sequential
- **Load balance**: 1.04x variance (excellent)

### 📁 Generated Files
- **Detailed Report**: `.claude/livecontext/automated_test_YYYY-MM-DD_HH-MM-SS.md`
  - Individual test case results
  - Category-wise breakdown
  - Performance analysis
- **Test Logs**: `tests/tmp/test-results-[1-10].log`

### 🎯 Next Steps
[Based on variance analysis]
```

### Step 3: Failure Path - Intelligent Troubleshooting

**CRITICAL: Create detailed test case report even for failures!**

#### Step 3.1: Read All Test Logs (Including Failed)

**Read all environment test logs** to extract complete test results:
```bash
# Read all 10 environment logs
@tests/tmp/test-results-1.log
@tests/tmp/test-results-2.log
...
@tests/tmp/test-results-10.log
```

#### Step 3.2: Extract All Test Cases

From each log, extract **all tests** (passed and failed):
- Test name, file, environment, duration, status
- For **failed tests**, also extract:
  - Error type (AssertionError, ConnectionError, TimeoutError, etc.)
  - Error message
  - Traceback (last few lines)

#### Step 3.3: Create Comprehensive Report

**Create** `.claude/livecontext/automated_test_YYYY-MM-DD_HH-MM-SS.md` with:

1. **Executive Summary**:
   - Total: 43 tests
   - Passed: X tests
   - Failed: Y tests
   - Pass rate: X%
   - Execution time and speedup

2. **Detailed Test Results by Category** - **MANDATORY**:
   - Group ALL tests by category
   - Mark failed tests with ❌ and error summary
   - Example:
   ```markdown
   ### 📦 Queue Task API Tests (8 tests) - 6 Passed, 2 Failed

   | Test Case | Environment | Duration | Status |
   |-----------|-------------|----------|--------|
   | `test_install_package_via_queue` | Env 4 (8191) | ~28s | ✅ PASSED |
   | `test_version_switch_cnr_to_nightly` | Env 9 (8196) | 60s | ❌ FAILED - Timeout |
   ```

3. **Failed Tests Detailed Analysis**:
   - For each failed test, provide:
     - Test name and file
     - Environment and port
     - Error type and message
     - Relevant traceback excerpt
     - Server log reference

4. **Root Cause Analysis**:
   - Pattern detection across failures
   - Common failure types
   - Likely root causes

5. **Recommended Actions** (specific commands)

#### Step 3.4: Analyze Failure Patterns

**For each failed test**, read server logs if needed:
```
@tests/tmp/comfyui-parallel-N.log
```

**Categorize failures**:
- ❌ **API Error**: Connection refused, timeout, 404/500
- ❌ **Assertion Error**: Expected vs actual mismatch
- ❌ **Setup Error**: Environment configuration issue
- ❌ **Timeout Error**: Test exceeded time limit
- ❌ **Package Error**: Installation/version switching failed

#### Step 3.5: Provide Structured Analysis to User

```markdown
❌ **X tests failed across Y environments**

### 📊 Test Results Summary

| Category | Total | Passed | Failed | Pass Rate |
|----------|-------|--------|--------|-----------|
| Queue Task API | 8 | 6 | 2 | 75% |
| Version Switching | 19 | 17 | 2 | 89% |
| ... | ... | ... | ... | ... |

### ❌ Failed Tests Detail

#### 1. `test_version_switch_cnr_to_nightly` (Env 9, Port 8196)
- **Error Type**: TimeoutError
- **Error Message**: `Server did not respond within 60s`
- **Root Cause**: Likely server startup delay or API timeout
- **Log**: `tests/tmp/test-results-9.log:45`
- **Server Log**: `tests/tmp/comfyui-parallel-9.log`

#### 2. `test_install_package_via_queue` (Env 4, Port 8191)
- **Error Type**: AssertionError
- **Error Message**: `Expected package in installed list`
- **Root Cause**: Package installation failed or API response incomplete
- **Log**: `tests/tmp/test-results-4.log:32`

### 🔍 Root Cause Analysis

**Pattern**: Both failures are in environments with version switching operations
- Likely cause: Server response timeout during complex operations
- Recommendation: Increase timeout or investigate server performance

### 🛠️ Recommended Actions

1. **Check server startup timing**:
   ```bash
   grep "To see the GUI" tests/tmp/comfyui-parallel-{4,9}.log
   ```

2. **Re-run failed tests in isolation**:
   ```bash
   COMFYUI_PATH=tests/env/ComfyUI_9 \
   TEST_SERVER_PORT=8196 \
   pytest tests/glob/test_queue_task_api.py::test_version_switch_cnr_to_nightly -v -s
   ```

3. **If timeout persists, increase timeout in conftest.py**

4. **Full re-test after fixes**:
   ```bash
   ./tests/run_automated_tests.sh
   ```

### 📁 Detailed Logs
- **Full Report**: `.claude/livecontext/automated_test_YYYY-MM-DD_HH-MM-SS.md`
- **Failed Test Logs**:
  - `tests/tmp/test-results-4.log` (line 32)
  - `tests/tmp/test-results-9.log` (line 45)
- **Server Logs**: `tests/tmp/comfyui-parallel-{4,9}.log`
```

### Step 4: Performance Analysis (Both Paths)

**Analyze load balancing from report**:

```markdown
**Load Balancing Analysis**:
- Variance: X.XXx
- Max duration: XXXs (Env N)
- Min duration: XXXs (Env N)
- Assessment: [Excellent <1.2x | Good <2.0x | Poor >2.0x]

[If Poor]
**Optimization Available**:
The current test distribution is not optimal. You can improve execution time by 41% with:
```bash
./tests/update_test_durations.sh  # Takes ~15-20 min
```
This will regenerate timing data for optimal load balancing.
```

---

## 🛠️ Common Troubleshooting Scenarios

### Scenario 1: Server Startup Failures

**Symptoms**: Environment logs show server didn't start

**Check**:
```
@tests/tmp/comfyui-parallel-N.log
```

**Common causes**:
- Port already in use
- Missing dependencies
- ComfyUI branch issues

**Fix**:
```bash
# Clean up ports
pkill -f "ComfyUI/main.py"
sleep 2

# Re-run
./tests/run_automated_tests.sh
```

### Scenario 2: API Connection Failures

**Symptoms**: `Connection refused` or `Timeout` errors

**Analysis checklist**:
1. Was server ready? (Check server log for "To see the GUI" message)
2. Correct port? (8188-8197 for envs 1-10)
3. Request before server ready? (Race condition)

**Fix**: Usually transient - re-run tests

### Scenario 3: Version Switching Failures

**Symptoms**: `test_version_switch_*` failures

**Analysis**:
- Check package installation logs
- Verify `.tracking` file presence (CNR packages)
- Check `.git` directory (nightly packages)

**Fix**:
```bash
# Clean specific package state
rm -rf tests/env/ComfyUI_N/custom_nodes/ComfyUI_SigmoidOffsetScheduler
rm -rf tests/env/ComfyUI_N/custom_nodes/.disabled/*[Ss]igmoid*

# Re-run tests
./tests/run_automated_tests.sh
```

### Scenario 4: Environment-Specific Failures

**Symptoms**: Same test passes in some envs, fails in others

**Analysis**: Setup inconsistency or race condition

**Fix**:
```bash
# Rebuild specific environment
rm -rf tests/env/ComfyUI_N
NUM_ENVS=10 ./tests/setup_parallel_test_envs.sh

# Or rebuild all
rm -rf tests/env/ComfyUI_*
NUM_ENVS=10 ./tests/setup_parallel_test_envs.sh
```

---

## 📊 Report Sections to Analyze

When reading the report, focus on:

1. **Summary Statistics**:
   - Total/passed/failed counts
   - Overall pass rate
   - Execution time

2. **Per-Environment Results**:
   - Which environments failed?
   - Duration variance patterns
   - Test distribution

3. **Performance Metrics**:
   - Load balancing effectiveness
   - Speedup vs sequential
   - Optimization opportunities

4. **Log References**:
   - Where to find detailed logs
   - Which logs to check for failures

---

## 🎯 Your Goal as Claude Code

**Primary**: Generate **detailed test case report** and provide actionable insights

**CRITICAL Requirements**:

1. **Read ALL test logs** (`tests/tmp/test-results-[1-10].log`)
2. **Extract individual test cases** - NOT just environment summaries
3. **Group by category** - Queue Task API, Version Switching, etc.
4. **Create detailed tables** - Test name, environment, duration, status
5. **Include coverage descriptions** - What each category tests

**Success Path**:
- ✅ Detailed test case breakdown by category (tables with all 43 tests)
- ✅ Category summary with test counts
- ✅ Performance metrics and load balancing analysis
- ✅ Concise user-facing summary with highlights
- ✅ Optimization suggestions (if applicable)

**Failure Path**:
- ✅ Detailed test case breakdown (including failed tests with error details)
- ✅ Failed tests analysis section (error type, message, traceback)
- ✅ Root cause analysis with pattern detection
- ✅ Specific remediation commands for each failure
- ✅ Step-by-step verification instructions

**Always**:
- ✅ Read ALL 10 test result logs (not just summary)
- ✅ Create comprehensive `.claude/livecontext/automated_test_*.md` report
- ✅ Include individual test case results in tables
- ✅ Provide context, explanation, and next steps
- ✅ Use markdown formatting for clarity

---

## 📝 Example Output (Success)

```markdown
✅ **All 43 tests passed successfully!**

### 📊 Category Breakdown
| Category | Tests | Status |
|----------|-------|--------|
| Queue Task API | 8 | ✅ All Passed |
| Version Switching | 19 | ✅ All Passed |
| Enable/Disable API | 5 | ✅ All Passed |
| Update API | 4 | ✅ All Passed |
| Installed API | 4 | ✅ All Passed |
| Case Sensitivity | 1 | ✅ Passed |
| Complex Scenarios | 2 | ✅ All Passed |

### ⚡ Performance
- **Execution time**: 118s (1m 58s)
- **Speedup**: 9.76x vs sequential (19.3min → 2.0min)
- **Load balance**: 1.04x variance (excellent)

### 📋 Test Highlights

**Version Switching Comprehensive (19 tests)** - Most comprehensive coverage:
- CNR ↔ Nightly conversion scenarios
- Version upgrades/downgrades (CNR only)
- Fix operations for corrupted packages
- Uninstall scenarios (CNR only, Nightly only, Mixed)
- Reinstall validation and cleanup verification

**Complex Scenarios (12 tests)**:
- Multiple disabled versions (CNR + Nightly)
- Enable operations with multiple disabled versions
- Disable operations with other disabled versions
- Update operations with disabled versions present
- Install operations when other versions exist
- Uninstall operations removing all versions
- Version upgrade chains and switching preservations

**Queue Task API (8 tests)**:
- Package install/uninstall via queue
- Version switching (CNR→Nightly, CNR→CNR)
- Case-insensitive operations
- Multi-task queuing

**Nightly Downgrade/Upgrade (5 tests)** - Git-based version management:
- Downgrade via git reset and upgrade via git pull
- Multiple commit reset and upgrade cycles
- Git pull behavior validation
- Unstaged file handling during reset
- Soft reset with modified files

### 📁 Generated Files
- **Detailed Report**: `.claude/livecontext/automated_test_2025-11-06_11-41-47.md`
  - 59 individual test case results
  - Category-wise breakdown with coverage details
  - Performance metrics and load balancing analysis
- **Test Logs**: `tests/tmp/test-results-[1-10].log`
- **Server Logs**: `tests/tmp/comfyui-parallel-[1-10].log`

### 🎯 Status
No action needed - test infrastructure working optimally!
```

## 📝 Example Output (Failure)

```markdown
❌ **3 tests failed across 2 environments (95% pass rate)**

### 📊 Test Results Summary

| Category | Total | Passed | Failed | Pass Rate |
|----------|-------|--------|--------|-----------|
| Version Switching Comprehensive | 19 | 18 | 1 | 95% |
| Complex Scenarios | 12 | 12 | 0 | 100% |
| Queue Task API | 8 | 6 | 2 | 75% |
| Nightly Downgrade/Upgrade | 5 | 5 | 0 | 100% |
| Enable/Disable API | 5 | 5 | 0 | 100% |
| Update API | 4 | 4 | 0 | 100% |
| Installed API (Original Case) | 4 | 4 | 0 | 100% |
| Case Sensitivity Integration | 2 | 2 | 0 | 100% |
| **TOTAL** | **59** | **56** | **3** | **95%** |

### ❌ Failed Tests Detail

#### 1. `test_version_switch_cnr_to_nightly` (Env 9, Port 8196)
- **Category**: Queue Task API
- **Duration**: 60s (timeout)
- **Error Type**: `requests.exceptions.Timeout`
- **Error Message**: `HTTPConnectionPool(host='127.0.0.1', port=8196): Read timed out.`
- **Root Cause**: Server did not respond within 60s during version switching
- **Recommendation**: Check server performance or increase timeout
- **Logs**:
  - Test: `tests/tmp/test-results-9.log:234-256`
  - Server: `tests/tmp/comfyui-parallel-9.log`

#### 2. `test_install_package_via_queue` (Env 4, Port 8191)
- **Category**: Queue Task API
- **Duration**: 32s
- **Error Type**: `AssertionError`
- **Error Message**: `assert 'ComfyUI_SigmoidOffsetScheduler' in installed_packages`
- **Traceback**:
  ```
  tests/glob/test_queue_task_api.py:145: AssertionError
      assert 'ComfyUI_SigmoidOffsetScheduler' in installed_packages
      E   AssertionError: Package not found in /installed response
  ```
- **Root Cause**: Package installation via queue task succeeded but not reflected in installed list
- **Recommendation**: Verify task completion status and installed API sync
- **Logs**: `tests/tmp/test-results-4.log:98-125`

#### 3. `test_cnr_version_upgrade` (Env 7, Port 8194)
- **Category**: Version Switching
- **Duration**: 28s
- **Error Type**: `AssertionError`
- **Error Message**: `Expected version '1.2.0', got '1.1.0'`
- **Root Cause**: Version upgrade operation completed but version not updated
- **Logs**: `tests/tmp/test-results-7.log:167-189`

### 🔍 Root Cause Analysis

**Common Pattern**: All failures involve package state management
1. **Test 1**: Timeout during version switching → Server performance issue
2. **Test 2**: Installed API not reflecting queue task result → API sync issue
3. **Test 3**: Version upgrade not persisted → Package metadata issue

**Likely Causes**:
- Server performance degradation under load (Test 1)
- Race condition between task completion and API query (Test 2)
- Package metadata cache not invalidated (Test 3)

### 🛠️ Recommended Actions

1. **Verify server health**:
   ```bash
   grep -A 10 "version_switch_cnr_to_nightly" tests/tmp/comfyui-parallel-9.log
   tail -100 tests/tmp/comfyui-parallel-9.log
   ```

2. **Re-run failed tests in isolation**:
   ```bash
   # Test 1
   COMFYUI_PATH=tests/env/ComfyUI_9 TEST_SERVER_PORT=8196 \
     pytest tests/glob/test_queue_task_api.py::test_version_switch_cnr_to_nightly -v -s

   # Test 2
   COMFYUI_PATH=tests/env/ComfyUI_4 TEST_SERVER_PORT=8191 \
     pytest tests/glob/test_queue_task_api.py::test_install_package_via_queue -v -s

   # Test 3
   COMFYUI_PATH=tests/env/ComfyUI_7 TEST_SERVER_PORT=8194 \
     pytest tests/glob/test_version_switching_comprehensive.py::test_cnr_version_upgrade -v -s
   ```

3. **If timeout persists**, increase timeout in `tests/glob/conftest.py`:
   ```python
   DEFAULT_TIMEOUT = 90  # Increase from 60 to 90
   ```

4. **Check for race conditions** - Add delay after queue task completion:
   ```python
   await task_completion()
   time.sleep(2)  # Allow API to sync
   ```

5. **Full re-test** after fixes:
   ```bash
   ./tests/run_automated_tests.sh
   ```

### 📁 Detailed Files
- **Full Report**: `.claude/livecontext/automated_test_2025-11-06_11-41-47.md`
  - All 43 test case results (40 passed, 3 failed)
  - Category breakdown with detailed failure analysis
- **Failed Test Logs**:
  - `tests/tmp/test-results-4.log` (line 98-125)
  - `tests/tmp/test-results-7.log` (line 167-189)
  - `tests/tmp/test-results-9.log` (line 234-256)
- **Server Logs**: `tests/tmp/comfyui-parallel-{4,7,9}.log`
```

---

**Last Updated**: 2025-11-07
**Script Version**: run_automated_tests.sh
**Test Count**: 59 tests across 10 environments
**Documentation**: Updated with all test categories and detailed descriptions

## 📝 Report Requirements Summary

**What MUST be in the report** (`.claude/livecontext/automated_test_*.md`):

1. ✅ **Executive Summary** - Overall metrics (total, passed, failed, pass rate, execution time)
2. ✅ **Detailed Test Results by Category** - **MOST IMPORTANT SECTION**:
   - Group all 59 tests by category (Version Switching, Complex Scenarios, etc.)
   - Create tables: Test Case | Environment | Duration | Status
   - Include coverage description for each category
   - For failures: Add error type, message, traceback excerpt
3. ✅ **Test Category Summary Table** - Category | Total | Passed | Failed | Coverage Areas
4. ✅ **Load Balancing Analysis** - Variance, max/min duration, assessment
5. ✅ **Performance Insights** - Speedup calculation, efficiency metrics
6. ✅ **Configuration Details** - Environment setup, Python version, branch, etc.
7. ✅ **Failed Tests Detailed Analysis** (if applicable) - Per-test error analysis
8. ✅ **Root Cause Analysis** (if applicable) - Pattern detection across failures
9. ✅ **Recommended Actions** (if applicable) - Specific commands to run

**What to show the user** (console output):

1. ✅ **Concise summary** - Pass/fail status, category breakdown table
2. ✅ **Performance highlights** - Execution time, speedup, load balance
3. ✅ **Test highlights** - Key coverage areas with brief descriptions
4. ✅ **Generated files** - Path to detailed report and logs
5. ✅ **Next steps** - Action items or "No action needed"
6. ✅ **Failed tests summary** (if applicable) - Brief error summary with log references

---

## 📚 Test Category Details

### 1. Version Switching Comprehensive (19 tests)
**File**: `tests/glob/test_version_switching_comprehensive.py`

**Coverage**:
- CNR ↔ Nightly bidirectional switching
- CNR version upgrades and downgrades
- Nightly git pull updates
- Package fix operations for corrupted packages
- Uninstall operations (CNR only, Nightly only, Mixed versions)
- Reinstall validation and cleanup verification
- Invalid version error handling
- Same version reinstall skip logic

**Key Tests**:
- `test_reverse_scenario_nightly_cnr_nightly` - Nightly→CNR→Nightly
- `test_forward_scenario_cnr_nightly_cnr` - CNR→Nightly→CNR
- `test_cnr_version_upgrade` - CNR version upgrade
- `test_cnr_version_downgrade` - CNR version downgrade
- `test_fix_cnr_package` - Fix corrupted CNR package
- `test_fix_nightly_package` - Fix corrupted Nightly package

---

### 2. Complex Scenarios (12 tests)
**File**: `tests/glob/test_complex_scenarios.py`

**Coverage**:
- Multiple disabled versions (CNR + Nightly)
- Enable operations with both CNR and Nightly disabled
- Disable operations when other version already disabled
- Update operations with disabled versions present
- Install operations when other versions exist (enabled or disabled)
- Uninstall operations removing all versions
- Version upgrade chains with old version cleanup
- CNR-Nightly switching with preservation of disabled Nightly

**Key Tests**:
- `test_enable_cnr_when_both_disabled` - Enable CNR when both disabled
- `test_enable_nightly_when_both_disabled` - Enable Nightly when both disabled
- `test_update_cnr_with_nightly_disabled` - Update CNR with Nightly disabled
- `test_install_cnr_when_nightly_enabled` - Install CNR when Nightly enabled
- `test_uninstall_removes_all_versions` - Uninstall removes all versions
- `test_cnr_version_upgrade_removes_old` - Old CNR removed after upgrade

---

### 3. Queue Task API (8 tests)
**File**: `tests/glob/test_queue_task_api.py`

**Coverage**:
- Package installation via queue task
- Package uninstallation via queue task
- Install/uninstall cycle validation
- Case-insensitive package operations
- Multiple task queuing
- Version switching via queue (CNR↔Nightly, CNR↔CNR)
- Version switching for disabled packages

**Key Tests**:
- `test_install_package_via_queue` - Install package via queue
- `test_uninstall_package_via_queue` - Uninstall package via queue
- `test_install_uninstall_cycle` - Full install/uninstall cycle
- `test_case_insensitive_operations` - Case-insensitive lookups
- `test_version_switch_cnr_to_nightly` - CNR→Nightly via queue
- `test_version_switch_between_cnr_versions` - CNR→CNR via queue

---

### 4. Nightly Downgrade/Upgrade (5 tests)
**File**: `tests/glob/test_nightly_downgrade_upgrade.py`

**Coverage**:
- Nightly package downgrade via git reset
- Upgrade back to latest via git pull (update operation)
- Multiple commit reset and upgrade cycles
- Git pull behavior validation
- Unstaged file handling during git reset
- Soft reset with modified files

**Key Tests**:
- `test_nightly_downgrade_via_reset_then_upgrade` - Reset and upgrade cycle
- `test_nightly_downgrade_multiple_commits_then_upgrade` - Multiple commit reset
- `test_nightly_verify_git_pull_behavior` - Git pull validation
- `test_nightly_reset_to_first_commit_with_unstaged_files` - Unstaged file handling
- `test_nightly_soft_reset_with_modified_files_then_upgrade` - Soft reset behavior

---

### 5. Enable/Disable API (5 tests)
**File**: `tests/glob/test_enable_disable_api.py`

**Coverage**:
- Package enable operations
- Package disable operations
- Duplicate enable handling (idempotency)
- Duplicate disable handling (idempotency)
- Enable/disable cycle validation

**Key Tests**:
- `test_enable_package` - Enable disabled package
- `test_disable_package` - Disable enabled package
- `test_duplicate_enable` - Enable already enabled package
- `test_duplicate_disable` - Disable already disabled package
- `test_enable_disable_cycle` - Full cycle validation

---

### 6. Update API (4 tests)
**File**: `tests/glob/test_update_api.py`

**Coverage**:
- CNR package update operations
- Nightly package update (git pull)
- Already latest version handling
- Update cycle validation

**Key Tests**:
- `test_update_cnr_package` - Update CNR to latest
- `test_update_nightly_package` - Update Nightly via git pull
- `test_update_already_latest` - No-op when already latest
- `test_update_cycle` - Multiple update operations

---

### 7. Installed API (Original Case) (4 tests)
**File**: `tests/glob/test_installed_api_original_case.py`

**Coverage**:
- Original case preservation in /installed API
- CNR package original case validation
- Nightly package original case validation
- API response structure matching PyPI format

**Key Tests**:
- `test_installed_api_preserves_original_case` - Original case in API response
- `test_cnr_package_original_case` - CNR package case preservation
- `test_nightly_package_original_case` - Nightly package case preservation
- `test_api_response_structure_matches_pypi` - API structure validation

---

### 8. Case Sensitivity Integration (2 tests)
**File**: `tests/glob/test_case_sensitivity_integration.py`

**Coverage**:
- Case-insensitive package lookup
- Full workflow with case variations

**Key Tests**:
- `test_case_insensitive_lookup` - Lookup with different case
- `test_case_sensitivity_full_workflow` - End-to-end case handling

---

## 📊 Test File Summary

| Test File | Tests | Lines | Primary Focus |
|-----------|-------|-------|---------------|
| `test_version_switching_comprehensive.py` | 19 | ~600 | Version management |
| `test_complex_scenarios.py` | 12 | ~450 | Multi-version states |
| `test_queue_task_api.py` | 8 | ~350 | Queue operations |
| `test_nightly_downgrade_upgrade.py` | 5 | ~400 | Git operations |
| `test_enable_disable_api.py` | 5 | ~200 | Enable/disable |
| `test_update_api.py` | 4 | ~180 | Update operations |
| `test_installed_api_original_case.py` | 4 | ~150 | API case handling |
| `test_case_sensitivity_integration.py` | 2 | ~100 | Case integration |
| **TOTAL** | **59** | **~2,430** | **All core features** |
