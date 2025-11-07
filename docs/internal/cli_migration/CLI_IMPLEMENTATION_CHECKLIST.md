# CLI Glob Migration - Implementation Todo List

## 📅 Project Timeline: 3.5 Days

---

# 🚀 Phase 1: Initial Setup & Import Changes (0.5 day)

## Day 1 Morning

### ✅ Setup and Preparation (30 min)
- [ ] Read implementation context file
- [ ] Review glob APIs documentation  
- [ ] Set up development environment
- [ ] Create backup of current CLI

### 🔄 Import Path Changes (1 hour)
- [ ] **CRITICAL**: Update import statements in `cm_cli/__main__.py:39-41`
  ```python
  # Change from:
  from ..legacy import manager_core as core
  from ..legacy.manager_core import unified_manager
  
  # Change to:
  from ..glob import manager_core as core
  from ..glob.manager_core import unified_manager
  ```
- [ ] Test CLI loads without crashing
- [ ] Identify immediate import-related errors

### 🧪 Initial Testing (30 min)
- [ ] Test basic CLI help: `python -m comfyui_manager.cm_cli help`
- [ ] Test simple commands that should work: `python -m comfyui_manager.cm_cli show snapshot`
- [ ] Document all errors found
- [ ] Prioritize fixes needed

---

# ⚙️ Phase 2: Core Function Implementation (2 days)

## Day 1 Afternoon + Day 2

### 🛠️ install_node() Function Update (3 hours)
**File**: `cm_cli/__main__.py:187-235`  
**Complexity**: Medium

#### Tasks:
- [ ] **Replace Git URL handling logic**
  ```python
  # OLD (line ~191):
  if core.is_valid_url(node_spec_str):
      res = asyncio.run(core.gitclone_install(node_spec_str, no_deps=cmd_ctx.no_deps))
  
  # NEW:
  if unified_manager.is_url_like(node_spec_str):
      repo_name = os.path.basename(node_spec_str)
      if repo_name.endswith('.git'):
          repo_name = repo_name[:-4]
      res = asyncio.run(unified_manager.repo_install(
          node_spec_str, repo_name, instant_execution=True, no_deps=cmd_ctx.no_deps
      ))
  ```
- [ ] Test Git URL installation
- [ ] Test CNR package installation
- [ ] Verify error handling works correctly
- [ ] Update progress messages if needed

### 🔍 show_list() Function Rewrite - Installed-Only Approach (3 hours)
**File**: `cm_cli/__main__.py:418-534`  
**Complexity**: High - Complete architectural change
**New Approach**: Show only installed nodepacks with on-demand info retrieval

#### Key Changes:
- ❌ Remove: Full cache loading (`get_custom_nodes()`)
- ❌ Remove: Support for `show all`, `show not-installed`, `show cnr`  
- ✅ Add: Lightweight caching system for nodepack metadata
- ✅ Add: On-demand CNR API calls for additional info

#### Tasks:
- [ ] **Phase 2A: Lightweight Cache Implementation (1 hour)**
  ```python
  class NodePackageCache:
      def __init__(self, cache_file_path: str):
          self.cache_file = cache_file_path
          self.cache_data = self._load_cache()
      
      def get_metadata(self, nodepack_id: str) -> dict:
          # Get cached metadata or fetch on-demand from CNR
          
      def update_metadata(self, nodepack_id: str, metadata: dict):
          # Update cache (called during install)
  ```

- [ ] **Phase 2B: New show_list Implementation (1.5 hours)**  
  ```python
  def show_list(kind, simple=False):
      # Validate supported commands
      if kind not in ['installed', 'enabled', 'disabled']:
          print(f"Unsupported: 'show {kind}'. Use: installed/enabled/disabled")
          return
          
      # Get installed packages only
      all_packages = []
      for packages in unified_manager.installed_node_packages.values():
          all_packages.extend(packages)
      
      # Filter by status
      if kind == 'enabled':
          packages = [pkg for pkg in all_packages if pkg.is_enabled]
      elif kind == 'disabled':
          packages = [pkg for pkg in all_packages if not pkg.is_enabled]  
      else:  # 'installed'
          packages = all_packages
  ```

- [ ] **Phase 2C: On-Demand Display with Cache (0.5 hour)**
  ```python
      cache = NodePackageCache(cache_file_path)
      
      for package in packages:
          # Basic info from InstalledNodePackage
          status = "[  ENABLED   ]" if package.is_enabled else "[ DISABLED   ]"
          
          # Enhanced info from cache or on-demand
          cached_info = cache.get_metadata(package.id)  
          name = cached_info.get('name', package.id)
          author = cached_info.get('author', 'Unknown')
          version = cached_info.get('version', 'Unknown')
          
          if simple:
              print(f"{name}@{version}")
          else:
              print(f"{status} {name:50} {package.id:30} (author: {author:20}) [{version}]")
  ```

#### Install-time Cache Update:
- [ ] **Update install_node() to populate cache**
  ```python
  # After successful installation in install_node()
  if install_success:
      metadata = cnr_utils.get_nodepackage_info(installed_package.id)
      cache.update_metadata(installed_package.id, metadata)
  ```

#### Testing:
- [ ] Test `show installed` (enabled + disabled packages)
- [ ] Test `show enabled` (only enabled packages)
- [ ] Test `show disabled` (only disabled packages) 
- [ ] Test unsupported commands show helpful error
- [ ] Test `simple-show` variants work correctly
- [ ] Test cache functionality (create, read, update)
- [ ] Test on-demand CNR info retrieval for cache misses

