# CLI Migration Testing Checklist

## 🧪 Testing Strategy Overview
**Approach**: Progressive testing at each implementation phase  
**Tools**: Manual CLI testing, comparison with legacy behavior  
**Environment**: ComfyUI development environment with test packages

---

# 📋 Phase 1 Testing (Import Changes)

## ✅ Basic CLI Loading (Must Pass)
```bash
# Test CLI loads without import errors
python -m comfyui_manager.cm_cli --help
python -m comfyui_manager.cm_cli help

# Expected: CLI help displays, no ImportError exceptions
```

## ✅ Simple Command Smoke Tests
```bash
# Commands that should work immediately
python -m comfyui_manager.cm_cli show snapshot
python -m comfyui_manager.cm_cli clear

# Expected: Commands execute, may show different output but no crashes
```

## 🐛 Error Identification
- [ ] Document all import-related errors
- [ ] Identify which functions fail immediately  
- [ ] Note any missing attributes/methods used by CLI
- [ ] List functions that need immediate attention

**Pass Criteria**: CLI loads and basic commands don't crash

---

# 🔧 Phase 2 Testing (Core Functions)

## 🚀 Install Command Testing

### CNR Package Installation
```bash
# Test CNR package installation
python -m comfyui_manager.cm_cli install ComfyUI-Manager
python -m comfyui_manager.cm_cli install <known-cnr-package>

# Expected behaviors:
# - Package resolves correctly
# - Installation proceeds
# - Success/failure message displayed
# - Package appears in enabled state
```
**Test Cases**:
- [ ] Install new CNR package
- [ ] Install already-installed package (should skip)
- [ ] Install non-existent package (should error gracefully)
- [ ] Install with `--no-deps` flag

### Git URL Installation  
```bash
# Test Git URL installation
python -m comfyui_manager.cm_cli install https://github.com/user/repo.git
python -m comfyui_manager.cm_cli install https://github.com/user/repo

# Expected behaviors:
# - URL detected as Git repository
# - repo_install() method called
# - Installation proceeds or fails gracefully
```
**Test Cases**:
- [ ] Install from Git URL with .git suffix
- [ ] Install from Git URL without .git suffix
- [ ] Install from invalid Git URL (should error)
- [ ] Install from private repository (may fail gracefully)

## 📊 Show Commands Testing

### Show Installed/Enabled
```bash
python -m comfyui_manager.cm_cli show installed
python -m comfyui_manager.cm_cli show enabled

# Expected: List of enabled packages with:
# - Package names
# - Version information  
# - Author/publisher info where available
# - Correct status indicators
```

### Show Disabled/Not-Installed
```bash  
python -m comfyui_manager.cm_cli show disabled
python -m comfyui_manager.cm_cli show not-installed

# Expected: Appropriate package lists with status
```

### Show All & Simple Mode
```bash
python -m comfyui_manager.cm_cli show all
python -m comfyui_manager.cm_cli simple-show all

# Expected: Comprehensive package list
# Simple mode should show condensed format
```

**Detailed Test Matrix**:
- [ ] `show installed` - displays all installed packages
- [ ] `show enabled` - displays only enabled packages  
- [ ] `show disabled` - displays only disabled packages
- [ ] `show not-installed` - displays available but not installed packages
- [ ] `show all` - displays comprehensive list
- [ ] `show cnr` - displays CNR packages only
- [ ] `simple-show` variants - condensed output format

**Validation Criteria**:
- [ ] Package counts make sense (enabled + disabled = installed)
- [ ] CNR packages show publisher information
- [ ] Nightly packages marked appropriately
- [ ] Unknown packages handled correctly
- [ ] No crashes with empty package sets

## ⚙️ Management Commands Testing

### Enable/Disable Commands
```bash
# Enable disabled package
python -m comfyui_manager.cm_cli disable <package-name>
python -m comfyui_manager.cm_cli show disabled  # Should appear
python -m comfyui_manager.cm_cli enable <package-name>
python -m comfyui_manager.cm_cli show enabled   # Should appear

# Test edge cases  
python -m comfyui_manager.cm_cli enable <already-enabled-package>  # Should skip
python -m comfyui_manager.cm_cli disable <non-existent-package>    # Should error
```

**Test Cases**:
- [ ] Enable disabled package
- [ ] Disable enabled package
- [ ] Enable already-enabled package (skip)
- [ ] Disable already-disabled package (skip)
- [ ] Enable non-existent package (error)
- [ ] Disable non-existent package (error)

### Uninstall Commands
```bash
# Uninstall package
python -m comfyui_manager.cm_cli uninstall <test-package>
python -m comfyui_manager.cm_cli show installed  # Should not appear

# Test variations
python -m comfyui_manager.cm_cli uninstall <package>@unknown
```

**Test Cases**:
- [ ] Uninstall CNR package
- [ ] Uninstall nightly package  
- [ ] Uninstall unknown package
- [ ] Uninstall non-existent package (should error gracefully)

### Update Commands
```bash
# Update specific package
python -m comfyui_manager.cm_cli update <package-name>

# Update all packages
python -m comfyui_manager.cm_cli update all
```

**Test Cases**:
- [ ] Update single package
- [ ] Update all packages
- [ ] Update non-existent package (should error)
- [ ] Update already up-to-date package (should skip)

## 🗃️ Advanced Function Testing

### get_all_installed_node_specs()
```bash
# This function is used internally by update/enable/disable "all" commands
python -m comfyui_manager.cm_cli update all
python -m comfyui_manager.cm_cli enable all  
python -m comfyui_manager.cm_cli disable all

# Expected: Commands process all installed packages
```

