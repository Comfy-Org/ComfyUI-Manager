# Test Design Document for pip_util.py (TDD)

## 1. Test Strategy Overview

### Testing Philosophy
- **Test-First Approach**: Write tests before implementation
- **Comprehensive Coverage**: Target ≥80% code coverage
- **Isolated Testing**: Each test should be independent and repeatable
- **Clear Assertions**: Each test validates a single behavior
- **Mock External Dependencies**: Isolate unit under test from system calls
- **Environment Isolation**: Use dedicated venv to prevent Python environment corruption

### Test Pyramid Structure
```
        /\
       /  \  E2E Tests (5%)
      /    \ Policy Integration Tests (60%)
     /      \ Unit Tests (35%)
    /________\
```

**Focus**: Policy application behavior rather than JSON format validation

### Test Environment Setup

**⚠️ IMPORTANT: Always use isolated virtual environment for testing**

```bash
# Initial setup (first time only)
cd tests
./setup_test_env.sh

# Activate test environment before running tests
source test_venv/bin/activate

# Run pip_util tests
cd common/pip_util
pytest

# Deactivate when done
deactivate
```

**Why isolated environment?**
- ✅ Prevents test dependencies from corrupting main Python environment
- ✅ Allows safe installation/uninstallation during tests
- ✅ Ensures consistent test results across machines
- ✅ Easy to recreate clean environment

**Test Directory Structure**:
```
tests/                                    # Project-level test directory
├── setup_test_env.sh                    # Automated venv setup script
├── requirements.txt                     # Test-specific dependencies
├── pytest.ini                          # Global pytest configuration
├── README.md                           # Test suite overview
└── common/                             # Tests for comfyui_manager/common/
    └── pip_util/                       # Tests for pip_util.py
        ├── conftest.py                 # pip_util-specific fixtures
        ├── pytest.ini                  # pip_util-specific pytest config
        ├── README.md                   # Detailed test execution guide
        └── test_*.py                   # Actual test files
```

**Test Infrastructure Files**:
- `tests/setup_test_env.sh` - Automated venv setup script
- `tests/requirements.txt` - Test-specific dependencies
- `tests/pytest.ini` - Global pytest configuration
- `tests/common/pip_util/conftest.py` - pip_util test fixtures
- `tests/common/pip_util/pytest.ini` - pip_util coverage settings
- `tests/common/pip_util/README.md` - Detailed execution guide
- `tests/.gitignore` - Exclude venv and artifacts from version control

---

## 2. Unit Tests

### 2.1 Policy Loading Tests (`test_get_pip_policy.py`)

#### Test: `test_get_pip_policy_caching`
**Purpose**: Verify policy is loaded only once and cached

**Setup**:
- Policy file with basic content

**Execution**:
```python
policy1 = get_pip_policy()
policy2 = get_pip_policy()
```

**Assertions**:
- `policy1 is policy2` (same object reference)
- File read operations occur only once (verify with mock)
- Debug log shows "Returning cached pip policy" on second call

**Expected Result**: Policy is cached and reused

---

#### Test: `test_get_pip_policy_user_override_replaces_package`
**Purpose**: Verify user policy completely replaces base policy per package

**Setup**:
- Base policy: `{"numpy": {"apply_first_match": [{"type": "skip"}]}}`
- User policy: `{"numpy": {"apply_first_match": [{"type": "force_version", "version": "1.26.0"}]}}`

**Execution**:
```python
policy = get_pip_policy()
```

**Assertions**:
- `policy["numpy"]["apply_first_match"][0]["type"] == "force_version"`
- Base numpy policy is completely replaced (not merged at section level)

**Expected Result**: User policy completely overrides base policy for numpy

---

### 2.2 Package Spec Parsing Tests (`test_parse_package_spec.py`)

#### Test: `test_parse_package_spec_name_only`
**Purpose**: Parse package name without version

**Execution**:
```python
batch = PipBatch()
name, spec = batch._parse_package_spec("numpy")
```

**Assertions**:
- `name == "numpy"`
- `spec is None`

**Expected Result**: Package name extracted, no version spec

---

#### Test: `test_parse_package_spec_exact_version`
**Purpose**: Parse package with exact version

**Execution**:
```python
name, spec = batch._parse_package_spec("numpy==1.26.0")
```

**Assertions**:
- `name == "numpy"`
- `spec == "==1.26.0"`

**Expected Result**: Name and exact version spec extracted

---

#### Test: `test_parse_package_spec_min_version`
**Purpose**: Parse package with minimum version

**Execution**:
```python
name, spec = batch._parse_package_spec("pandas>=2.0.0")
```

**Assertions**:
- `name == "pandas"`
- `spec == ">=2.0.0"`

**Expected Result**: Name and minimum version spec extracted

---

#### Test: `test_parse_package_spec_max_version`
**Purpose**: Parse package with maximum version

**Execution**:
```python
name, spec = batch._parse_package_spec("scipy<1.10.0")
```

**Assertions**:
- `name == "scipy"`
- `spec == "<1.10.0"`

**Expected Result**: Name and maximum version spec extracted

---

#### Test: `test_parse_package_spec_compatible_version`
**Purpose**: Parse package with compatible version (~=)

**Execution**:
```python
name, spec = batch._parse_package_spec("requests~=2.28")
```

**Assertions**:
- `name == "requests"`
- `spec == "~=2.28"`

**Expected Result**: Name and compatible version spec extracted

---

#### Test: `test_parse_package_spec_hyphenated_name`
**Purpose**: Parse package with hyphens in name

**Execution**:
```python
name, spec = batch._parse_package_spec("scikit-learn>=1.0")
```

**Assertions**:
- `name == "scikit-learn"`
- `spec == ">=1.0"`

**Expected Result**: Hyphenated name correctly parsed

---

#### Test: `test_parse_package_spec_invalid_format`
**Purpose**: Verify ValueError on invalid format

**Execution**:
```python
batch._parse_package_spec("invalid package name!")
```

**Assertions**:
- `ValueError` is raised
- Error message contains "Invalid package spec"

**Expected Result**: ValueError raised for invalid format

---

### 2.3 Condition Evaluation Tests (`test_evaluate_condition.py`)

#### Test: `test_evaluate_condition_none`
**Purpose**: Verify None condition always returns True

**Execution**:
```python
result = batch._evaluate_condition(None, "numpy", {})
```

**Assertions**:
- `result is True`

**Expected Result**: None condition is always satisfied

---

#### Test: `test_evaluate_condition_installed_package_exists`
**Purpose**: Verify installed condition when package exists

**Setup**:
```python
condition = {"type": "installed", "package": "numpy"}
installed = {"numpy": "1.26.0"}
```

**Execution**:
```python
result = batch._evaluate_condition(condition, "numba", installed)
```

**Assertions**:
- `result is True`

**Expected Result**: Condition satisfied when package is installed

---

#### Test: `test_evaluate_condition_installed_package_not_exists`
**Purpose**: Verify installed condition when package doesn't exist

**Setup**:
```python
condition = {"type": "installed", "package": "numpy"}
installed = {}
```

**Execution**:
```python
result = batch._evaluate_condition(condition, "numba", installed)
```

**Assertions**:
- `result is False`

**Expected Result**: Condition not satisfied when package is missing

---

#### Test: `test_evaluate_condition_installed_version_match`
**Purpose**: Verify version spec matching

**Setup**:
```python
condition = {"type": "installed", "package": "numpy", "spec": ">=1.20.0"}
installed = {"numpy": "1.26.0"}
```

**Execution**:
```python
result = batch._evaluate_condition(condition, "numba", installed)
```

**Assertions**:
- `result is True`

**Expected Result**: Condition satisfied when version matches spec

---

#### Test: `test_evaluate_condition_installed_version_no_match`
**Purpose**: Verify version spec not matching

**Setup**:
```python
condition = {"type": "installed", "package": "numpy", "spec": ">=2.0.0"}
installed = {"numpy": "1.26.0"}
```

**Execution**:
```python
result = batch._evaluate_condition(condition, "numba", installed)
```

**Assertions**:
- `result is False`

**Expected Result**: Condition not satisfied when version doesn't match

---

#### Test: `test_evaluate_condition_installed_self_reference`
**Purpose**: Verify self-reference when package field omitted

**Setup**:
```python
condition = {"type": "installed", "spec": ">=1.0.0"}
installed = {"numpy": "1.26.0"}
```

**Execution**:
```python
result = batch._evaluate_condition(condition, "numpy", installed)
```

**Assertions**:
- `result is True`

**Expected Result**: Package name defaults to self when not specified

---

#### Test: `test_evaluate_condition_platform_os_match`
**Purpose**: Verify platform OS condition matching

**Setup**:
```python
condition = {"type": "platform", "os": platform.system().lower()}
```

