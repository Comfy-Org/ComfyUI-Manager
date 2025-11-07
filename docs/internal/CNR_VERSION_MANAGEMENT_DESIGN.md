# CNR Version Management Design

**Version**: 1.1
**Date**: 2025-11-08
**Status**: Official Design Policy

## Overview

This document describes the official design policy for CNR (ComfyUI Node Registry) version management in ComfyUI Manager.

## Core Design Principles

### 1. In-Place Upgrade Policy

**Policy**: CNR upgrades are performed as **in-place replacements** without version history preservation.

**Rationale**:
- **Simplicity**: Single version management is easier for users and maintainers
- **Disk Space**: Prevents accumulation of old package versions
- **Clear State**: Users always know which version is active
- **Consistency**: Same behavior for enabled and disabled states

**Behavior**:
```
Before: custom_nodes/PackageName/ (CNR v1.0.1 with .tracking)
Action: Install CNR v1.0.2
After:  custom_nodes/PackageName/ (CNR v1.0.2 with .tracking)
Result: Old v1.0.1 REMOVED (not preserved)
```

### 2. Single CNR Version Policy

**Policy**: Only **ONE CNR version** exists at any given time (either enabled OR disabled, never both).

**Rationale**:
- **State Clarity**: No ambiguity about which CNR version is current
- **Resource Management**: Minimal disk usage
- **User Experience**: Clear version state without confusion
- **Design Consistency**: Uniform handling across operations

**States**:
- **Enabled**: `custom_nodes/PackageName/` (with `.tracking`)
- **Disabled**: `.disabled/packagename@version/` (with `.tracking`)
- **Never**: Multiple CNR versions coexisting

### 3. CNR vs Nightly Differentiation

**Policy**: Different handling for CNR and Nightly packages based on use cases.

| Aspect | CNR Packages (`.tracking`) | Nightly Packages (`.git`) |
|--------|----------------------------|---------------------------|
| **Purpose** | Stable releases | Development versions |
| **Preservation** | Not preserved (in-place upgrade) | Preserved (multiple versions) |
| **Version Policy** | Single version only | Multiple versions allowed |
| **Use Case** | Production use | Testing and development |

**Rationale**:
- **CNR**: Stable releases don't need version history; users want single stable version
- **Nightly**: Development versions benefit from multiple versions for testing

### 4. API Response Priority Rules

**Policy**: The `/v2/customnode/installed` API applies two priority rules to prevent duplicate package entries and ensure clear state representation.

**Rule 1 (Enabled-Priority)**:
- **Policy**: When both enabled and disabled versions of the same package exist → Return ONLY the enabled version
- **Rationale**: Prevents frontend confusion from duplicate package entries
- **Implementation**: `comfyui_manager/glob/manager_core.py:1801` in `get_installed_nodepacks()`

**Rule 2 (CNR-Priority for Disabled Packages)**:
- **Policy**: When both CNR and Nightly versions are disabled → Return ONLY the CNR version
- **Rationale**: CNR versions are stable releases and should be preferred over development Nightly builds when both are inactive
- **Implementation**: `comfyui_manager/glob/manager_core.py:1801` in `get_installed_nodepacks()`

**Priority Matrix**:

| Scenario | Enabled Versions | Disabled Versions | API Response |
|----------|------------------|-------------------|--------------|
| 1. CNR enabled only | CNR v1.0.1 | None | CNR v1.0.1 (`enabled: true`) |
| 2. CNR enabled + Nightly disabled | CNR v1.0.1 | Nightly | **Only CNR v1.0.1** (`enabled: true`) ← Rule 1 |
| 3. Nightly enabled + CNR disabled | Nightly | CNR v1.0.1 | **Only Nightly** (`enabled: true`) ← Rule 1 |
| 4. CNR disabled + Nightly disabled | None | CNR v1.0.1, Nightly | **Only CNR v1.0.1** (`enabled: false`) ← Rule 2 |
| 5. Different packages disabled | None | PackageA, PackageB | Both packages (`enabled: false`) |

