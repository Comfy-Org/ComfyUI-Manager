# pip_util.py Implementation Plan Document

## 1. Project Overview

### Purpose
Implement a policy-based pip package management system that minimizes breaking existing installed dependencies

### Core Features
- JSON-based policy file loading and merging (lazy loading)
- Per-package installation policy evaluation and application
- Performance optimization through batch-level pip freeze caching
- Automated conditional package removal/restoration

### Technology Stack
- Python 3.x
- packaging library (version comparison)
- subprocess (pip command execution)
- json (policy file parsing)

---

## 2. Architecture Design

### 2.1 Global Policy Management (Lazy Loading Pattern)

```
┌─────────────────────────────────────┐
│  get_pip_policy()                   │
│  - Auto-loads policy files on       │
│    first call via lazy loading      │
│  - Returns cache on subsequent calls│
└─────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────┐
│  _pip_policy_cache (global)         │
│  - Merged policy dictionary         │
│  - {package_name: policy_object}    │
└─────────────────────────────────────┘
```

### 2.2 Batch Operation Class (PipBatch)

```
┌─────────────────────────────────────┐
│  PipBatch (Context Manager)         │
│  ┌───────────────────────────────┐  │
│  │ _installed_cache              │  │
│  │ - Caches pip freeze results   │  │
│  │ - {package: version}          │  │
│  └───────────────────────────────┘  │
│                                     │
│  Public Methods:                    │
│  ├─ install()                       │
│  ├─ ensure_not_installed()          │
│  └─ ensure_installed()              │
│                                     │
│  Private Methods:                   │
│  ├─ _get_installed_packages()       │
│  ├─ _refresh_installed_cache()      │
│  ├─ _invalidate_cache()             │
│  ├─ _parse_package_spec()           │
│  └─ _evaluate_condition()           │
└─────────────────────────────────────┘
```

### 2.3 Policy Evaluation Flow

```
install("numpy>=1.20") called
    │
    ▼
get_pip_policy() → Load policy (lazy)
    │
    ▼
Parse package name: "numpy"
    │
    ▼
Look up "numpy" policy in policy dictionary
    │
    ├─ Evaluate apply_first_match (exclusive)
    │   ├─ skip → Return False (don't install)
    │   ├─ force_version → Change version
    │   └─ replace → Replace package
    │
    ├─ Evaluate apply_all_matches (cumulative)
    │   ├─ pin_dependencies → Pin dependencies
    │   ├─ install_with → Additional packages
    │   └─ warn → Warning log
    │
    ▼
Execute pip install
    │
    ▼
Invalidate cache (_invalidate_cache)
```

---

## 3. Phase-by-Phase Implementation Plan

### Phase 1: Core Infrastructure Setup (2-3 hours)

#### Task 1.1: Project Structure and Dependency Setup (30 min)
**Implementation**:
- Create `pip_util.py` file
- Add necessary import statements
  ```python
  import json
  import logging
  import platform
  import re
  import subprocess
  from pathlib import Path
  from typing import Dict, List, Optional, Tuple

  from packaging.specifiers import SpecifierSet
  from packaging.version import Version

  from . import manager_util, context
  ```
- Set up logging
  ```python
  logger = logging.getLogger(__name__)
  ```

**Validation**:
- Module loads without import errors
- Logger works correctly

#### Task 1.2: Global Variable and get_pip_policy() Implementation (1 hour)
**Implementation**:
- Declare global variable
  ```python
  _pip_policy_cache: Optional[Dict] = None
  ```
- Implement `get_pip_policy()` function
  - Check cache and early return
  - Read base policy file (`{manager_util.comfyui_manager_path}/pip-policy.json`)
  - Read user policy file (`{context.manager_files_path}/pip-policy.user.json`)
  - Create file if doesn't exist (for user policy)
  - Merge policies (complete package-level replacement)
  - Save to cache and return

**Exception Handling**:
- `FileNotFoundError`: File not found → Use empty dictionary
- `json.JSONDecodeError`: JSON parse failure → Warning log + empty dictionary
- General exception: Warning log + empty dictionary

**Validation**:
- Returns empty dictionary when policy files don't exist
- Returns correct merged result when policy files exist
- Confirms cache usage on second call (load log appears only once)