**Validation**:
- [ ] "all" commands process expected number of packages
- [ ] Package specs format correctly (name@version)
- [ ] No duplicates in package list
- [ ] All package types included (CNR, nightly, unknown)

---

# 🧹 Phase 3 Testing (Feature Removal & Polish)

## ❌ Removed Feature Testing

### deps-in-workflow Command
```bash  
python -m comfyui_manager.cm_cli deps-in-workflow workflow.json deps.json

# Expected: Clear error message explaining feature removal
# Should NOT crash or show confusing errors
```

### install-deps Command (if affected)
```bash
python -m comfyui_manager.cm_cli install-deps deps.json

# Expected: Either works with alternative implementation or shows clear error
```

**Validation**:
- [ ] Error messages are user-friendly
- [ ] No stack traces for removed features
- [ ] Help text updated to reflect changes
- [ ] Alternative solutions mentioned where applicable

## 📸 Snapshot Functionality  

### Save/Restore Snapshots
```bash
# Save snapshot
python -m comfyui_manager.cm_cli save-snapshot test-snapshot.json
ls snapshots/  # Should show new snapshot

# Restore snapshot  
python -m comfyui_manager.cm_cli restore-snapshot test-snapshot.json
```

**Test Cases**:
- [ ] Save snapshot to default location
- [ ] Save snapshot to custom path
- [ ] Restore snapshot successfully
- [ ] Handle invalid snapshot files gracefully

### Snapshot Display
```bash
python -m comfyui_manager.cm_cli show snapshot
python -m comfyui_manager.cm_cli show snapshot-list
```

**Validation**:
- [ ] Current state displayed correctly
- [ ] Snapshot list shows available snapshots
- [ ] JSON format valid and readable

---

# 🎯 Comprehensive Integration Testing

## 🔄 End-to-End Workflows

### Complete Package Lifecycle
```bash
# 1. Install package
python -m comfyui_manager.cm_cli install <test-package>

# 2. Verify installation
python -m comfyui_manager.cm_cli show enabled | grep <test-package>

# 3. Disable package
python -m comfyui_manager.cm_cli disable <test-package>  

# 4. Verify disabled
python -m comfyui_manager.cm_cli show disabled | grep <test-package>

# 5. Re-enable package
python -m comfyui_manager.cm_cli enable <test-package>

# 6. Update package
python -m comfyui_manager.cm_cli update <test-package>

# 7. Uninstall package
python -m comfyui_manager.cm_cli uninstall <test-package>

# 8. Verify removal
python -m comfyui_manager.cm_cli show installed | grep <test-package>  # Should be empty
```

### Batch Operations
```bash
# Install multiple packages
python -m comfyui_manager.cm_cli install package1 package2 package3

# Disable all packages  
python -m comfyui_manager.cm_cli disable all

# Enable all packages
python -m comfyui_manager.cm_cli enable all

# Update all packages
python -m comfyui_manager.cm_cli update all
```

## 🚨 Error Condition Testing

### Network/Connectivity Issues
- [ ] Test with no internet connection
- [ ] Test with slow internet connection
- [ ] Test with CNR API unavailable

### File System Issues  
- [ ] Test with insufficient disk space
- [ ] Test with permission errors
- [ ] Test with corrupted package directories

### Invalid Input Handling
- [ ] Non-existent package names
- [ ] Invalid Git URLs
- [ ] Malformed command arguments
- [ ] Special characters in package names

---

# 📊 Performance & Regression Testing

## ⚡ Performance Comparison
```bash
# Time core operations
time python -m comfyui_manager.cm_cli show all
time python -m comfyui_manager.cm_cli install <test-package>
time python -m comfyui_manager.cm_cli update all

# Compare with legacy timings if available
```

**Validation**:
- [ ] Operations complete in reasonable time
- [ ] No significant performance regression
- [ ] Memory usage acceptable

## 🔄 Regression Testing

### Output Format Comparison
- [ ] Compare show command output with legacy version
- [ ] Document acceptable format differences  
- [ ] Ensure essential information preserved

### Behavioral Consistency
- [ ] Command success/failure behavior matches legacy
- [ ] Error message quality comparable to legacy
- [ ] User experience remains smooth

---

# ✅ Final Validation Checklist

## Must Pass (Blockers)
- [ ] All core commands functional (install/uninstall/enable/disable/update)
- [ ] Show commands display accurate package information
- [ ] No crashes or unhandled exceptions
- [ ] No modifications to glob module
- [ ] CLI loads and responds to help commands

## Should Pass (Important)  
- [ ] Output format reasonably similar to legacy
- [ ] Performance comparable to legacy
- [ ] Error handling graceful and informative
- [ ] Removed features clearly communicated

## May Pass (Nice to Have)
- [ ] Output format identical to legacy
- [ ] Performance better than legacy
- [ ] Additional error recovery features
- [ ] Code improvements and cleanup

---

# 🧰 Testing Tools & Commands

## Essential Test Commands
```bash
# Quick smoke test
python -m comfyui_manager.cm_cli --help

# Core functionality test
python -m comfyui_manager.cm_cli show all

# Package management test  
python -m comfyui_manager.cm_cli install <safe-test-package>

# Cleanup test
python -m comfyui_manager.cm_cli uninstall <test-package>
```

## Debug Commands  
```bash
# Check Python imports
python -c "from comfyui_manager.glob import manager_core; print('OK')"

# Check data structures
python -c "from comfyui_manager.glob.manager_core import unified_manager; print(len(unified_manager.installed_node_packages))"

# Check CNR access
python -c "from comfyui_manager.common import cnr_utils; print(len(cnr_utils.get_all_nodepackages()))"
```

---

Use this checklist systematically during implementation to ensure comprehensive testing and validation of the CLI migration.