**Execution**:
```python
result = batch._evaluate_condition(condition, "package", {})
```

**Assertions**:
- `result is True`

**Expected Result**: Condition satisfied when OS matches

---

#### Test: `test_evaluate_condition_platform_os_no_match`
**Purpose**: Verify platform OS condition not matching

**Setup**:
```python
current_os = platform.system().lower()
other_os = "fakeos" if current_os != "fakeos" else "anotherfakeos"
condition = {"type": "platform", "os": other_os}
```

**Execution**:
```python
result = batch._evaluate_condition(condition, "package", {})
```

**Assertions**:
- `result is False`

**Expected Result**: Condition not satisfied when OS doesn't match

---

#### Test: `test_evaluate_condition_platform_gpu_available`
**Purpose**: Verify GPU detection (mock torch.cuda)

**Setup**:
- Mock `torch.cuda.is_available()` to return True
- Condition: `{"type": "platform", "has_gpu": True}`

**Execution**:
```python
result = batch._evaluate_condition(condition, "package", {})
```

**Assertions**:
- `result is True`

**Expected Result**: Condition satisfied when GPU is available

---

#### Test: `test_evaluate_condition_platform_gpu_not_available`
**Purpose**: Verify GPU not available

**Setup**:
- Mock `torch.cuda.is_available()` to return False
- Condition: `{"type": "platform", "has_gpu": True}`

**Execution**:
```python
result = batch._evaluate_condition(condition, "package", {})
```

**Assertions**:
- `result is False`

**Expected Result**: Condition not satisfied when GPU is not available

---

#### Test: `test_evaluate_condition_platform_torch_not_installed`
**Purpose**: Verify behavior when torch is not installed

**Setup**:
- Mock torch import to raise ImportError
- Condition: `{"type": "platform", "has_gpu": True}`

**Execution**:
```python
result = batch._evaluate_condition(condition, "package", {})
```

**Assertions**:
- `result is False`

**Expected Result**: GPU assumed unavailable when torch not installed

---

#### Test: `test_evaluate_condition_unknown_type`
**Purpose**: Verify handling of unknown condition type

**Setup**:
```python
condition = {"type": "unknown_type"}
```

**Execution**:
```python
result = batch._evaluate_condition(condition, "package", {})
```

**Assertions**:
- `result is False`
- Warning log is generated

**Expected Result**: Unknown condition type returns False with warning

---

### 2.4 pip freeze Caching Tests (`test_pip_freeze_cache.py`)

#### Test: `test_refresh_installed_cache_success`
**Purpose**: Verify pip freeze parsing

**Setup**:
- Mock `manager_util.make_pip_cmd()` to return `["pip", "freeze"]`
- Mock `subprocess.run()` to return:
  ```
  numpy==1.26.0
  pandas==2.0.0
  scipy==1.11.0
  ```

**Execution**:
```python
batch._refresh_installed_cache()
```

**Assertions**:
- `batch._installed_cache == {"numpy": "1.26.0", "pandas": "2.0.0", "scipy": "1.11.0"}`
- Debug log shows "Refreshed installed packages cache: 3 packages"

**Expected Result**: Cache populated with parsed packages

---

#### Test: `test_refresh_installed_cache_skip_editable`
**Purpose**: Verify editable packages are skipped

**Setup**:
- Mock subprocess to return:
  ```
  numpy==1.26.0
  -e git+https://github.com/user/repo.git@main#egg=mypackage
  pandas==2.0.0
  ```

**Execution**:
```python
batch._refresh_installed_cache()
```

**Assertions**:
- `"mypackage" not in batch._installed_cache`
- `"numpy" in batch._installed_cache`
- `"pandas" in batch._installed_cache`

**Expected Result**: Editable packages ignored

---

#### Test: `test_refresh_installed_cache_skip_comments`
**Purpose**: Verify comments are skipped

**Setup**:
- Mock subprocess to return:
  ```
  # This is a comment
  numpy==1.26.0
  ## Another comment
  pandas==2.0.0
  ```

**Execution**:
```python
batch._refresh_installed_cache()
```

**Assertions**:
- Cache contains only numpy and pandas
- No comment lines in cache

**Expected Result**: Comments ignored

---

#### Test: `test_refresh_installed_cache_pip_freeze_fails`
**Purpose**: Verify handling of pip freeze failure

**Setup**:
- Mock `subprocess.run()` to raise `CalledProcessError`

**Execution**:
```python
batch._refresh_installed_cache()
```

**Assertions**:
- `batch._installed_cache == {}`
- Warning log is generated

**Expected Result**: Empty cache with warning on failure

---

#### Test: `test_get_installed_packages_lazy_load`
**Purpose**: Verify lazy loading of cache

**Setup**:
- `batch._installed_cache = None`

**Execution**:
```python
packages = batch._get_installed_packages()
```

**Assertions**:
- `_refresh_installed_cache()` is called (verify with mock)
- `packages` contains parsed packages

**Expected Result**: Cache is loaded on first access

---

#### Test: `test_get_installed_packages_use_cache`
**Purpose**: Verify cache is reused

**Setup**:
- `batch._installed_cache = {"numpy": "1.26.0"}`

**Execution**:
```python
packages = batch._get_installed_packages()
```

**Assertions**:
- `_refresh_installed_cache()` is NOT called
- `packages == {"numpy": "1.26.0"}`

**Expected Result**: Existing cache is returned

---

#### Test: `test_invalidate_cache`
**Purpose**: Verify cache invalidation

**Setup**:
- `batch._installed_cache = {"numpy": "1.26.0"}`

**Execution**:
```python
batch._invalidate_cache()
```

**Assertions**:
- `batch._installed_cache is None`

**Expected Result**: Cache is cleared

---

## 3. Policy Application Tests (Integration)

### 3.1 apply_first_match Policy Tests (`test_apply_first_match.py`)

#### Test: `test_skip_policy_blocks_installation`
**Purpose**: Verify skip policy prevents installation

**Setup**:
- Policy: `{"torch": {"apply_first_match": [{"type": "skip", "reason": "Manual CUDA management"}]}}`

**Execution**:
```python
with PipBatch() as batch:
    result = batch.install("torch")
```

**Assertions**:
- `result is False`
- pip install is NOT called
- Info log: "Skipping installation of torch: Manual CUDA management"

**Expected Result**: Installation blocked by skip policy

---

#### Test: `test_force_version_overrides_requested_version`
**Purpose**: Verify force_version changes requested version

**Setup**:
- Policy: `{"numba": {"apply_first_match": [{"type": "force_version", "version": "0.57.0"}]}}`
- Request: `"numba>=0.58"`

**Execution**:
```python
result = batch.install("numba>=0.58")
```

**Assertions**:
- pip install called with "numba==0.57.0" (NOT "numba>=0.58")
- Info log shows forced version

**Expected Result**: Requested version replaced with policy version

---

#### Test: `test_force_version_with_condition_numpy_compatibility`
**Purpose**: Verify conditional force_version for numba/numpy compatibility

**Setup**:
- Policy:
  ```json
  {
    "numba": {
      "apply_first_match": [
        {
          "condition": {"type": "installed", "package": "numpy", "spec": "<2.0.0"},
          "type": "force_version",
          "version": "0.57.0",
          "reason": "numba 0.58+ requires numpy >=2.0.0"
        }
      ]
    }
  }
  ```
- Installed: `{"numpy": "1.26.0"}`

**Execution**:
```python
result = batch.install("numba")
```

**Assertions**:
- Condition satisfied (numpy 1.26.0 < 2.0.0)
- pip install called with "numba==0.57.0"
- Info log shows compatibility reason

**Expected Result**: Compatible numba version installed based on numpy version

---

#### Test: `test_force_version_condition_not_met_uses_default`
**Purpose**: Verify default installation when condition fails

**Setup**:
- Same policy as above
- Installed: `{"numpy": "2.1.0"}`

**Execution**:
```python
result = batch.install("numba")
```

**Assertions**:
- Condition NOT satisfied (numpy 2.1.0 >= 2.0.0)
- pip install called with "numba" (original request, no version forcing)

**Expected Result**: Default installation when condition not met

---

#### Test: `test_replace_PIL_with_Pillow`
**Purpose**: Verify package replacement policy

**Setup**:
- Policy: `{"PIL": {"apply_first_match": [{"type": "replace", "replacement": "Pillow"}]}}`

**Execution**:
```python
result = batch.install("PIL")
```

**Assertions**:
- pip install called with "Pillow" (NOT "PIL")
- Info log: "Replacing PIL with Pillow"

**Expected Result**: Deprecated package replaced with modern alternative

---

#### Test: `test_replace_opencv_to_contrib`
**Purpose**: Verify replacement with version spec

