# Glob Module API Reference for CLI Migration

## 🎯 Quick Reference
This document provides essential glob module APIs available for CLI implementation. **READ ONLY** - do not modify glob module.

---

## 📦 Core Classes

### UnifiedManager
**Location**: `comfyui_manager/glob/manager_core.py:436`  
**Instance**: Available as `unified_manager` (global instance)

#### Data Structures
```python
class UnifiedManager:
    def __init__(self):
        # PRIMARY DATA - Use these instead of legacy dicts
        self.installed_node_packages: dict[str, list[InstalledNodePackage]]
        self.repo_nodepack_map: dict[str, InstalledNodePackage]  # compact_url -> package
        self.processed_install: set
```

#### Core Methods (Direct CLI Equivalents)
```python
# Installation & Management
async def install_by_id(packname: str, version_spec=None, channel=None, 
                       mode=None, instant_execution=False, no_deps=False, 
                       return_postinstall=False) -> ManagedResult
def unified_enable(packname: str, version_spec=None) -> ManagedResult
def unified_disable(packname: str) -> ManagedResult  
def unified_uninstall(packname: str) -> ManagedResult
def unified_update(packname: str, instant_execution=False, no_deps=False, 
                  return_postinstall=False) -> ManagedResult
def unified_fix(packname: str, version_spec, instant_execution=False, 
               no_deps=False) -> ManagedResult

# Package Resolution & Info
def resolve_node_spec(packname: str, guess_mode=None) -> tuple[str, str, bool] | None
def get_active_pack(packname: str) -> InstalledNodePackage | None
def get_inactive_pack(packname: str, version_spec=None) -> InstalledNodePackage | None

# Git Repository Operations  
async def repo_install(url: str, repo_path: str, instant_execution=False, 
                      no_deps=False, return_postinstall=False) -> ManagedResult
def repo_update(repo_path: str, instant_execution=False, no_deps=False,
               return_postinstall=False) -> ManagedResult

# Utilities
def is_url_like(url: str) -> bool
def reload() -> None
```

---

### InstalledNodePackage  
**Location**: `comfyui_manager/common/node_package.py:10`

```python
@dataclass
class InstalledNodePackage:
    # Core Data
    id: str                    # Package identifier
    fullpath: str             # Installation path
    disabled: bool            # Disabled state
    version: str              # Version (cnr version, "nightly", or "unknown")  
    repo_url: str = None      # Git repository URL (for nightly/unknown)

    # Computed Properties
    @property
    def is_unknown(self) -> bool:    # version == "unknown"
    @property  
    def is_nightly(self) -> bool:    # version == "nightly"
    @property
    def is_from_cnr(self) -> bool:   # not unknown and not nightly
    @property
    def is_enabled(self) -> bool:    # not disabled
    @property
    def is_disabled(self) -> bool:   # disabled
    
    # Methods
    def get_commit_hash(self) -> str
    def isValid(self) -> bool
    
    @staticmethod
    def from_fullpath(fullpath: str, resolve_from_path) -> InstalledNodePackage
```

---

### ManagedResult
**Location**: `comfyui_manager/glob/manager_core.py:285`

```python
class ManagedResult:
    def __init__(self, action: str):
        self.action: str = action      # 'install-cnr', 'install-git', 'enable', 'skip', etc.
        self.result: bool = True       # Success/failure
        self.msg: str = ""            # Human readable message
        self.target: str = None       # Target identifier
        self.postinstall = None       # Post-install callback
        
    # Methods
    def fail(self, msg: str = "") -> ManagedResult
    def with_msg(self, msg: str) -> ManagedResult
    def with_target(self, target: str) -> ManagedResult
    def with_postinstall(self, postinstall) -> ManagedResult
```

---

## 🛠️ Standalone Functions

### Core Manager Functions
```python
# Snapshot Operations
async def save_snapshot_with_postfix(postfix: str, path: str = None, 
                                    custom_nodes_only: bool = False) -> str

async def restore_snapshot(snapshot_path: str, git_helper_extras=None) -> None

# Node Utilities  
def simple_check_custom_node(url: str) -> str  # Returns: 'installed', 'not-installed', 'disabled'

# Path Utilities
def get_custom_nodes_paths() -> list[str]
```

---

## 🔗 CNR Utilities
**Location**: `comfyui_manager/common/cnr_utils.py`

```python
# Essential CNR functions for CLI
def get_nodepack(packname: str) -> dict | None
    # Returns CNR package info or None

def get_all_nodepackages() -> dict[str, dict]
    # Returns all CNR packages {package_id: package_info}

def all_versions_of_node(node_name: str) -> list[dict] | None  
    # Returns version history for a package
```

---

## 📋 Usage Patterns for CLI Migration

### 1. Replace Legacy Dict Access
```python
# ❌ OLD (Legacy way)
for k, v in unified_manager.active_nodes.items():
    version, fullpath = v
    print(f"Active: {k} @ {version}")

# ✅ NEW (Glob way)
for packages in unified_manager.installed_node_packages.values():
    for pack in packages:
        if pack.is_enabled:
            print(f"Active: {pack.id} @ {pack.version}")
```