#### Task 1.3: PipBatch Class Basic Structure (30 min)
**Implementation**:
- Class definition and `__init__`
  ```python
  class PipBatch:
      def __init__(self):
          self._installed_cache: Optional[Dict[str, str]] = None
  ```
- Context manager methods (`__enter__`, `__exit__`)
  ```python
  def __enter__(self):
      return self

  def __exit__(self, exc_type, exc_val, exc_tb):
      self._installed_cache = None
      return False
  ```

**Validation**:
- `with PipBatch() as batch:` syntax works correctly
- Cache cleared on `__exit__` call

---

### Phase 2: Caching and Utility Methods (2-3 hours)

#### Task 2.1: pip freeze Caching Methods (1 hour)
**Implementation**:
- Implement `_refresh_installed_cache()`
  - Call `manager_util.make_pip_cmd(["freeze"])`
  - Execute command via subprocess
  - Parse output (package==version format)
  - Exclude editable packages (-e) and comments (#)
  - Convert to dictionary and store in `self._installed_cache`

- Implement `_get_installed_packages()`
  - Call `_refresh_installed_cache()` if cache is None
  - Return cache

- Implement `_invalidate_cache()`
  - Set `self._installed_cache = None`

**Exception Handling**:
- `subprocess.CalledProcessError`: pip freeze failure → Empty dictionary
- Parse error: Ignore line + warning log

**Validation**:
- pip freeze results correctly parsed into dictionary
- New load occurs after cache invalidation and re-query

#### Task 2.2: Package Spec Parsing (30 min)
**Implementation**:
- Implement `_parse_package_spec(package_info)`
  - Regex pattern: `^([a-zA-Z0-9_-]+)([><=!~]+.*)?$`
  - Split package name and version spec
  - Return tuple: `(package_name, version_spec)`

**Exception Handling**:
- Parse failure: Raise `ValueError`

**Validation**:
- "numpy" → ("numpy", None)
- "numpy==1.26.0" → ("numpy", "==1.26.0")
- "pandas>=2.0.0" → ("pandas", ">=2.0.0")
- Invalid format → ValueError

#### Task 2.3: Condition Evaluation Method (1.5 hours)
**Implementation**:
- Implement `_evaluate_condition(condition, package_name, installed_packages)`

**Handling by Condition Type**:
1. **condition is None**: Always return True
2. **"installed" type**:
   - `target_package = condition.get("package", package_name)`
   - Check version with `installed_packages.get(target_package)`
   - If spec exists, compare using `packaging.specifiers.SpecifierSet`
   - If no spec, only check installation status
3. **"platform" type**:
   - `os` condition: Compare with `platform.system()`
   - `has_gpu` condition: Check `torch.cuda.is_available()` (False if torch unavailable)
   - `comfyui_version` condition: TODO (currently warning)

**Exception Handling**:
- Version comparison failure: Warning log + return False
- Unknown condition type: Warning log + return False

**Validation**:
- Write test cases for each condition type
- Verify edge case handling (torch not installed, invalid version format, etc.)

---

### Phase 3: Core Installation Logic Implementation (4-5 hours)

#### Task 3.1: install() Method - Basic Flow (2 hours)
**Implementation**:
1. Parse package spec (`_parse_package_spec`)
2. Query installed package cache (`_get_installed_packages`)
3. If `override_policy=True`, install directly and return
4. Call `get_pip_policy()` to load policy
5. Default installation if no policy exists

**Validation**:
- Verify policy ignored when override_policy=True
- Verify default installation for packages without policy

#### Task 3.2: install() Method - apply_first_match Policy (1 hour)
**Implementation**:
- Iterate through policy list top-to-bottom
- Evaluate each policy's condition (`_evaluate_condition`)
- When condition satisfied:
  - **skip**: Log reason and return False
  - **force_version**: Force version change
  - **replace**: Replace package
- Apply only first match (break)

**Validation**:
- Verify installation blocked by skip policy
- Verify version changed by force_version
- Verify package replaced by replace

#### Task 3.3: install() Method - apply_all_matches Policy (1 hour)
**Implementation**:
- Iterate through policy list top-to-bottom
- Evaluate each policy's condition
- Apply all condition-satisfying policies:
  - **pin_dependencies**: Pin to installed version
  - **install_with**: Add to additional package list
  - **warn**: Output warning log

**Validation**:
- Verify multiple policies applied simultaneously
- Verify version pinning by pin_dependencies
- Verify additional package installation by install_with

#### Task 3.4: install() Method - Installation Execution and Retry Logic (1 hour)
**Implementation**:
1. Compose final package list
2. Generate command using `manager_util.make_pip_cmd()`
3. Handle `extra_index_url`
4. Execute installation via subprocess
5. Handle failure based on on_failure setting:
   - `retry_without_pin`: Retry without pins
   - `fail`: Raise exception
   - Other: Warning log
6. Invalidate cache on success

**Validation**:
- Verify normal installation
- Verify retry logic on pin failure
- Verify error handling

---

### Phase 4: Batch Operation Methods Implementation (2-3 hours)

#### Task 4.1: ensure_not_installed() Implementation (1.5 hours)
**Implementation**:
1. Call `get_pip_policy()`
2. Iterate through all package policies
3. Check each package's uninstall policy
4. When condition satisfied:
   - Check if target package is installed
   - If installed, execute `pip uninstall -y {target}`
   - Remove from cache
   - Add to removal list
5. Execute only first match (per package)
6. Return list of removed packages

**Exception Handling**:
- Individual package removal failure: Warning log + continue

**Validation**:
- Verify package removal by uninstall policy
- Verify batch removal of multiple packages
- Verify continued processing of other packages even on removal failure

#### Task 4.2: ensure_installed() Implementation (1.5 hours)
**Implementation**:
1. Call `get_pip_policy()`
2. Iterate through all package policies
3. Check each package's restore policy
4. When condition satisfied:
   - Check target package's current version
   - If absent or different version:
     - Execute `pip install {target}=={version}`
     - Add extra_index_url if present
     - Update cache
     - Add to restoration list
5. Execute only first match (per package)
6. Return list of restored packages

**Exception Handling**:
- Individual package installation failure: Warning log + continue

**Validation**:
- Verify package restoration by restore policy
- Verify reinstallation on version mismatch
- Verify continued processing of other packages even on restoration failure

---

## 4. Testing Strategy

### 4.1 Unit Tests

#### Policy Loading Tests
```python
def test_get_pip_policy_empty():
    """Returns empty dictionary when policy files don't exist"""

def test_get_pip_policy_merge():
    """Correctly merges base and user policies"""

def test_get_pip_policy_cache():
    """Uses cache on second call"""
```

#### Package Parsing Tests
```python
def test_parse_package_spec_simple():
    """'numpy' → ('numpy', None)"""

def test_parse_package_spec_version():
    """'numpy==1.26.0' → ('numpy', '==1.26.0')"""

def test_parse_package_spec_range():
    """'pandas>=2.0.0' → ('pandas', '>=2.0.0')"""

def test_parse_package_spec_invalid():
    """Invalid format → ValueError"""
```

#### Condition Evaluation Tests
```python
def test_evaluate_condition_none():
    """None condition → True"""

def test_evaluate_condition_installed():
    """Evaluates installed package condition"""

def test_evaluate_condition_platform():
    """Evaluates platform condition"""
```

### 4.2 Integration Tests

#### Installation Policy Tests
```python
def test_install_with_skip_policy():
    """Blocks installation with skip policy"""

def test_install_with_force_version():
    """Changes version with force_version policy"""

def test_install_with_replace():
    """Replaces package with replace policy"""

def test_install_with_pin_dependencies():
    """Pins versions with pin_dependencies"""
```

#### Batch Operation Tests
```python
def test_ensure_not_installed():
    """Removes packages with uninstall policy"""

def test_ensure_installed():
    """Restores packages with restore policy"""

def test_batch_workflow():
    """Tests complete batch workflow"""
```

### 4.3 Edge Case Tests

```python
def test_install_without_policy():
    """Default installation for packages without policy"""

def test_install_override_policy():
    """Ignores policy with override_policy=True"""

def test_pip_freeze_failure():
    """Handles empty cache on pip freeze failure"""

def test_json_parse_error():
    """Handles malformed JSON files"""

def test_subprocess_failure():
    """Exception handling when pip command fails"""
```

---

## 5. Error Handling Strategy

### 5.1 Policy Loading Errors
- **File not found**: Warning log + empty dictionary
- **JSON parse failure**: Error log + empty dictionary
- **No read permission**: Warning log + empty dictionary

### 5.2 Package Installation Errors
- **pip command failure**: Depends on on_failure setting
  - `retry_without_pin`: Retry
  - `fail`: Raise exception
  - Other: Warning log
- **Invalid package spec**: Raise ValueError

### 5.3 Batch Operation Errors
- **Individual package failure**: Warning log + continue to next package
- **pip freeze failure**: Empty dictionary + warning log

---

## 6. Performance Optimization

### 6.1 Caching Strategy
- **Policy cache**: Reused program-wide via global variable
- **pip freeze cache**: Reused per batch, invalidated after install/remove
- **lazy loading**: Load only when needed

### 6.2 Parallel Processing Considerations
- Current implementation is not thread-safe
- Consider adding threading.Lock if needed
- Batch operations execute sequentially only

---

## 7. Documentation Requirements

### 7.1 Code Documentation
- Docstrings required for all public methods
- Specify parameters, return values, and exceptions
- Include usage examples

### 7.2 User Guide
- Explain `pip-policy.json` structure
- Policy writing examples
- Usage pattern examples

### 7.3 Developer Guide
- Architecture explanation
- Extension methods
- Test execution methods

---

## 8. Deployment Checklist

### 8.1 Code Quality
- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] Code coverage ≥80%
- [ ] No linting errors (flake8, pylint)
- [ ] Type hints complete (mypy passes)

