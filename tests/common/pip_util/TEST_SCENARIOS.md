# pip_util Test Scenarios - Test Data Specification

This document precisely defines all test scenarios, packages, versions, and expected behaviors used in the pip_util test suite.

## Table of Contents
1. [Test Scenario 1: Dependency Version Protection](#scenario-1-dependency-version-protection)
2. [Test Scenario 2: Complex Dependency Chain](#scenario-2-complex-dependency-chain)
3. [Test Scenario 3: Package Deletion and Restore](#scenario-3-package-deletion-and-restore)
4. [Test Scenario 4: Version Change and Restore](#scenario-4-version-change-and-restore)
5. [Test Scenario 5: Full Workflow Integration](#scenario-5-full-workflow-integration)
6. [Test Scenario 6: Pin Failure Retry](#scenario-6-pin-failure-retry)

---

## Scenario 1: Dependency Version Protection

**File**: `test_dependency_protection.py::test_dependency_version_protection_with_pin`

**Purpose**: Verify that `pin_dependencies` policy prevents dependency upgrades during package installation.

### Initial Environment State
```python
installed_packages = {
    "urllib3": "1.26.15",          # OLD stable version
    "certifi": "2023.7.22",        # OLD version
    "charset-normalizer": "3.2.0"  # OLD version
}
```

### Policy Configuration
```json
{
  "requests": {
    "apply_all_matches": [
      {
        "type": "pin_dependencies",
        "pinned_packages": ["urllib3", "certifi", "charset-normalizer"],
        "on_failure": "retry_without_pin"
      }
    ]
  }
}
```

### Action
```python
batch.install("requests")
```

### Expected pip Command
```bash
pip install requests urllib3==1.26.15 certifi==2023.7.22 charset-normalizer==3.2.0
```

### Expected Final State
```python
installed_packages = {
    "urllib3": "1.26.15",          # PROTECTED - stayed at old version
    "certifi": "2023.7.22",        # PROTECTED - stayed at old version
    "charset-normalizer": "3.2.0", # PROTECTED - stayed at old version
    "requests": "2.31.0"            # NEWLY installed
}
```

### Without Pin (What Would Happen)
```python
# If pin_dependencies was NOT used:
installed_packages = {
    "urllib3": "2.1.0",            # UPGRADED to 2.x (breaking change)
    "certifi": "2024.2.2",         # UPGRADED to latest
    "charset-normalizer": "3.3.2", # UPGRADED to latest
    "requests": "2.31.0"
}
```

**Key Point**: Pin prevents `urllib3` from upgrading to 2.x, which has breaking API changes.

---

## Scenario 2: Complex Dependency Chain

**File**: `test_dependency_protection.py::test_dependency_chain_with_click_colorama`

**Purpose**: Verify that `force_version` + `pin_dependencies` work together correctly.

### Initial Environment State
```python
installed_packages = {
    "colorama": "0.4.6"  # Existing dependency
}
```

### Policy Configuration
```json
{
  "click": {
    "apply_first_match": [
      {
        "condition": {
          "type": "installed",
          "package": "colorama",
          "spec": "<0.5.0"
        },
        "type": "force_version",
        "version": "8.1.3",
        "reason": "click 8.1.3 compatible with colorama <0.5"
      }
    ],
    "apply_all_matches": [
      {
        "type": "pin_dependencies",
        "pinned_packages": ["colorama"]
      }
    ]
  }
}
```

### Condition Evaluation
```python
# Check: colorama installed AND version < 0.5.0?
colorama_installed = True
colorama_version = "0.4.6"  # 0.4.6 < 0.5.0 → True
# Result: Condition satisfied → apply force_version
```

### Action
```python
batch.install("click")
```

### Expected pip Command
```bash
pip install click==8.1.3 colorama==0.4.6
```

### Expected Final State
```python
installed_packages = {
    "colorama": "0.4.6",  # PINNED - version protected
    "click": "8.1.3"       # FORCED to specific version
}
```

**Key Point**:
- `force_version` forces click to install version 8.1.3
- `pin_dependencies` ensures colorama stays at 0.4.6

---

## Scenario 3: Package Deletion and Restore

**File**: `test_environment_recovery.py::test_package_deletion_and_restore`

**Purpose**: Verify that deleted packages can be restored to required versions.

### Initial Environment State
```python
installed_packages = {
    "six": "1.16.0",        # Critical package
    "attrs": "23.1.0",
    "packaging": "23.1"
}
```

### Policy Configuration
```json
{
  "six": {
    "restore": [
      {
        "target": "six",
        "version": "1.16.0",
        "reason": "six must be maintained at 1.16.0 for compatibility"
      }
    ]
  }
}
```

### Action Sequence

**Step 1**: Install package that removes six
```python
batch.install("python-dateutil")
```

**Step 1 Result**: six is DELETED
```python
installed_packages = {
    # "six": "1.16.0",  # ❌ DELETED by python-dateutil
    "attrs": "23.1.0",
    "packaging": "23.1",
    "python-dateutil": "2.8.2"  # ✅ NEW
}
```

**Step 2**: Restore deleted packages
```python
batch.ensure_installed()
```

**Step 2 Result**: six is RESTORED
```python
installed_packages = {
    "six": "1.16.0",              # ✅ RESTORED to required version
    "attrs": "23.1.0",
    "packaging": "23.1",
    "python-dateutil": "2.8.2"
}
```

### Expected pip Commands
```bash
# Step 1: Install
pip install python-dateutil

# Step 2: Restore
pip install six==1.16.0
```

**Key Point**: `restore` policy automatically reinstalls deleted packages.

---

## Scenario 4: Version Change and Restore

**File**: `test_environment_recovery.py::test_version_change_and_restore`

**Purpose**: Verify that packages with changed versions can be restored to required versions.

### Initial Environment State
```python
installed_packages = {
    "urllib3": "1.26.15",      # OLD version (required)
    "certifi": "2023.7.22"
}
```

### Policy Configuration
```json
{
  "urllib3": {
    "restore": [
      {
        "condition": {
          "type": "installed",
          "spec": "!=1.26.15"
        },
        "target": "urllib3",
        "version": "1.26.15",
        "reason": "urllib3 must be 1.26.15 for compatibility"
      }
    ]
  }
}
```

### Action Sequence

**Step 1**: Install package that upgrades urllib3
```python
batch.install("requests")
```

**Step 1 Result**: urllib3 is UPGRADED
```python
installed_packages = {
    "urllib3": "2.1.0",        # ❌ UPGRADED from 1.26.15 to 2.1.0
    "certifi": "2023.7.22",
    "requests": "2.31.0"       # ✅ NEW
}
```

**Step 2**: Check restore condition
```python
# Condition: urllib3 installed AND version != 1.26.15?
urllib3_version = "2.1.0"
condition_met = (urllib3_version != "1.26.15")  # True
# Result: Restore urllib3 to 1.26.15
```

**Step 2**: Restore to required version
```python
batch.ensure_installed()
```

**Step 2 Result**: urllib3 is DOWNGRADED
```python
installed_packages = {
    "urllib3": "1.26.15",      # ✅ RESTORED to required version
    "certifi": "2023.7.22",
    "requests": "2.31.0"
}
```

### Expected pip Commands
```bash
# Step 1: Install (causes upgrade)
pip install requests

# Step 2: Restore (downgrade)
pip install urllib3==1.26.15
```

**Key Point**: `restore` with condition can revert unwanted version changes.

---

## Scenario 5: Full Workflow Integration

**File**: `test_full_workflow_integration.py::test_uninstall_install_restore_workflow`

**Purpose**: Verify complete workflow: uninstall → install → restore.

### Initial Environment State
```python
installed_packages = {
    "old-package": "1.0.0",        # To be removed
    "critical-package": "1.2.3",   # To be restored
    "urllib3": "1.26.15",
    "certifi": "2023.7.22"
}
```

### Policy Configuration
```json
{
  "old-package": {
    "uninstall": [
      {
        "target": "old-package"
      }
    ]
  },
  "requests": {
    "apply_all_matches": [
      {
        "type": "pin_dependencies",
        "pinned_packages": ["urllib3", "certifi"]
      }
    ]
  },
  "critical-package": {
    "restore": [
      {
        "target": "critical-package",
        "version": "1.2.3"
      }
    ]
  }
}
```

### Action Sequence

**Step 1**: Remove old packages
```python
removed = batch.ensure_not_installed()
```

**Step 1 Result**:
```python
installed_packages = {
    # "old-package": "1.0.0",  # ❌ REMOVED
    "critical-package": "1.2.3",
    "urllib3": "1.26.15",
    "certifi": "2023.7.22"
}
removed = ["old-package"]
```

**Step 2**: Install new package with pins
```python
batch.install("requests")
```

**Step 2 Result**:
```python
installed_packages = {
    "critical-package": "1.2.3",
    "urllib3": "1.26.15",      # PINNED - no upgrade
    "certifi": "2023.7.22",    # PINNED - no upgrade
    "requests": "2.31.0"        # NEW
}
```

**Step 3**: Restore required packages
```python
restored = batch.ensure_installed()
```

**Step 3 Result**:
```python
installed_packages = {
    "critical-package": "1.2.3",  # Still present
    "urllib3": "1.26.15",
    "certifi": "2023.7.22",
    "requests": "2.31.0"
}
restored = []  # Nothing to restore (all present)
```

### Expected pip Commands
```bash
# Step 1: Uninstall
pip uninstall -y old-package

# Step 2: Install with pins
pip install requests urllib3==1.26.15 certifi==2023.7.22

# Step 3: (No command - all packages present)
```

**Key Point**: Complete workflow demonstrates policy coordination.

---

## Scenario 6: Pin Failure Retry

**File**: `test_pin_failure_retry.py::test_pin_failure_retry_without_pin_succeeds`

**Purpose**: Verify automatic retry without pins when installation with pins fails.

### Initial Environment State
```python
installed_packages = {
    "urllib3": "1.26.15",
    "certifi": "2023.7.22"
}
```

### Policy Configuration
```json
{
  "requests": {
    "apply_all_matches": [
      {
        "type": "pin_dependencies",
        "pinned_packages": ["urllib3", "certifi"],
        "on_failure": "retry_without_pin"
      }
    ]
  }
}
```

### Action
```python
batch.install("requests")
```

### Attempt 1: Install WITH pins (FAILS)
```bash
# Command:
pip install requests urllib3==1.26.15 certifi==2023.7.22

# Result: FAILURE (dependency conflict)
# Error: "Package conflict: requests requires urllib3>=2.0"
```

### Attempt 2: Retry WITHOUT pins (SUCCEEDS)
```bash
# Command:
pip install requests

# Result: SUCCESS
```

**Final State**:
```python
installed_packages = {
    "urllib3": "2.1.0",        # UPGRADED (pins removed)
    "certifi": "2024.2.2",     # UPGRADED (pins removed)
    "requests": "2.31.0"        # INSTALLED
}
```

### Expected Behavior
1. **First attempt**: Install with pinned versions
2. **On failure**: Log warning about conflict
3. **Retry**: Install without pins
4. **Success**: Package installed, dependencies upgraded

**Key Point**: `retry_without_pin` provides automatic fallback for compatibility issues.

---

## Scenario 6b: Pin Failure with Hard Fail

**File**: `test_pin_failure_retry.py::test_pin_failure_with_fail_raises_exception`

**Purpose**: Verify that `on_failure: fail` raises exception instead of retrying.

### Initial Environment State
```python
installed_packages = {
    "urllib3": "1.26.15",
    "certifi": "2023.7.22"
}
```

### Policy Configuration
```json
{
  "requests": {
    "apply_all_matches": [
      {
        "type": "pin_dependencies",
        "pinned_packages": ["urllib3", "certifi"],
        "on_failure": "fail"
      }
    ]
  }
}
```

### Action
```python
batch.install("requests")
```

### Attempt 1: Install WITH pins (FAILS)
```bash
# Command:
pip install requests urllib3==1.26.15 certifi==2023.7.22

# Result: FAILURE (dependency conflict)
# Error: "Package conflict: requests requires urllib3>=2.0"
```

### Expected Behavior
1. **First attempt**: Install with pinned versions
2. **On failure**: Raise `subprocess.CalledProcessError`
3. **No retry**: Exception propagates to caller
4. **No changes**: Environment unchanged

**Key Point**: `on_failure: fail` ensures strict version requirements.

---

## Summary Table: All Test Packages

| Package | Initial Version | Action | Final Version | Role |
|---------|----------------|--------|---------------|------|
| **urllib3** | 1.26.15 | Pin | 1.26.15 | Protected dependency |
| **certifi** | 2023.7.22 | Pin | 2023.7.22 | Protected dependency |
| **charset-normalizer** | 3.2.0 | Pin | 3.2.0 | Protected dependency |
| **requests** | (not installed) | Install | 2.31.0 | New package |
| **colorama** | 0.4.6 | Pin | 0.4.6 | Protected dependency |
| **click** | (not installed) | Force version | 8.1.3 | New package with forced version |
| **six** | 1.16.0 | Delete→Restore | 1.16.0 | Deleted then restored |
| **python-dateutil** | (not installed) | Install | 2.8.2 | Package that deletes six |
| **attrs** | 23.1.0 | No change | 23.1.0 | Bystander package |
| **packaging** | 23.1 | No change | 23.1 | Bystander package |

## Policy Types Summary

| Policy Type | Purpose | Example |
|-------------|---------|---------|
| **pin_dependencies** | Prevent dependency upgrades | Keep urllib3 at 1.26.15 |
| **force_version** | Force specific package version | Install click==8.1.3 |
| **restore** | Reinstall deleted/changed packages | Restore six to 1.16.0 |
| **uninstall** | Remove obsolete packages | Remove old-package |
| **on_failure** | Handle installation failures | retry_without_pin or fail |

## Test Data Design Principles

1. **Lightweight Packages**: All packages are <200KB for fast testing
2. **Real Dependencies**: Use actual PyPI package relationships
3. **Version Realism**: Use real version numbers from PyPI
4. **Clear Scenarios**: Each test demonstrates one clear behavior
5. **Reproducible**: Mock ensures consistent behavior across environments