### 📝 get_all_installed_node_specs() Update (1 hour)
**File**: `cm_cli/__main__.py:573-605`  
**Complexity**: Medium

#### Tasks:
- [ ] **Rewrite using InstalledNodePackage**
  ```python
  def get_all_installed_node_specs():
      res = []
      for packages in unified_manager.installed_node_packages.values():
          for pack in packages:
              node_spec_str = f"{pack.id}@{pack.version}"
              res.append(node_spec_str)
      return res
  ```
- [ ] Test with `update all` command
- [ ] Verify node spec format is correct

### ⚙️ Context Management Updates (1 hour)
**File**: `cm_cli/__main__.py:117-134`  
**Complexity**: Low

#### Tasks:
- [ ] **Remove load_nightly() call**
  ```python  
  def set_channel_mode(self, channel, mode):
      if mode is not None:
          self.mode = mode
      if channel is not None:
          self.channel = channel
      
      # OLD: asyncio.run(unified_manager.reload(...))
      # OLD: asyncio.run(unified_manager.load_nightly(...))
      
      # NEW: Just reload
      unified_manager.reload()
  ```
- [ ] Test channel/mode switching still works

---

# 🧹 Phase 3: Feature Removal & Final Testing (1 day)

## Day 3

### ❌ Remove Unavailable Features (2 hours)
**Complexity**: Low

#### deps-in-workflow Command Removal:
- [ ] **Update deps_in_workflow() function** (`cm_cli/__main__.py:1000-1050`)
  ```python
  @app.command("deps-in-workflow")  
  def deps_in_workflow(...):
      print("[bold red]ERROR: This feature is not available in the current version.[/bold red]")
      print("The 'deps-in-workflow' feature has been removed.")
      print("Please use alternative workflow analysis tools.")
      sys.exit(1)
  ```
- [ ] Test command shows proper error message
- [ ] Update help text to reflect removal

#### install-deps Command Update:
- [ ] **Update install_deps() function** (`cm_cli/__main__.py:1203-1250`)
  ```python  
  # Remove extract_nodes_from_workflow usage (line ~1033)
  # Replace with error handling or alternative approach
  ```
- [ ] Test with dependency files

### 🧪 Comprehensive Testing (4 hours)

#### Core Command Testing (2 hours):
- [ ] **Install Commands**:
  - [ ] `install <cnr-package>`
  - [ ] `install <git-url>`
  - [ ] `install all` (if applicable)
  
- [ ] **Uninstall Commands**:
  - [ ] `uninstall <package>`
  - [ ] `uninstall all`

- [ ] **Enable/Disable Commands**:
  - [ ] `enable <package>`
  - [ ] `disable <package>`
  - [ ] `enable all` / `disable all`

- [ ] **Update Commands**:
  - [ ] `update <package>`
  - [ ] `update all`

#### Show Commands Testing (1 hour):
- [ ] `show installed`
- [ ] `show enabled`
- [ ] `show disabled` 
- [ ] `show all`
- [ ] `show not-installed`
- [ ] `simple-show` variants

#### Advanced Features Testing (1 hour):
- [ ] `save-snapshot`
- [ ] `restore-snapshot`
- [ ] `show snapshot`
- [ ] `show snapshot-list`
- [ ] `clear`
- [ ] `cli-only-mode`

### 🐛 Bug Fixes & Polish (2 hours)
- [ ] Fix any errors found during testing
- [ ] Improve error messages
- [ ] Ensure output formatting consistency
- [ ] Performance optimization if needed
- [ ] Code cleanup and comments

---

# 📋 Daily Checklists

## End of Day 1 Checklist:
- [ ] Imports successfully changed
- [ ] Basic CLI loading works
- [ ] install_node() handles both CNR and Git URLs
- [ ] No critical crashes in core functions

## End of Day 2 Checklist:
- [ ] show_list() displays all package types correctly
- [ ] get_all_installed_node_specs() works with new data structure
- [ ] Context management updated
- [ ] Core functionality regression-free

## End of Day 3 Checklist:
- [ ] All CLI commands tested and working
- [ ] Removed features show appropriate messages
- [ ] Output format acceptable to users
- [ ] No glob module modifications made
- [ ] Ready for code review

---

# 🎯 Success Criteria

## Must Pass:
- [ ] All core commands functional (install/uninstall/enable/disable/update)
- [ ] show commands display accurate information
- [ ] No modifications to glob module
- [ ] CLI code changes < 200 lines
- [ ] No critical regressions

## Bonus Points:
- [ ] Output format matches legacy closely
- [ ] Performance equals or exceeds legacy
- [ ] Error messages user-friendly
- [ ] Code is clean and maintainable

---

# 🚨 Emergency Contacts & Resources

## If Stuck:
1. **Review**: `CLI_PURE_GLOB_MIGRATION_PLAN.md` for detailed technical specs
2. **Reference**: `CLI_IMPLEMENTATION_CONTEXT.md` for current state
3. **Debug**: Use `print()` statements to understand data structures
4. **Fallback**: Implement minimal working version first, polish later

## Key Files to Reference:
- `comfyui_manager/glob/manager_core.py` - UnifiedManager APIs
- `comfyui_manager/common/node_package.py` - InstalledNodePackage class
- `comfyui_manager/common/cnr_utils.py` - CNR utilities

---

**Remember**: Focus on making it work first, then making it perfect. The constraint is NO glob modifications - CLI must adapt to glob's way of doing things.