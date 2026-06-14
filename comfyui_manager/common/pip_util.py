"""
pip_util - Policy-based pip package management system

This module provides a policy-based approach to pip package installation
to minimize dependency conflicts and protect existing installed packages.

Usage:
    # Batch operations (policy auto-loaded)
    with PipBatch() as batch:
        batch.ensure_not_installed()
        batch.install("numpy>=1.20")
        batch.install("pandas>=2.0")
        batch.install("scipy>=1.7")
        batch.ensure_installed()
"""

import json
import logging
import platform
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from . import manager_util, context

logger = logging.getLogger(__name__)

# Global policy cache (lazy loaded on first access)
_pip_policy_cache: Optional[Dict] = None


def get_pip_policy() -> Dict:
    """
    Get pip policy with lazy loading.

    Returns the cached policy if available, otherwise loads it from files.
    This function automatically loads the policy on first access.

    Thread safety: This function is NOT thread-safe.
    Ensure single-threaded access during initialization.

    Returns:
        Dictionary of merged pip policies

    Example:
        >>> policy = get_pip_policy()
        >>> numpy_policy = policy.get("numpy", {})
    """
    global _pip_policy_cache

    # Return cached policy if already loaded
    if _pip_policy_cache is not None:
        logger.debug("Returning cached pip policy")
        return _pip_policy_cache

    logger.info("Loading pip policies...")

    # Load base policy
    base_policy = {}
    base_policy_path = Path(manager_util.comfyui_manager_path) / "pip-policy.json"

    try:
        if base_policy_path.exists():
            with open(base_policy_path, 'r', encoding='utf-8') as f:
                base_policy = json.load(f)
            logger.debug(f"Loaded base policy from {base_policy_path}")
        else:
            logger.warning(f"Base policy file not found: {base_policy_path}")
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse base policy JSON: {e}")
        base_policy = {}
    except Exception as e:
        logger.warning(f"Failed to read base policy file: {e}")
        base_policy = {}

    # Load user policy
    user_policy = {}
    user_policy_path = Path(context.manager_files_path) / "pip-policy.user.json"

    try:
        if user_policy_path.exists():
            with open(user_policy_path, 'r', encoding='utf-8') as f:
                user_policy = json.load(f)
            logger.debug(f"Loaded user policy from {user_policy_path}")
        else:
            # Create empty user policy file
            user_policy_path.parent.mkdir(parents=True, exist_ok=True)
            with open(user_policy_path, 'w', encoding='utf-8') as f:
                json.dump({"_comment": "User-specific pip policy overrides"}, f, indent=2)
            logger.info(f"Created empty user policy file: {user_policy_path}")
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse user policy JSON: {e}")
        user_policy = {}
    except Exception as e:
        logger.warning(f"Failed to read user policy file: {e}")
        user_policy = {}

    # Merge policies (package-level override: user completely replaces base per package)
    merged_policy = base_policy.copy()
    for package_name, package_policy in user_policy.items():
        if package_name.startswith("_"):  # Skip metadata fields like _comment
            continue
        merged_policy[package_name] = package_policy  # Complete package replacement

    # Store in global cache
    _pip_policy_cache = merged_policy
    logger.info(f"Policy loaded successfully: {len(_pip_policy_cache)} package policies")

    return _pip_policy_cache


