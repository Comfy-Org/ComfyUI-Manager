# Glob API Endpoint Tests

This directory contains endpoint tests for the ComfyUI Manager glob API implementation.

## Quick Navigation

- **Running Tests**: See [Running Tests](#running-tests) section below
- **Test Coverage**: See [Test Coverage](#test-coverage) section
- **Known Issues**: See [Known Issues and Fixes](#known-issues-and-fixes) section
- **Detailed Execution Guide**: See [TESTING_GUIDE.md](./TESTING_GUIDE.md)
- **Future Test Plans**: See [docs/internal/test_planning/](../../docs/internal/test_planning/)

## Test Files

- `test_queue_task_api.py` - Queue task API tests for install/uninstall/version switching operations (8 tests)
- `test_enable_disable_api.py` - Queue task API tests for enable/disable operations (5 tests)
- `test_update_api.py` - Queue task API tests for update operations (4 tests)
- `test_complex_scenarios.py` - Multi-version complex scenarios (10 tests) - **Phase 1 + 3 + 4 + 5 + 6**
- `test_installed_api_original_case.py` - Installed API case preservation tests (4 tests)
- `test_version_switching_comprehensive.py` - Comprehensive version switching tests (19 tests)
- `test_case_sensitivity_integration.py` - Full integration test for case sensitivity (1 test)

**Total: 51 tests - All passing ✅** (+5 P1 tests: Phase 3.1, Phase 5.1, Phase 5.2, Phase 5.3, Phase 6)

## Running Tests

### Prerequisites

1. Install test dependencies:
```bash
pip install pytest requests
```

2. Start ComfyUI server with Manager:
```bash
cd tests/env
./run.sh
```

### Run All Tests

```bash
# From project root
pytest tests/glob/ -v

# With coverage
pytest tests/glob/ -v --cov=comfyui_manager.glob --cov-report=html
```

### Run Specific Tests

```bash
# Run specific test file
pytest tests/glob/test_queue_task_api.py -v

# Run specific test function
pytest tests/glob/test_queue_task_api.py::test_install_package_via_queue -v

# Run with output
pytest tests/glob/test_queue_task_api.py -v -s
```

## Environment Variables

- `COMFYUI_TEST_URL` - Base URL for ComfyUI server (default: http://127.0.0.1:8188)
- `TEST_SERVER_PORT` - Server port (default: 8188, automatically used by conftest.py)
- `COMFYUI_CUSTOM_NODES_PATH` - Path to custom_nodes directory (default: tests/env/ComfyUI/custom_nodes)

**Important**: All tests now use the `server_url` fixture from `conftest.py`, which reads from these environment variables. This ensures compatibility with parallel test execution.

Example:
```bash
# Single test environment
COMFYUI_TEST_URL=http://localhost:8188 pytest tests/glob/ -v

# Parallel test environment (port automatically set)
TEST_SERVER_PORT=8189 pytest tests/glob/ -v
```

## Test Coverage

The test suite covers:

1. **Install Operations** (test_queue_task_api.py)
   - Install package via queue task API
   - Version switching between CNR and Nightly
   - Case-insensitive package name handling
   - Queue multiple install tasks

2. **Uninstall Operations** (test_queue_task_api.py)
   - Uninstall package via queue task API
   - Complete install/uninstall cycle
   - Case-insensitive uninstall operations

3. **Enable/Disable Operations** (test_enable_disable_api.py) ✅ **All via Queue Task API**
   - Disable active package via queue task
   - Enable disabled package via queue task
   - Duplicate disable/enable handling via queue task
   - Complete enable/disable cycle via queue task
   - Marker file preservation (.tracking, .git)

4. **Update Operations** (test_update_api.py)
   - Update CNR package to latest version
   - Update Nightly package (git pull)
   - Skip update when already latest
   - Complete update workflow cycle

5. **Complex Multi-Version Scenarios** (test_complex_scenarios.py)
   - **Phase 1**: Enable from Multiple Disabled States
     - Enable CNR when both CNR and Nightly are disabled
     - Enable Nightly when both CNR and Nightly are disabled
   - **Phase 3**: Disable Complex Scenarios
     - Disable CNR when Nightly is disabled (both end up disabled)
   - **Phase 4**: Update with Other Versions Present
     - Update CNR with Nightly disabled (selective update)
     - Update Nightly with CNR disabled (selective update)
     - Update enabled package with multiple disabled versions
   - **Phase 5**: Install with Existing Versions (Complete) ✅
     - Install CNR when Nightly is enabled (automatic version switch)
     - Install Nightly when CNR is enabled (automatic version switch)
     - Install new version when both CNR and Nightly are disabled
   - **Phase 6**: Uninstall with Multiple Versions ✅
     - Uninstall removes all versions (enabled + all disabled) - default behavior
   - Version-specific enable with @version syntax
   - Multiple disabled versions management

6. **Version Switching Comprehensive** (test_version_switching_comprehensive.py)
   - Reverse scenario: Nightly → CNR → Nightly
   - Same version reinstall detection and skip

7. **Case Sensitivity Integration** (test_case_sensitivity_integration.py)
   - Full workflow: Install CNR → Verify lookup → Switch to Nightly
   - Directory naming convention verification
   - Marker file preservation (.tracking, .git)
   - Supports both pytest and standalone execution
   - Repeated version switching (4+ times)
   - Cleanup verification (no orphaned files)
   - Fresh install after complete uninstall

7. **Queue Management**
   - Queue multiple tasks
   - Start queue processing
   - Task execution order and completion

8. **Integration Tests**
   - Verify package in installed list
   - Verify filesystem changes
   - Version identification (.tracking vs .git)
   - .disabled/ directory mechanism

## Known Issues and Fixes

### Issue 1: Glob API Parameters
**Important**: Glob API does NOT support `channel` or `mode` parameters.

**Note**:
- `channel` and `mode` parameters are legacy-only features
- `InstallPackParams` data model includes these fields because it's shared between legacy and glob implementations
- Glob API implementation ignores these parameters
- Tests should NOT include `channel` or `mode` in request parameters

### Issue 2: Case-Insensitive Package Operations (PARTIALLY RESOLVED)
**Previous Problem**: Operations failed when using different cases (e.g., "ComfyUI_SigmoidOffsetScheduler" vs "comfyui_sigmoidoffsetscheduler")

**Current Status**:
- **Install**: Requires exact package name due to CNR server limitations (case-sensitive)
- **Uninstall/Enable/Disable**: Works with any case variation using `cnr_utils.normalize_package_name()`

**Normalization Function** (`cnr_utils.normalize_package_name()`):
- Strips leading/trailing whitespace with `.strip()`
- Converts to lowercase with `.lower()`
- Accepts any case variation (e.g., "ComfyUI_SigmoidOffsetScheduler", "COMFYUI_SIGMOIDOFFSETSCHEDULER", " comfyui_sigmoidoffsetscheduler ")

**Examples**:
```python
# Install - requires exact case
{"id": "ComfyUI_SigmoidOffsetScheduler"}  # ✓ Works
{"id": "comfyui_sigmoidoffsetscheduler"}  # ✗ Fails (CNR limitation)

# Uninstall - accepts any case
{"node_name": "ComfyUI_SigmoidOffsetScheduler"}  # ✓ Works
{"node_name": " ComfyUI_SigmoidOffsetScheduler "}  # ✓ Works (normalized)
{"node_name": "COMFYUI_SIGMOIDOFFSETSCHEDULER"}  # ✓ Works (normalized)
{"node_name": "comfyui_sigmoidoffsetscheduler"}  # ✓ Works (normalized)
```

### Issue 3: `.disabled/` Directory Mechanism
**Critical Discovery**: The `.disabled/` directory is used by the **disable** operation to store disabled packages.

**Implementation** (manager_core.py:1115-1154):
```python
def unified_disable(self, packname: str):
    # Disable moves package to .disabled/ with version suffix
    to_path = os.path.join(base_path, '.disabled', f"{folder_name}@{matched_active.version.replace('.', '_')}")
    shutil.move(matched_active.fullpath, to_path)
```

**Directory Naming Format**:
- CNR packages: `.disabled/{package_name_normalized}@{version}`
  - Example: `.disabled/comfyui_sigmoidoffsetscheduler@1_0_2`
- Nightly packages: `.disabled/{package_name_normalized}@nightly`
  - Example: `.disabled/comfyui_sigmoidoffsetscheduler@nightly`

**Key Points**:
- Package names are **normalized** (lowercase) in directory names
- Version dots are **replaced with underscores** (e.g., `1.0.2` → `1_0_2`)
- Disabled packages **preserve** their marker files (`.tracking` for CNR, `.git` for Nightly)
- Enable operation **moves packages back** from `.disabled/` to `custom_nodes/`

**Testing Implications**:
- Complex multi-version scenarios require **install → disable** sequences
- Fixture pattern: Install CNR → Disable → Install Nightly → Disable
- Tests must check `.disabled/` with **case-insensitive** searches
- Directory format must match normalized names with version suffixes

### Issue 4: Version Switch Mechanism
**Behavior**: Version switching uses a **slot-based system** with Nightly and Archive as separate slots.

**Slot-Based System Concept**:
- **Nightly Slot**: Git-based installation (one slot)
- **Archive Slot**: Registry-based installation (one slot)
- Only **one slot is active** at a time
- The inactive slot is stored in `.disabled/`
- Archive versions update **within the Archive slot**

**Two Types of Version Switch**:

**1. Slot Switch: Nightly ↔ Archive (uses `.disabled/` mechanism)**
- **Archive → Nightly**:
  - Archive (any version) → moved to `.disabled/ComfyUI_SigmoidOffsetScheduler`
  - Nightly → active in `custom_nodes/ComfyUI_SigmoidOffsetScheduler`

- **Nightly → Archive**:
  - Nightly → moved to `.disabled/ComfyUI_SigmoidOffsetScheduler`
  - Archive (any version) → **restored from `.disabled/`** and becomes active

**2. Version Update: Archive ↔ Archive (in-place update within Archive slot)**
- **1.0.1 → 1.0.2** (when Archive slot is active):
  - Directory contents updated in-place
  - pyproject.toml version updated: 1.0.1 → 1.0.2
  - `.tracking` file updated
  - NO `.disabled/` directory used

**3. Combined Operation: Nightly (active) + Archive 1.0 (disabled) → Archive 2.0**
- **Step 1 - Slot Switch**: Nightly → `.disabled/`, Archive 1.0 → active
- **Step 2 - Version Update**: Archive 1.0 → 2.0 (in-place within Archive slot)
- **Result**: Archive 2.0 active, Nightly in `.disabled/`

**Version Identification**:
- **Archive versions**: Use `pyproject.toml` version field
- **Nightly version**: pyproject.toml **ignored**, Git commit SHA used instead

**Key Points**:
- **Slot Switch** (Nightly ↔ Archive): `.disabled/` mechanism for enable/disable
- **Version Update** (Archive ↔ Archive): In-place content update within slot
- Archive installations have `.tracking` file
- Nightly installations have `.git` directory
- Only one slot is active at a time

### Issue 5: Version Selection Logic (RESOLVED)
**Problem**: When enabling a package with both CNR and Nightly versions disabled, the system would always enable CNR instead of respecting the user's choice.

**Root Cause** (manager_server.py:876-919):
- `do_enable()` was parsing `version_spec` from `cnr_id` (e.g., `packagename@nightly`)
- But it wasn't passing `version_spec` to `unified_enable()`
- This caused `unified_enable()` to use default version selection (latest CNR)

**Solution**:
```python
# Before (manager_server.py:876)
res = core.unified_manager.unified_enable(node_name)  # Missing version_spec!

# After (manager_server.py:876)
res = core.unified_manager.unified_enable(node_name, version_spec)  # ✅ Fixed
```

**API Usage**:
```python
# Enable CNR version (default or latest)
{"cnr_id": "ComfyUI_SigmoidOffsetScheduler"}

# Enable specific CNR version
{"cnr_id": "ComfyUI_SigmoidOffsetScheduler@1.0.1"}

# Enable Nightly version
{"cnr_id": "ComfyUI_SigmoidOffsetScheduler@nightly"}
```

**Version Selection Priority** (manager_core.py:get_inactive_pack):
1. Explicit version in cnr_id (e.g., `@nightly`, `@1.0.1`)
2. Latest CNR version (if available)
3. Nightly version (if no CNR available)
4. Unknown version (fallback)

**Files Modified**:
- `comfyui_manager/glob/manager_server.py` - Pass version_spec to unified_enable
- `comfyui_manager/common/node_package.py` - Parse @version from disabled directory names
- `comfyui_manager/glob/manager_core.py` - Fix is_disabled() early-return bug

**Status**: ✅ Resolved - All 42 tests passing

## Test Data

Test package: `ComfyUI_SigmoidOffsetScheduler`
- Package ID: `ComfyUI_SigmoidOffsetScheduler`
- CNR ID (lowercase): `comfyui_sigmoidoffsetscheduler`
- Version: `1.0.2`
- Nightly: Git clone from main branch

## Additional Documentation

### Test Execution Guide
- **[TESTING_GUIDE.md](./TESTING_GUIDE.md)** - Detailed guide for running tests, updating OpenAPI schemas, and troubleshooting

### Future Test Plans
- **[docs/internal/test_planning/](../../docs/internal/test_planning/)** - Planned but not yet implemented test scenarios

---

## Contributing

When adding new tests:
1. Follow pytest naming conventions (test_*.py, test_*)
2. Use fixtures for common setup/teardown
3. Add docstrings explaining test purpose
4. Update this README with test coverage information
5. For complex scenario tests, see [docs/internal/test_planning/](../../docs/internal/test_planning/)
