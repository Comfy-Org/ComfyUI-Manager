# Future Test Plans

**Type**: Planning Document (Future Tests)
**Status**: P1 tests COMPLETE ✅ - Additional scenarios remain planned
**Current Implementation Status**: See [tests/glob/README.md](../../../tests/glob/README.md)

**Last Updated**: 2025-11-06

---

## Overview

This document contains test scenarios that are **planned but not yet implemented**. For currently implemented tests, see [tests/glob/README.md](../../../tests/glob/README.md).

**Currently Implemented**: 51 tests ✅ (includes all P1 complex scenarios)
**P1 Implementation**: COMPLETE ✅ (Phase 3.1, 5.1, 5.2, 5.3, 6)
**Planned in this document**: Additional scenarios for comprehensive coverage (P0, P2)

---

## 📋 Table of Contents

1. [Simple Test Scenarios](#simple-test-scenarios) - Additional basic API tests
2. [Complex Multi-Version Scenarios](#complex-multi-version-scenarios) - Advanced state management tests
3. [Priority Matrix](#priority-matrix) - Implementation priorities

---

# Simple Test Scenarios

These are straightforward single-version/type test scenarios that extend the existing test suite.

## 3. Error Handling Testing (Priority: Medium)

### Test 3.1: Install Non-existent Package
**Purpose**: Handle invalid package names

**Steps**:
1. Attempt to install with non-existent package ID
2. Verify appropriate error message

**Verification Items**:
- ✓ Error status returned
- ✓ Clear error message
- ✓ No server crash

### Test 3.2: Invalid Version Specification
**Purpose**: Handle non-existent version installation attempts

**Steps**:
1. Attempt to install with non-existent version (e.g., "99.99.99")
2. Verify error handling

**Verification Items**:
- ✓ Error status returned
- ✓ Clear error message

### Test 3.3: Permission Error Simulation
**Purpose**: Handle file system permission issues

**Steps**:
1. Set custom_nodes directory to read-only
2. Attempt package installation
3. Verify error handling
4. Restore permissions

**Verification Items**:
- ✓ Permission error detected
- ✓ Clear error message
- ✓ Partial installation rollback

---

## 4. Dependency Management Testing (Priority: Medium)

### Test 4.1: Installation with Dependencies
**Purpose**: Automatic installation of dependencies from packages with requirements.txt

**Steps**:
1. Install package with dependencies
2. Verify requirements.txt processing
3. Verify dependency packages installed

**Verification Items**:
- ✓ requirements.txt executed
- ✓ Dependency packages installed
- ✓ Installation scripts executed

### Test 4.2: no_deps Flag Testing
**Purpose**: Verify option to skip dependency installation

**Steps**:
1. Install package with no_deps=true
2. Verify requirements.txt skipped
3. Verify installation scripts skipped

**Verification Items**:
- ✓ Dependency installation skipped
- ✓ Only package files installed

---

## 5. Multi-package Management Testing (Priority: Medium)

### Test 5.1: Concurrent Multiple Package Installation
**Purpose**: Concurrent installation of multiple independent packages

**Steps**:
1. Add 3 different packages to queue
2. Start queue
3. Verify all packages installed

**Verification Items**:
- ✓ All packages installed successfully
- ✓ Installation order guaranteed
- ✓ Individual failures don't affect other packages

### Test 5.2: Same Package Concurrent Installation (Conflict Handling)
**Purpose**: Handle concurrent requests for same package

**Steps**:
1. Add same package to queue twice
2. Start queue
3. Verify duplicate handling

**Verification Items**:
- ✓ First installation successful
- ✓ Second request skipped
- ✓ Handled without errors

---

## 6. Security Level Testing (Priority: Low)

### Test 6.1: Installation Restrictions by Security Level
**Purpose**: Allow/deny installation based on security_level settings

**Steps**:
1. Set security_level to "strong"
2. Attempt installation with non-CNR registered URL
3. Verify rejection

**Verification Items**:
- ✓ Security level validation
- ✓ Appropriate error message

---

# Complex Multi-Version Scenarios

These scenarios test complex interactions between multiple versions and types of the same package.

## Test Philosophy

### Real-World Scenarios
1. User switches from Nightly to CNR
2. Install both CNR and Nightly, activate only one
3. Keep multiple versions in .disabled/ and switch as needed
4. Other versions exist in disabled state during Update

---

## Phase 7: Complex Version Switch Chains (Priority: High)

### Test 7.1: CNR Old Enabled → CNR New (Other Versions Disabled)
**Initial State:**
```
custom_nodes/:
  └── ComfyUI_SigmoidOffsetScheduler/  (CNR 1.0.1)
.disabled/:
  ├── ComfyUI_SigmoidOffsetScheduler_1.0.0/
  └── ComfyUI_SigmoidOffsetScheduler_nightly/
```

**Operation:** Install CNR v1.0.2 (version switch)

**Expected Result:**
```
custom_nodes/:
  └── ComfyUI_SigmoidOffsetScheduler/  (CNR 1.0.2)
.disabled/:
  ├── ComfyUI_SigmoidOffsetScheduler_1.0.0/
  ├── ComfyUI_SigmoidOffsetScheduler_1.0.1/  (old enabled version)
  └── ComfyUI_SigmoidOffsetScheduler_nightly/
```

**Verification Items:**
- ✓ Existing enabled version auto-disabled
- ✓ New version enabled
- ✓ All disabled versions maintained
- ✓ Version history managed

### Test 7.2: Version Switch Chain (Nightly → CNR Old → CNR New)
**Scenario:** Sequential version transitions

**Step 1:** Nightly enabled
**Step 2:** Switch to CNR 1.0.1
**Step 3:** Switch to CNR 1.0.2

**Verification Items:**
- ✓ Each transition step operates normally
- ✓ Version history accumulates
- ✓ Rollback-capable state maintained

---

## Phase 8: Edge Cases & Error Scenarios (Priority: Medium)

### Test 8.1: Corrupted Package in .disabled/
**Situation:** Corrupted package exists in .disabled/

**Operation:** Attempt Enable

**Expected Result:**
- Clear error message
- Fallback to other version (if possible)
- System stability maintained

### Test 8.2: Name Collision in .disabled/
**Situation:** Package with same name already exists in .disabled/

**Operation:** Attempt Disable

**Expected Result:**
- Generate unique name (timestamp, etc.)
- No data loss
- All versions distinguishable

### Test 8.3: Enable Non-existent Version
**Situation:** Requested version not in .disabled/

**Operation:** Enable specific version

**Expected Result:**
- Clear error message
- Available version list provided
- Graceful failure

---

# Priority Matrix

**Note**: Phases 3, 4, 5, and 6 are now complete and documented in [tests/glob/README.md](../../../tests/glob/README.md). This matrix shows only planned future tests.

| Phase | Scenario | Priority | Status | Complexity | Real-World Frequency |
|-------|----------|----------|--------|------------|---------------------|
| 7 | Complex Version Switch Chains | P0 | 🔄 PARTIAL | High | High |
| 8 | Edge Cases & Error Scenarios | P2 | ⏳ PLANNED | High | Low |
| Simple | Error Handling (3.1-3.3) | P2 | ⏳ PLANNED | Medium | Medium |
| Simple | Dependency Management (4.1-4.2) | P2 | ⏳ PLANNED | Medium | Medium |
| Simple | Multi-package Management (5.1-5.2) | P2 | ⏳ PLANNED | Medium | Low |
| Simple | Security Level Testing (6.1) | P2 | ⏳ PLANNED | Low | Low |

**Priority Definitions:**
- **P0:** High priority (implement next) - Phase 7 Complex Version Switch
- **P1:** Medium priority - ✅ **ALL COMPLETE** (Phase 3, 4, 5, 6 - see tests/glob/README.md)
- **P2:** Low priority (implement as needed) - Simple tests and Phase 8

**Status Definitions:**
- 🔄 PARTIAL: Some tests implemented (Phase 7 has version switching tests in test_version_switching_comprehensive.py)
- ⏳ PLANNED: Not yet started

**Recommended Next Steps:**
1. **Phase 7 Remaining Tests** (P0) - Complex version switch chains with multiple disabled versions
2. **Simple Test Scenarios** (P2) - Error handling, dependency management, multi-package operations
3. **Phase 8** (P2) - Edge cases and error scenarios

---

# Implementation Notes

## Fixture Patterns

For multi-version tests, use these fixture patterns:

```python
@pytest.fixture
def setup_multi_disabled_cnr_and_nightly(api_client, custom_nodes_path):
    """
    Install both CNR and Nightly in disabled state.

    Pattern:
    1. Install CNR → custom_nodes/
    2. Disable CNR → .disabled/comfyui_sigmoidoffsetscheduler@1_0_2
    3. Install Nightly → custom_nodes/
    4. Disable Nightly → .disabled/comfyui_sigmoidoffsetscheduler@nightly
    """
    # Implementation details in archived COMPLEX_SCENARIOS_TEST_PLAN.md
```

## Verification Helpers

Use these verification patterns:

```python
def verify_version_state(custom_nodes_path, expected_state):
    """
    Verify package state matches expectations.

    expected_state = {
        'enabled': {'type': 'cnr' | 'nightly' | None, 'version': '1.0.2'},
        'disabled': [
            {'type': 'cnr', 'version': '1.0.1'},
            {'type': 'nightly'}
        ]
    }
    """
    # Implementation details in archived COMPLEX_SCENARIOS_TEST_PLAN.md
```

---

# References

## Archived Implementation Guides

Detailed implementation examples, code snippets, and fixtures are available in archived planning documents:
- `.claude/archive/docs_2025-11-04/COMPLEX_SCENARIOS_TEST_PLAN.md` - Complete implementation guide with code examples
- `.claude/archive/docs_2025-11-04/TEST_PLAN_ADDITIONAL.md` - Simple test scenarios

## Current Implementation

For currently implemented tests and their status:
- **[tests/glob/README.md](../../../tests/glob/README.md)** - Current test status and coverage

---

**End of Future Test Plans**