**Setup**:
- Policy: `{"opencv-python": {"apply_first_match": [{"type": "replace", "replacement": "opencv-contrib-python", "version": ">=4.8.0"}]}}`

**Execution**:
```python
result = batch.install("opencv-python")
```

**Assertions**:
- pip install called with "opencv-contrib-python>=4.8.0"

**Expected Result**: Package replaced with enhanced version

---

#### Test: `test_replace_onnxruntime_gpu_on_linux`
**Purpose**: Verify platform-conditional replacement

**Setup**:
- Policy:
  ```json
  {
    "onnxruntime": {
      "apply_first_match": [
        {
          "condition": {"type": "platform", "os": "linux", "has_gpu": true},
          "type": "replace",
          "replacement": "onnxruntime-gpu"
        }
      ]
    }
  }
  ```
- Platform: Linux with GPU

**Execution**:
```python
result = batch.install("onnxruntime")
```

**Assertions**:
- Condition satisfied (Linux + GPU)
- pip install called with "onnxruntime-gpu"

**Expected Result**: GPU version installed on compatible platform

---

#### Test: `test_first_match_only_one_policy_executed`
**Purpose**: Verify only first matching policy is applied

**Setup**:
- Policy with multiple matching conditions:
  ```json
  {
    "pkg": {
      "apply_first_match": [
        {"type": "force_version", "version": "1.0"},
        {"type": "force_version", "version": "2.0"},
        {"type": "skip"}
      ]
    }
  }
  ```

**Execution**:
```python
result = batch.install("pkg")
```

**Assertions**:
- Only first policy applied
- pip install called with "pkg==1.0" (NOT "pkg==2.0")

**Expected Result**: Exclusive execution - first match only

---

#### Test: `test_extra_index_url_from_force_version_policy`
**Purpose**: Verify custom repository URL from policy

**Setup**:
- Policy: `{"pkg": {"apply_first_match": [{"type": "force_version", "version": "1.0", "extra_index_url": "https://custom.repo/simple"}]}}`

**Execution**:
```python
result = batch.install("pkg")
```

**Assertions**:
- pip install called with "--extra-index-url https://custom.repo/simple"

**Expected Result**: Custom repository used from policy

---

### 3.2 apply_all_matches Policy Tests (`test_apply_all_matches.py`)

#### Test: `test_pin_dependencies_prevents_upgrades`
**Purpose**: Verify dependency pinning to current versions

**Setup**:
- Policy:
  ```json
  {
    "new-experimental-pkg": {
      "apply_all_matches": [
        {
          "type": "pin_dependencies",
          "pinned_packages": ["numpy", "pandas", "scipy"]
        }
      ]
    }
  }
  ```
- Installed: `{"numpy": "1.26.0", "pandas": "2.0.0", "scipy": "1.11.0"}`

**Execution**:
```python
result = batch.install("new-experimental-pkg")
```

**Assertions**:
- pip install called with:
  ```
  ["new-experimental-pkg", "numpy==1.26.0", "pandas==2.0.0", "scipy==1.11.0"]
  ```
- Info log shows pinned packages

**Expected Result**: Dependencies pinned to prevent breaking changes

---

#### Test: `test_pin_dependencies_skip_uninstalled_packages`
**Purpose**: Verify pinning only installed packages

**Setup**:
- Policy pins ["numpy", "pandas", "scipy"]
- Installed: `{"numpy": "1.26.0"}` (only numpy installed)

**Execution**:
```python
result = batch.install("new-pkg")
```

**Assertions**:
- pip install called with ["new-pkg", "numpy==1.26.0"]
- pandas and scipy NOT pinned (not installed)
- Warning log for packages that couldn't be pinned

**Expected Result**: Only installed packages pinned

---

#### Test: `test_pin_dependencies_retry_without_pin_on_failure`
**Purpose**: Verify retry logic when pinning causes failure

**Setup**:
- Policy with `on_failure: "retry_without_pin"`
- Mock first install to fail, second to succeed

**Execution**:
```python
result = batch.install("new-pkg")
```

**Assertions**:
- First call: ["new-pkg", "numpy==1.26.0", "pandas==2.0.0"] → fails
- Second call: ["new-pkg"] → succeeds
- Warning log: "Installation failed with pinned dependencies, retrying without pins"
- `result is True`

**Expected Result**: Successful retry without pins

---

#### Test: `test_pin_dependencies_fail_on_failure`
**Purpose**: Verify hard failure when on_failure is "fail"

**Setup**:
- Policy:
  ```json
  {
    "pytorch-addon": {
      "apply_all_matches": [
        {
          "condition": {"type": "installed", "package": "torch", "spec": ">=2.0.0"},
          "type": "pin_dependencies",
          "pinned_packages": ["torch", "torchvision", "torchaudio"],
          "on_failure": "fail"
        }
      ]
    }
  }
  ```
- Installed: `{"torch": "2.1.0", "torchvision": "0.16.0", "torchaudio": "2.1.0"}`
- Mock install to fail

**Execution**:
```python
result = batch.install("pytorch-addon")
```

**Assertions**:
- Exception raised
- No retry attempted
- Error log shows installation failure

**Expected Result**: Hard failure prevents PyTorch ecosystem breakage

---

#### Test: `test_install_with_adds_dependencies`
**Purpose**: Verify additional dependencies are installed together

**Setup**:
- Policy:
  ```json
  {
    "some-ml-package": {
      "apply_all_matches": [
        {
          "condition": {"type": "installed", "package": "transformers", "spec": ">=4.30.0"},
          "type": "install_with",
          "additional_packages": ["accelerate>=0.20.0", "sentencepiece>=0.1.99"]
        }
      ]
    }
  }
  ```
- Installed: `{"transformers": "4.35.0"}`

**Execution**:
```python
result = batch.install("some-ml-package")
```

**Assertions**:
- pip install called with:
  ```
  ["some-ml-package", "accelerate>=0.20.0", "sentencepiece>=0.1.99"]
  ```
- Info log shows additional packages

**Expected Result**: Required dependencies installed together

---

#### Test: `test_warn_policy_logs_and_continues`
**Purpose**: Verify warning policy logs message and continues

**Setup**:
- Policy:
  ```json
  {
    "tensorflow": {
      "apply_all_matches": [
        {
          "condition": {"type": "installed", "package": "torch"},
          "type": "warn",
          "message": "Installing TensorFlow alongside PyTorch may cause CUDA conflicts"
        }
      ]
    }
  }
  ```
- Installed: `{"torch": "2.1.0"}`

**Execution**:
```python
result = batch.install("tensorflow")
```

**Assertions**:
- Warning log shows CUDA conflict message
- Installation proceeds
- `result is True`

**Expected Result**: Warning logged, installation continues

---

#### Test: `test_multiple_apply_all_matches_cumulative`
**Purpose**: Verify all matching policies are applied (not just first)

**Setup**:
- Policy:
  ```json
  {
    "pkg": {
      "apply_all_matches": [
        {"type": "install_with", "additional_packages": ["dep1"]},
        {"type": "install_with", "additional_packages": ["dep2"]},
        {"type": "warn", "message": "Test warning"}
      ]
    }
  }
  ```

**Execution**:
```python
result = batch.install("pkg")
```

**Assertions**:
- ALL policies executed (not just first)
- pip install called with ["pkg", "dep1", "dep2"]
- Warning log present

**Expected Result**: Cumulative application of all matches

---

#### Test: `test_pin_and_install_with_combined`
**Purpose**: Verify pin_dependencies and install_with work together

**Setup**:
- Policy with both pin_dependencies and install_with
- Installed: `{"numpy": "1.26.0"}`

**Execution**:
```python
result = batch.install("pkg")
```

**Assertions**:
- pip install called with:
  ```
  ["pkg", "numpy==1.26.0", "extra-dep"]
  ```

**Expected Result**: Both policies applied together

---

### 3.3 uninstall Policy Tests (`test_uninstall_policy.py`)

#### Test: `test_uninstall_conflicting_package`
**Purpose**: Verify removal of conflicting package

**Setup**:
- Policy:
  ```json
  {
    "some-package": {
      "uninstall": [
        {
          "condition": {"type": "installed", "package": "conflicting-package", "spec": ">=2.0.0"},
          "target": "conflicting-package",
          "reason": "conflicting-package >=2.0.0 conflicts with some-package"
        }
      ]
    }
  }
  ```
- Installed: `{"conflicting-package": "2.1.0"}`

**Execution**:
```python
with PipBatch() as batch:
    removed = batch.ensure_not_installed()
```

**Assertions**:
- `"conflicting-package" in removed`
- pip uninstall called with "-y conflicting-package"
- Info log shows conflict reason
- Package removed from cache

**Expected Result**: Conflicting package removed before installation

---