### 8.2 Documentation
- [ ] README.md written
- [ ] API documentation generated
- [ ] Example policy files written
- [ ] Usage guide written

### 8.3 Performance Verification
- [ ] Policy loading performance measured (<100ms)
- [ ] pip freeze caching effectiveness verified (≥50% speed improvement)
- [ ] Memory usage confirmed (<10MB)

### 8.4 Security Verification
- [ ] Input validation complete
- [ ] Path traversal prevention
- [ ] Command injection prevention
- [ ] JSON parsing safety confirmed

---

## 9. Future Improvements

### 9.1 Short-term (1-2 weeks)
- Implement ComfyUI version check
- Implement user confirmation prompt (allow_continue=false)
- Thread-safe improvements (add Lock)

### 9.2 Mid-term (1-2 months)
- Add policy validation tools
- Policy migration tools
- More detailed logging and debugging options

### 9.3 Long-term (3-6 months)
- Web UI for policy management
- Provide policy templates
- Community policy sharing system

---

## 10. Risks and Mitigation Strategies

### Risk 1: Policy Conflicts
**Description**: Policies for different packages may conflict
**Mitigation**: Develop policy validation tools, conflict detection algorithm

### Risk 2: pip Version Compatibility
**Description**: Must work across various pip versions
**Mitigation**: Test on multiple pip versions, version-specific branching