### 2. Package Installation
```python
# CNR Package Installation
res = await unified_manager.install_by_id("package-name", "1.0.0", 
                                         instant_execution=True, no_deps=False)

# Git URL Installation  
if unified_manager.is_url_like(url):
    repo_name = os.path.basename(url).replace('.git', '')
    res = await unified_manager.repo_install(url, repo_name, 
                                            instant_execution=True, no_deps=False)
```

### 3. Package State Queries
```python
# Check if package is active
active_pack = unified_manager.get_active_pack("package-name")
if active_pack:
    print(f"Package is enabled: {active_pack.version}")

# Check if package is inactive
inactive_pack = unified_manager.get_inactive_pack("package-name")
if inactive_pack:
    print(f"Package is disabled: {inactive_pack.version}")
```

### 4. CNR Data Access
```python
# Get CNR package information
from ..common import cnr_utils

cnr_info = cnr_utils.get_nodepack("package-name")
if cnr_info:
    publisher = cnr_info.get('publisher', {}).get('name', 'Unknown')
    print(f"Publisher: {publisher}")

# Get all CNR packages (for show not-installed)
all_cnr = cnr_utils.get_all_nodepackages()
```

### 5. Result Handling
```python
res = await unified_manager.install_by_id("package-name")

if res.action == 'skip':
    print(f"SKIP: {res.msg}")
elif res.action == 'install-cnr' and res.result:
    print(f"INSTALLED: {res.target}")
elif res.action == 'enable' and res.result:
    print(f"ENABLED: package was already installed")
else:
    print(f"ERROR: {res.msg}")
```

---

## 🚫 NOT Available in Glob (Handle These)

### Legacy Functions That Don't Exist:
- `get_custom_nodes()` → Use `cnr_utils.get_all_nodepackages()`
- `load_nightly()` → Remove or stub
- `extract_nodes_from_workflow()` → Remove feature
- `gitclone_install()` → Use `repo_install()`

### Legacy Properties That Don't Exist:
- `active_nodes` → Use `installed_node_packages` + filter by `is_enabled`
- `cnr_map` → Use `cnr_utils.get_all_nodepackages()`  
- `cnr_inactive_nodes` → Use `installed_node_packages` + filter by `is_disabled` and `is_from_cnr`
- `nightly_inactive_nodes` → Use `installed_node_packages` + filter by `is_disabled` and `is_nightly`
- `unknown_active_nodes` → Use `installed_node_packages` + filter by `is_enabled` and `is_unknown`
- `unknown_inactive_nodes` → Use `installed_node_packages` + filter by `is_disabled` and `is_unknown`

---

## 🔄 Data Migration Examples

### Show Enabled Packages
```python
def show_enabled_packages():
    enabled_packages = []
    
    # Collect enabled packages
    for packages in unified_manager.installed_node_packages.values():
        for pack in packages:
            if pack.is_enabled:
                enabled_packages.append(pack)
    
    # Display with CNR info
    for pack in enabled_packages:
        if pack.is_from_cnr:
            cnr_info = cnr_utils.get_nodepack(pack.id)
            publisher = cnr_info.get('publisher', {}).get('name', 'Unknown') if cnr_info else 'Unknown'
            print(f"[    ENABLED    ] {pack.id:50} (author: {publisher}) [{pack.version}]")
        elif pack.is_nightly:
            print(f"[    ENABLED    ] {pack.id:50} (nightly) [NIGHTLY]")
        else:
            print(f"[    ENABLED    ] {pack.id:50} (unknown) [UNKNOWN]")
```

### Show Not-Installed Packages  
```python
def show_not_installed_packages():
    # Get installed package IDs
    installed_ids = set()
    for packages in unified_manager.installed_node_packages.values():
        for pack in packages:
            installed_ids.add(pack.id)
    
    # Get all CNR packages
    all_cnr = cnr_utils.get_all_nodepackages()
    
    # Show not-installed
    for pack_id, pack_info in all_cnr.items():
        if pack_id not in installed_ids:
            publisher = pack_info.get('publisher', {}).get('name', 'Unknown')
            latest_version = pack_info.get('latest_version', {}).get('version', '0.0.0')
            print(f"[ NOT INSTALLED ] {pack_info['name']:50} {pack_id:30} (author: {publisher}) [{latest_version}]")
```

---

## ⚠️ Key Constraints

1. **NO MODIFICATIONS**: Do not add any functions or properties to glob module
2. **USE EXISTING APIs**: Only use the functions and classes documented above
3. **ADAPT CLI**: CLI must adapt to glob's data structures and patterns
4. **REMOVE IF NEEDED**: Remove features that can't be implemented with available APIs

This reference should provide everything needed to implement the CLI migration using only existing glob APIs.