#### Test: `test_uninstall_unconditional_security_ban`
**Purpose**: Verify unconditional removal of banned package

**Setup**:
- Policy:
  ```json
  {
    "banned-malicious-package": {
      "uninstall": [
        {
          "target": "banned-malicious-package",
          "reason": "Security vulnerability CVE-2024-XXXXX"
        }
      ]
    }
  }
  ```
- Installed: `{"banned-malicious-package": "1.0.0"}`

**Execution**:
```python
removed = batch.ensure_not_installed()
```

**Assertions**:
- Package removed (no condition check)
- Info log shows security reason

**Expected Result**: Banned package always removed

---

#### Test: `test_uninstall_multiple_packages_first_match_per_package`
**Purpose**: Verify first-match-only rule per package

**Setup**:
- Multiple uninstall policies for same package
- All conditions satisfied

**Execution**:
```python
removed = batch.ensure_not_installed()
```

**Assertions**:
- Only first matching policy executed per package
- Package removed only once

**Expected Result**: First match rule enforced

---

#### Test: `test_uninstall_continues_on_individual_failure`
**Purpose**: Verify batch continues on individual removal failure

**Setup**:
- Multiple packages to remove
- One removal fails

**Execution**:
```python
removed = batch.ensure_not_installed()
```

**Assertions**:
- Other packages still processed
- Warning log for failed removal
- Partial success list returned

**Expected Result**: Batch resilience to individual failures

---

### 3.4 restore Policy Tests (`test_restore_policy.py`)

#### Test: `test_restore_missing_critical_package`
**Purpose**: Verify restoration of missing critical package

**Setup**:
- Policy:
  ```json
  {
    "critical-package": {
      "restore": [
        {
          "target": "critical-package",
          "version": "1.2.3",
          "reason": "critical-package must be version 1.2.3"
        }
      ]
    }
  }
  ```
- Installed: `{}` (package not installed)

**Execution**:
```python
with PipBatch() as batch:
    restored = batch.ensure_installed()
```

**Assertions**:
- `"critical-package" in restored`
- pip install called with "critical-package==1.2.3"
- Info log shows restoration reason
- Cache updated with new version

**Expected Result**: Missing critical package restored

---

#### Test: `test_restore_wrong_version_of_critical_package`
**Purpose**: Verify restoration when version is wrong

**Setup**:
- Policy: restore to version 1.2.3
- Installed: `{"critical-package": "1.2.2"}`

**Execution**:
```python
restored = batch.ensure_installed()
```

**Assertions**:
- Package restored to 1.2.3
- Info log shows version mismatch

**Expected Result**: Incorrect version corrected

---

#### Test: `test_restore_conditional_version_check`
**Purpose**: Verify conditional restoration

**Setup**:
- Policy:
  ```json
  {
    "critical-package": {
      "restore": [
        {
          "condition": {"type": "installed", "package": "critical-package", "spec": "!=1.2.3"},
          "target": "critical-package",
          "version": "1.2.3"
        }
      ]
    }
  }
  ```
- Installed: `{"critical-package": "1.2.3"}`

**Execution**:
```python
restored = batch.ensure_installed()
```

**Assertions**:
- `restored == []` (condition not satisfied, version already correct)
- No pip install called

**Expected Result**: No action when version already correct

---

#### Test: `test_restore_with_extra_index_url`
**Purpose**: Verify custom repository for restoration

**Setup**:
- Policy with extra_index_url: "https://custom-repo.example.com/simple"

**Execution**:
```python
restored = batch.ensure_installed()
```

**Assertions**:
- pip install called with "--extra-index-url https://custom-repo.example.com/simple"

**Expected Result**: Custom repository used for restoration

---

#### Test: `test_restore_different_package_target`
**Purpose**: Verify restore can target different package

**Setup**:
- Policy for package A restores package B

**Execution**:
```python
restored = batch.ensure_installed()
```

**Assertions**:
- Package B restored (not A)

**Expected Result**: Cross-package restoration supported

---

### 3.5 ensure_not_installed() Tests (`test_ensure_not_installed.py`)

#### Test: `test_ensure_not_installed_remove_package`
**Purpose**: Remove package matching uninstall policy

**Setup**:
- Policy: `{"pkg": {"uninstall": [{"target": "conflicting-pkg"}]}}`
- Installed: `{"conflicting-pkg": "1.0.0"}`

**Execution**:
```python
removed = batch.ensure_not_installed()
```

**Assertions**:
- `"conflicting-pkg" in removed`
- pip uninstall executed with "-y conflicting-pkg"
- Info log shows removal reason

**Expected Result**: Conflicting package removed

---

#### Test: `test_ensure_not_installed_package_not_installed`
**Purpose**: Skip removal if package not installed

**Setup**:
- Policy: `{"pkg": {"uninstall": [{"target": "missing-pkg"}]}}`
- Installed: `{}`

**Execution**:
```python
removed = batch.ensure_not_installed()
```

**Assertions**:
- `removed == []`
- pip uninstall NOT called

**Expected Result**: No action when package not installed

---

#### Test: `test_ensure_not_installed_condition_satisfied`
**Purpose**: Remove only when condition satisfied

**Setup**:
- Policy with condition requiring numpy>=2.0
- Installed numpy is 1.26.0

**Execution**:
```python
removed = batch.ensure_not_installed()
```

**Assertions**:
- Target package NOT removed (condition failed)
- `removed == []`

**Expected Result**: Condition prevents removal

---

#### Test: `test_ensure_not_installed_first_match_only`
**Purpose**: Execute only first matching policy

**Setup**:
- Multiple uninstall policies for same package
- All conditions satisfied

**Execution**:
```python
removed = batch.ensure_not_installed()
```

**Assertions**:
- Only first policy executed
- Package removed only once

**Expected Result**: First match only

---

#### Test: `test_ensure_not_installed_failure_continues`
**Purpose**: Continue on individual removal failure

**Setup**:
- Multiple packages to remove
- One removal fails

**Execution**:
```python
removed = batch.ensure_not_installed()
```

**Assertions**:
- Other packages still processed
- Warning log for failed removal
- Partial success list returned

**Expected Result**: Failure doesn't stop other removals

---

### 3.6 ensure_installed() Tests (`test_ensure_installed.py`)

#### Test: `test_ensure_installed_restore_missing_package`
**Purpose**: Restore missing package

**Setup**:
- Policy: `{"critical-pkg": {"restore": [{"target": "critical-pkg", "version": "1.0.0"}]}}`
- Installed: `{}`

**Execution**:
```python
restored = batch.ensure_installed()
```

**Assertions**:
- `"critical-pkg" in restored`
- pip install executed with "critical-pkg==1.0.0"
- Info log shows restoration reason

**Expected Result**: Missing package restored

---

#### Test: `test_ensure_installed_restore_wrong_version`
**Purpose**: Restore package with wrong version

**Setup**:
- Policy: `{"pkg": {"restore": [{"target": "pkg", "version": "2.0.0"}]}}`
- Installed: `{"pkg": "1.0.0"}`

**Execution**:
```python
restored = batch.ensure_installed()
```

**Assertions**:
- `"pkg" in restored`
- pip install executed with "pkg==2.0.0"

**Expected Result**: Wrong version replaced

---

#### Test: `test_ensure_installed_skip_correct_version`
**Purpose**: Skip restoration when version is correct

**Setup**:
- Policy: `{"pkg": {"restore": [{"target": "pkg", "version": "1.0.0"}]}}`
- Installed: `{"pkg": "1.0.0"}`

**Execution**:
```python
restored = batch.ensure_installed()
```

**Assertions**:
- `restored == []`
- pip install NOT called

**Expected Result**: No action when version correct

---

#### Test: `test_ensure_installed_with_extra_index_url`
**Purpose**: Use custom repository for restoration

**Setup**:
- Policy with extra_index_url

**Execution**:
```python
restored = batch.ensure_installed()
```

**Assertions**:
- pip install called with `--extra-index-url`

**Expected Result**: Custom repository used

---

#### Test: `test_ensure_installed_condition_check`
**Purpose**: Restore only when condition satisfied

**Setup**:
- Policy with condition
- Condition not met

**Execution**:
```python
restored = batch.ensure_installed()
```

**Assertions**:
- Target package NOT restored
- `restored == []`

**Expected Result**: Condition prevents restoration

---

#### Test: `test_ensure_installed_failure_continues`
**Purpose**: Continue on individual restoration failure

**Setup**:
- Multiple packages to restore
- One restoration fails

**Execution**:
```python
restored = batch.ensure_installed()
```

**Assertions**:
- Other packages still processed
- Warning log for failed restoration
- Partial success list returned

**Expected Result**: Failure doesn't stop other restorations

---

## 4. End-to-End Tests

