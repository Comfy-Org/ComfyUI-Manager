# Package Version Management Design

## Overview

ComfyUI Manager supports two package version types, each with distinct installation methods and version switching mechanisms:

1. **CNR Version (Archive)**: Production-ready releases with semantic versioning (e.g., v1.0.2), published to CNR server, verified, and distributed as ZIP archives
2. **Nightly Version**: Real-time development builds from Git repository without semantic versioning, providing direct access to latest code via git pull

## Package ID Normalization

### Case Sensitivity Handling

**Source of Truth**: Package IDs originate from `pyproject.toml` with their original case (e.g., `ComfyUI_SigmoidOffsetScheduler`)

**Normalization Process**:
1. `cnr_utils.normalize_package_name()` provides centralized normalization (`cnr_utils.py:28-48`):
   ```python
   def normalize_package_name(name: str) -> str:
       """
       Normalize package name for case-insensitive matching.
       - Strip leading/trailing whitespace
       - Convert to lowercase
       """
       return name.strip().lower()
   ```
2. `cnr_utils.read_cnr_info()` uses this normalization when indexing (`cnr_utils.py:314`):
   ```python
   name = project.get('name').strip().lower()
   ```
3. Package indexed in `installed_node_packages` with lowercase ID: `'comfyui_sigmoidoffsetscheduler'`
4. **Critical**: All lookups (`is_enabled()`, `unified_disable()`) must use `cnr_utils.normalize_package_name()` for matching

**Implementation** (`manager_core.py:1374, 1389`):
```python
# Before checking if package is enabled or disabling
packname_normalized = cnr_utils.normalize_package_name(packname)
if self.is_enabled(packname_normalized):
    self.unified_disable(packname_normalized)
```

## Package Identification

### How Packages Are Identified

**Critical**: Packages MUST be identified by marker files and metadata, NOT by directory names.

**Identification Flow** (`manager_core.py:691-703`, `node_package.py:49-81`):

```python
def resolve_from_path(fullpath):
    """
    Identify package type and ID using markers and metadata files.

    Priority:
    1. Check for .git directory (Nightly)
    2. Check for .tracking + pyproject.toml (CNR)
    3. Unknown/legacy (fallback to directory name)
    """
    # 1. Nightly Detection
    url = git_utils.git_url(fullpath)  # Checks for .git/config
    if url:
        url = git_utils.compact_url(url)
        commit_hash = git_utils.get_commit_hash(fullpath)
        return {'id': url, 'ver': 'nightly', 'hash': commit_hash}

    # 2. CNR Detection
    info = cnr_utils.read_cnr_info(fullpath)  # Checks for .tracking + pyproject.toml
    if info:
        return {'id': info['id'], 'ver': info['version']}

    # 3. Unknown (fallback)
    return None
```

### Marker-Based Identification

**1. Nightly Packages**:
- **Marker**: `.git` directory presence
- **ID Extraction**: Read URL from `.git/config` using `git_utils.git_url()` (`git_utils.py:34-53`)
- **ID Format**: Compact URL (e.g., `https://github.com/owner/repo` → compact form)
- **Why**: Git repositories are uniquely identified by their remote URL

**2. CNR Packages**:
- **Markers**: `.tracking` file AND `pyproject.toml` file (`.git` must NOT exist)
- **ID Extraction**: Read `name` from `pyproject.toml` using `cnr_utils.read_cnr_info()` (`cnr_utils.py:302-334`)
- **ID Format**: Normalized lowercase from `pyproject.toml` (e.g., `ComfyUI_Foo` → `comfyui_foo`)
- **Why**: CNR packages are identified by their canonical name in package metadata

**Implementation** (`cnr_utils.py:302-334`):
```python
def read_cnr_info(fullpath):
    toml_path = os.path.join(fullpath, 'pyproject.toml')
    tracking_path = os.path.join(fullpath, '.tracking')

    # MUST have both markers and NO .git directory
    if not os.path.exists(toml_path) or not os.path.exists(tracking_path):
        return None  # not valid CNR node pack

    with open(toml_path, "r", encoding="utf-8") as f:
        data = toml.load(f)
        project = data.get('project', {})
        name = project.get('name').strip().lower()  # ← Normalized for indexing
        original_name = project.get('name')          # ← Original case preserved
        version = str(manager_util.StrictVersion(project.get('version')))

        return {
            "id": name,              # Normalized ID for lookups
            "original_name": original_name,
            "version": version,
            "url": repository
        }
```

### Why NOT Directory Names?

**Problem with directory-based identification**:
1. **Case Sensitivity Issues**: Same package can have different directory names
   - Active: `ComfyUI_Foo` (original case)
   - Disabled: `comfyui_foo@1_0_2` (lowercase)
