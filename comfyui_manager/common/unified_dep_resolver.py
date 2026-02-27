"""Unified Dependency Resolver for ComfyUI Manager.

Resolves and installs all node-pack dependencies at once using ``uv pip compile``
followed by ``uv pip install -r``, replacing per-node-pack ``pip install`` calls.

Responsibility scope
--------------------
- Dependency collection, resolution, and installation **only**.
- ``install.py`` execution and ``PIPFixer`` calls are the caller's responsibility.

See Also
--------
- docs/dev/PRD-unified-dependency-resolver.md
- docs/dev/DESIGN-unified-dependency-resolver.md
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass, field

from . import manager_util

logger = logging.getLogger("ComfyUI-Manager")

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class UvNotAvailableError(RuntimeError):
    """Raised when neither ``python -m uv`` nor standalone ``uv`` is found."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PackageRequirement:
    """Individual package dependency."""
    name: str       # Normalised package name
    spec: str       # Original spec string (e.g. ``torch>=2.0``)
    source: str     # Absolute path of the source node pack


@dataclass
class CollectedDeps:
    """Aggregated dependency collection result."""
    requirements: list[PackageRequirement] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    sources: dict[str, list[str]] = field(default_factory=dict)
    extra_index_urls: list[str] = field(default_factory=list)


@dataclass
class LockfileResult:
    """Result of ``uv pip compile``."""
    success: bool
    lockfile_path: str | None = None
    conflicts: list[str] = field(default_factory=list)
    stderr: str = ""


@dataclass
class InstallResult:
    """Result of ``uv pip install -r`` (atomic: all-or-nothing)."""
    success: bool
    installed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    stderr: str = ""


@dataclass
class ResolveResult:
    """Full pipeline result."""
    success: bool
    collected: CollectedDeps | None = None
    lockfile: LockfileResult | None = None
    install: InstallResult | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

_TMP_PREFIX = "comfyui_resolver_"

# Security: reject dangerous requirement patterns.
_DANGEROUS_PATTERNS = re.compile(
    r'^(-r\b|--requirement\b|-e\b|--editable\b|-c\b|--constraint\b'
    r'|--find-links\b|-f\b|.*@\s*file://)',
    re.IGNORECASE,
)

# Credential redaction in index URLs.
_CREDENTIAL_PATTERN = re.compile(r'://([^@]+)@')

# Version-spec parsing (same regex as existing ``is_blacklisted()``).
_VERSION_SPEC_PATTERN = re.compile(r'([^<>!~=]+)([<>!~=]=?)([^ ]*)')



def collect_node_pack_paths(custom_nodes_dirs: list[str]) -> list[str]:
    """Collect all installed node-pack directory paths.

    Parameters
    ----------
    custom_nodes_dirs:
        Base directories returned by ``folder_paths.get_folder_paths('custom_nodes')``.

    Returns
    -------
    list[str]
        Paths of node-pack directories (immediate subdirectories of each base).
    """
    paths: list[str] = []
    for base in custom_nodes_dirs:
        if os.path.isdir(base):
            for name in os.listdir(base):
                fullpath = os.path.join(base, name)
                if os.path.isdir(fullpath):
                    paths.append(fullpath)
    return paths


def collect_base_requirements(comfy_path: str) -> list[str]:
    """Read ComfyUI's own base requirements as constraint lines.

    Reads ``requirements.txt`` and ``manager_requirements.txt`` from *comfy_path*.
    These are ComfyUI-level dependencies only — never read from node packs.

    Parameters
    ----------
    comfy_path:
        Root directory of the ComfyUI installation.

    Returns
    -------
    list[str]
        Non-empty, non-comment requirement lines.
    """
    reqs: list[str] = []
    for filename in ("requirements.txt", "manager_requirements.txt"):
        req_path = os.path.join(comfy_path, filename)
        if os.path.exists(req_path):
            with open(req_path, encoding="utf-8") as f:
                reqs.extend(
                    line.strip() for line in f
                    if line.strip() and not line.strip().startswith('#')
                )
    return reqs


