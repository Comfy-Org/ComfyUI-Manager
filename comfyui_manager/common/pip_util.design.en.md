# Design Document for pip_util.py Implementation

This is designed to minimize breaking existing installed dependencies.

## List of Functions to Implement

## Global Policy Management

### Global Variables
```python
_pip_policy_cache = None  # Policy cache (program-wide, loaded once)
```

### Global Functions

* get_pip_policy(): Returns policy for resolving pip dependency conflicts (lazy loading)
  - **Call timing**: Called whenever needed (automatically loads only once on first call)
  - **Purpose**: Returns policy cache, automatically loads if cache is empty
  - **Execution flow**:
    1. Declare global _pip_policy_cache
    2. If _pip_policy_cache is already loaded, return immediately (prevent duplicate loading)
    3. Read base policy file:
       - Path: {manager_util.comfyui_manager_path}/pip-policy.json
       - Use empty dictionary if file doesn't exist
       - Log error and use empty dictionary if JSON parsing fails
    4. Read user policy file:
       - Path: {context.manager_files_path}/pip-policy.user.json
       - Create empty JSON file if doesn't exist ({"_comment": "User-specific pip policy overrides"})
       - Log warning and use empty dictionary if JSON parsing fails
    5. Apply merge rules (merge by package name):
       - Start with base policy as base
       - For each package in user policy:
         * Package only in user policy: add to base
         * Package only in base policy: keep in base
         * Package in both: completely replace with user policy (entire package replacement, not section-level)
    6. Store merged policy in _pip_policy_cache
    7. Log policy load success (include number of loaded package policies)
    8. Return _pip_policy_cache
  - **Return value**: Dict (merged policy dictionary)
  - **Exception handling**:
    - File read failure: Log warning and treat file as empty dictionary
    - JSON parsing failure: Log error and treat file as empty dictionary
  - **Notes**:
    - Lazy loading pattern automatically loads on first call
    - Not thread-safe, caution needed in multi-threaded environments

- Policy file structure should support the following scenarios:
    - Dictionary structure of {dependency name -> policy object}
    - Policy object has four policy sections:
        - **uninstall**: Package removal policy (pre-processing, condition optional)
        - **apply_first_match**: Evaluate top-to-bottom and execute only the first policy that satisfies condition (exclusive)
        - **apply_all_matches**: Execute all policies that satisfy conditions (cumulative)
        - **restore**: Package restoration policy (post-processing, condition optional)

    - Condition types:
        - installed: Check version condition of already installed dependencies
            - spec is optional
            - package field: Specify package to check (optional, defaults to self)
                - Explicit: Reference another package (e.g., numba checks numpy version)
                - Omitted: Check own version (e.g., critical-package checks its own version)
        - platform: Platform conditions (os, has_gpu, comfyui_version, etc.)
        - If condition is absent, always considered satisfied

    - uninstall policy (pre-removal policy):
        - Removal policy list (condition is optional, evaluate top-to-bottom and execute only first match)
        - When condition satisfied (or always if no condition): remove target package and abort installation
        - If this policy is applied, all subsequent steps are ignored
        - target field specifies package to remove
        - Example: Unconditionally remove if specific package is installed

    - Actions available in apply_first_match (determine installation method, exclusive):
        - skip: Block installation of specific dependency
        - force_version: Force change to specific version during installation
            - extra_index_url field can specify custom package repository (optional)
        - replace: Replace with different dependency
            - extra_index_url field can specify custom package repository (optional)

    - Actions available in apply_all_matches (installation options, cumulative):
        - pin_dependencies: Pin currently installed versions of other dependencies
            - pinned_packages field specifies package list
            - Example: `pip install requests urllib3==1.26.15 certifi==2023.7.22 charset-normalizer==3.2.0`
            - Real use case: Prevent urllib3 from upgrading to 2.x when installing requests
            - on_failure: "fail" or "retry_without_pin"
        - install_with: Specify additional dependencies to install together
        - warn: Record warning message in log

    - restore policy (post-restoration policy):
        - Restoration policy list (condition is optional, evaluate top-to-bottom and execute only first match)
        - Executed after package installation completes (post-processing)
        - When condition satisfied (or always if no condition): force install target package to specific version
        - target field specifies package to restore (can be different package)
        - version field specifies version to install
        - extra_index_url field can specify custom package repository (optional)
        - Example: Reinstall/change version if specific package is deleted or wrong version

    - Execution order:
        1. uninstall evaluation: If condition satisfied, remove package and **terminate** (ignore subsequent steps)
        2. apply_first_match evaluation:
            - Execute first policy that satisfies condition among skip/force_version/replace
            - If no matching policy, proceed with default installation of originally requested package
        3. apply_all_matches evaluation: Apply all pin_dependencies, install_with, warn that satisfy conditions
        4. Execute actual package installation (pip install or uv pip install)
        5. restore evaluation: If condition satisfied, restore target package (post-processing)