**Test Coverage**:
- `tests/glob/test_installed_api_enabled_priority.py`
  - `test_installed_api_shows_only_enabled_when_both_exist` - Verifies Rule 1
  - `test_installed_api_cnr_priority_when_both_disabled` - Verifies Rule 2

## Detailed Behavior Specifications

### CNR Upgrade (Enabled → Enabled)

**Scenario**: Upgrading from CNR v1.0.1 to v1.0.2 when v1.0.1 is enabled

```
Initial State:
  custom_nodes/PackageName/  (CNR v1.0.1 with .tracking)

Action:
  Install CNR v1.0.2

Process:
  1. Download CNR v1.0.2
  2. Remove existing custom_nodes/PackageName/
  3. Install CNR v1.0.2 to custom_nodes/PackageName/
  4. Create .tracking file

Final State:
  custom_nodes/PackageName/  (CNR v1.0.2 with .tracking)

Result:
  ✓ v1.0.2 installed and enabled
  ✓ v1.0.1 completely removed
  ✓ No version history preserved
```

### CNR Switch from Disabled

**Scenario**: Switching from disabled CNR v1.0.1 to CNR v1.0.2

```
Initial State:
  custom_nodes/PackageName/  (Nightly with .git)
  .disabled/packagename@1_0_1/  (CNR v1.0.1 with .tracking)

User Action:
  Install CNR v1.0.2

Process:
  Step 1: Enable disabled CNR v1.0.1
    - Move .disabled/packagename@1_0_1/ → custom_nodes/PackageName/
    - Move custom_nodes/PackageName/ → .disabled/packagename@nightly/

  Step 2: Upgrade CNR v1.0.1 → v1.0.2 (in-place)
    - Download CNR v1.0.2
    - Remove custom_nodes/PackageName/
    - Install CNR v1.0.2 to custom_nodes/PackageName/

Final State:
  custom_nodes/PackageName/  (CNR v1.0.2 with .tracking)
  .disabled/packagename@nightly/  (Nightly preserved)

Result:
  ✓ CNR v1.0.2 installed and enabled
  ✓ CNR v1.0.1 removed (not preserved in .disabled/)
  ✓ Nightly preserved in .disabled/
```

### CNR Disable

**Scenario**: Disabling CNR v1.0.1 when Nightly exists

```
Initial State:
  custom_nodes/PackageName/  (CNR v1.0.1 with .tracking)

Action:
  Disable CNR v1.0.1

Final State:
  .disabled/packagename@1_0_1/  (CNR v1.0.1 with .tracking)

Note:
  - Only ONE disabled CNR version exists
  - If another CNR is already disabled, it is replaced
```

### Nightly Installation (with CNR Disabled)

**Scenario**: Installing Nightly when CNR v1.0.1 is disabled

```
Initial State:
  .disabled/packagename@1_0_1/  (CNR v1.0.1 with .tracking)

Action:
  Install Nightly

Final State:
  custom_nodes/PackageName/  (Nightly with .git)
  .disabled/packagename@1_0_1/  (CNR v1.0.1 preserved)

Result:
  ✓ Nightly installed and enabled
  ✓ Disabled CNR v1.0.1 preserved (not removed)
  ✓ Different handling for Nightly vs CNR
```

## Implementation Requirements

### CNR Install/Upgrade Operation

1. **Check for existing CNR versions**:
   - Enabled: `custom_nodes/PackageName/` with `.tracking`
   - Disabled: `.disabled/*` with `.tracking`

2. **Remove old CNR versions**:
   - If enabled CNR exists: Remove it
   - If disabled CNR exists: Remove it
   - Ensure only ONE CNR version will exist after operation

3. **Install new CNR version**:
   - Download and extract to target location
   - Create `.tracking` file
   - Register in package database

4. **Preserve Nightly packages**:
   - Do NOT remove packages with `.git` directory
   - Nightly packages should be preserved in `.disabled/`

### CNR Disable Operation

1. **Move enabled CNR to disabled**:
   - Move `custom_nodes/PackageName/` → `.disabled/packagename@version/`
   - Use **installed version** for directory name (not registry latest)