### 4.1 Complete Workflow Test (`test_e2e_workflow.py`)

#### Test: `test_complete_batch_workflow`
**Purpose**: Test full batch operation sequence

**Setup**:
- Policy with uninstall, install, and restore policies
- Initial installed packages state

**Execution**:
```python
with PipBatch() as batch:
    removed = batch.ensure_not_installed()
    batch.install("numpy>=1.20")
    batch.install("pandas>=2.0")
    restored = batch.ensure_installed()
```

**Assertions**:
- All operations executed in correct order
- Cache invalidated at appropriate times
- Final package state matches expectations

**Expected Result**: Complete workflow succeeds

---

#### Test: `test_context_manager_cleanup`
**Purpose**: Verify context manager cleans up cache

**Execution**:
```python
with PipBatch() as batch:
    batch.install("numpy")
    # Cache exists here
# Cache should be None here
```

**Assertions**:
- Cache is cleared on exit
- No memory leaks

**Expected Result**: Automatic cleanup works

---

## 5. Real Environment Simulation Tests

This section simulates real pip environments to verify that policies work correctly in realistic scenarios.

### 5.1 Initial Environment Setup Tests (`test_environment_setup.py`)

#### Test: `test_preset_packages_installed`
**Purpose**: Simulate environment with pre-installed packages at test start

**Setup**:
```python
# Simulate pre-installed environment with fixture
installed_packages = {
    "numpy": "1.26.0",
    "pandas": "2.0.0",
    "scipy": "1.11.0",
    "torch": "2.1.0",
    "torchvision": "0.16.0"
}
mock_pip_freeze_custom(installed_packages)
```

**Execution**:
```python
with PipBatch() as batch:
    packages = batch._get_installed_packages()
```

**Assertions**:
- `packages == installed_packages`
- All preset packages are recognized

**Expected Result**: Initial environment is accurately simulated

---

### 5.2 Complex Dependency Scenario Tests (`test_complex_dependencies.py`)

#### Test: `test_dependency_version_protection_with_pin`
**Purpose**: Verify existing dependency versions are protected by pin during package installation

**Setup**:
- Policy:
  ```json
  {
    "new-experimental-pkg": {
      "apply_all_matches": [
        {
          "type": "pin_dependencies",
          "pinned_packages": ["numpy", "pandas", "scipy"],
          "on_failure": "retry_without_pin"
        }
      ]
    }
  }
  ```
- Installed: `{"numpy": "1.26.0", "pandas": "2.0.0", "scipy": "1.11.0"}`
- Mock: new-experimental-pkg attempts to upgrade numpy to 2.0.0

**Execution**:
```python
with PipBatch() as batch:
    result = batch.install("new-experimental-pkg")
    final_packages = batch._get_installed_packages()
```

**Assertions**:
- pip install command includes ["new-experimental-pkg", "numpy==1.26.0", "pandas==2.0.0", "scipy==1.11.0"]
- `final_packages["numpy"] == "1.26.0"` (version maintained)
- `final_packages["pandas"] == "2.0.0"` (version maintained)

**Expected Result**: Existing dependency versions are protected by pin

---

#### Test: `test_dependency_chain_with_numba_numpy`
**Purpose**: Verify numba-numpy dependency chain is handled correctly

**Setup**:
- Policy:
  ```json
  {
    "numba": {
      "apply_first_match": [
        {
          "condition": {"type": "installed", "package": "numpy", "spec": "<2.0.0"},
          "type": "force_version",
          "version": "0.57.0"
        }
      ],
      "apply_all_matches": [
        {
          "type": "pin_dependencies",
          "pinned_packages": ["numpy"]
        }
      ]
    }
  }
  ```
- Installed: `{"numpy": "1.26.0"}`

**Execution**:
```python
result = batch.install("numba")
```

**Assertions**:
- Condition evaluation: numpy 1.26.0 < 2.0.0 → True
- force_version applied: changed to numba==0.57.0
- pin_dependencies applied: numpy==1.26.0 added
- pip install command: ["numba==0.57.0", "numpy==1.26.0"]
- numpy version still 1.26.0 after installation

**Expected Result**: Dependency chain is handled correctly

---

### 5.3 Environment Corruption and Recovery Tests (`test_environment_recovery.py`)

#### Test: `test_package_deletion_and_restore`
**Purpose**: Verify critical package deleted by installation is restored by restore policy

**Setup**:
- Policy:
  ```json
  {
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
- Initial installed: `{"critical-package": "1.2.3", "numpy": "1.26.0"}`
- Mock: "breaking-package" installation deletes critical-package

**Execution**:
```python
with PipBatch() as batch:
    # Install breaking-package → critical-package deleted
    batch.install("breaking-package")
    installed_after_install = batch._get_installed_packages()

    # Restore with restore policy
    restored = batch.ensure_installed()
    final_packages = batch._get_installed_packages()
```

**Assertions**:
- `"critical-package" not in installed_after_install` (deletion confirmed)
- `"critical-package" in restored` (included in restore list)
- `final_packages["critical-package"] == "1.2.3"` (restored with correct version)

**Expected Result**: Deleted package is restored by restore policy

---

#### Test: `test_version_change_and_restore`
**Purpose**: Verify package version changed by installation is restored to original version

**Setup**:
- Policy:
  ```json
  {
    "critical-package": {
      "restore": [
        {
          "condition": {"type": "installed", "spec": "!=1.2.3"},
          "target": "critical-package",
          "version": "1.2.3"
        }
      ]
    }
  }
  ```
- Initial: `{"critical-package": "1.2.3"}`
- Mock: "version-changer-package" installation changes critical-package to 2.0.0

**Execution**:
```python
with PipBatch() as batch:
    batch.install("version-changer-package")
    installed_after = batch._get_installed_packages()

    restored = batch.ensure_installed()
    final = batch._get_installed_packages()