## Batch Unit Class (PipBatch)

### Class Structure
```python
class PipBatch:
    """
    pip package installation batch unit manager
    Maintains pip freeze cache during batch operations for performance optimization

    Usage pattern:
        # Batch operations (policy auto-loaded)
        with PipBatch() as batch:
            batch.ensure_not_installed()
            batch.install("numpy>=1.20")
            batch.install("pandas>=2.0")
            batch.install("scipy>=1.7")
            batch.ensure_installed()
    """

    def __init__(self):
        self._installed_cache = None   # Installed packages cache (batch-level)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._installed_cache = None
```

### Private Methods

* PipBatch._refresh_installed_cache():
  - **Purpose**: Read currently installed package information and refresh cache
  - **Execution flow**:
    1. Generate command using manager_util.make_pip_cmd(["freeze"])
    2. Execute pip freeze via subprocess
    3. Parse output:
       - Each line is in "package_name==version" format
       - Parse "package_name==version" to create dictionary
       - Ignore editable packages (starting with -e)
       - Ignore comments (starting with #)
    4. Store parsed dictionary in self._installed_cache
  - **Return value**: None
  - **Exception handling**:
    - pip freeze failure: Set cache to empty dictionary and log warning
    - Parse failure: Ignore line and continue

* PipBatch._get_installed_packages():
  - **Purpose**: Return cached installed package information (refresh if cache is None)
  - **Execution flow**:
    1. If self._installed_cache is None, call _refresh_installed_cache()
    2. Return self._installed_cache
  - **Return value**: {package_name: version} dictionary

* PipBatch._invalidate_cache():
  - **Purpose**: Invalidate cache after package install/uninstall
  - **Execution flow**:
    1. Set self._installed_cache = None
  - **Return value**: None
  - **Call timing**: After install(), ensure_not_installed(), ensure_installed()

* PipBatch._parse_package_spec(package_info):
  - **Purpose**: Split package spec string into package name and version spec
  - **Parameters**:
    - package_info: "numpy", "numpy==1.26.0", "numpy>=1.20.0", "numpy~=1.20", etc.
  - **Execution flow**:
    1. Use regex to split package name and version spec
    2. Pattern: `^([a-zA-Z0-9_-]+)([><=!~]+.*)?$`
  - **Return value**: (package_name, version_spec) tuple
    - Examples: ("numpy", "==1.26.0"), ("pandas", ">=2.0.0"), ("scipy", None)
  - **Exception handling**:
    - Parse failure: Raise ValueError

* PipBatch._evaluate_condition(condition, package_name, installed_packages):
  - **Purpose**: Evaluate policy condition and return whether satisfied
  - **Parameters**:
    - condition: Policy condition object (dictionary)
    - package_name: Name of package currently being processed
    - installed_packages: {package_name: version} dictionary
  - **Execution flow**:
    1. If condition is None, return True (always satisfied)
    2. Branch based on condition["type"]:
       a. "installed" type:
          - target_package = condition.get("package", package_name)
          - Check current version with installed_packages.get(target_package)
          - If not installed (None), return False
          - If spec exists, compare version using packaging.specifiers.SpecifierSet
          - If no spec, only check installation status (True)
       b. "platform" type:
          - If condition["os"] exists, compare with platform.system()
          - If condition["has_gpu"] exists, check GPU presence (torch.cuda.is_available(), etc.)
          - If condition["comfyui_version"] exists, compare ComfyUI version
          - Return True if all conditions satisfied
    3. Return True if all conditions satisfied, False if any unsatisfied
  - **Return value**: bool
  - **Exception handling**:
    - Version comparison failure: Log warning and return False
    - Unknown condition type: Log warning and return False


### Public Methods

* PipBatch.install(package_info, extra_index_url=None, override_policy=False):
  - **Purpose**: Perform policy-based pip package installation (individual package basis)
  - **Parameters**:
    - package_info: Package name and version spec (e.g., "numpy", "numpy==1.26.0", "numpy>=1.20.0")
    - extra_index_url: Additional package repository URL (optional)
    - override_policy: If True, skip policy application and install directly (default: False)
  - **Execution flow**:
    1. Call get_pip_policy() to get policy (lazy loading)
    2. Use self._parse_package_spec() to split package_info into package name and version spec
    3. Call self._get_installed_packages() to get cached installed package information
    4. If override_policy=True → Jump directly to step 10 (skip policy)
    5. Get policy for package name from policy dictionary
    6. If no policy → Jump to step 10 (default installation)
    7. **apply_first_match policy evaluation** (exclusive - only first match):
       - Iterate through policy list top-to-bottom
       - Evaluate each policy's condition with self._evaluate_condition()
       - When first condition-satisfying policy found:
         * type="skip": Log reason and return False (don't install)
         * type="force_version": Change package_info version to policy's version
         * type="replace": Completely replace package_info with policy's replacement package
       - If no matching policy, keep original package_info
    8. **apply_all_matches policy evaluation** (cumulative - all matches):
       - Iterate through policy list top-to-bottom
       - Evaluate each policy's condition with self._evaluate_condition()
       - For all condition-satisfying policies:
         * type="pin_dependencies":
           - For each package in pinned_packages, query current version with self._installed_cache.get(pkg)
           - Pin to installed version in "package==version" format
           - Add to installation package list
         * type="install_with":
           - Add additional_packages to installation package list
         * type="warn":
           - Output message as warning log
           - If allow_continue=false, wait for user confirmation (optional)
    9. Compose final installation package list:
       - Main package (modified/replaced package_info)
       - Packages pinned by pin_dependencies
       - Packages added by install_with
    10. Handle extra_index_url:
       - Parameter-passed extra_index_url takes priority
       - Otherwise use extra_index_url defined in policy
    11. Generate pip/uv command using manager_util.make_pip_cmd():
       - Basic format: ["pip", "install"] + package list
       - If extra_index_url exists: add ["--extra-index-url", url]
    12. Execute command via subprocess
    13. Handle installation failure:
       - If pin_dependencies's on_failure="retry_without_pin":
         * Retry with only main package excluding pinned packages
       - If on_failure="fail":
         * Raise exception and abort installation
       - Otherwise: Log warning and continue
    14. On successful installation:
       - Call self._invalidate_cache() (invalidate cache)
       - Log info if reason exists
       - Return True
  - **Return value**: Installation success status (bool)
  - **Exception handling**:
    - Policy parsing failure: Log warning and proceed with default installation
    - Installation failure: Log error and raise exception (depends on on_failure setting)
  - **Notes**:
    - restore policy not handled in this method (batch-processed in ensure_installed())
    - uninstall policy not handled in this method (batch-processed in ensure_not_installed())

* PipBatch.ensure_not_installed():
  - **Purpose**: Iterate through all policies and remove all packages satisfying uninstall conditions (batch processing)
  - **Parameters**: None
  - **Execution flow**:
    1. Call get_pip_policy() to get policy (lazy loading)
    2. Call self._get_installed_packages() to get cached installed package information
    3. Iterate through all package policies in policy dictionary:
       a. Check if each package has uninstall policy
       b. If uninstall policy exists:
          - Iterate through uninstall policy list top-to-bottom
          - Evaluate each policy's condition with self._evaluate_condition()
          - When first condition-satisfying policy found:
            * Check if target package exists in self._installed_cache
            * If installed:
              - Generate command with manager_util.make_pip_cmd(["uninstall", "-y", target])
              - Execute pip uninstall via subprocess
              - Log reason in info log
              - Add to removed package list
              - Remove package from self._installed_cache
            * Move to next package (only first match per package)
    4. Complete iteration through all package policies
  - **Return value**: List of removed package names (list of str)
  - **Exception handling**:
    - Individual package removal failure: Log warning only and continue to next package
  - **Call timing**:
    - Called at batch operation start to pre-remove conflicting packages
    - Called before multiple package installations to clean installation environment

* PipBatch.ensure_installed():
  - **Purpose**: Iterate through all policies and restore all packages satisfying restore conditions (batch processing)
  - **Parameters**: None
  - **Execution flow**:
    1. Call get_pip_policy() to get policy (lazy loading)
    2. Call self._get_installed_packages() to get cached installed package information
    3. Iterate through all package policies in policy dictionary:
       a. Check if each package has restore policy
       b. If restore policy exists:
          - Iterate through restore policy list top-to-bottom
          - Evaluate each policy's condition with self._evaluate_condition()
          - When first condition-satisfying policy found:
            * Get target package name (policy's "target" field)
            * Get version specified in version field
            * Check current version with self._installed_cache.get(target)
            * If current version is None or different from specified version:
              - Compose as package_spec = f"{target}=={version}" format
              - Generate command with manager_util.make_pip_cmd(["install", package_spec])
              - If extra_index_url exists, add ["--extra-index-url", url]
              - Execute pip install via subprocess
              - Log reason in info log
              - Add to restored package list
              - Update cache: self._installed_cache[target] = version
            * Move to next package (only first match per package)
    4. Complete iteration through all package policies
  - **Return value**: List of restored package names (list of str)
  - **Exception handling**:
    - Individual package installation failure: Log warning only and continue to next package
  - **Call timing**:
    - Called at batch operation end to restore essential package versions
    - Called for environment verification after multiple package installations


## pip-policy.json Examples

### Base Policy File ({manager_util.comfyui_manager_path}/pip-policy.json)
```json
{
  "torch": {
    "apply_first_match": [
      {
        "type": "skip",
        "reason": "PyTorch installation should be managed manually due to CUDA compatibility"
      }
    ]
  },

  "opencv-python": {
    "apply_first_match": [
      {
        "type": "replace",
        "replacement": "opencv-contrib-python",
        "version": ">=4.8.0",
        "reason": "opencv-contrib-python includes all opencv-python features plus extras"
      }
    ]
  },

  "PIL": {
    "apply_first_match": [
      {
        "type": "replace",
        "replacement": "Pillow",
        "reason": "PIL is deprecated, use Pillow instead"
      }
    ]
  },

  "click": {
    "apply_first_match": [
      {
        "condition": {
          "type": "installed",
          "package": "colorama",
          "spec": "<0.5.0"
        },
        "type": "force_version",
        "version": "8.1.3",
        "reason": "click 8.1.3 compatible with colorama <0.5"
      }
    ],
    "apply_all_matches": [
      {
        "type": "pin_dependencies",
        "pinned_packages": ["colorama"],
        "reason": "Prevent colorama upgrade that may break compatibility"
      }
    ]
  },

  "requests": {
    "apply_all_matches": [
      {
        "type": "pin_dependencies",
        "pinned_packages": ["urllib3", "certifi", "charset-normalizer"],
        "on_failure": "retry_without_pin",
        "reason": "Prevent urllib3 from upgrading to 2.x which has breaking changes"
      }
    ]
  },

  "six": {
    "restore": [
      {
        "target": "six",
        "version": "1.16.0",
        "reason": "six must be maintained at 1.16.0 for compatibility"
      }
    ]
  },

  "urllib3": {
    "restore": [
      {
        "condition": {
          "type": "installed",
          "spec": "!=1.26.15"
        },
        "target": "urllib3",
        "version": "1.26.15",
        "reason": "urllib3 must be 1.26.15 for compatibility with legacy code"
      }
    ]
  },

  "onnxruntime": {
    "apply_first_match": [
      {
        "condition": {
          "type": "platform",
          "os": "linux",
          "has_gpu": true
        },
        "type": "replace",
        "replacement": "onnxruntime-gpu",
        "reason": "Use GPU version on Linux with CUDA"
      }
    ]
  },

  "legacy-custom-node-package": {
    "apply_first_match": [
      {
        "condition": {
          "type": "platform",
          "comfyui_version": "<1.0.0"
        },
        "type": "force_version",
        "version": "0.9.0",
        "reason": "legacy-custom-node-package 0.9.0 is compatible with ComfyUI <1.0.0"
      },
      {
        "condition": {
          "type": "platform",
          "comfyui_version": ">=1.0.0"
        },
        "type": "force_version",
        "version": "1.5.0",
        "reason": "legacy-custom-node-package 1.5.0 is required for ComfyUI >=1.0.0"
      }
    ]
  },

  "tensorflow": {
    "apply_all_matches": [
      {
        "condition": {
          "type": "installed",
          "package": "torch"
        },
        "type": "warn",
        "message": "Installing TensorFlow alongside PyTorch may cause CUDA conflicts",
        "allow_continue": true
      }
    ]
  },

  "some-package": {
    "uninstall": [
      {
        "condition": {
          "type": "installed",
          "package": "conflicting-package",
          "spec": ">=2.0.0"
        },
        "target": "conflicting-package",
        "reason": "conflicting-package >=2.0.0 conflicts with some-package"
      }
    ]
  },

  "banned-malicious-package": {
    "uninstall": [
      {
        "target": "banned-malicious-package",
        "reason": "Security vulnerability CVE-2024-XXXXX, always remove if attempting to install"
      }
    ]
  },

  "critical-package": {
    "restore": [
      {
        "condition": {
          "type": "installed",
          "package": "critical-package",
          "spec": "!=1.2.3"
        },
        "target": "critical-package",
        "version": "1.2.3",
        "extra_index_url": "https://custom-repo.example.com/simple",
        "reason": "critical-package must be version 1.2.3, restore if different or missing"
      }
    ]
  },

  "stable-package": {
    "apply_first_match": [
      {
        "condition": {
          "type": "installed",
          "package": "critical-dependency",
          "spec": ">=2.0.0"
        },
        "type": "force_version",
        "version": "1.5.0",
        "extra_index_url": "https://custom-repo.example.com/simple",
        "reason": "stable-package 1.5.0 is required when critical-dependency >=2.0.0 is installed"
      }
    ]
  },

  "new-experimental-package": {
    "apply_all_matches": [
      {
        "type": "pin_dependencies",
        "pinned_packages": ["numpy", "pandas", "scipy"],
        "on_failure": "retry_without_pin",
        "reason": "new-experimental-package may upgrade numpy/pandas/scipy, pin them to prevent breakage"
      }
    ]
  },

  "pytorch-addon": {
    "apply_all_matches": [
      {
        "condition": {
          "type": "installed",
          "package": "torch",
          "spec": ">=2.0.0"
        },
        "type": "pin_dependencies",
        "pinned_packages": ["torch", "torchvision", "torchaudio"],
        "on_failure": "fail",
        "reason": "pytorch-addon must not change PyTorch ecosystem versions"
      }
    ]
  }
}
```

### Policy Structure Schema
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "patternProperties": {
    "^.*$": {
      "type": "object",
      "properties": {
        "uninstall": {
          "type": "array",
          "description": "When condition satisfied (or always if no condition), remove package and terminate",
          "items": {
            "type": "object",
            "required": ["target"],
            "properties": {
              "condition": {
                "type": "object",
                "description": "Optional: always remove if absent",
                "required": ["type"],
                "properties": {
                  "type": {"enum": ["installed", "platform"]},
                  "package": {"type": "string", "description": "Optional: defaults to self"},
                  "spec": {"type": "string", "description": "Optional: version condition"},
                  "os": {"type": "string"},
                  "has_gpu": {"type": "boolean"},
                  "comfyui_version": {"type": "string"}
                }
              },
              "target": {
                "type": "string",
                "description": "Package name to remove"
              },
              "reason": {"type": "string"}
            }
          }
        },
        "restore": {
          "type": "array",
          "description": "When condition satisfied (or always if no condition), restore package and terminate",
          "items": {
            "type": "object",
            "required": ["target", "version"],
            "properties": {
              "condition": {
                "type": "object",
                "description": "Optional: always restore if absent",
                "required": ["type"],
                "properties": {
                  "type": {"enum": ["installed", "platform"]},
                  "package": {"type": "string", "description": "Optional: defaults to self"},
                  "spec": {"type": "string", "description": "Optional: version condition"},
                  "os": {"type": "string"},
                  "has_gpu": {"type": "boolean"},
                  "comfyui_version": {"type": "string"}
                }
              },
              "target": {
                "type": "string",
                "description": "Package name to restore"
              },
              "version": {
                "type": "string",
                "description": "Version to restore"
              },
              "extra_index_url": {"type": "string"},
              "reason": {"type": "string"}
            }
          }
        },
        "apply_first_match": {
          "type": "array",
          "description": "Execute only first condition-satisfying policy (exclusive)",
          "items": {
            "type": "object",
            "required": ["type"],
            "properties": {
              "condition": {
                "type": "object",
                "description": "Optional: always apply if absent",
                "required": ["type"],
                "properties": {
                  "type": {"enum": ["installed", "platform"]},
                  "package": {"type": "string", "description": "Optional: defaults to self"},
                  "spec": {"type": "string", "description": "Optional: version condition"},
                  "os": {"type": "string"},
                  "has_gpu": {"type": "boolean"},
                  "comfyui_version": {"type": "string"}
                }
              },
              "type": {
                "enum": ["skip", "force_version", "replace"],
                "description": "Exclusive action: determines installation method"
              },
              "version": {"type": "string"},
              "replacement": {"type": "string"},
              "extra_index_url": {"type": "string"},
              "reason": {"type": "string"}
            }
          }
        },
        "apply_all_matches": {
          "type": "array",
          "description": "Execute all condition-satisfying policies (cumulative)",
          "items": {
            "type": "object",
            "required": ["type"],
            "properties": {
              "condition": {
                "type": "object",
                "description": "Optional: always apply if absent",
                "required": ["type"],
                "properties": {
                  "type": {"enum": ["installed", "platform"]},
                  "package": {"type": "string", "description": "Optional: defaults to self"},
                  "spec": {"type": "string", "description": "Optional: version condition"},
                  "os": {"type": "string"},
                  "has_gpu": {"type": "boolean"},
                  "comfyui_version": {"type": "string"}
                }
              },
              "type": {
                "enum": ["pin_dependencies", "install_with", "warn"],
                "description": "Cumulative action: adds installation options"
              },
              "pinned_packages": {
                "type": "array",
                "items": {"type": "string"}
              },
              "on_failure": {"enum": ["fail", "retry_without_pin"]},
              "additional_packages": {"type": "array"},
              "message": {"type": "string"},
              "allow_continue": {"type": "boolean"},
              "reason": {"type": "string"}
            }
          }
        }
      }
    }
  }
}
```


## Error Handling

* Default behavior when errors occur during policy execution:
    - Log error and continue
    - Only treat as installation failure when pin_dependencies's on_failure="fail"
    - For other cases, leave warning and attempt originally requested installation


* pip_install: Performs pip package installation
- Use manager_util.make_pip_cmd to generate commands for selective application of uv and pip
- Provide functionality to skip policy application through override_policy flag