2. **Remove any existing disabled CNR**:
   - Only ONE disabled CNR version allowed
   - If another CNR already in `.disabled/`, remove it first

3. **Preserve disabled Nightly**:
   - Do NOT remove disabled Nightly packages
   - Multiple Nightly versions can coexist in `.disabled/`

### CNR Enable Operation

1. **Check for enabled package**:
   - If another package enabled, disable it first

2. **Move disabled CNR to enabled**:
   - Move `.disabled/packagename@version/` → `custom_nodes/PackageName/`

3. **Maintain single CNR policy**:
   - After enable, no CNR should remain in `.disabled/`
   - Only Nightly packages should remain in `.disabled/`

## Test Coverage

### Phase 7: Version Management Behavior Tests

**Test 7.1: `test_cnr_version_upgrade_removes_old`**
- ✅ Verifies in-place upgrade removes old CNR version
- ✅ Confirms only one CNR version exists after upgrade
- ✅ Documents single version policy

**Test 7.2: `test_cnr_nightly_switching_preserves_nightly_only`**
- ✅ Verifies Nightly preservation across CNR upgrades
- ✅ Confirms old CNR versions removed (not preserved)
- ✅ Documents different handling for CNR vs Nightly

### Other Relevant Tests

**Phase 1-6 Tests**:
- ✅ All tests comply with single CNR version policy
- ✅ No tests assume multiple CNR versions coexist
- ✅ Fixtures properly handle CNR vs Nightly differences

## Known Behaviors

### Correct Behaviors (By Design)

1. **CNR Upgrades Remove Old Versions**
   - Status: ✅ Intentional design
   - Reason: In-place upgrade policy
   - Test: Phase 7.1 verifies this

2. **Only One CNR Version Exists**
   - Status: ✅ Intentional design
   - Reason: Single version policy
   - Test: Phase 7.2 verifies this

3. **Nightly Preserved, CNR Not**
   - Status: ✅ Intentional design
   - Reason: Different use cases
   - Test: Phase 7.2 verifies this

### Known Issues

1. **Disable API Version Mismatch**
   - Status: ⚠️ Bug to be fixed
   - Issue: Disabled directory name uses registry latest instead of installed version
   - Impact: Incorrect directory naming
   - Priority: Medium

## Design Rationale

### Why In-Place Upgrade?

**Benefits**:
- Simple mental model for users
- No disk space accumulation
- Clear version state
- Easier maintenance

**Trade-offs**:
- No automatic rollback capability
- Users must reinstall old versions from registry
- Network required for version downgrades

**Decision**: Benefits outweigh trade-offs for stable release management.

### Why Different CNR vs Nightly Handling?

**CNR (Stable Releases)**:
- Users want single stable version
- Production use case
- Rollback via registry if needed

**Nightly (Development Builds)**:
- Developers test multiple versions
- Development use case
- Local version testing important

**Decision**: Different use cases justify different policies.

## Future Considerations

### Potential Enhancements (Not Currently Planned)

1. **Optional Version History**
   - Configurable preservation of last N versions
   - Opt-in via configuration flag
   - Separate history directory

2. **CNR Rollback API**
   - Dedicated rollback endpoint
   - Re-download from registry
   - Preserve current version before downgrade

3. **Version Pinning**
   - Pin specific CNR version
   - Prevent automatic upgrades
   - Per-package configuration

**Note**: These are potential future enhancements, not current requirements.

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.1 | 2025-11-08 | Added API Response Priority Rules (Rule 1: Enabled-Priority, Rule 2: CNR-Priority) |
| 1.0 | 2025-11-06 | Initial design document based on user clarification |

## References

- Phase 7 Test Implementation: `tests/glob/test_complex_scenarios.py`
- Policy Clarification: `.claude/livecontext/cnr_version_policy_clarification.md`
- Bug Report: `.claude/livecontext/bugs_to_file.md`

---

**Approved By**: User feedback 2025-11-06
**Status**: Official Policy
**Compliance**: All tests verified against this policy