class PipBatch:
    """
    Pip package installation batch manager.

    Maintains pip freeze cache during a batch of operations for performance optimization.

    Usage pattern:
        # Batch operations (policy auto-loaded)
        with PipBatch() as batch:
            batch.ensure_not_installed()
            batch.install("numpy>=1.20")
            batch.install("pandas>=2.0")
            batch.install("scipy>=1.7")
            batch.ensure_installed()

    Attributes:
        _installed_cache: Cache of installed packages from pip freeze
    """

    def __init__(self):
        """Initialize PipBatch with empty cache."""
        self._installed_cache: Optional[Dict[str, str]] = None

    def __enter__(self):
        """Enter context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager and clear cache."""
        self._installed_cache = None
        return False

    def _refresh_installed_cache(self) -> None:
        """
        Refresh the installed packages cache by executing pip freeze.

        Parses pip freeze output into a dictionary of {package_name: version}.
        Ignores editable packages and comments.

        Raises:
            No exceptions raised - failures result in empty cache with warning log
        """
        try:
            cmd = manager_util.make_pip_cmd(["freeze"])
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)

            packages = {}
            for line in result.stdout.strip().split('\n'):
                line = line.strip()

                # Skip empty lines
                if not line:
                    continue

                # Skip editable packages (-e /path/to/package or -e git+https://...)
                # Editable packages don't have version info and are typically development-only
                if line.startswith('-e '):
                    continue

                # Skip comments (defensive: pip freeze typically doesn't output comments,
                # but this handles manually edited requirements.txt or future pip changes)
                if line.startswith('#'):
                    continue

                # Parse package==version
                if '==' in line:
                    try:
                        package_name, version = line.split('==', 1)
                        packages[package_name.strip()] = version.strip()
                    except ValueError:
                        logger.warning(f"Failed to parse pip freeze line: {line}")
                        continue

            self._installed_cache = packages
            logger.debug(f"Refreshed installed packages cache: {len(packages)} packages")

        except subprocess.CalledProcessError as e:
            logger.warning(f"pip freeze failed: {e}")
            self._installed_cache = {}
        except Exception as e:
            logger.warning(f"Failed to refresh installed packages cache: {e}")
            self._installed_cache = {}

    def _get_installed_packages(self) -> Dict[str, str]:
        """
        Get cached installed packages, refresh if cache is None.

        Returns:
            Dictionary of {package_name: version}
        """
        if self._installed_cache is None:
            self._refresh_installed_cache()
        return self._installed_cache

    def _invalidate_cache(self) -> None:
        """
        Invalidate the installed packages cache.

        Should be called after install/uninstall operations.
        """
        self._installed_cache = None

    def _parse_package_spec(self, package_info: str) -> Tuple[str, Optional[str]]:
        """
        Parse package spec string into package name and version spec using PEP 508.

        Uses the packaging library to properly parse package specifications according to
        PEP 508 standard, which handles complex cases like extras and multiple version
        constraints that simple regex cannot handle correctly.

        Args:
            package_info: Package specification like "numpy", "numpy==1.26.0", "numpy>=1.20.0",
                         or complex specs like "package[extra]>=1.0,<2.0"

        Returns:
            Tuple of (package_name, version_spec)
            Examples: ("numpy", "==1.26.0"), ("pandas", ">=2.0.0"), ("scipy", None)
            Package names are normalized (e.g., "NumPy" -> "numpy")

        Raises:
            ValueError: If package_info cannot be parsed according to PEP 508

        Example:
            >>> batch._parse_package_spec("numpy>=1.20")
            ("numpy", ">=1.20")
            >>> batch._parse_package_spec("requests[security]>=2.0,<3.0")
            ("requests", ">=2.0,<3.0")
        """
        try:
            req = Requirement(package_info)
            package_name = req.name  # Normalized package name
            version_spec = str(req.specifier) if req.specifier else None
            return package_name, version_spec
        except Exception as e:
            raise ValueError(f"Invalid package spec: {package_info}") from e

    def _evaluate_condition(self, condition: Optional[Dict], package_name: str,
                           installed_packages: Dict[str, str]) -> bool:
        """
        Evaluate policy condition and return whether it's satisfied.

        Args:
            condition: Policy condition object (dict) or None
            package_name: Current package being processed
            installed_packages: Dictionary of {package_name: version}

        Returns:
            True if condition is satisfied, False otherwise
            None condition always returns True

        Example:
            >>> condition = {"type": "installed", "package": "numpy", "spec": ">=1.20"}
            >>> batch._evaluate_condition(condition, "numba", {"numpy": "1.26.0"})
            True
        """
        # No condition means always satisfied
        if condition is None:
            return True

        condition_type = condition.get("type")

        if condition_type == "installed":
            # Check if a package is installed with optional version spec
            target_package = condition.get("package", package_name)
            installed_version = installed_packages.get(target_package)

            # Package not installed
            if installed_version is None:
                return False

            # Check version spec if provided
            spec = condition.get("spec")
            if spec:
                try:
                    specifier = SpecifierSet(spec)
                    return Version(installed_version) in specifier
                except Exception as e:
                    logger.warning(f"Failed to compare version {installed_version} with spec {spec}: {e}")
                    return False

            # Package is installed (no spec check)
            return True

        elif condition_type == "platform":
            # Check platform conditions (os, has_gpu, comfyui_version)
            conditions_met = True

            # Check OS
            if "os" in condition:
                expected_os = condition["os"].lower()
                actual_os = platform.system().lower()
                if expected_os not in actual_os and actual_os not in expected_os:
                    conditions_met = False

            # Check GPU availability
            if "has_gpu" in condition:
                expected_gpu = condition["has_gpu"]
                try:
                    import torch
                    has_gpu = torch.cuda.is_available()
                except ImportError:
                    has_gpu = False

                if expected_gpu != has_gpu:
                    conditions_met = False

            # Check ComfyUI version
            if "comfyui_version" in condition:
                # TODO: Implement ComfyUI version check
                logger.warning("ComfyUI version condition not yet implemented")

            return conditions_met

        else:
            logger.warning(f"Unknown condition type: {condition_type}")
            return False

    def install(self, package_info: str, extra_index_url: Optional[str] = None,
                override_policy: bool = False) -> bool:
        """
        Install a pip package with policy-based modifications.

        Args:
            package_info: Package specification (e.g., "numpy", "numpy==1.26.0", "numpy>=1.20.0")
            extra_index_url: Additional package repository URL (optional)
            override_policy: If True, skip policy application and install directly (default: False)

        Returns:
            True if installation succeeded, False if skipped by policy

        Raises:
            ValueError: If package_info cannot be parsed
            subprocess.CalledProcessError: If installation fails (depending on policy on_failure settings)

        Example:
            >>> with PipBatch() as batch:
            ...     batch.install("numpy>=1.20")
            ...     batch.install("torch", override_policy=True)
        """
        # Parse package spec
        try:
            package_name, version_spec = self._parse_package_spec(package_info)
        except ValueError as e:
            logger.error(f"Invalid package spec: {e}")
            raise

        # Get installed packages cache
        installed_packages = self._get_installed_packages()

        # Override policy - skip to direct installation
        if override_policy:
            logger.info(f"Installing {package_info} (policy override)")
            cmd = manager_util.make_pip_cmd(["install", package_info])
            if extra_index_url:
                cmd.extend(["--extra-index-url", extra_index_url])

            try:
                subprocess.run(cmd, check=True)
                self._invalidate_cache()
                logger.info(f"Successfully installed {package_info}")
                return True
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to install {package_info}: {e}")
                raise

        # Get policy (lazy loading)
        pip_policy = get_pip_policy()
        policy = pip_policy.get(package_name, {})

        # If no policy, proceed with default installation
        if not policy:
            logger.debug(f"No policy found for {package_name}, proceeding with default installation")
            cmd = manager_util.make_pip_cmd(["install", package_info])
            if extra_index_url:
                cmd.extend(["--extra-index-url", extra_index_url])

            try:
                subprocess.run(cmd, check=True)
                self._invalidate_cache()
                logger.info(f"Successfully installed {package_info}")
                return True
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to install {package_info}: {e}")
                raise

        # Apply apply_first_match policies (exclusive - first match only)
        final_package_info = package_info
        final_extra_index_url = extra_index_url
        policy_reason = None

        apply_first_match = policy.get("apply_first_match", [])
        for policy_item in apply_first_match:
            condition = policy_item.get("condition")
            if self._evaluate_condition(condition, package_name, installed_packages):
                policy_type = policy_item.get("type")

                if policy_type == "skip":
                    reason = policy_item.get("reason", "No reason provided")
                    logger.info(f"Skipping installation of {package_name}: {reason}")
                    return False

                elif policy_type == "force_version":
                    forced_version = policy_item.get("version")
                    final_package_info = f"{package_name}=={forced_version}"
                    policy_reason = policy_item.get("reason")
                    if "extra_index_url" in policy_item:
                        final_extra_index_url = policy_item["extra_index_url"]
                    logger.info(f"Force version for {package_name}: {forced_version} ({policy_reason})")
                    break  # First match only

                elif policy_type == "replace":
                    replacement = policy_item.get("replacement")
                    replacement_version = policy_item.get("version", "")
                    if replacement_version:
                        final_package_info = f"{replacement}{replacement_version}"
                    else:
                        final_package_info = replacement
                    policy_reason = policy_item.get("reason")
                    if "extra_index_url" in policy_item:
                        final_extra_index_url = policy_item["extra_index_url"]
                    logger.info(f"Replacing {package_name} with {final_package_info}: {policy_reason}")
                    break  # First match only

        # Apply apply_all_matches policies (cumulative - all matches)
        additional_packages = []
        pinned_packages = []
        pin_on_failure = "fail"

        apply_all_matches = policy.get("apply_all_matches", [])
        for policy_item in apply_all_matches:
            condition = policy_item.get("condition")
            if self._evaluate_condition(condition, package_name, installed_packages):
                policy_type = policy_item.get("type")

                if policy_type == "pin_dependencies":
                    pin_list = policy_item.get("pinned_packages", [])
                    for pkg in pin_list:
                        installed_version = installed_packages.get(pkg)
                        if installed_version:
                            pinned_packages.append(f"{pkg}=={installed_version}")
                        else:
                            logger.warning(f"Cannot pin {pkg}: not currently installed")
                    pin_on_failure = policy_item.get("on_failure", "fail")
                    reason = policy_item.get("reason", "")
                    logger.info(f"Pinning dependencies: {pinned_packages} ({reason})")

                elif policy_type == "install_with":
                    additional = policy_item.get("additional_packages", [])
                    additional_packages.extend(additional)
                    reason = policy_item.get("reason", "")
                    logger.info(f"Installing additional packages: {additional} ({reason})")

                elif policy_type == "warn":
                    message = policy_item.get("message", "")
                    allow_continue = policy_item.get("allow_continue", True)
                    logger.warning(f"Policy warning for {package_name}: {message}")
                    if not allow_continue:
                        # TODO: Implement user confirmation
                        logger.info("User confirmation required (not implemented, continuing)")

        # Build final package list
        packages_to_install = [final_package_info] + pinned_packages + additional_packages

        # Execute installation
        cmd = manager_util.make_pip_cmd(["install"] + packages_to_install)
        if final_extra_index_url:
            cmd.extend(["--extra-index-url", final_extra_index_url])

        try:
            subprocess.run(cmd, check=True)
            self._invalidate_cache()
            if policy_reason:
                logger.info(f"Successfully installed {final_package_info}: {policy_reason}")
            else:
                logger.info(f"Successfully installed {final_package_info}")
            return True

        except subprocess.CalledProcessError as e:
            # Handle installation failure
            if pinned_packages and pin_on_failure == "retry_without_pin":
                logger.warning(f"Installation failed with pinned dependencies, retrying without pins")
                retry_cmd = manager_util.make_pip_cmd(["install", final_package_info])
                if final_extra_index_url:
                    retry_cmd.extend(["--extra-index-url", final_extra_index_url])

                try:
                    subprocess.run(retry_cmd, check=True)
                    self._invalidate_cache()
                    logger.info(f"Successfully installed {final_package_info} (without pins)")
                    return True
                except subprocess.CalledProcessError as retry_error:
                    logger.error(f"Retry installation also failed: {retry_error}")
                    raise

            elif pin_on_failure == "fail":
                logger.error(f"Installation failed: {e}")
                raise

            else:
                logger.warning(f"Installation failed, but continuing: {e}")
                return False

    def ensure_not_installed(self) -> List[str]:
        """
        Remove all packages matching uninstall policies (batch processing).

        Iterates through all package policies and executes uninstall actions
        where conditions are satisfied.

        Returns:
            List of removed package names

        Example:
            >>> with PipBatch() as batch:
            ...     removed = batch.ensure_not_installed()
            ...     print(f"Removed: {removed}")
        """
        # Get policy (lazy loading)
        pip_policy = get_pip_policy()

        installed_packages = self._get_installed_packages()
        removed_packages = []

        for package_name, policy in pip_policy.items():
            uninstall_policies = policy.get("uninstall", [])

            for uninstall_policy in uninstall_policies:
                condition = uninstall_policy.get("condition")

                if self._evaluate_condition(condition, package_name, installed_packages):
                    target = uninstall_policy.get("target")
                    reason = uninstall_policy.get("reason", "No reason provided")

                    # Check if target is installed
                    if target in installed_packages:
                        try:
                            cmd = manager_util.make_pip_cmd(["uninstall", "-y", target])
                            subprocess.run(cmd, check=True)

                            logger.info(f"Uninstalled {target}: {reason}")
                            removed_packages.append(target)

                            # Remove from cache
                            del installed_packages[target]

                        except subprocess.CalledProcessError as e:
                            logger.warning(f"Failed to uninstall {target}: {e}")

                    # First match only per package
                    break

        return removed_packages

    def ensure_installed(self) -> List[str]:
        """
        Restore all packages matching restore policies (batch processing).

        Iterates through all package policies and executes restore actions
        where conditions are satisfied.

        Returns:
            List of restored package names

        Example:
            >>> with PipBatch() as batch:
            ...     batch.install("numpy>=1.20")
            ...     restored = batch.ensure_installed()
            ...     print(f"Restored: {restored}")
        """
        # Get policy (lazy loading)
        pip_policy = get_pip_policy()

        installed_packages = self._get_installed_packages()
        restored_packages = []

        for package_name, policy in pip_policy.items():
            restore_policies = policy.get("restore", [])

            for restore_policy in restore_policies:
                condition = restore_policy.get("condition")

                if self._evaluate_condition(condition, package_name, installed_packages):
                    target = restore_policy.get("target")
                    version = restore_policy.get("version")
                    reason = restore_policy.get("reason", "No reason provided")
                    extra_index_url = restore_policy.get("extra_index_url")

                    # Check if target needs restoration
                    current_version = installed_packages.get(target)

                    if current_version is None or current_version != version:
                        try:
                            package_spec = f"{target}=={version}"
                            cmd = manager_util.make_pip_cmd(["install", package_spec])

                            if extra_index_url:
                                cmd.extend(["--extra-index-url", extra_index_url])

                            subprocess.run(cmd, check=True)

                            logger.info(f"Restored {package_spec}: {reason}")
                            restored_packages.append(target)

                            # Update cache
                            installed_packages[target] = version

                        except subprocess.CalledProcessError as e:
                            logger.warning(f"Failed to restore {target}: {e}")

                    # First match only per package
                    break

        return restored_packages