### Risk 3: Performance Degradation
**Description**: Installation speed may decrease due to policy evaluation
**Mitigation**: Optimize caching, minimize condition evaluation

### Risk 4: Policy Misconfiguration
**Description**: Users may write incorrect policies
**Mitigation**: JSON schema validation, provide examples and guides

---

## 11. Timeline

### Week 1
- Phase 1: Core Infrastructure Setup (Day 1-2)
- Phase 2: Caching and Utility Methods (Day 3-4)
- Write unit tests (Day 5)

### Week 2
- Phase 3: Core Installation Logic Implementation (Day 1-3)
- Phase 4: Batch Operation Methods Implementation (Day 4-5)

### Week 3
- Integration and edge case testing (Day 1-2)
- Documentation (Day 3)
- Code review and refactoring (Day 4-5)

### Week 4
- Performance optimization (Day 1-2)
- Security verification (Day 3)
- Final testing and deployment preparation (Day 4-5)

---

## 12. Success Criteria

### Feature Completeness
- ✅ All policy types (uninstall, apply_first_match, apply_all_matches, restore) work correctly
- ✅ Policy merge logic works correctly
- ✅ Batch operations perform normally

### Quality Metrics
- ✅ Test coverage ≥80%
- ✅ All tests pass
- ✅ 0 linting errors
- ✅ 100% type hint completion

### Performance Metrics
- ✅ Policy loading <100ms
- ✅ ≥50% performance improvement with pip freeze caching
- ✅ Memory usage <10MB

### Usability
- ✅ Clear error messages
- ✅ Sufficient documentation
- ✅ Verified in real-world use cases
