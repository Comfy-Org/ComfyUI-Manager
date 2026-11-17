# pip_util Integration Tests

Real integration tests for `pip_util.py` using actual PyPI packages and pip operations.

## Overview

These tests use a **real isolated venv** to verify pip_util behavior with actual package installations, deletions, and version changes. No mocks - real pip operations only.

## Quick Start

### 1. Setup Test Environment

```bash
cd tests/common/pip_util
./setup_test_env.sh
```

This creates `test_venv/` with base packages:
- urllib3==1.26.15
- certifi==2023.7.22
- charset-normalizer==3.2.0
- colorama==0.4.6
- six==1.16.0
- attrs==23.1.0
- packaging==23.1
- pytest (latest)

### 2. Run Tests

```bash
# Run all integration tests
pytest -v --override-ini="addopts="

# Run specific test
pytest test_dependency_protection.py -v --override-ini="addopts="

# Run with markers
pytest -m integration -v --override-ini="addopts="
```

## Test Architecture

### Real venv Integration

- **No subprocess mocking** - uses real pip install/uninstall
- **Isolated test venv** - prevents system contamination
- **Automatic cleanup** - `reset_test_venv` fixture restores state after each test

### Test Fixtures

**venv Management**:
- `test_venv_path` - Path to test venv (session scope)
- `test_pip_cmd` - pip command for test venv
- `reset_test_venv` - Restore venv to initial state after each test

**Helpers**:
- `get_installed_packages()` - Get current venv packages
- `install_packages(*packages)` - Install packages in test venv
- `uninstall_packages(*packages)` - Uninstall packages in test venv

**Policy Configuration**:
- `temp_policy_dir` - Temporary directory for base policies
- `temp_user_policy_dir` - Temporary directory for user policies
- `mock_manager_util` - Mock manager_util paths to use temp dirs
- `mock_context` - Mock context paths to use temp dirs

## Test Scenarios

### Scenario 1: Dependency Version Protection
**File**: `test_dependency_protection.py::test_dependency_version_protection_with_pin`

**Initial State**:
```python
urllib3==1.26.15
certifi==2023.7.22
charset-normalizer==3.2.0
```

**Action**: Install `requests` with pin_dependencies policy

**Expected Result**:
```python
# Dependencies stay at old versions (protected by pin)
urllib3==1.26.15          # NOT upgraded to 2.x
certifi==2023.7.22        # NOT upgraded
charset-normalizer==3.2.0 # NOT upgraded
requests==2.31.0          # newly installed
```

### Scenario 2: Click-Colorama Dependency Chain
**File**: `test_dependency_protection.py::test_dependency_chain_with_click_colorama`

**Initial State**:
```python
colorama==0.4.6
```

**Action**: Install `click` with force_version + pin_dependencies

**Expected Result**:
```python
colorama==0.4.6  # PINNED
click==8.1.3     # FORCED to specific version
```

### Scenario 3: Package Deletion and Restore
**File**: `test_environment_recovery.py::test_package_deletion_and_restore`

**Initial State**:
```python
six==1.16.0
attrs==23.1.0
packaging==23.1
```

**Action**: Delete `six` → call `batch.ensure_installed()`

**Expected Result**:
```python
six==1.16.0  # RESTORED to required version
```

### Scenario 4: Version Change and Restore
**File**: `test_environment_recovery.py::test_version_change_and_restore`

**Initial State**:
```python
urllib3==1.26.15
```

**Action**: Upgrade `urllib3` to 2.1.0 → call `batch.ensure_installed()`

**Expected Result**:
```python
urllib3==1.26.15  # RESTORED to required version (downgraded)
```

## Test Categories

### Priority 1 (Essential) ✅ ALL PASSING
- ✅ Dependency version protection (enhanced with exact versions)
- ✅ Package deletion and restore (enhanced with exact versions)
- ✅ Version change and restore (enhanced with downgrade verification)
- ✅ Pin only affects specified packages ✨ NEW
- ✅ Major version jump prevention ✨ NEW

### Priority 2 (Important)
- ✅ Complex dependency chains (python-dateutil + six)
- ⏳ Full workflow integration (TODO: update to real venv)
- ⏳ Pin failure retry (TODO: update to real venv)

### Priority 3 (Edge Cases)
- ⏳ Platform conditions (TODO: update to real venv)
- ⏳ Policy priority (TODO: update to real venv)
- ⏳ Unit tests (no venv needed)
- ⏳ Edge cases (no venv needed)

## Package Selection

All test packages are **real PyPI packages < 200KB**:

| Package | Size | Version | Purpose |
|---------|------|---------|---------|
| **urllib3** | ~100KB | 1.26.15 | Protected dependency (prevent 2.x upgrade) |
| **certifi** | ~10KB | 2023.7.22 | SSL certificates (pinned) |
| **charset-normalizer** | ~46KB | 3.2.0 | Charset detection (pinned) |
| **requests** | ~100KB | 2.31.0 | Main package to install |
| **colorama** | ~25KB | 0.4.6 | Terminal colors (pinned) |
| **click** | ~90KB | 8.1.3 | CLI framework (forced version) |
| **six** | ~11KB | 1.16.0 | Python 2/3 compatibility (restore) |
| **attrs** | ~61KB | 23.1.0 | Bystander package |
| **packaging** | ~48KB | 23.1 | Bystander package |

## Cleanup

### Manual Cleanup
```bash
# Remove test venv
rm -rf test_venv/

# Recreate fresh venv
./setup_test_env.sh
```

### Automatic Cleanup
The `reset_test_venv` fixture automatically:
1. Records initial package state
2. Runs test
3. Removes all packages (except pip/setuptools/wheel)
4. Reinstalls initial packages

## Troubleshooting

### Error: "Test venv not found"
**Solution**: Run `./setup_test_env.sh`

### Error: "Package not installed in initial state"
**Solution**: Check `requirements-test-base.txt` and recreate venv

### Tests are slow
**Reason**: Real pip operations take 2-3 seconds per test
**This is expected** - we're doing actual pip install/uninstall

## Implementation Details

### How reset_test_venv Works

```python
@pytest.fixture
def reset_test_venv(test_pip_cmd):
    # 1. Record initial state
    initial = subprocess.run(test_pip_cmd + ["freeze"], ...)

    yield  # Run test here

    # 2. Remove all packages
    current = subprocess.run(test_pip_cmd + ["freeze"], ...)
    subprocess.run(test_pip_cmd + ["uninstall", "-y", ...], ...)

    # 3. Restore initial state
    subprocess.run(test_pip_cmd + ["install", "-r", initial], ...)
```

### How make_pip_cmd is Patched

```python
@pytest.fixture(autouse=True)
def setup_pip_util(monkeypatch, test_pip_cmd):
    from comfyui_manager.common import pip_util

    def make_test_pip_cmd(args: List[str]) -> List[str]:
        return test_pip_cmd + args  # Use test venv pip

    monkeypatch.setattr(
        pip_util.manager_util,
        "make_pip_cmd",
        make_test_pip_cmd
    )
```

## Dependency Analysis Tool

Use `analyze_dependencies.py` to examine package dependencies before adding new tests:

```bash
# Analyze specific package
python analyze_dependencies.py requests

# Analyze all test packages
python analyze_dependencies.py --all

# Show current environment
python analyze_dependencies.py --env
```

**Output includes**:
- Latest available versions
- Dependencies that would be installed
- Version upgrades that would occur
- Impact of pin constraints

**Example output**:
```
📦 Latest version: 2.32.5
🔍 Scenario A: Install without constraints
   Would install 5 packages:
     • urllib3    1.26.15 → 2.5.0    ⚠️ UPGRADE

🔍 Scenario B: Install with pin constraints
   Would install 5 packages:
     • urllib3    1.26.15 (no change) 📌 PINNED

   ✅ Pin prevented 2 upgrade(s)
```

## Test Statistics

**Current Status**: 6 tests, 100% passing

```
test_dependency_version_protection_with_pin       PASSED  (2.28s)
test_dependency_chain_with_six_pin               PASSED  (2.00s)
test_pin_only_affects_specified_packages         PASSED  (2.25s) ✨ NEW
test_major_version_jump_prevention               PASSED  (3.53s) ✨ NEW
test_package_deletion_and_restore                PASSED  (2.25s)
test_version_change_and_restore                  PASSED  (2.24s)

Total: 14.10s
```

**Test Improvements**:
- ✅ All tests verify exact version numbers
- ✅ All tests reference DEPENDENCY_TREE_CONTEXT.md
- ✅ Added 2 new critical tests (pin selectivity, major version prevention)
- ✅ Enhanced error messages with expected vs actual values

## Design Documents

- **TEST_IMPROVEMENTS.md** - Summary of test enhancements based on dependency context
- **DEPENDENCY_TREE_CONTEXT.md** - Verified dependency trees for all test packages
- **DEPENDENCY_ANALYSIS.md** - Dependency analysis methodology
- **CONTEXT_FILES_GUIDE.md** - Guide for using context files
- **TEST_SCENARIOS.md** - Detailed test scenario specifications
- **pip_util.test-design.md** - Test design and architecture
- **pip_util.design.en.md** - pip_util design documentation
