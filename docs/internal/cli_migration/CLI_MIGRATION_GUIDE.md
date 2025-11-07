# CLI Migration Guide: Legacy to Glob Module

**Status**: ✅ Completed (Historical Reference)
**Last Updated**: 2025-08-30
**Purpose**: Complete guide for migrating ComfyUI Manager CLI from legacy to glob module

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Legacy vs Glob Comparison](#legacy-vs-glob-comparison)
3. [Migration Strategy](#migration-strategy)
4. [Implementation Details](#implementation-details)
5. [Key Constraints](#key-constraints)
6. [API Reference](#api-reference-quick)
7. [Rollback Plan](#rollback-plan)

---

## Overview

### Objective
Migrate ComfyUI Manager CLI from legacy module to glob module using **only existing glob APIs** without modifying the glob module itself.

### Scope
- **Target File**: `comfyui_manager/cm_cli/__main__.py` (1305 lines)
- **Timeline**: 3.5 days
- **Approach**: Minimal CLI changes, maximum compatibility
- **Constraint**: ❌ NO glob module modifications

### Current State
```python
# Current imports (Lines 39-41)
from ..legacy import manager_core as core
from ..legacy.manager_core import unified_manager

# Target imports
from ..glob import manager_core as core
from ..glob.manager_core import unified_manager
```

---

## Legacy vs Glob Comparison

### Core Architecture Differences

#### Legacy Module (Current)
**Data Structure**: Dictionary-based global state
```python
unified_manager.active_nodes          # Active nodes dict
unified_manager.unknown_active_nodes  # Unknown active nodes
unified_manager.cnr_inactive_nodes    # Inactive CNR nodes
unified_manager.nightly_inactive_nodes # Inactive nightly nodes
unified_manager.unknown_inactive_nodes # Unknown inactive nodes
unified_manager.cnr_map               # CNR info mapping
```

#### Glob Module (Target)
**Data Structure**: Object-oriented with InstalledNodePackage
```python
unified_manager.installed_node_packages  # dict[str, list[InstalledNodePackage]]
unified_manager.repo_nodepack_map        # dict[str, InstalledNodePackage]
```

### Method Compatibility Matrix

| Method | Legacy | Glob | Status | Action |
|--------|--------|------|--------|--------|
| `unified_enable()` | ✅ | ✅ | Compatible | Direct mapping |
| `unified_disable()` | ✅ | ✅ | Compatible | Direct mapping |
| `unified_uninstall()` | ✅ | ✅ | Compatible | Direct mapping |
| `unified_update()` | ✅ | ✅ | Compatible | Direct mapping |
| `install_by_id()` | Sync | Async | Modified | Use asyncio.run() |
| `gitclone_install()` | ✅ | ❌ | Replaced | Use repo_install() |
| `get_custom_nodes()` | ✅ | ❌ | Removed | Use cnr_utils |
| `load_nightly()` | ✅ | ❌ | Removed | Not needed |
| `extract_nodes_from_workflow()` | ✅ | ❌ | Removed | Feature removed |

### InstalledNodePackage Class

```python
@dataclass
class InstalledNodePackage:
    id: str                 # Package identifier
    fullpath: str           # Full filesystem path
    disabled: bool          # Disabled status
    version: str            # Version (nightly/unknown/x.y.z)
    repo_url: str = None    # Repository URL
    
    # Properties
    @property
    def is_unknown(self) -> bool: return self.version == "unknown"
    
    @property  
    def is_nightly(self) -> bool: return self.version == "nightly"
    
    @property
    def is_from_cnr(self) -> bool: return not (self.is_unknown or self.is_nightly)
    
    @property
    def is_enabled(self) -> bool: return not self.disabled
    
    @property
    def is_disabled(self) -> bool: return self.disabled
```

---

## Migration Strategy

### Phase 1: Setup (0.5 day)
**Goal**: Basic migration with error identification

1. **Import Path Changes**
   ```python
   # Change 2 lines
   from ..glob import manager_core as core
   from ..glob.manager_core import unified_manager
   ```

2. **Initial Testing**
   - Run basic commands
   - Identify breaking changes
   - Document errors

3. **Error Analysis**
   - List all affected functions
   - Categorize by priority
   - Plan fixes

### Phase 2: Core Implementation (2 days)
**Goal**: Adapt CLI to glob architecture

1. **install_node() Updates**
   ```python
   # Replace gitclone_install with repo_install
   if unified_manager.is_url_like(node_spec_str):
       res = asyncio.run(unified_manager.repo_install(
           node_spec_str,
           os.path.basename(node_spec_str),
           instant_execution=True,
           no_deps=cmd_ctx.no_deps
       ))
   ```

2. **show_list() Rewrite** (Most complex change)
   - Migrate from dictionary-based to InstalledNodePackage-based
   - Implement installed-only approach with optional CNR lookup
   - See [show_list() Implementation](#show_list-implementation) section

3. **Context Management**
   - Update get_all_installed_node_specs()
   - Adapt to new data structures

4. **Data Structure Migration**
   - Replace all active_nodes references
   - Use installed_node_packages instead

### Phase 3: Final Testing (1 day)
**Goal**: Comprehensive validation

1. **Feature Removal**
   - Remove deps-in-workflow (not supported)
   - Stub unsupported features

2. **Testing**
   - Test all CLI commands
   - Verify output format
   - Check edge cases

3. **Polish**
   - Fix bugs
   - Improve error messages
   - Update help text

---

## Implementation Details

### show_list() Implementation

**Challenge**: Legacy uses multiple dictionaries, glob uses single InstalledNodePackage collection

**Solution**: Installed-only approach with on-demand CNR lookup

```python
def show_list(kind: str, simple: bool = False):
    """
    Display node package list
    
    Args:
        kind: 'installed', 'enabled', 'disabled', 'all'
        simple: If True, show simple format
    """
    
    # Get all installed packages
    all_packages = []
    for packages in unified_manager.installed_node_packages.values():
        all_packages.extend(packages)
    
    # Filter by kind
    if kind == "enabled":
        packages = [p for p in all_packages if p.is_enabled]
    elif kind == "disabled":
        packages = [p for p in all_packages if p.is_disabled]
    elif kind == "installed" or kind == "all":
        packages = all_packages
    else:
        print(f"Unknown kind: {kind}")
        return
    
    # Display
    if simple:
        for pkg in packages:
            print(pkg.id)
    else:
        # Detailed display with CNR info on-demand
        for pkg in packages:
            status = "disabled" if pkg.disabled else "enabled"
            version_info = f"v{pkg.version}" if pkg.version != "unknown" else "unknown"
            
            print(f"[{status}] {pkg.id} ({version_info})")
            
            # Optionally fetch CNR info for non-nightly packages
            if pkg.is_from_cnr and not simple:
                cnr_info = cnr_utils.get_nodepackage(pkg.id)
                if cnr_info:
                    print(f"  Description: {cnr_info.get('description', 'N/A')}")
```

**Key Changes**:
1. Single source of truth: `installed_node_packages`
2. No separate active/inactive dictionaries
3. On-demand CNR lookup instead of pre-cached cnr_map
4. Filter by InstalledNodePackage properties

### Git Installation Migration

**Before (Legacy)**:
```python
if core.is_valid_url(node_spec_str):
    res = asyncio.run(core.gitclone_install(
        node_spec_str, 
        no_deps=cmd_ctx.no_deps
    ))
```

**After (Glob)**:
```python
if unified_manager.is_url_like(node_spec_str):
    res = asyncio.run(unified_manager.repo_install(
        node_spec_str,
        os.path.basename(node_spec_str),  # repo_path derived from URL
        instant_execution=True,            # Execute immediately
        no_deps=cmd_ctx.no_deps           # Respect --no-deps flag
    ))
```

### Async Function Handling

**Pattern**: Wrap async glob methods with asyncio.run()

```python
# install_by_id is async in glob
res = asyncio.run(unified_manager.install_by_id(
    packname=node_name,
    version_spec=version,
    instant_execution=True,
    no_deps=cmd_ctx.no_deps
))
```

---

## Key Constraints

### Hard Constraints (Cannot Change)
1. ❌ **No glob module modifications**
   - Cannot add new methods to UnifiedManager
   - Cannot add compatibility properties
   - Must use existing APIs only

2. ❌ **No legacy dependencies**
   - CLI must work without legacy module
   - Clean break from old architecture

3. ❌ **Maintain CLI interface**
   - Command syntax unchanged
   - Output format similar (minor differences acceptable)

### Soft Constraints (Acceptable Trade-offs)
1. ✅ **Feature removal acceptable**
   - deps-in-workflow feature can be removed
   - Channel/mode support can be simplified

2. ✅ **Performance trade-offs acceptable**
   - On-demand CNR lookup vs pre-cached
   - Slight performance degradation acceptable

3. ✅ **Output format flexibility**
   - Minor formatting differences acceptable
   - Must remain readable and useful

---

## API Reference (Quick)

### UnifiedManager Core Methods

```python
# Installation
async def install_by_id(packname, version_spec, instant_execution, no_deps) -> ManagedResult

# Git/URL installation  
async def repo_install(url, repo_path, instant_execution, no_deps) -> ManagedResult

# Enable/Disable
def unified_enable(packname, version_spec=None) -> ManagedResult
def unified_disable(packname) -> ManagedResult

# Update/Uninstall
def unified_update(packname, instant_execution, no_deps) -> ManagedResult
def unified_uninstall(packname) -> ManagedResult

# Query
def get_active_pack(packname) -> InstalledNodePackage | None
def get_inactive_pack(packname, version_spec) -> InstalledNodePackage | None
def resolve_node_spec(packname, guess_mode) -> NodeSpec

# Utility
def is_url_like(text) -> bool
```

### Data Access

```python
# Installed packages
unified_manager.installed_node_packages: dict[str, list[InstalledNodePackage]]

# Repository mapping
unified_manager.repo_nodepack_map: dict[str, InstalledNodePackage]
```

### External Utilities

```python
# CNR utilities
from ..common import cnr_utils
cnr_utils.get_nodepackage(id) -> dict
cnr_utils.get_all_nodepackages() -> list[dict]
```

For complete API reference, see [CLI_API_REFERENCE.md](CLI_API_REFERENCE.md)

---

## Rollback Plan

### If Migration Fails

1. **Immediate Rollback** (< 5 minutes)
   ```python
   # Revert imports in __main__.py
   from ..legacy import manager_core as core
   from ..legacy.manager_core import unified_manager
   ```

2. **Verify Rollback**
   ```bash
   # Test basic commands
   cm-cli show installed
   cm-cli install <package>
   ```

3. **Document Issues**
   - Note what failed
   - Gather error logs
   - Plan fixes

### Risk Mitigation

1. **Backup**: Keep legacy module available
2. **Testing**: Comprehensive test suite before deployment
3. **Staging**: Test in non-production environment first
4. **Monitoring**: Watch for errors after deployment

---

## Success Criteria

### Must Pass (Blockers)
- ✅ All core commands functional (install, update, enable, disable, uninstall)
- ✅ Package information displays correctly
- ✅ No glob module modifications
- ✅ No critical regressions

### Should Pass (Important)
- ✅ Output format similar to legacy
- ✅ Performance comparable to legacy
- ✅ User-friendly error messages
- ✅ Help text updated

### Nice to Have
- ✅ Improved code structure
- ✅ Better error handling
- ✅ Type hints added

---

## Reference Documents

- **[CLI_API_REFERENCE.md](CLI_API_REFERENCE.md)** - Complete API documentation
- **[CLI_IMPLEMENTATION_CHECKLIST.md](CLI_IMPLEMENTATION_CHECKLIST.md)** - Step-by-step tasks
- **[CLI_TESTING_GUIDE.md](CLI_TESTING_GUIDE.md)** - Testing strategy

---

## Conclusion

The CLI migration from legacy to glob module is achievable through systematic adaptation of CLI code to glob's object-oriented architecture. The key is respecting the constraint of no glob modifications while leveraging existing glob APIs effectively.

**Status**: This migration has been completed successfully. The CLI now uses glob module exclusively.