2. **Version Suffix Confusion**: Disabled directories include version in name
3. **User Modifications**: Users can rename directories, breaking identification

**Correct Approach**:
- **Source of Truth**: Marker files (`.git`, `.tracking`, `pyproject.toml`)
- **Consistent IDs**: Based on metadata content, not filesystem names
- **Case Insensitive**: Normalized lookups work regardless of directory name

### Package Lookup Flow

**Index Building** (`manager_core.py:444-478`):
```python
def reload(self):
    self.installed_node_packages: dict[str, list[InstalledNodePackage]] = defaultdict(list)

    # Scan active packages
    for x in os.listdir(custom_nodes_path):
        fullpath = os.path.join(custom_nodes_path, x)
        if x not in ['__pycache__', '.disabled']:
            node_package = InstalledNodePackage.from_fullpath(fullpath, self.resolve_from_path)
            # ↓ Uses ID from resolve_from_path(), NOT directory name
            self.installed_node_packages[node_package.id].append(node_package)

    # Scan disabled packages
    for x in os.listdir(disabled_dir):
        fullpath = os.path.join(disabled_dir, x)
        node_package = InstalledNodePackage.from_fullpath(fullpath, self.resolve_from_path)
        # ↓ Same ID extraction, consistent indexing
        self.installed_node_packages[node_package.id].append(node_package)
```

**Lookup Process**:
1. Normalize search term: `cnr_utils.normalize_package_name(packname)`
2. Look up in `installed_node_packages` dict by normalized ID
3. Match found packages by version if needed
4. Return `InstalledNodePackage` objects with full metadata

### Edge Cases

**1. Package with `.git` AND `.tracking`**:
- **Detection**: Treated as Nightly (`.git` checked first)
- **Reason**: Git repo takes precedence over archive markers
- **Fix**: Remove `.tracking` file to avoid confusion

**2. Missing Marker Files**:
- **CNR without `.tracking`**: Treated as Unknown
- **Nightly without `.git`**: Treated as Unknown or CNR (if has `.tracking`)
- **Recovery**: Re-install package to restore correct markers

**3. Corrupted `pyproject.toml`**:
- **Detection**: `read_cnr_info()` returns `None`
- **Result**: Package treated as Unknown
- **Recovery**: Manual fix or re-install

## Version Types

ComfyUI Manager supports two main package version types:

### 1. CNR Version (Comfy Node Registry - Versioned Releases)