class UnifiedDepResolver:
    """Unified dependency resolver.

    Resolves and installs all dependencies of (installed + new) node packs at
    once using *uv*.

    Parameters
    ----------
    node_pack_paths:
        Absolute paths of node-pack directories to consider.
    base_requirements:
        Lines from ComfyUI's own ``requirements.txt`` (used as constraints).
    blacklist:
        Package names to skip unconditionally (default: ``cm_global.pip_blacklist``).
    overrides:
        Package-name remapping dict (default: ``cm_global.pip_overrides``).
    downgrade_blacklist:
        Packages whose installed versions must not be downgraded
        (default: ``cm_global.pip_downgrade_blacklist``).
    """

    def __init__(
        self,
        node_pack_paths: list[str],
        base_requirements: list[str] | None = None,
        blacklist: set[str] | None = None,
        overrides: dict[str, str] | None = None,
        downgrade_blacklist: list[str] | None = None,
    ) -> None:
        self.node_pack_paths = node_pack_paths
        self.base_requirements = base_requirements or []
        self.blacklist: set[str] = blacklist if blacklist is not None else set()
        self.overrides: dict[str, str] = overrides if overrides is not None else {}
        self.downgrade_blacklist: list[str] = (
            downgrade_blacklist if downgrade_blacklist is not None else []
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve_and_install(self) -> ResolveResult:
        """Execute the full pipeline: cleanup → collect → compile → install."""
        self.cleanup_stale_tmp()

        tmp_dir: str | None = None
        try:
            # 1. Collect
            collected = self.collect_requirements()
            if not collected.requirements:
                logger.info("[UnifiedDepResolver] No dependencies to resolve")
                return ResolveResult(success=True, collected=collected)

            logger.info(
                "[UnifiedDepResolver] Collected %d deps from %d sources (skipped %d)",
                len(collected.requirements),
                len(collected.sources),
                len(collected.skipped),
            )

            # 2. Compile
            lockfile = self.compile_lockfile(collected)
            if not lockfile.success:
                return ResolveResult(
                    success=False,
                    collected=collected,
                    lockfile=lockfile,
                    error=f"compile failed: {'; '.join(lockfile.conflicts)}",
                )
            # tmp_dir is the parent of lockfile_path
            tmp_dir = os.path.dirname(lockfile.lockfile_path)  # type: ignore[arg-type]

            # 3. Install
            install = self.install_from_lockfile(lockfile.lockfile_path)  # type: ignore[arg-type]
            return ResolveResult(
                success=install.success,
                collected=collected,
                lockfile=lockfile,
                install=install,
                error=install.stderr if not install.success else None,
            )
        except UvNotAvailableError:
            raise
        except Exception as exc:
            logger.warning("[UnifiedDepResolver] unexpected error: %s", exc)
            return ResolveResult(success=False, error=str(exc))
        finally:
            if tmp_dir and os.path.isdir(tmp_dir):
                shutil.rmtree(tmp_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Step 1: collect
    # ------------------------------------------------------------------

    def collect_requirements(self) -> CollectedDeps:
        """Collect dependencies from all node packs."""
        requirements: list[PackageRequirement] = []
        skipped: list[tuple[str, str]] = []
        sources: dict[str, list[str]] = defaultdict(list)
        extra_index_urls: list[str] = []

        # Snapshot installed packages once to avoid repeated subprocess calls.
        # Skip when downgrade_blacklist is empty (the common default).
        installed_snapshot = (
            manager_util.get_installed_packages()
            if self.downgrade_blacklist else {}
        )

        for pack_path in self.node_pack_paths:
            # Exclude disabled node packs (directory-based mechanism).
            if self._is_disabled_path(pack_path):
                continue

            req_file = os.path.join(pack_path, "requirements.txt")
            if not os.path.exists(req_file):
                continue

            for raw_line in self._read_requirements(req_file):
                line = raw_line.split('#')[0].strip()
                if not line:
                    continue

                # 0. Security: reject dangerous patterns
                if _DANGEROUS_PATTERNS.match(line):
                    skipped.append((line, f"rejected: dangerous pattern in {pack_path}"))
                    logger.warning(
                        "[UnifiedDepResolver] rejected dangerous line: '%s' from %s",
                        line, pack_path,
                    )
                    continue

                # 1. Separate --index-url / --extra-index-url handling
                #    (before path separator check, because URLs contain '/')
                if '--index-url' in line or '--extra-index-url' in line:
                    pkg_spec, index_urls = self._split_index_url(line)
                    extra_index_urls.extend(index_urls)
                    line = pkg_spec
                    if not line:
                        # Standalone option line (no package prefix)
                        continue

                # Reject path separators in package name portion
                pkg_name_part = re.split(r'[><=!~;]', line)[0]
                if '/' in pkg_name_part or '\\' in pkg_name_part:
                    skipped.append((line, "rejected: path separator in package name"))
                    logger.warning(
                        "[UnifiedDepResolver] rejected path separator: '%s' from %s",
                        line, pack_path,
                    )
                    continue

                # 2. Remap package name
                pkg_spec = self._remap_package(line)

                # 3. Extract normalised name
                pkg_name = self._extract_package_name(pkg_spec)

                # 4. Blacklist check
                if pkg_name in self.blacklist:
                    skipped.append((pkg_spec, "blacklisted"))
                    continue

                # 5. Downgrade blacklist check
                if self._is_downgrade_blacklisted(pkg_name, pkg_spec,
                                                  installed_snapshot):
                    skipped.append((pkg_spec, "downgrade blacklisted"))
                    continue

                # 6. Collect (no dedup — uv handles resolution)
                requirements.append(
                    PackageRequirement(name=pkg_name, spec=pkg_spec, source=pack_path)
                )
                sources[pkg_name].append(pack_path)

        return CollectedDeps(
            requirements=requirements,
            skipped=skipped,
            sources=dict(sources),
            extra_index_urls=list(set(extra_index_urls)),
        )

    # ------------------------------------------------------------------
    # Step 2: compile
    # ------------------------------------------------------------------

    def compile_lockfile(self, deps: CollectedDeps) -> LockfileResult:
        """Generate pinned requirements via ``uv pip compile``."""
        tmp_dir = tempfile.mkdtemp(prefix=_TMP_PREFIX)

        try:
            # Write temp requirements
            tmp_req = os.path.join(tmp_dir, "input-requirements.txt")
            with open(tmp_req, "w", encoding="utf-8") as fh:
                for req in deps.requirements:
                    fh.write(req.spec + "\n")

            # Write constraints (base dependencies)
            tmp_constraints: str | None = None
            if self.base_requirements:
                tmp_constraints = os.path.join(tmp_dir, "constraints.txt")
                with open(tmp_constraints, "w", encoding="utf-8") as fh:
                    for line in self.base_requirements:
                        fh.write(line.strip() + "\n")

            lockfile_path = os.path.join(tmp_dir, "resolved-requirements.txt")

            cmd = self._get_uv_cmd() + [
                "pip", "compile",
                tmp_req,
                "--output-file", lockfile_path,
                "--python", sys.executable,
            ]
            if tmp_constraints:
                cmd += ["--constraint", tmp_constraints]

            for url in deps.extra_index_urls:
                logger.info(
                    "[UnifiedDepResolver] extra-index-url: %s",
                    self._redact_url(url),
                )
                cmd += ["--extra-index-url", url]

            logger.info("[UnifiedDepResolver] running: %s", " ".join(
                self._redact_url(c) for c in cmd
            ))

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
            except subprocess.TimeoutExpired:
                logger.warning("[UnifiedDepResolver] uv pip compile timed out (300s)")
                return LockfileResult(
                    success=False,
                    conflicts=["compile timeout exceeded (300s)"],
                    stderr="TimeoutExpired",
                )

            if result.returncode != 0:
                conflicts = self._parse_conflicts(result.stderr)
                return LockfileResult(
                    success=False,
                    conflicts=conflicts,
                    stderr=result.stderr,
                )

            if not os.path.exists(lockfile_path):
                return LockfileResult(
                    success=False,
                    conflicts=["lockfile not created despite success return code"],
                    stderr=result.stderr,
                )

            return LockfileResult(success=True, lockfile_path=lockfile_path)

        except UvNotAvailableError:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    # ------------------------------------------------------------------
    # Step 3: install
    # ------------------------------------------------------------------

    def install_from_lockfile(self, lockfile_path: str) -> InstallResult:
        """Install from pinned requirements (``uv pip install -r``).

        Do **not** use ``uv pip sync`` — it deletes packages not in the
        lockfile, risking removal of torch, ComfyUI deps, etc.
        """
        cmd = self._get_uv_cmd() + [
            "pip", "install",
            "--requirement", lockfile_path,
            "--python", sys.executable,
        ]

        logger.info("[UnifiedDepResolver] running: %s", " ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
            )
        except subprocess.TimeoutExpired:
            logger.warning("[UnifiedDepResolver] uv pip install timed out (600s)")
            return InstallResult(
                success=False,
                stderr="TimeoutExpired: install exceeded 600s",
            )

        installed, skipped_pkgs = self._parse_install_output(result)

        return InstallResult(
            success=result.returncode == 0,
            installed=installed,
            skipped=skipped_pkgs,
            stderr=result.stderr if result.returncode != 0 else "",
        )

    # ------------------------------------------------------------------
    # uv command resolution
    # ------------------------------------------------------------------

    def _get_uv_cmd(self) -> list[str]:
        """Determine the ``uv`` command to use.

        ``python_embeded`` spelling is intentional — matches the actual path
        name in the ComfyUI Windows distribution.
        """
        embedded = 'python_embeded' in sys.executable

        # 1. Try uv as a Python module
        try:
            test_cmd = (
                [sys.executable]
                + (['-s'] if embedded else [])
                + ['-m', 'uv', '--version']
            )
            subprocess.check_output(test_cmd, stderr=subprocess.DEVNULL, timeout=5)
            return [sys.executable] + (['-s'] if embedded else []) + ['-m', 'uv']
        except Exception:
            pass

        # 2. Standalone uv executable
        if shutil.which('uv'):
            return ['uv']

        raise UvNotAvailableError("uv is not available")

    # ------------------------------------------------------------------
    # Helpers — collection
    # ------------------------------------------------------------------

    @staticmethod
    def _is_disabled_path(path: str) -> bool:
        """Return ``True`` if *path* is within a ``.disabled`` directory."""
        # New style: custom_nodes/.disabled/{name}
        if '/.disabled/' in path or os.path.basename(os.path.dirname(path)) == '.disabled':
            return True
        # Old style: {name}.disabled suffix
        if path.rstrip('/').endswith('.disabled'):
            return True
        return False

    @staticmethod
    def _read_requirements(filepath: str) -> list[str]:
        """Read requirements file using ``robust_readlines`` pattern."""
        return manager_util.robust_readlines(filepath)

    @staticmethod
    def _split_index_url(line: str) -> tuple[str, list[str]]:
        """Split index-url options from a requirement line.

        Handles lines with one or more ``--index-url`` / ``--extra-index-url``
        options.  Returns ``(package_spec, [url, ...])``.

        Examples::

            "torch --extra-index-url U1 --index-url U2"
            → ("torch", ["U1", "U2"])

            "--index-url URL"
            → ("", ["URL"])
        """
        urls: list[str] = []
        remainder_tokens: list[str] = []

        # Regex: match --extra-index-url or --index-url followed by its value
        option_re = re.compile(
            r'(--(?:extra-)?index-url)\s+(\S+)'
        )

        # Pattern for bare option flags without a URL value
        bare_option_re = re.compile(r'^--(?:extra-)?index-url$')

        last_end = 0
        for m in option_re.finditer(line):
            # Text before this option is part of the package spec
            before = line[last_end:m.start()].strip()
            if before:
                remainder_tokens.append(before)
            urls.append(m.group(2))
            last_end = m.end()

        # Trailing text after last option
        trailing = line[last_end:].strip()
        if trailing:
            remainder_tokens.append(trailing)

        # Strip any bare option flags that leaked into remainder tokens
        # (e.g. "--index-url" with no URL value after it)
        remainder_tokens = [
            t for t in remainder_tokens if not bare_option_re.match(t)
        ]

        pkg_spec = " ".join(remainder_tokens).strip()
        return pkg_spec, urls

    def _remap_package(self, pkg: str) -> str:
        """Apply ``pip_overrides`` remapping."""
        if pkg in self.overrides:
            remapped = self.overrides[pkg]
            logger.info("[UnifiedDepResolver] '%s' remapped to '%s'", pkg, remapped)
            return remapped
        return pkg

    @staticmethod
    def _extract_package_name(spec: str) -> str:
        """Extract normalised package name from a requirement spec."""
        name = re.split(r'[><=!~;\[@ ]', spec)[0].strip()
        return name.lower().replace('-', '_')

    def _is_downgrade_blacklisted(self, pkg_name: str, pkg_spec: str,
                                      installed: dict) -> bool:
        """Reproduce the downgrade logic from ``is_blacklisted()``.

        Uses ``manager_util.StrictVersion`` — **not** ``packaging.version``.

        Args:
            installed: Pre-fetched snapshot from
                ``manager_util.get_installed_packages()``.
        """
        if pkg_name not in self.downgrade_blacklist:
            return False

        match = _VERSION_SPEC_PATTERN.search(pkg_spec)

        if match is None:
            # No version spec: prevent reinstall if already installed
            if pkg_name in installed:
                return True
        elif match.group(2) in ('<=', '==', '<', '~='):
            if pkg_name in installed:
                try:
                    installed_ver = manager_util.StrictVersion(installed[pkg_name])
                    requested_ver = manager_util.StrictVersion(match.group(3))
                    if installed_ver >= requested_ver:
                        return True
                except (ValueError, TypeError):
                    logger.warning(
                        "[UnifiedDepResolver] version parse failed: %s", pkg_spec,
                    )
                    return False

        return False

    # ------------------------------------------------------------------
    # Helpers — parsing & output
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_conflicts(stderr: str) -> list[str]:
        """Extract conflict descriptions from ``uv pip compile`` stderr."""
        conflicts: list[str] = []
        for line in stderr.splitlines():
            line = line.strip()
            if line and ('conflict' in line.lower() or 'error' in line.lower()):
                conflicts.append(line)
        return conflicts or [stderr.strip()] if stderr.strip() else []

    @staticmethod
    def _parse_install_output(
        result: subprocess.CompletedProcess[str],
    ) -> tuple[list[str], list[str]]:
        """Parse ``uv pip install`` stdout for installed/skipped packages."""
        installed: list[str] = []
        skipped_pkgs: list[str] = []
        for line in result.stdout.splitlines():
            line_lower = line.strip().lower()
            if 'installed' in line_lower or 'updated' in line_lower:
                installed.append(line.strip())
            elif 'already' in line_lower or 'satisfied' in line_lower:
                skipped_pkgs.append(line.strip())
        return installed, skipped_pkgs

    @staticmethod
    def _redact_url(url: str) -> str:
        """Mask ``user:pass@`` credentials in URLs."""
        return _CREDENTIAL_PATTERN.sub('://****@', url)

    # ------------------------------------------------------------------
    # Temp-file housekeeping
    # ------------------------------------------------------------------

    @classmethod
    def cleanup_stale_tmp(cls, max_age_seconds: int = 3600) -> None:
        """Remove stale temp directories from previous abnormal terminations."""
        tmp_root = tempfile.gettempdir()
        now = time.time()
        for entry in os.scandir(tmp_root):
            if entry.is_dir() and entry.name.startswith(_TMP_PREFIX):
                try:
                    age = now - entry.stat().st_mtime
                    if age > max_age_seconds:
                        shutil.rmtree(entry.path, ignore_errors=True)
                        logger.info(
                            "[UnifiedDepResolver] cleaned stale tmp: %s", entry.path,
                        )
                except OSError:
                    pass