```

**Assertions**:
- `installed_after["critical-package"] == "2.0.0"` (changed)
- Condition evaluation: "2.0.0" != "1.2.3" → True
- `"critical-package" in restored`
- `final["critical-package"] == "1.2.3"` (restored)

**Expected Result**: Changed version is restored to original version

---

## 6. Policy Execution Order and Interaction Tests

### 6.1 Full Workflow Integration Tests (`test_full_workflow_integration.py`)

#### Test: `test_uninstall_install_restore_workflow`
**Purpose**: Verify complete uninstall → install → restore workflow

**Setup**:
- Policy:
  ```json
  {
    "target-package": {
      "uninstall": [
        {
          "condition": {"type": "installed", "package": "conflicting-pkg"},
          "target": "conflicting-pkg"
        }
      ],
      "apply_all_matches": [
        {
          "type": "pin_dependencies",
          "pinned_packages": ["numpy", "pandas"]
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
- Initial: `{"conflicting-pkg": "1.0.0", "numpy": "1.26.0", "pandas": "2.0.0", "critical-package": "1.2.3"}`
- Mock: target-package installation deletes critical-package

**Execution**:
```python
with PipBatch() as batch:
    # Step 1: uninstall
    removed = batch.ensure_not_installed()

    # Step 2: install
    result = batch.install("target-package")

    # Step 3: restore
    restored = batch.ensure_installed()
```

**Assertions**:
- Step 1: `"conflicting-pkg" in removed`
- Step 2: pip install ["target-package", "numpy==1.26.0", "pandas==2.0.0"]
- Step 3: `"critical-package" in restored`
- Final state: conflicting-pkg removed, critical-package restored

**Expected Result**: Complete workflow executes in correct order

---

#### Test: `test_cache_invalidation_across_workflow`
**Purpose**: Verify cache is correctly refreshed at each workflow step

**Setup**:
- Policy with uninstall, install, restore

**Execution**:
```python
with PipBatch() as batch:
    cache1 = batch._get_installed_packages()

    removed = batch.ensure_not_installed()
    cache2 = batch._get_installed_packages()  # Should reload

    batch.install("new-package")
    cache3 = batch._get_installed_packages()  # Should reload

    restored = batch.ensure_installed()
    cache4 = batch._get_installed_packages()  # Should reload
```

**Assertions**:
- cache1: Initial state
- cache2: removed packages are gone
- cache3: new-package is added
- cache4: restored packages are added
- Cache is accurately refreshed at each step

**Expected Result**: Cache is correctly updated after each operation

---

### 6.2 Policy Conflict and Priority Tests (`test_policy_conflicts.py`)

#### Test: `test_user_policy_overrides_base_policy`
**Purpose**: Verify user policy completely overwrites base policy

**Setup**:
- Base policy:
  ```json
  {
    "numpy": {
      "apply_first_match": [{"type": "skip"}]
    }
  }
  ```
- User policy:
  ```json
  {
    "numpy": {
      "apply_first_match": [{"type": "force_version", "version": "1.26.0"}]
    }
  }
  ```

**Execution**:
```python
policy = get_pip_policy()
```

**Assertions**:
- `policy["numpy"]["apply_first_match"][0]["type"] == "force_version"`
- Base policy's skip is completely gone (not section-level merge)

**Expected Result**: User policy completely replaces base policy per package

---

#### Test: `test_first_match_stops_at_first_satisfied`
**Purpose**: Verify apply_first_match stops at first satisfied condition

**Setup**:
- Policy:
  ```json
  {
    "pkg": {
      "apply_first_match": [
        {"condition": {"type": "installed", "package": "numpy"}, "type": "force_version", "version": "1.0"},
        {"type": "force_version", "version": "2.0"},
        {"type": "skip"}
      ]
    }
  }
  ```
- Installed: `{"numpy": "1.26.0"}`

**Execution**:
```python
result = batch.install("pkg")
```

**Assertions**:
- First condition satisfied (numpy is installed)
- pip install called with "pkg==1.0" (NOT "pkg==2.0")
- Second and third policies not executed

**Expected Result**: Only first satisfied condition is executed (exclusive)

---

## 7. Failure and Recovery Scenario Tests

### 7.1 Pin Failure and Retry Tests (`test_pin_failure_retry.py`)

#### Test: `test_pin_failure_retry_without_pin_succeeds`
**Purpose**: Verify retry without pin succeeds when installation with pin fails

**Setup**:
- Policy:
  ```json
  {
    "new-pkg": {
      "apply_all_matches": [
        {
          "type": "pin_dependencies",
          "pinned_packages": ["numpy", "pandas"],
          "on_failure": "retry_without_pin"
        }
      ]
    }
  }
  ```
- Installed: `{"numpy": "1.26.0", "pandas": "2.0.0"}`
- Mock subprocess:
  - First install ["new-pkg", "numpy==1.26.0", "pandas==2.0.0"] → fails
  - Second install ["new-pkg"] → succeeds

**Execution**:
```python
result = batch.install("new-pkg")
```

**Assertions**:
- First subprocess call: ["pip", "install", "new-pkg", "numpy==1.26.0", "pandas==2.0.0"]
- First call fails
- Warning log: "Installation failed with pinned dependencies, retrying without pins"
- Second subprocess call: ["pip", "install", "new-pkg"]
- Second call succeeds
- `result is True`

**Expected Result**: Retry without pin succeeds after pin failure

---

#### Test: `test_pin_failure_with_fail_raises_exception`
**Purpose**: Verify exception is raised when on_failure is "fail"

**Setup**:
- Policy:
  ```json
  {
    "pytorch-addon": {
      "apply_all_matches": [
        {
          "condition": {"type": "installed", "package": "torch", "spec": ">=2.0.0"},
          "type": "pin_dependencies",
          "pinned_packages": ["torch", "torchvision", "torchaudio"],
          "on_failure": "fail"
        }
      ]
    }
  }
  ```
- Installed: `{"torch": "2.1.0", "torchvision": "0.16.0", "torchaudio": "2.1.0"}`
- Mock: install fails

**Execution**:
```python
with pytest.raises(Exception):
    batch.install("pytorch-addon")
```

**Assertions**:
- pip install attempted: ["pytorch-addon", "torch==2.1.0", "torchvision==0.16.0", "torchaudio==2.1.0"]
- Installation fails
- Exception raised (no retry)
- Error log recorded

**Expected Result**: Exception raised when on_failure="fail", process stops

---

### 7.2 Partial Failure Handling Tests (`test_partial_failures.py`)

#### Test: `test_ensure_not_installed_continues_on_individual_failure`
**Purpose**: Verify other packages are processed when individual package removal fails

**Setup**:
- Policy:
  ```json
  {
    "pkg-a": {"uninstall": [{"target": "old-pkg-1"}]},
    "pkg-b": {"uninstall": [{"target": "old-pkg-2"}]},
    "pkg-c": {"uninstall": [{"target": "old-pkg-3"}]}
  }
  ```
- Installed: `{"old-pkg-1": "1.0", "old-pkg-2": "1.0", "old-pkg-3": "1.0"}`
- Mock: old-pkg-2 removal fails

**Execution**:
```python
removed = batch.ensure_not_installed()
```

**Assertions**:
- old-pkg-1 removal attempted → success
- old-pkg-2 removal attempted → failure → Warning log
- old-pkg-3 removal attempted → success
- `removed == ["old-pkg-1", "old-pkg-3"]`

**Expected Result**: Individual failure doesn't stop entire process

---

#### Test: `test_ensure_installed_continues_on_individual_failure`
**Purpose**: Verify other packages are processed when individual package restoration fails

**Setup**:
- Policy with 3 restore policies
- Mock: Second restore fails

**Execution**:
```python
restored = batch.ensure_installed()
```

**Assertions**:
- First restore succeeds
- Second restore fails → Warning log
- Third restore succeeds
- `restored == ["pkg-1", "pkg-3"]`

**Expected Result**: Individual failure doesn't prevent other restores

---

## 8. Edge Cases and Boundary Condition Tests

### 8.1 Empty Policy Handling Tests (`test_empty_policies.py`)

#### Test: `test_empty_base_policy_uses_default_installation`
**Purpose**: Verify default installation behavior when base policy is empty

**Setup**:
- Base policy: `{}`
- User policy: `{}`

**Execution**:
```python
policy = get_pip_policy()
result = batch.install("numpy")
```

**Assertions**:
- `policy == {}`
- pip install called with ["numpy"] (no policy applied)
- `result is True`

**Expected Result**: Falls back to default installation when policy is empty

---

#### Test: `test_package_without_policy_default_installation`
**Purpose**: Verify package without policy is installed with default behavior

**Setup**:
- Policy: `{"numpy": {...}}` (no policy for pandas)

**Execution**:
```python
result = batch.install("pandas")
```

**Assertions**:
- pip install called with ["pandas"]
- No policy evaluation
- `result is True`

**Expected Result**: Package without policy is installed as-is

---

### 8.2 Malformed Policy Handling Tests (`test_malformed_policies.py`)

#### Test: `test_json_parse_error_fallback_to_empty`
**Purpose**: Verify empty dictionary is returned on JSON parse error

**Setup**:
- Base policy file: Malformed JSON (syntax error)

**Execution**:
```python
policy = get_pip_policy()
```

**Assertions**:
- Error log: "Failed to parse pip-policy.json"
- `policy == {}`

**Expected Result**: Empty dictionary returned on parse error

---

#### Test: `test_unknown_condition_type_returns_false`
**Purpose**: Verify False is returned for unknown condition type

**Setup**:
```python
condition = {"type": "unknown_type", "some_field": "value"}
```

**Execution**:
```python
result = batch._evaluate_condition(condition, "pkg", {})
```

**Assertions**:
- `result is False`
- Warning log: "Unknown condition type: unknown_type"

**Expected Result**: Unknown type treated as unsatisfied condition

---

### 8.3 Self-Reference Scenario Tests (`test_self_reference.py`)

#### Test: `test_restore_self_version_check`
**Purpose**: Verify restore policy checking its own package version

**Setup**:
- Policy:
  ```json
  {
    "critical-package": {
      "restore": [
        {
          "condition": {"type": "installed", "spec": "!=1.2.3"},
          "target": "critical-package",
          "version": "1.2.3"
        }
      ]
    }
  }
  ```
- Installed: `{"critical-package": "1.2.2"}`

**Execution**:
```python
restored = batch.ensure_installed()
```

**Assertions**:
- Condition evaluation: package field omitted → check self ("critical-package")
- "1.2.2" != "1.2.3" → True
- `"critical-package" in restored`
- Final version: "1.2.3"

**Expected Result**: Reinstall when own version is incorrect

---

### 8.4 Circular Dependency Prevention Tests (`test_circular_dependencies.py`)

#### Test: `test_no_infinite_loop_in_restore`
**Purpose**: Verify circular dependency doesn't cause infinite loop in restore

**Setup**:
- Policy:
  ```json
  {
    "pkg-a": {
      "restore": [
        {
          "condition": {"type": "installed", "package": "pkg-b", "spec": ">=1.0"},
          "target": "pkg-a",
          "version": "1.0"
        }
      ]
    },
    "pkg-b": {
      "restore": [
        {
          "condition": {"type": "installed", "package": "pkg-a", "spec": ">=1.0"},
          "target": "pkg-b",
          "version": "1.0"
        }
      ]
    }
  }
  ```
- Installed: `{}`

**Execution**:
```python
restored = batch.ensure_installed()
```

**Assertions**:
- First iteration: pkg-a, pkg-b conditions both unsatisfied (not installed)
- No recursive calls
- `restored == []`

**Expected Result**: Circular dependency doesn't cause infinite loop

**Notes**:
- Current design runs restore once, so no circular issue
- If recursive restore is needed, visited set or similar mechanism required

---

## 9. Platform and Environment Condition Tests

### 9.1 OS-Specific Behavior Tests (`test_platform_os.py`)

#### Test: `test_linux_gpu_uses_gpu_package`
**Purpose**: Verify GPU-specific package is installed on Linux + GPU environment

**Setup**:
- Policy:
  ```json
  {
    "onnxruntime": {
      "apply_first_match": [
        {
          "condition": {"type": "platform", "os": "linux", "has_gpu": true},
          "type": "replace",
          "replacement": "onnxruntime-gpu"
        }
      ]
    }
  }
  ```
- Mock: `platform.system() → "Linux"`, `torch.cuda.is_available() → True`

**Execution**:
```python
result = batch.install("onnxruntime")
```

**Assertions**:
- Condition evaluation: os="linux" ✓, has_gpu=True ✓
- Replace applied: onnxruntime → onnxruntime-gpu
- pip install ["onnxruntime-gpu"]

**Expected Result**: Replaced with GPU version

---

#### Test: `test_windows_no_gpu_uses_cpu_package`
**Purpose**: Verify CPU package is installed on Windows + No GPU environment

**Setup**:
- Same policy as above
- Mock: `platform.system() → "Windows"`, `torch.cuda.is_available() → False`

**Execution**:
```python
result = batch.install("onnxruntime")
```

**Assertions**:
- Condition evaluation: os="windows" ≠ "linux" → False
- Replace not applied
- pip install ["onnxruntime"] (original package)

**Expected Result**: Original package installed when condition not satisfied

---

### 9.2 GPU Detection Tests (`test_platform_gpu.py`)

#### Test: `test_torch_cuda_available_true`
**Purpose**: Verify GPU is recognized when torch.cuda.is_available() = True

**Setup**:
- Mock torch.cuda.is_available() → True
- Condition: `{"type": "platform", "has_gpu": true}`

**Execution**:
```python
result = batch._evaluate_condition(condition, "pkg", {})
```

**Assertions**:
- `result is True`

**Expected Result**: GPU recognized as available

---

#### Test: `test_torch_cuda_available_false`
**Purpose**: Verify GPU is not recognized when torch.cuda.is_available() = False

**Setup**:
- Mock torch.cuda.is_available() → False

**Execution**:
```python
result = batch._evaluate_condition(condition, "pkg", {})
```

**Assertions**:
- `result is False`

**Expected Result**: GPU recognized as unavailable

---

#### Test: `test_torch_not_installed_assumes_no_gpu`
**Purpose**: Verify GPU is assumed unavailable when torch is not installed

**Setup**:
- Mock torch import → ImportError

**Execution**:
```python
result = batch._evaluate_condition(condition, "pkg", {})
```

**Assertions**:
- ImportError handled
- `result is False`

**Expected Result**: Assumed no GPU when torch is not installed

---

### 9.3 ComfyUI Version Condition Tests (`test_platform_comfyui_version.py`)

#### Test: `test_comfyui_version_condition_not_implemented_warning`
**Purpose**: Verify warning for currently unimplemented comfyui_version condition

**Setup**:
- Condition: `{"type": "platform", "comfyui_version": ">=1.0.0"}`

**Execution**:
```python
result = batch._evaluate_condition(condition, "pkg", {})
```

**Assertions**:
- Warning log: "comfyui_version condition is not yet implemented"
- `result is False`

**Expected Result**: Warning for unimplemented feature and False returned

**Notes**: Change this test to actual implementation test when feature is implemented

---

## 10. extra_index_url Handling Tests

### 10.1 Policy URL Tests (`test_extra_index_url_policy.py`)

#### Test: `test_policy_extra_index_url_in_force_version`
**Purpose**: Verify extra_index_url from force_version policy is used

**Setup**:
- Policy:
  ```json
  {
    "pkg": {
      "apply_first_match": [
        {
          "type": "force_version",
          "version": "1.0.0",
          "extra_index_url": "https://custom-repo.example.com/simple"
        }
      ]
    }
  }
  ```

**Execution**:
```python
result = batch.install("pkg")
```

**Assertions**:
- pip install ["pkg==1.0.0", "--extra-index-url", "https://custom-repo.example.com/simple"]

**Expected Result**: Policy URL is included in command

---

#### Test: `test_parameter_url_overrides_policy_url`
**Purpose**: Verify parameter URL takes precedence over policy URL

**Setup**:
- Policy: extra_index_url = "https://policy-repo.com/simple"
- Parameter: extra_index_url = "https://param-repo.com/simple"

**Execution**:
```python
result = batch.install("pkg", extra_index_url="https://param-repo.com/simple")
```

**Assertions**:
- pip install uses "https://param-repo.com/simple" (NOT policy URL)

**Expected Result**: Parameter URL takes precedence

---

### 10.2 Restore URL Tests (`test_extra_index_url_restore.py`)

#### Test: `test_restore_with_extra_index_url`
**Purpose**: Verify extra_index_url from restore policy is used

**Setup**:
- Policy:
  ```json
  {
    "critical-pkg": {
      "restore": [
        {
          "target": "critical-pkg",
          "version": "1.2.3",
          "extra_index_url": "https://custom-repo.example.com/simple"
        }
      ]
    }
  }
  ```
- Installed: `{}` (package not present)

**Execution**:
```python
restored = batch.ensure_installed()
```

**Assertions**:
- pip install ["critical-pkg==1.2.3", "--extra-index-url", "https://custom-repo.example.com/simple"]
- `"critical-pkg" in restored`

**Expected Result**: Policy URL is used during restore

---

## 11. Large Batch and Performance Tests

### 11.1 Multiple Package Handling Tests (`test_large_batch.py`)

#### Test: `test_batch_with_20_packages`
**Purpose**: Verify cache efficiency when installing 20 packages in batch

**Setup**:
- 20 packages, each with different policy

**Execution**:
```python
with PipBatch() as batch:
    for i in range(20):
        batch.install(f"pkg-{i}")
```

**Assertions**:
- Count pip freeze calls
- First install: 1 call
- Subsequent installs: invalidate then re-call
- Total calls = 20 (1 per install)

**Expected Result**: Cache operates efficiently within batch

---

#### Test: `test_complex_policy_combinations`
**Purpose**: Verify complex policy combinations are all applied correctly

**Setup**:
- 20 packages:
  - 5: uninstall policies
  - 3: skip policies
  - 4: force_version policies
  - 2: replace policies
  - 6: pin_dependencies policies

**Execution**:
```python
with PipBatch() as batch:
    removed = batch.ensure_not_installed()

    for pkg in packages:
        batch.install(pkg)

    restored = batch.ensure_installed()
```

**Assertions**:
- uninstall policies: 5 packages removed verified
- skip policies: 3 packages not installed verified
- force_version: 4 packages forced version verified
- replace: 2 packages replaced verified
- pin: 6 packages pinned dependencies verified

**Expected Result**: All policies are applied correctly

---

## 12. Logging and Debugging Tests

### 12.1 Reason Logging Tests (`test_reason_logging.py`)

#### Test: `test_skip_reason_logged`
**Purpose**: Verify reason from skip policy is logged

**Setup**:
- Policy:
  ```json
  {
    "torch": {
      "apply_first_match": [
        {"type": "skip", "reason": "Manual CUDA management required"}
      ]
    }
  }
  ```

**Execution**:
```python
result = batch.install("torch")
```

**Assertions**:
- `result is False`
- Info log: "Skipping installation of torch: Manual CUDA management required"

**Expected Result**: Reason is logged

---

#### Test: `test_all_policy_reasons_logged`
**Purpose**: Verify reasons from all policy types are logged

**Setup**:
- Policies with reasons: skip, force_version, replace, uninstall, restore, warn, pin_dependencies

**Execution**:
```python
# Execute all policy types
```

**Assertions**:
- Each policy execution logs reason in info or warning log

**Expected Result**: All reasons are appropriately logged

---

### 12.2 Policy Loading Logging Tests (`test_policy_loading_logs.py`)

#### Test: `test_policy_load_success_logged`
**Purpose**: Verify log on successful policy load

**Setup**:
- Policy file with 5 packages

**Execution**:
```python
policy = get_pip_policy()
```

**Assertions**:
- Debug log: "Loaded pip policy with 5 package policies"

**Expected Result**: Load success log recorded

---

#### Test: `test_cache_refresh_logged`
**Purpose**: Verify log on cache refresh

**Execution**:
```python
batch._refresh_installed_cache()
```

**Assertions**:
- Debug log: "Refreshed installed packages cache: N packages"

**Expected Result**: Cache refresh log recorded

---

## 13. Test Priorities and Execution Plan

### Priority 1 (Essential - Must Implement)
1. ✅ **Full workflow integration** (`test_uninstall_install_restore_workflow`)
2. ✅ **Complex dependency protection** (`test_dependency_version_protection_with_pin`)
3. ✅ **Environment corruption and recovery** (`test_package_deletion_and_restore`, `test_version_change_and_restore`)
4. ✅ **Pin failure retry** (`test_pin_failure_retry_without_pin_succeeds`)
5. ✅ **Cache consistency** (`test_cache_invalidation_across_workflow`)

### Priority 2 (Important - Implement If Possible)
6. ✅ **Policy priority** (`test_user_policy_overrides_base_policy`)
7. ✅ **Dependency chain** (`test_dependency_chain_with_click_colorama`) - Uses lightweight click+colorama instead of numba+numpy
8. ✅ **Platform conditions** (`test_linux_gpu_uses_gpu_package`) - Real onnxruntime-gpu scenario
9. ✅ **extra_index_url** (`test_parameter_url_overrides_policy_url`)
10. ✅ **Partial failure handling** (`test_ensure_not_installed_continues_on_individual_failure`)

### Priority 3 (Recommended - If Time Permits)
11. ✅ **Edge cases** (empty policies, malformed policies, self-reference)
12. ✅ **Large batch** (`test_batch_with_20_packages`)
13. ✅ **Logging verification** (reason, policy load, cache refresh)

---

## 14. Test Fixtures and Mocks

### 14.1 Common Fixtures (`conftest.py`)

```python
@pytest.fixture
def temp_policy_dir(tmp_path):
    """Create temporary directory for policy files"""
    policy_dir = tmp_path / "policies"
    policy_dir.mkdir()
    return policy_dir

@pytest.fixture
def mock_manager_util(monkeypatch, temp_policy_dir):
    """Mock manager_util module"""
    monkeypatch.setattr("pip_util.manager_util.comfyui_manager_path", str(temp_policy_dir))
    monkeypatch.setattr("pip_util.manager_util.make_pip_cmd", lambda args: ["pip"] + args)

@pytest.fixture
def mock_context(monkeypatch, temp_policy_dir):
    """Mock context module"""
    monkeypatch.setattr("pip_util.context.manager_files_path", str(temp_policy_dir))

@pytest.fixture
def mock_subprocess_success(monkeypatch):
    """Mock successful subprocess execution"""
    def mock_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr("subprocess.run", mock_run)

@pytest.fixture
def mock_pip_freeze(monkeypatch):
    """Mock pip freeze output with lightweight real packages"""
    def mock_run(cmd, **kwargs):
        if "freeze" in cmd:
            output = "urllib3==1.26.15\ncertifi==2023.7.22\ncharset-normalizer==3.2.0\ncolorama==0.4.6\n"
            return subprocess.CompletedProcess(cmd, 0, output, "")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr("subprocess.run", mock_run)
```

---

## 14.2 Test Packages (Lightweight Real PyPI Packages)

All tests use **real lightweight packages from PyPI** for realistic scenarios:

### Core Test Packages

| Package | Size | Version Used | Purpose in Tests |
|---------|------|--------------|------------------|
| **requests** | ~100KB | 2.31.0 | Main package to install with pinned dependencies |
| **urllib3** | ~100KB | 1.26.15 | Protected dependency (prevent upgrade to 2.x) |
| **certifi** | ~10KB | 2023.7.22 | SSL certificate package (pinned) |
| **charset-normalizer** | ~50KB | 3.2.0 | Character encoding (pinned) |
| **click** | ~100KB | 8.1.3 | CLI framework (force_version testing) |
| **colorama** | ~10KB | 0.4.6 | Terminal colors (dependency pinning) |
| **six** | ~10KB | 1.16.0 | Python 2/3 compatibility (restore testing) |
| **python-dateutil** | ~50KB | 2.8.2 | Package that may conflict with six |
| **attrs** | ~50KB | 23.1.0 | Class attributes (bystander package) |
| **packaging** | ~40KB | 23.1 | Version parsing (bystander package) |

### Why These Packages?

1. **Lightweight**: All packages < 200KB for fast testing
2. **Real Dependencies**: Actual PyPI package relationships
3. **Common Issues**: Test real-world scenarios:
   - urllib3 1.x → 2.x breaking change
   - Package conflicts (six vs python-dateutil)
   - Version pinning needs
4. **Fast Installation**: Quick test execution

### Test Scenario Mapping

**Dependency Protection Tests**:
- Install `requests` while protecting `urllib3`, `certifi`, `charset-normalizer`
- Prevent urllib3 upgrade to 2.x (breaking API changes)

**Dependency Chain Tests**:
- Install `click` with forced version when `colorama <0.5.0` detected
- Pin colorama to prevent incompatible upgrade

**Environment Recovery Tests**:
- Install `python-dateutil` which may remove `six`
- Restore `six` to 1.16.0
- Install `requests` which upgrades `urllib3` to 2.1.0
- Restore `urllib3` to 1.26.15

**Platform Condition Tests**:
- Install `onnxruntime-gpu` on Linux + GPU
- Install `onnxruntime` (CPU) on Windows or no GPU

### Package Relationship Diagram

```
requests 2.31.0
├── urllib3 (requires <2.0, >=1.21.1)
├── certifi (requires >=2017.4.17)
└── charset-normalizer (requires >=2, <4)

click 8.1.3
└── colorama (Windows only, optional)

python-dateutil 2.8.2
└── six (requires >=1.5)
```

---

## 15. Coverage Goals

### Target Coverage Metrics
- **Overall**: ≥80%
- **Core Functions**: ≥90%
  - `get_pip_policy()`
  - `install()`
  - `ensure_not_installed()`
  - `ensure_installed()`
- **Utility Functions**: ≥80%
  - `_parse_package_spec()`
  - `_evaluate_condition()`
- **Error Paths**: 100%

### Coverage Report Commands
```bash
# Run tests with coverage
pytest --cov=pip_util --cov-report=html --cov-report=term

# View detailed coverage
open htmlcov/index.html
```

---

## 16. Test Execution Order (TDD Workflow)

### Phase 1: Red Phase (Write Failing Tests)
1. Write policy loading tests
2. Write package spec parsing tests
3. Write condition evaluation tests
4. Run tests → All fail (no implementation)

### Phase 2: Green Phase (Minimal Implementation)
1. Implement `get_pip_policy()` to pass tests
2. Implement `_parse_package_spec()` to pass tests
3. Implement `_evaluate_condition()` to pass tests
4. Run tests → All pass

### Phase 3: Refactor Phase
1. Optimize code
2. Remove duplication
3. Improve readability
4. Run tests → All still pass

### Phase 4-6: Repeat for Remaining Features
- Repeat Red-Green-Refactor for pip freeze caching
- Repeat for install() method
- Repeat for batch operations

---

## 17. CI/CD Integration

### Pre-commit Hooks
```yaml
repos:
  - repo: local
    hooks:
      - id: pytest-check
        name: pytest
        entry: pytest
        language: system
        pass_filenames: false
        always_run: true
```

### GitHub Actions Workflow
```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Install dependencies
        run: pip install -r requirements-test.txt
      - name: Run tests
        run: pytest --cov=pip_util --cov-report=xml
      - name: Upload coverage
        uses: codecov/codecov-action@v2
```

---

## 18. Test Maintenance Guidelines

### When to Update Tests
- **Breaking changes**: Update affected tests immediately
- **New features**: Write tests first (TDD)
- **Bug fixes**: Add regression test before fix

### Test Naming Convention
- `test_<function>_<scenario>_<expected_result>`
- Example: `test_install_skip_policy_returns_false`

### Test Documentation
- Each test has clear docstring
- Purpose, setup, execution, assertions documented
- Edge cases explicitly noted

---

## 19. Performance Test Considerations

### Performance Benchmarks
```python
def test_get_pip_policy_performance():
    """Policy loading should complete in <100ms"""
    import time
    start = time.time()
    get_pip_policy()
    duration = time.time() - start
    assert duration < 0.1, f"Policy loading took {duration}s, expected <0.1s"

def test_pip_freeze_caching_performance():
    """Cached access should be >50% faster"""
    # Measure first call (with pip freeze)
    # Measure second call (from cache)
    # Assert second is >50% faster
```

---

## 20. Success Criteria

### Test Suite Completeness
- ✅ All public methods have tests
- ✅ All error paths have tests
- ✅ Edge cases covered
- ✅ Integration tests verify behavior
- ✅ E2E tests verify workflows

### Quality Metrics
- ✅ Coverage ≥80%
- ✅ All tests pass
- ✅ No flaky tests
- ✅ Tests run in <30 seconds
- ✅ Clear documentation for all tests