**Also known as**: Archive version (because it's distributed as ZIP archive)

**Purpose**: Production-ready releases that have been versioned, published to CNR server, and verified before distribution

**Characteristics**:
- Semantic versioning assigned (e.g., v1.0.2, v2.1.0)
- Published to CNR server with verification process
- Stable, tested releases for production use
- Distributed as ZIP archives for reliability

**Installation Method**: ZIP file extraction from CNR (Comfy Node Registry)

**Identification**:
- Presence of `.tracking` file in package directory
- **Directory naming**:
  - **Active** (`custom_nodes/`): Uses `name` from `pyproject.toml` with original case (e.g., `ComfyUI_SigmoidOffsetScheduler`)
    - This is the `original_name` in glob/ implementation
  - **Disabled** (`.disabled/`): Uses `{package_name}@{version}` format (e.g., `comfyui_sigmoidoffsetscheduler@1_0_2`)
- Package indexed with lowercase ID from `pyproject.toml`
- Versioned releases (e.g., v1.0.2, v2.1.0)

**`.tracking` File Purpose**:
- **Primary**: Marker to identify this as a CNR/archive installation
- **Critical**: Contains list of original files from the archive
- **Update Use Case**: When updating to a new version:
  1. Read `.tracking` to identify original archive files
  2. Delete ONLY original archive files
  3. Preserve user-generated files (configs, models, custom code)
  4. Extract new archive version
  5. Update `.tracking` with new file list

**File Structure**:
```
custom_nodes/
  ComfyUI_SigmoidOffsetScheduler/
    .tracking              # List of original archive files
    pyproject.toml         # name = "ComfyUI_SigmoidOffsetScheduler"
    __init__.py
    nodes.py
    (user-created files preserved during update)
```

### 2. Nightly Version (Development Builds)

**Purpose**: Real-time development builds from Git repository without semantic versioning

**Characteristics**:
- No semantic version assigned (version = "nightly")
- Direct access to latest development code
- Real-time updates via git pull
- For testing, development, and early adoption
- Not verified through CNR publication process

**Installation Method**: Git repository clone

**Identification**:
- Presence of `.git` directory in package directory
- `version: "nightly"` in package metadata
- **Directory naming**:
  - **Active** (`custom_nodes/`): Uses `name` from `pyproject.toml` with original case (e.g., `ComfyUI_SigmoidOffsetScheduler`)
    - This is the `original_name` in glob/ implementation
  - **Disabled** (`.disabled/`): Uses `{package_name}@nightly` format (e.g., `comfyui_sigmoidoffsetscheduler@nightly`)

**Update Mechanism**:
- `git pull` on existing repository
- All user modifications in git working tree preserved by git

**File Structure**:
```
custom_nodes/
  ComfyUI_SigmoidOffsetScheduler/
    .git/                  # Git repository marker
    pyproject.toml
    __init__.py
    nodes.py
    (git tracks all changes)
```

## Version Switching Mechanisms

### CNR ↔ Nightly (Uses `.disabled/` Directory)

**Mechanism**: Enable/disable toggling - only ONE version active at a time

**Process**:
1. **CNR → Nightly**:
   ```
   Before: custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (has .tracking)
   After:  custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (has .git)
           .disabled/comfyui_sigmoidoffsetscheduler@1_0_2/ (has .tracking)
   ```
   - Move archive directory to `.disabled/comfyui_sigmoidoffsetscheduler@{version}/`
   - Git clone nightly to `custom_nodes/ComfyUI_SigmoidOffsetScheduler/`

2. **Nightly → CNR**:
   ```
   Before: custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (has .git)
           .disabled/comfyui_sigmoidoffsetscheduler@1_0_2/ (has .tracking)
   After:  custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (has .tracking)
           .disabled/comfyui_sigmoidoffsetscheduler@nightly/ (has .git)
   ```
   - Move nightly directory to `.disabled/comfyui_sigmoidoffsetscheduler@nightly/`
   - Restore archive from `.disabled/comfyui_sigmoidoffsetscheduler@{version}/`

**Key Points**:
- Both versions preserved in filesystem (one in `.disabled/`)
- Switching is fast (just move operations)
- No re-download needed when switching back

### CNR Version Update (In-Place Update)

**Mechanism**: Direct directory content update - NO `.disabled/` directory used

**When**: Switching between different CNR versions (e.g., v1.0.1 → v1.0.2)

**Process**:
```
Before: custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (v1.0.1, has .tracking)
After:  custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (v1.0.2, has .tracking)
```

**Steps**:
1. Read `.tracking` to identify original v1.0.1 files
2. Delete only original v1.0.1 files (preserve user-created files)
3. Extract v1.0.2 archive to same directory
4. Update `.tracking` with v1.0.2 file list
5. Update `pyproject.toml` version metadata

**Critical**: Directory name and location remain unchanged

## API Design Decisions

### Enable/Disable Operations

**Design Decision**: ❌ **NO DIRECT ENABLE/DISABLE API PROVIDED**

**Rationale**:
- Enable/disable operations occur **ONLY as a by-product** of version switching
- Version switching is the primary operation that manages package state
- Direct enable/disable API would:
  1. Create ambiguity about which version to enable/disable
  2. Bypass version management logic
  3. Lead to inconsistent package state

**Implementation**:
- `unified_enable()` and `unified_disable()` are **internal methods only**
- Called exclusively from version switching operations:
  - `install_by_id()` (manager_core.py:1695-1724)
  - `cnr_switch_version_instant()` (manager_core.py:941)
  - `repo_update()` (manager_core.py:2144-2232)

**User Workflow**:
```
User wants to disable CNR version and enable Nightly:
  ✅ Correct: install(package, version="nightly")
             → automatically disables CNR, enables Nightly
  ❌ Wrong:   disable(package) + enable(package, "nightly")
             → not supported, ambiguous
```

**Testing Approach**:
- Enable/disable tested **indirectly** through version switching tests
- Test 1-12 validate enable/disable behavior via install/update operations
- No direct enable/disable API tests needed (API doesn't exist)

## Implementation Details

### Version Detection Logic

**Location**: `comfyui_manager/common/node_package.py`

```python
@dataclass
class InstalledNodePackage:
    @property
    def is_nightly(self) -> bool:
        return self.version == "nightly"

    @property
    def is_from_cnr(self) -> bool:
        return not self.is_unknown and not self.is_nightly
```

**Detection Order**:
1. Check for `.tracking` file → CNR (Archive) version
2. Check for `.git` directory → Nightly version
3. Otherwise → Unknown/legacy

### Reload Timing

**Critical**: `unified_manager.reload()` must be called:
1. **Before each queued task** (`manager_server.py:1245`):
   ```python
   # Reload installed packages before each task to ensure latest state
   core.unified_manager.reload()
   ```
2. **Before version switching** (`manager_core.py:1370`):
   ```python
   # Reload to ensure we have the latest package state before checking
   self.reload()
   ```

**Why**: Ensures `installed_node_packages` dict reflects actual filesystem state

### Disable Mechanism

**Implementation** (`manager_core.py:982-1017`, specifically line 1011):
```python
def unified_disable(self, packname: str):
    # ... validation logic ...

    # Generate disabled directory name with version suffix
    base_path = extract_base_custom_nodes_dir(matched_active.fullpath)
    folder_name = packname if not self.is_url_like(packname) else os.path.basename(matched_active.fullpath)
    to_path = os.path.join(base_path, '.disabled', f"{folder_name}@{matched_active.version.replace('.', '_')}")

    shutil.move(matched_active.fullpath, to_path)
```

**Naming Convention**:
- `{folder_name}@{version}` format for ALL version types
- CNR v1.0.2 → `comfyui_foo@1_0_2` (dots replaced with underscores)
- Nightly → `comfyui_foo@nightly`

### Case Sensitivity Fix

**Problem**: Package IDs normalized to lowercase during indexing but not during lookup

**Solution** (`manager_core.py:1372-1378, 1388-1393`):
```python
# Normalize packname using centralized cnr_utils function
# CNR packages are indexed with lowercase IDs from pyproject.toml
packname_normalized = cnr_utils.normalize_package_name(packname)

if self.is_enabled(packname_normalized):
    self.unified_disable(packname_normalized)
```

**Why Centralized Function**:
- Consistent normalization across entire codebase
- Single source of truth for package name normalization logic
- Easier to maintain and test
- Located in `cnr_utils.py:28-48`

## Directory Structure Examples

### Complete Example: All Version Types Coexisting

```
custom_nodes/
  ComfyUI_SigmoidOffsetScheduler/        # Active version (CNR v2.0.0 in this example)
    pyproject.toml                        # name = "ComfyUI_SigmoidOffsetScheduler"
    __init__.py
    nodes.py

  .disabled/                              # Inactive versions storage
    comfyui_sigmoidoffsetscheduler@nightly/ # ← Nightly (disabled)
      .git/                               # ← Nightly marker
      pyproject.toml
      __init__.py
      nodes.py

    comfyui_sigmoidoffsetscheduler@1_0_2/ # ← CNR v1.0.2 (disabled)
      .tracking                           # ← CNR marker with file list
      pyproject.toml
      __init__.py
      nodes.py

    comfyui_sigmoidoffsetscheduler@1_0_1/ # ← CNR v1.0.1 (disabled)
      .tracking
      pyproject.toml
      __init__.py
      nodes.py
```

**Key Points**:
- Active directory ALWAYS uses `original_name` without version suffix
- Each disabled version has `@{version}` suffix to avoid conflicts
- Multiple disabled versions can coexist (nightly + multiple CNR versions)

## Summary Table

| Version Type | Purpose | Marker | Active Directory Name | Disabled Directory Name | Update Method | Switch Mechanism |
|--------------|---------|--------|----------------------|------------------------|---------------|------------------|
| **CNR** (Archive) | Production-ready releases with semantic versioning, published to CNR server and verified | `.tracking` file | `original_name` (e.g., `ComfyUI_Foo`) | `{package}@{version}` (e.g., `comfyui_foo@1_0_2`) | In-place update (preserve user files) | `.disabled/` toggle |
| **Nightly** | Real-time development builds from Git repository without semantic versioning | `.git/` directory | `original_name` (e.g., `ComfyUI_Foo`) | `{package}@nightly` (e.g., `comfyui_foo@nightly`) | `git pull` | `.disabled/` toggle |

**Important Constraints**:
- **Active directory name**: MUST use `original_name` (from `pyproject.toml`) without version suffix
  - Other code may depend on this specific directory name
  - Only ONE version can be active at a time
- **Disabled directory name**: MUST include `@{version}` suffix to allow multiple disabled versions to coexist
  - CNR: `@{version}` (e.g., `@1_0_2`)
  - Nightly: `@nightly`

## Edge Cases

### 1. Multiple CNR Versions
- Each stored in `.disabled/` with version suffix
- Only one can be active at a time
- Switching between CNR versions = direct content update (not via `.disabled/`)

### 2. Package ID Case Variations
- Always normalize to lowercase for internal lookups
- Preserve original case in filesystem/display
- Match against lowercase indexed keys

### 3. Corrupted `.tracking` File
- Treat as unknown version type
- Warn user before update/uninstall
- May require manual cleanup

### 4. Mixed CNR + Nightly in `.disabled/`
- Both can coexist in `.disabled/`
- Only one can be active in `custom_nodes/`
- Switch logic detects type and handles appropriately
