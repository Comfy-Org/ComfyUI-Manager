"""Tests for comfyui_manager.common.unified_dep_resolver."""

from __future__ import annotations

import importlib
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
from unittest import mock

import pytest

# ---------------------------------------------------------------------------
# Import the module under test by loading it directly, replacing the
# ``from . import manager_util`` relative import with a fake module.
# This avoids needing the full ComfyUI runtime.
# ---------------------------------------------------------------------------

_MOCK_INSTALLED_PACKAGES: dict[str, str] = {}


class _FakeStrictVersion:
    """Minimal replica of manager_util.StrictVersion for testing."""

    def __init__(self, version_string: str) -> None:
        parts = version_string.split('.')
        self.major = int(parts[0])
        self.minor = int(parts[1]) if len(parts) > 1 else 0
        self.patch = int(parts[2]) if len(parts) > 2 else 0

    def __ge__(self, other: _FakeStrictVersion) -> bool:
        return (self.major, self.minor, self.patch) >= (other.major, other.minor, other.patch)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _FakeStrictVersion):
            return NotImplemented
        return (self.major, self.minor, self.patch) == (other.major, other.minor, other.patch)

    def __lt__(self, other: _FakeStrictVersion) -> bool:
        return (self.major, self.minor, self.patch) < (other.major, other.minor, other.patch)


def _fake_get_installed_packages(renew: bool = False) -> dict[str, str]:
    return _MOCK_INSTALLED_PACKAGES


def _fake_robust_readlines(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8") as f:
        return f.readlines()


# Build a fake manager_util module
_manager_util_fake = types.ModuleType("comfyui_manager.common.manager_util")
_manager_util_fake.StrictVersion = _FakeStrictVersion
_manager_util_fake.get_installed_packages = _fake_get_installed_packages
_manager_util_fake.robust_readlines = _fake_robust_readlines

# Ensure parent packages exist in sys.modules
if "comfyui_manager" not in sys.modules:
    sys.modules["comfyui_manager"] = types.ModuleType("comfyui_manager")
if "comfyui_manager.common" not in sys.modules:
    _common_mod = types.ModuleType("comfyui_manager.common")
    sys.modules["comfyui_manager.common"] = _common_mod
    sys.modules["comfyui_manager"].common = _common_mod  # type: ignore[attr-defined]

# Inject the fake manager_util
sys.modules["comfyui_manager.common.manager_util"] = _manager_util_fake
sys.modules["comfyui_manager.common"].manager_util = _manager_util_fake  # type: ignore[attr-defined]

# Now load the module under test via spec
_MODULE_PATH = os.path.join(
    os.path.dirname(__file__), os.pardir,
    "comfyui_manager", "common", "unified_dep_resolver.py",
)
_spec = importlib.util.spec_from_file_location(
    "comfyui_manager.common.unified_dep_resolver",
    os.path.abspath(_MODULE_PATH),
)
assert _spec is not None and _spec.loader is not None
_udr_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _udr_module
_spec.loader.exec_module(_udr_module)

# Pull symbols into the test namespace
CollectedDeps = _udr_module.CollectedDeps
InstallResult = _udr_module.InstallResult
LockfileResult = _udr_module.LockfileResult
PackageRequirement = _udr_module.PackageRequirement
ResolveResult = _udr_module.ResolveResult
UnifiedDepResolver = _udr_module.UnifiedDepResolver
UvNotAvailableError = _udr_module.UvNotAvailableError
collect_base_requirements = _udr_module.collect_base_requirements
collect_node_pack_paths = _udr_module.collect_node_pack_paths
_CREDENTIAL_PATTERN = _udr_module._CREDENTIAL_PATTERN
_DANGEROUS_PATTERNS = _udr_module._DANGEROUS_PATTERNS
_INLINE_DANGEROUS_OPTIONS = _udr_module._INLINE_DANGEROUS_OPTIONS
_TMP_PREFIX = _udr_module._TMP_PREFIX
_VERSION_SPEC_PATTERN = _udr_module._VERSION_SPEC_PATTERN


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_node_pack(tmp: str, name: str, requirements: str | None = None) -> str:
    """Create a fake node pack directory with optional requirements.txt."""
    path = os.path.join(tmp, name)
    os.makedirs(path, exist_ok=True)
    if requirements is not None:
        with open(os.path.join(path, "requirements.txt"), "w") as f:
            f.write(requirements)
    return path


def _resolver(
    paths: list[str],
    blacklist: set[str] | None = None,
    overrides: dict[str, str] | None = None,
    downgrade_blacklist: list[str] | None = None,
) -> UnifiedDepResolver:
    return UnifiedDepResolver(
        node_pack_paths=paths,
        blacklist=blacklist or set(),
        overrides=overrides or {},
        downgrade_blacklist=downgrade_blacklist or [],
    )


# ===========================================================================
# Data class instantiation
# ===========================================================================

class TestDataClasses:
    def test_package_requirement(self):
        pr = PackageRequirement(name="torch", spec="torch>=2.0", source="/packs/a")
        assert pr.name == "torch"
        assert pr.spec == "torch>=2.0"

    def test_collected_deps_defaults(self):
        cd = CollectedDeps()
        assert cd.requirements == []
        assert cd.skipped == []
        assert cd.sources == {}
        assert cd.extra_index_urls == []

    def test_lockfile_result(self):
        lr = LockfileResult(success=True, lockfile_path="/tmp/x.txt")
        assert lr.success
        assert lr.conflicts == []

    def test_install_result(self):
        ir = InstallResult(success=False, stderr="boom")
        assert not ir.success
        assert ir.installed == []

    def test_resolve_result(self):
        rr = ResolveResult(success=True)
        assert rr.collected is None
        assert rr.error is None


# ===========================================================================
# collect_requirements
# ===========================================================================

class TestCollectRequirements:
    def test_normal_parsing(self, tmp_path):
        p = _make_node_pack(str(tmp_path), "pack_a", "numpy>=1.20\nrequests\n")
        r = _resolver([p])
        deps = r.collect_requirements()
        assert len(deps.requirements) == 2
        names = {req.name for req in deps.requirements}
        assert "numpy" in names
        assert "requests" in names

    def test_empty_requirements(self, tmp_path):
        p = _make_node_pack(str(tmp_path), "pack_a", "")
        r = _resolver([p])
        deps = r.collect_requirements()
        assert deps.requirements == []

    def test_no_requirements_file(self, tmp_path):
        p = _make_node_pack(str(tmp_path), "pack_a")  # No requirements.txt
        r = _resolver([p])
        deps = r.collect_requirements()
        assert deps.requirements == []

    def test_comment_and_blank_handling(self, tmp_path):
        p = _make_node_pack(str(tmp_path), "pack_a", "# comment\n\nnumpy\n  \n")
        r = _resolver([p])
        deps = r.collect_requirements()
        assert len(deps.requirements) == 1

    def test_inline_comment_stripping(self, tmp_path):
        p = _make_node_pack(str(tmp_path), "pack_a", "numpy>=1.0  # pin version\n")
        r = _resolver([p])
        deps = r.collect_requirements()
        assert deps.requirements[0].spec == "numpy>=1.0"

    def test_blacklist_filtering(self, tmp_path):
        p = _make_node_pack(str(tmp_path), "pack_a", "torch\nnumpy\ntorchaudio\n")
        r = _resolver([p], blacklist={"torch", "torchaudio"})
        deps = r.collect_requirements()
        assert len(deps.requirements) == 1
        assert deps.requirements[0].name == "numpy"
        assert len(deps.skipped) == 2

    def test_remap_application(self, tmp_path):
        p = _make_node_pack(str(tmp_path), "pack_a", "old-package\n")
        r = _resolver([p], overrides={"old-package": "new-package>=1.0"})
        deps = r.collect_requirements()
        assert deps.requirements[0].spec == "new-package>=1.0"

    def test_disabled_path_new_style(self, tmp_path):
        disabled_dir = os.path.join(str(tmp_path), ".disabled")
        p = _make_node_pack(disabled_dir, "pack_a", "numpy\n")
        r = _resolver([p])
        deps = r.collect_requirements()
        assert deps.requirements == []

    def test_disabled_path_old_style(self, tmp_path):
        p = _make_node_pack(str(tmp_path), "pack_a.disabled", "numpy\n")
        r = _resolver([p])
        deps = r.collect_requirements()
        assert deps.requirements == []

    def test_duplicate_specs_kept(self, tmp_path):
        p1 = _make_node_pack(str(tmp_path), "pack_a", "numpy>=1.20\n")
        p2 = _make_node_pack(str(tmp_path), "pack_b", "numpy>=1.22\n")
        r = _resolver([p1, p2])
        deps = r.collect_requirements()
        numpy_reqs = [req for req in deps.requirements if req.name == "numpy"]
        assert len(numpy_reqs) == 2  # Both specs preserved

    def test_sources_tracking(self, tmp_path):
        p1 = _make_node_pack(str(tmp_path), "pack_a", "numpy\n")
        p2 = _make_node_pack(str(tmp_path), "pack_b", "numpy\n")
        r = _resolver([p1, p2])
        deps = r.collect_requirements()
        assert len(deps.sources["numpy"]) == 2

    def test_sources_stores_pack_path_and_spec_tuple(self, tmp_path):
        """sources entries must be (pack_path, pkg_spec) tuples."""
        p = _make_node_pack(str(tmp_path), "pack_a", "numpy>=1.20\n")
        r = _resolver([p])
        deps = r.collect_requirements()
        entries = deps.sources["numpy"]
        assert len(entries) == 1
        pack_path, pkg_spec = entries[0]
        assert pack_path == p
        assert pkg_spec == "numpy>=1.20"

    def test_sources_captures_spec_per_requester(self, tmp_path):
        """Each requester's exact spec is preserved independently."""
        p1 = _make_node_pack(str(tmp_path), "pack_a", "torch>=2.1\n")
        p2 = _make_node_pack(str(tmp_path), "pack_b", "torch<2.0\n")
        r = _resolver([p1, p2])
        deps = r.collect_requirements()
        specs = {pkg_spec for _, pkg_spec in deps.sources["torch"]}
        assert specs == {"torch>=2.1", "torch<2.0"}


# ===========================================================================
# Input sanitization
# ===========================================================================

class TestInputSanitization:
    @pytest.mark.parametrize("line", [
        "-r ../../../etc/hosts",
        "--requirement secret.txt",
        "-e git+https://evil.com/repo",
        "--editable ./local",
        "-c constraint.txt",
        "--constraint external.txt",
        "--find-links http://evil.com/pkgs",
        "-f http://evil.com/pkgs",
        "evil_pkg @ file:///etc/passwd",
    ])
    def test_dangerous_patterns_rejected(self, line, tmp_path):
        p = _make_node_pack(str(tmp_path), "pack_a", line + "\n")
        r = _resolver([p])
        deps = r.collect_requirements()
        assert deps.requirements == []
        assert len(deps.skipped) == 1
        assert "rejected" in deps.skipped[0][1]

    def test_path_separator_rejected(self, tmp_path):
        p = _make_node_pack(str(tmp_path), "pack_a", "../evil/pkg\n")
        r = _resolver([p])
        deps = r.collect_requirements()
        assert deps.requirements == []
        assert "path separator" in deps.skipped[0][1]

    def test_backslash_rejected(self, tmp_path):
        p = _make_node_pack(str(tmp_path), "pack_a", "evil\\pkg\n")
        r = _resolver([p])
        deps = r.collect_requirements()
        assert deps.requirements == []

    def test_valid_spec_with_version(self, tmp_path):
        p = _make_node_pack(str(tmp_path), "pack_a", "numpy>=1.20\n")
        r = _resolver([p])
        deps = r.collect_requirements()
        assert len(deps.requirements) == 1

    def test_environment_marker_allowed(self, tmp_path):
        p = _make_node_pack(str(tmp_path), "pack_a",
                             'pywin32>=300; sys_platform=="win32"\n')
        r = _resolver([p])
        deps = r.collect_requirements()
        assert len(deps.requirements) == 1

    @pytest.mark.parametrize("line", [
        "torch --find-links localdir",
        "numpy --constraint evil.txt",
        "scipy --requirement secret.txt",
        "pkg --editable ./local",
        "torch -f localdir",
        "numpy -c evil.txt",
        "pkg -r secret.txt",
        "scipy -e ./local",
        # Concatenated short flags (no space between flag and value)
        "torch -fhttps://evil.com/packages",
        "numpy -cevil.txt",
        "pkg -rsecret.txt",
        "scipy -e./local",
        # Case-insensitive
        "torch --FIND-LINKS localdir",
        "numpy --Constraint evil.txt",
        # Additional dangerous options
        "torch --trusted-host evil.com",
        "numpy --global-option=--no-user-cfg",
        "pkg --install-option=--prefix=/tmp",
    ])
    def test_inline_dangerous_options_rejected(self, line, tmp_path):
        """Pip options after package name must be caught (not just at line start)."""
        p = _make_node_pack(str(tmp_path), "pack_a", line + "\n")
        r = _resolver([p])
        deps = r.collect_requirements()
        assert deps.requirements == [], f"'{line}' should have been rejected"
        assert len(deps.skipped) == 1
        assert "rejected" in deps.skipped[0][1]

    def test_index_url_not_blocked_by_inline_check(self, tmp_path):
        """--index-url and --extra-index-url are legitimate and extracted before inline check."""
        p = _make_node_pack(str(tmp_path), "pack_a",
                             "torch --extra-index-url https://download.pytorch.org/whl/cu121\n")
        r = _resolver([p])
        deps = r.collect_requirements()
        assert len(deps.requirements) == 1
        assert deps.requirements[0].name == "torch"
        assert len(deps.extra_index_urls) == 1

    def test_combined_index_url_and_dangerous_option(self, tmp_path):
        """A line with both --extra-index-url and --find-links must reject
        AND must NOT retain the extracted index URL."""
        p = _make_node_pack(str(tmp_path), "pack_a",
                             "torch --extra-index-url https://evil.com --find-links /local\n")
        r = _resolver([p])
        deps = r.collect_requirements()
        assert deps.requirements == [], "line should have been rejected"
        assert deps.extra_index_urls == [], "evil URL should not be retained"
        assert len(deps.skipped) == 1

    @pytest.mark.parametrize("spec", [
        "package[extra-c]>=1.0",
        "package[extra-r]",
        "my-e-package>=2.0",
        "some-f-lib",
        "re-crypto>=1.0",
        # Real-world packages with hyphens near short flag letters
        "opencv-contrib-python-headless",
        "scikit-learn>=1.0",
        "onnxruntime-gpu",
        "face-recognition>=1.3",
    ])
    def test_inline_check_no_false_positive_on_package_names(self, spec, tmp_path):
        """Short flags inside package names or extras must not trigger false positive."""
        p = _make_node_pack(str(tmp_path), "pack_a", spec + "\n")
        r = _resolver([p])
        deps = r.collect_requirements()
        assert len(deps.requirements) == 1, f"'{spec}' was incorrectly rejected"


# ===========================================================================
# --index-url separation
# ===========================================================================

class TestIndexUrlSeparation:
    def test_index_url_split(self, tmp_path):
        p = _make_node_pack(str(tmp_path), "pack_a",
                             "torch --index-url https://download.pytorch.org/whl/cu121\n")
        r = _resolver([p])
        deps = r.collect_requirements()
        assert len(deps.requirements) == 1
        assert deps.requirements[0].name == "torch"
        assert "https://download.pytorch.org/whl/cu121" in deps.extra_index_urls

    def test_no_index_url(self, tmp_path):
        p = _make_node_pack(str(tmp_path), "pack_a", "numpy>=1.20\n")
        r = _resolver([p])
        deps = r.collect_requirements()
        assert deps.extra_index_urls == []

    def test_duplicate_index_urls_deduplicated(self, tmp_path):
        p1 = _make_node_pack(str(tmp_path), "pack_a",
                              "torch --index-url https://example.com/whl\n")
        p2 = _make_node_pack(str(tmp_path), "pack_b",
                              "torchvision --index-url https://example.com/whl\n")
        r = _resolver([p1, p2], blacklist=set())
        deps = r.collect_requirements()
        assert len(deps.extra_index_urls) == 1

    def test_standalone_index_url_line(self, tmp_path):
        """Standalone ``--index-url URL`` line with no package prefix."""
        p = _make_node_pack(str(tmp_path), "pack_a",
                             "--index-url https://download.pytorch.org/whl/cu121\nnumpy>=1.20\n")
        r = _resolver([p])
        deps = r.collect_requirements()
        assert len(deps.requirements) == 1
        assert deps.requirements[0].name == "numpy"
        assert "https://download.pytorch.org/whl/cu121" in deps.extra_index_urls

    def test_standalone_extra_index_url_line(self, tmp_path):
        """Standalone ``--extra-index-url URL`` line must not become a package."""
        p = _make_node_pack(str(tmp_path), "pack_a",
                             "--extra-index-url https://custom.pypi.org/simple\nnumpy>=1.20\n")
        r = _resolver([p])
        deps = r.collect_requirements()
        assert len(deps.requirements) == 1
        assert deps.requirements[0].name == "numpy"
        assert "https://custom.pypi.org/simple" in deps.extra_index_urls

    def test_extra_index_url_with_package_prefix(self, tmp_path):
        """``package --extra-index-url URL`` splits correctly."""
        p = _make_node_pack(str(tmp_path), "pack_a",
                             "torch --extra-index-url https://download.pytorch.org/whl/cu121\n")
        r = _resolver([p])
        deps = r.collect_requirements()
        assert len(deps.requirements) == 1
        assert deps.requirements[0].name == "torch"
        assert "https://download.pytorch.org/whl/cu121" in deps.extra_index_urls

    def test_multiple_index_urls_on_single_line(self, tmp_path):
        """Multiple --extra-index-url / --index-url on the same line."""
        p = _make_node_pack(
            str(tmp_path), "pack_a",
            "torch --extra-index-url https://url1.example.com "
            "--index-url https://url2.example.com\n",
        )
        r = _resolver([p])
        deps = r.collect_requirements()
        assert len(deps.requirements) == 1
        assert deps.requirements[0].name == "torch"
        assert "https://url1.example.com" in deps.extra_index_urls
        assert "https://url2.example.com" in deps.extra_index_urls

    def test_bare_index_url_no_value(self, tmp_path):
        """Bare ``--index-url`` with no URL value must not become a package."""
        p = _make_node_pack(str(tmp_path), "pack_a",
                             "--index-url\nnumpy>=1.20\n")
        r = _resolver([p])
        deps = r.collect_requirements()
        assert len(deps.requirements) == 1
        assert deps.requirements[0].name == "numpy"
        assert deps.extra_index_urls == []


# ===========================================================================
# Downgrade blacklist
# ===========================================================================

class TestDowngradeBlacklist:
    def setup_method(self):
        _MOCK_INSTALLED_PACKAGES.clear()

    def test_not_in_blacklist_passes(self, tmp_path):
        _MOCK_INSTALLED_PACKAGES["numpy"] = "1.24.0"
        p = _make_node_pack(str(tmp_path), "pack_a", "numpy<=1.20\n")
        r = _resolver([p], downgrade_blacklist=["torch"])
        deps = r.collect_requirements()
        assert len(deps.requirements) == 1

    def test_no_version_spec_installed_blocked(self, tmp_path):
        _MOCK_INSTALLED_PACKAGES["torch"] = "2.1.0"
        p = _make_node_pack(str(tmp_path), "pack_a", "torch\n")
        r = _resolver([p], downgrade_blacklist=["torch"])
        deps = r.collect_requirements()
        assert deps.requirements == []
        assert "downgrade blacklisted" in deps.skipped[0][1]

    def test_no_version_spec_not_installed_passes(self, tmp_path):
        # torch not installed
        p = _make_node_pack(str(tmp_path), "pack_a", "torch\n")
        r = _resolver([p], downgrade_blacklist=["torch"])
        deps = r.collect_requirements()
        assert len(deps.requirements) == 1

    @pytest.mark.parametrize("operator,blocked", [
        ("<=1.20", True),   # downgrade blocked
        ("==1.20", True),   # exact match blocked (installed >= requested)
        ("<2.0", True),     # less-than blocked (installed >= requested)
        ("~=1.20", True),   # compatible release blocked
        (">=2.5", False),   # upgrade allowed
        (">2.0", False),    # greater-than allowed
        ("!=1.20", False),  # not-equal allowed
    ])
    def test_operator_handling(self, operator, blocked, tmp_path):
        _MOCK_INSTALLED_PACKAGES["torch"] = "2.1.0"
        p = _make_node_pack(str(tmp_path), "pack_a", f"torch{operator}\n")
        r = _resolver([p], downgrade_blacklist=["torch"])
        deps = r.collect_requirements()
        if blocked:
            assert deps.requirements == [], f"Expected torch{operator} to be blocked"
        else:
            assert len(deps.requirements) == 1, f"Expected torch{operator} to pass"

    def test_same_version_blocked(self, tmp_path):
        _MOCK_INSTALLED_PACKAGES["torch"] = "2.1.0"
        p = _make_node_pack(str(tmp_path), "pack_a", "torch==2.1.0\n")
        r = _resolver([p], downgrade_blacklist=["torch"])
        deps = r.collect_requirements()
        assert deps.requirements == []  # installed >= requested → blocked

    def test_higher_version_request_passes_eq(self, tmp_path):
        _MOCK_INSTALLED_PACKAGES["torch"] = "2.1.0"
        p = _make_node_pack(str(tmp_path), "pack_a", "torch==2.5.0\n")
        r = _resolver([p], downgrade_blacklist=["torch"])
        deps = r.collect_requirements()
        assert len(deps.requirements) == 1  # installed < requested → allowed

    def teardown_method(self):
        _MOCK_INSTALLED_PACKAGES.clear()


# ===========================================================================
# _get_uv_cmd
# ===========================================================================

class TestGetUvCmd:
    def test_module_uv(self):
        r = _resolver([])
        with mock.patch("subprocess.check_output", return_value=b"uv 0.4.0"):
            cmd = r._get_uv_cmd()
        assert cmd[-2:] == ["-m", "uv"]

    def test_standalone_uv(self):
        r = _resolver([])
        with mock.patch("subprocess.check_output", side_effect=FileNotFoundError):
            with mock.patch("shutil.which", return_value="/usr/bin/uv"):
                cmd = r._get_uv_cmd()
        assert cmd == ["uv"]

    def test_uv_not_available(self):
        r = _resolver([])
        with mock.patch("subprocess.check_output", side_effect=FileNotFoundError):
            with mock.patch("shutil.which", return_value=None):
                with pytest.raises(UvNotAvailableError):
                    r._get_uv_cmd()

    def test_embedded_python_uses_s_flag(self):
        r = _resolver([])
        with mock.patch("subprocess.check_output", return_value=b"uv 0.4.0"):
            with mock.patch.object(
                type(r), '_get_uv_cmd',
                wraps=r._get_uv_cmd,
            ):
                # Simulate embedded python
                with mock.patch(
                    "comfyui_manager.common.unified_dep_resolver.sys"
                ) as mock_sys:
                    mock_sys.executable = "/path/python_embeded/python.exe"
                    cmd = r._get_uv_cmd()
                assert "-s" in cmd


# ===========================================================================
# compile_lockfile
# ===========================================================================

class TestCompileLockfile:
    def test_success(self, tmp_path):
        r = _resolver([])
        deps = CollectedDeps(
            requirements=[PackageRequirement("numpy", "numpy>=1.20", "/pack/a")],
        )

        lockfile_content = "numpy==1.24.0\n"

        def fake_run(cmd, **kwargs):
            # Simulate uv writing the lockfile
            for i, arg in enumerate(cmd):
                if arg == "--output-file" and i + 1 < len(cmd):
                    with open(cmd[i + 1], "w") as f:
                        f.write(lockfile_content)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with mock.patch.object(r, "_get_uv_cmd", return_value=["uv"]):
            with mock.patch("subprocess.run", side_effect=fake_run):
                result = r.compile_lockfile(deps)

        assert result.success
        assert result.lockfile_path is not None
        # Clean up
        shutil.rmtree(os.path.dirname(result.lockfile_path), ignore_errors=True)

    def test_conflict_detection(self):
        r = _resolver([])
        deps = CollectedDeps(
            requirements=[PackageRequirement("numpy", "numpy>=1.20", "/pack/a")],
        )

        with mock.patch.object(r, "_get_uv_cmd", return_value=["uv"]):
            with mock.patch("subprocess.run", return_value=subprocess.CompletedProcess(
                [], 1, stdout="", stderr="error: conflict between numpy and scipy"
            )):
                result = r.compile_lockfile(deps)

        assert not result.success
        assert len(result.conflicts) > 0

    def test_timeout(self):
        r = _resolver([])
        deps = CollectedDeps(
            requirements=[PackageRequirement("numpy", "numpy", "/pack/a")],
        )

        with mock.patch.object(r, "_get_uv_cmd", return_value=["uv"]):
            with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("uv", 300)):
                result = r.compile_lockfile(deps)

        assert not result.success
        assert "timeout" in result.conflicts[0].lower()

    def test_lockfile_not_created(self):
        r = _resolver([])
        deps = CollectedDeps(
            requirements=[PackageRequirement("numpy", "numpy", "/pack/a")],
        )

        with mock.patch.object(r, "_get_uv_cmd", return_value=["uv"]):
            with mock.patch("subprocess.run", return_value=subprocess.CompletedProcess(
                [], 0, stdout="", stderr=""
            )):
                result = r.compile_lockfile(deps)

        assert not result.success
        assert "lockfile not created" in result.conflicts[0]

    def test_extra_index_urls_passed(self, tmp_path):
        r = _resolver([])
        deps = CollectedDeps(
            requirements=[PackageRequirement("torch", "torch", "/pack/a")],
            extra_index_urls=["https://download.pytorch.org/whl/cu121"],
        )

        captured_cmd: list[str] = []

        def fake_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            for i, arg in enumerate(cmd):
                if arg == "--output-file" and i + 1 < len(cmd):
                    with open(cmd[i + 1], "w") as f:
                        f.write("torch==2.1.0\n")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with mock.patch.object(r, "_get_uv_cmd", return_value=["uv"]):
            with mock.patch("subprocess.run", side_effect=fake_run):
                result = r.compile_lockfile(deps)

        assert result.success
        assert "--extra-index-url" in captured_cmd
        assert "https://download.pytorch.org/whl/cu121" in captured_cmd
        shutil.rmtree(os.path.dirname(result.lockfile_path), ignore_errors=True)

    def test_constraints_file_created(self, tmp_path):
        r = UnifiedDepResolver(
            node_pack_paths=[],
            base_requirements=["comfyui-core>=1.0"],
        )
        deps = CollectedDeps(
            requirements=[PackageRequirement("numpy", "numpy", "/pack/a")],
        )

        captured_cmd: list[str] = []

        def fake_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            for i, arg in enumerate(cmd):
                if arg == "--output-file" and i + 1 < len(cmd):
                    with open(cmd[i + 1], "w") as f:
                        f.write("numpy==1.24.0\n")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with mock.patch.object(r, "_get_uv_cmd", return_value=["uv"]):
            with mock.patch("subprocess.run", side_effect=fake_run):
                result = r.compile_lockfile(deps)

        assert result.success
        assert "--constraint" in captured_cmd
        shutil.rmtree(os.path.dirname(result.lockfile_path), ignore_errors=True)


# ===========================================================================
# install_from_lockfile
# ===========================================================================

class TestInstallFromLockfile:
    def test_success(self, tmp_path):
        lockfile = os.path.join(str(tmp_path), "resolved.txt")
        with open(lockfile, "w") as f:
            f.write("numpy==1.24.0\n")

        r = _resolver([])
        with mock.patch.object(r, "_get_uv_cmd", return_value=["uv"]):
            with mock.patch("subprocess.run", return_value=subprocess.CompletedProcess(
                [], 0, stdout="Installed numpy-1.24.0\n", stderr=""
            )):
                result = r.install_from_lockfile(lockfile)

        assert result.success
        assert len(result.installed) == 1

    def test_failure(self, tmp_path):
        lockfile = os.path.join(str(tmp_path), "resolved.txt")
        with open(lockfile, "w") as f:
            f.write("nonexistent-pkg==1.0.0\n")

        r = _resolver([])
        with mock.patch.object(r, "_get_uv_cmd", return_value=["uv"]):
            with mock.patch("subprocess.run", return_value=subprocess.CompletedProcess(
                [], 1, stdout="", stderr="No matching distribution found"
            )):
                result = r.install_from_lockfile(lockfile)

        assert not result.success
        assert result.stderr != ""

    def test_timeout(self, tmp_path):
        lockfile = os.path.join(str(tmp_path), "resolved.txt")
        with open(lockfile, "w") as f:
            f.write("numpy==1.24.0\n")

        r = _resolver([])
        with mock.patch.object(r, "_get_uv_cmd", return_value=["uv"]):
            with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("uv", 600)):
                result = r.install_from_lockfile(lockfile)

        assert not result.success
        assert "TimeoutExpired" in result.stderr

    def test_atomic_failure_empty_installed(self, tmp_path):
        lockfile = os.path.join(str(tmp_path), "resolved.txt")
        with open(lockfile, "w") as f:
            f.write("broken-pkg==1.0.0\n")

        r = _resolver([])
        with mock.patch.object(r, "_get_uv_cmd", return_value=["uv"]):
            with mock.patch("subprocess.run", return_value=subprocess.CompletedProcess(
                [], 1, stdout="", stderr="error"
            )):
                result = r.install_from_lockfile(lockfile)

        assert not result.success
        assert result.installed == []


# ===========================================================================
# Credential redaction
# ===========================================================================

class TestCredentialRedaction:
    def test_redact_user_pass(self):
        r = _resolver([])
        url = "https://user:pass123@pypi.example.com/simple"
        assert "user:pass123" not in r._redact_url(url)
        assert "****@" in r._redact_url(url)

    def test_no_credentials_passthrough(self):
        r = _resolver([])
        url = "https://pypi.org/simple"
        assert r._redact_url(url) == url

    def test_redact_pattern(self):
        assert _CREDENTIAL_PATTERN.sub('://****@', "https://a:b@host") == "https://****@host"


# ===========================================================================
# cleanup_stale_tmp
# ===========================================================================

class TestCleanupStaleTmp:
    def test_removes_old_dirs(self, tmp_path):
        stale = os.path.join(str(tmp_path), f"{_TMP_PREFIX}old")
        os.makedirs(stale)
        # Make it appear old
        old_time = time.time() - 7200  # 2 hours ago
        os.utime(stale, (old_time, old_time))

        with mock.patch("tempfile.gettempdir", return_value=str(tmp_path)):
            UnifiedDepResolver.cleanup_stale_tmp(max_age_seconds=3600)

        assert not os.path.exists(stale)

    def test_preserves_recent_dirs(self, tmp_path):
        recent = os.path.join(str(tmp_path), f"{_TMP_PREFIX}recent")
        os.makedirs(recent)

        with mock.patch("tempfile.gettempdir", return_value=str(tmp_path)):
            UnifiedDepResolver.cleanup_stale_tmp(max_age_seconds=3600)

        assert os.path.exists(recent)

    def test_ignores_non_prefix_dirs(self, tmp_path):
        other = os.path.join(str(tmp_path), "other_dir")
        os.makedirs(other)
        old_time = time.time() - 7200
        os.utime(other, (old_time, old_time))

        with mock.patch("tempfile.gettempdir", return_value=str(tmp_path)):
            UnifiedDepResolver.cleanup_stale_tmp(max_age_seconds=3600)

        assert os.path.exists(other)


# ===========================================================================
# Concurrency: unique temp directories
# ===========================================================================

class TestConcurrency:
    def test_unique_temp_directories(self):
        """Two resolver instances get unique temp dirs (via mkdtemp)."""
        dirs: list[str] = []

        original_mkdtemp = tempfile.mkdtemp

        def capturing_mkdtemp(**kwargs):
            d = original_mkdtemp(**kwargs)
            dirs.append(d)
            return d

        r = _resolver([])
        deps = CollectedDeps(
            requirements=[PackageRequirement("numpy", "numpy", "/p")],
        )

        def fake_run(cmd, **kwargs):
            for i, arg in enumerate(cmd):
                if arg == "--output-file" and i + 1 < len(cmd):
                    with open(cmd[i + 1], "w") as f:
                        f.write("numpy==1.24.0\n")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with mock.patch.object(r, "_get_uv_cmd", return_value=["uv"]):
            with mock.patch("subprocess.run", side_effect=fake_run):
                with mock.patch(
                    "comfyui_manager.common.unified_dep_resolver.tempfile.mkdtemp",
                    side_effect=capturing_mkdtemp,
                ):
                    r.compile_lockfile(deps)
                    r.compile_lockfile(deps)

        assert len(dirs) == 2
        assert dirs[0] != dirs[1]

        for d in dirs:
            shutil.rmtree(d, ignore_errors=True)


# ===========================================================================
# resolve_and_install (full pipeline)
# ===========================================================================

class TestResolveAndInstall:
    def test_no_deps_returns_success(self, tmp_path):
        p = _make_node_pack(str(tmp_path), "pack_a")  # No requirements.txt
        r = _resolver([p])
        result = r.resolve_and_install()
        assert result.success

    def test_uv_not_available_raises(self, tmp_path):
        p = _make_node_pack(str(tmp_path), "pack_a", "numpy\n")
        r = _resolver([p])
        with mock.patch.object(r, "_get_uv_cmd", side_effect=UvNotAvailableError("no uv")):
            with pytest.raises(UvNotAvailableError):
                r.resolve_and_install()

    def test_compile_failure_returns_error(self, tmp_path):
        p = _make_node_pack(str(tmp_path), "pack_a", "numpy\n")
        r = _resolver([p])

        with mock.patch.object(r, "_get_uv_cmd", return_value=["uv"]):
            with mock.patch("subprocess.run", return_value=subprocess.CompletedProcess(
                [], 1, stdout="", stderr="conflict error"
            )):
                result = r.resolve_and_install()

        assert not result.success
        assert "compile failed" in result.error

    def test_compile_failure_result_includes_collected(self, tmp_path):
        """result.collected must be populated on compile failure for conflict attribution."""
        p = _make_node_pack(str(tmp_path), "pack_a", "torch>=2.1\n")
        r = _resolver([p])

        with mock.patch.object(r, "_get_uv_cmd", return_value=["uv"]):
            with mock.patch("subprocess.run", return_value=subprocess.CompletedProcess(
                [], 1, stdout="",
                stderr="error: Because torch>=2.1 conflicts with torch<2.0, no solution found.",
            )):
                result = r.resolve_and_install()

        assert not result.success
        assert result.collected is not None
        assert result.lockfile is not None
        assert result.lockfile.conflicts  # conflict lines present for attribution

    def test_conflict_attribution_sources_filter(self, tmp_path):
        """Packages named in conflict lines can be looked up from sources."""
        from comfyui_manager.common.unified_dep_resolver import attribute_conflicts
        p1 = _make_node_pack(str(tmp_path), "pack_a", "torch>=2.1\n")
        p2 = _make_node_pack(str(tmp_path), "pack_b", "torch<2.0\n")
        r = _resolver([p1, p2])

        conflict_text = "error: torch>=2.1 conflicts with torch<2.0"

        with mock.patch.object(r, "_get_uv_cmd", return_value=["uv"]):
            with mock.patch("subprocess.run", return_value=subprocess.CompletedProcess(
                [], 1, stdout="", stderr=conflict_text,
            )):
                result = r.resolve_and_install()

        assert not result.success
        assert result.collected is not None
        attributed = attribute_conflicts(result.collected.sources, result.lockfile.conflicts)
        assert "torch" in attributed
        specs = {spec for _, spec in attributed["torch"]}
        assert specs == {"torch>=2.1", "torch<2.0"}

    def test_conflict_attribution_no_false_positive_on_underscore_prefix(self, tmp_path):
        """'torch' must NOT match 'torch_audio' in conflict text (underscore boundary)."""
        from comfyui_manager.common.unified_dep_resolver import attribute_conflicts
        p = _make_node_pack(str(tmp_path), "pack_a", "torch>=2.1\n")
        r = _resolver([p])

        conflict_text = "error: torch_audio>=2.1 conflicts with torch_audio<2.0"

        with mock.patch.object(r, "_get_uv_cmd", return_value=["uv"]):
            with mock.patch("subprocess.run", return_value=subprocess.CompletedProcess(
                [], 1, stdout="", stderr=conflict_text,
            )):
                result = r.resolve_and_install()

        assert not result.success
        assert result.collected is not None
        attributed = attribute_conflicts(result.collected.sources, result.lockfile.conflicts)
        # 'torch' should NOT match: conflict only mentions 'torch_audio'
        assert "torch" not in attributed

    def test_conflict_attribution_no_false_positive_on_prefix_match(self, tmp_path):
        """'torch' must NOT match 'torchvision' in conflict text (word boundary)."""
        from comfyui_manager.common.unified_dep_resolver import attribute_conflicts
        p = _make_node_pack(str(tmp_path), "pack_a", "torch>=2.1\n")
        r = _resolver([p])

        conflict_text = "error: torchvision>=0.16 conflicts with torchvision<0.15"

        with mock.patch.object(r, "_get_uv_cmd", return_value=["uv"]):
            with mock.patch("subprocess.run", return_value=subprocess.CompletedProcess(
                [], 1, stdout="", stderr=conflict_text,
            )):
                result = r.resolve_and_install()

        assert not result.success
        assert result.collected is not None
        attributed = attribute_conflicts(result.collected.sources, result.lockfile.conflicts)
        # 'torch' should NOT appear: conflict only mentions 'torchvision'
        assert "torch" not in attributed

    def test_conflict_attribution_hyphen_underscore_normalization(self, tmp_path):
        """Packages stored with hyphens match conflict text using underscores."""
        from comfyui_manager.common.unified_dep_resolver import attribute_conflicts
        p = _make_node_pack(str(tmp_path), "pack_a", "torch-audio>=2.1\n")
        r = _resolver([p])

        # uv may print 'torch_audio' (underscore) in conflict output
        conflict_text = "error: torch_audio>=2.1 conflicts with torch_audio<2.0"

        with mock.patch.object(r, "_get_uv_cmd", return_value=["uv"]):
            with mock.patch("subprocess.run", return_value=subprocess.CompletedProcess(
                [], 1, stdout="", stderr=conflict_text,
            )):
                result = r.resolve_and_install()

        assert not result.success
        assert result.collected is not None
        attributed = attribute_conflicts(result.collected.sources, result.lockfile.conflicts)
        # _extract_package_name normalizes 'torch-audio' → 'torch_audio'; uv uses underscores too
        assert "torch_audio" in attributed

    def test_full_success_pipeline(self, tmp_path):
        p = _make_node_pack(str(tmp_path), "pack_a", "numpy>=1.20\n")
        r = _resolver([p])

        call_count = {"compile": 0, "install": 0}

        def fake_run(cmd, **kwargs):
            cmd_str = " ".join(cmd)
            if "compile" in cmd_str:
                call_count["compile"] += 1
                for i, arg in enumerate(cmd):
                    if arg == "--output-file" and i + 1 < len(cmd):
                        with open(cmd[i + 1], "w") as f:
                            f.write("numpy==1.24.0\n")
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            elif "install" in cmd_str:
                call_count["install"] += 1
                return subprocess.CompletedProcess(
                    cmd, 0, stdout="Installed numpy-1.24.0\n", stderr=""
                )
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with mock.patch.object(r, "_get_uv_cmd", return_value=["uv"]):
            with mock.patch("subprocess.run", side_effect=fake_run):
                result = r.resolve_and_install()

        assert result.success
        assert call_count["compile"] == 1
        assert call_count["install"] == 1
        assert result.collected is not None
        assert len(result.collected.requirements) == 1


# ===========================================================================
# Multiple custom_nodes paths
# ===========================================================================

class TestMultiplePaths:
    def test_collection_from_multiple_paths(self, tmp_path):
        dir_a = os.path.join(str(tmp_path), "custom_nodes_a")
        dir_b = os.path.join(str(tmp_path), "custom_nodes_b")
        p1 = _make_node_pack(dir_a, "pack_1", "numpy\n")
        p2 = _make_node_pack(dir_b, "pack_2", "requests\n")
        r = _resolver([p1, p2])
        deps = r.collect_requirements()
        names = {req.name for req in deps.requirements}
        assert names == {"numpy", "requests"}


# ===========================================================================
# cm_global defensive access
# ===========================================================================

class TestDefensiveAccess:
    def test_default_blacklist_is_empty_set(self):
        r = UnifiedDepResolver(node_pack_paths=[])
        assert r.blacklist == set()

    def test_default_overrides_is_empty_dict(self):
        r = UnifiedDepResolver(node_pack_paths=[])
        assert r.overrides == {}

    def test_default_downgrade_blacklist_is_empty_list(self):
        r = UnifiedDepResolver(node_pack_paths=[])
        assert r.downgrade_blacklist == []

    def test_explicit_none_uses_defaults(self):
        r = UnifiedDepResolver(
            node_pack_paths=[],
            blacklist=None,
            overrides=None,
            downgrade_blacklist=None,
        )
        assert r.blacklist == set()
        assert r.overrides == {}
        assert r.downgrade_blacklist == []


# ===========================================================================
# Regex patterns
# ===========================================================================

class TestPatterns:
    def test_dangerous_pattern_matches(self):
        assert _DANGEROUS_PATTERNS.match("-r secret.txt")
        assert _DANGEROUS_PATTERNS.match("--requirement secret.txt")
        assert _DANGEROUS_PATTERNS.match("-e git+https://evil.com")
        assert _DANGEROUS_PATTERNS.match("--editable ./local")
        assert _DANGEROUS_PATTERNS.match("-c constraints.txt")
        assert _DANGEROUS_PATTERNS.match("--find-links http://evil.com")
        assert _DANGEROUS_PATTERNS.match("-f http://evil.com")
        assert _DANGEROUS_PATTERNS.match("pkg @ file:///etc/passwd")

    def test_dangerous_pattern_no_false_positive(self):
        assert _DANGEROUS_PATTERNS.match("numpy>=1.20") is None
        assert _DANGEROUS_PATTERNS.match("requests") is None
        assert _DANGEROUS_PATTERNS.match("torch --index-url https://x.com") is None

    def test_version_spec_pattern(self):
        m = _VERSION_SPEC_PATTERN.search("torch>=2.0")
        assert m is not None
        assert m.group(1) == "torch"
        assert m.group(2) == ">="
        assert m.group(3) == "2.0"

    def test_version_spec_no_version(self):
        m = _VERSION_SPEC_PATTERN.search("torch")
        assert m is None


# ===========================================================================
# _extract_package_name
# ===========================================================================

class TestExtractPackageName:
    def test_simple_name(self):
        assert UnifiedDepResolver._extract_package_name("numpy") == "numpy"

    def test_with_version(self):
        assert UnifiedDepResolver._extract_package_name("numpy>=1.20") == "numpy"

    def test_normalisation(self):
        assert UnifiedDepResolver._extract_package_name("My-Package>=1.0") == "my_package"

    def test_extras(self):
        assert UnifiedDepResolver._extract_package_name("requests[security]") == "requests"

    def test_at_url(self):
        assert UnifiedDepResolver._extract_package_name("pkg @ https://example.com/pkg.tar.gz") == "pkg"


# ===========================================================================
# _is_disabled_path
# ===========================================================================

class TestIsDisabledPath:
    def test_new_style(self):
        assert UnifiedDepResolver._is_disabled_path("/custom_nodes/.disabled/my_pack")

    def test_old_style(self):
        assert UnifiedDepResolver._is_disabled_path("/custom_nodes/my_pack.disabled")

    def test_normal_path(self):
        assert not UnifiedDepResolver._is_disabled_path("/custom_nodes/my_pack")

    def test_trailing_slash(self):
        assert UnifiedDepResolver._is_disabled_path("/custom_nodes/my_pack.disabled/")


# ===========================================================================
# collect_node_pack_paths
# ===========================================================================

class TestCollectNodePackPaths:
    def test_collects_subdirectories(self, tmp_path):
        base = tmp_path / "custom_nodes"
        base.mkdir()
        (base / "pack_a").mkdir()
        (base / "pack_b").mkdir()
        (base / "file.txt").touch()  # not a dir — should be excluded
        result = collect_node_pack_paths([str(base)])
        names = sorted(os.path.basename(p) for p in result)
        assert names == ["pack_a", "pack_b"]

    def test_nonexistent_base_dir(self):
        result = collect_node_pack_paths(["/nonexistent/path"])
        assert result == []

    def test_multiple_base_dirs(self, tmp_path):
        base1 = tmp_path / "cn1"
        base2 = tmp_path / "cn2"
        base1.mkdir()
        base2.mkdir()
        (base1 / "pack_a").mkdir()
        (base2 / "pack_b").mkdir()
        result = collect_node_pack_paths([str(base1), str(base2)])
        names = sorted(os.path.basename(p) for p in result)
        assert names == ["pack_a", "pack_b"]

    def test_empty_base_dir(self, tmp_path):
        base = tmp_path / "custom_nodes"
        base.mkdir()
        result = collect_node_pack_paths([str(base)])
        assert result == []


# ===========================================================================
# collect_base_requirements
# ===========================================================================

class TestCollectBaseRequirements:
    def test_reads_both_files(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("numpy>=1.20\n")
        (tmp_path / "manager_requirements.txt").write_text("requests\n")
        result = collect_base_requirements(str(tmp_path))
        assert result == ["numpy>=1.20", "requests"]

    def test_skips_comments_and_blanks(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("# comment\n\nnumpy\n  \n")
        result = collect_base_requirements(str(tmp_path))
        assert result == ["numpy"]

    def test_missing_files(self, tmp_path):
        result = collect_base_requirements(str(tmp_path))
        assert result == []

    def test_only_requirements_txt(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("torch\n")
        result = collect_base_requirements(str(tmp_path))
        assert result == ["torch"]


# ===========================================================================
# _parse_conflicts (direct unit tests)
# ===========================================================================

class TestParseConflicts:
    def test_extracts_conflict_lines(self):
        stderr = (
            "Resolved 10 packages\n"
            "error: package torch has conflicting requirements\n"
            "  conflict between numpy>=2.0 and numpy<1.25\n"
            "some other info\n"
        )
        result = UnifiedDepResolver._parse_conflicts(stderr)
        assert len(result) == 2
        assert "conflicting" in result[0]
        assert "conflict" in result[1]

    def test_extracts_error_lines(self):
        stderr = "ERROR: No matching distribution found for nonexistent-pkg\n"
        result = UnifiedDepResolver._parse_conflicts(stderr)
        assert len(result) == 1
        assert "nonexistent-pkg" in result[0]

    def test_empty_stderr(self):
        result = UnifiedDepResolver._parse_conflicts("")
        assert result == []

    def test_whitespace_only_stderr(self):
        result = UnifiedDepResolver._parse_conflicts("   \n\n  ")
        assert result == []

    def test_no_conflict_keywords_falls_back_to_full_stderr(self):
        stderr = "resolution failed due to incompatible versions"
        result = UnifiedDepResolver._parse_conflicts(stderr)
        # No 'conflict' or 'error' keyword → falls back to [stderr.strip()]
        assert result == [stderr.strip()]

    def test_mixed_lines(self):
        stderr = (
            "info: checking packages\n"
            "error: failed to resolve\n"
            "debug: trace output\n"
        )
        result = UnifiedDepResolver._parse_conflicts(stderr)
        assert len(result) == 1
        assert "failed to resolve" in result[0]


# ===========================================================================
# _parse_install_output (direct unit tests)
# ===========================================================================

class TestParseInstallOutput:
    def test_installed_packages(self):
        result = subprocess.CompletedProcess(
            [], 0,
            stdout="Installed numpy-1.24.0\nInstalled requests-2.31.0\n",
            stderr="",
        )
        installed, skipped = UnifiedDepResolver._parse_install_output(result)
        assert len(installed) == 2
        assert any("numpy" in p for p in installed)

    def test_skipped_packages(self):
        result = subprocess.CompletedProcess(
            [], 0,
            stdout="Requirement already satisfied: numpy==1.24.0\n",
            stderr="",
        )
        installed, skipped = UnifiedDepResolver._parse_install_output(result)
        assert len(installed) == 0
        assert len(skipped) == 1
        assert "already" in skipped[0].lower()

    def test_mixed_installed_and_skipped(self):
        result = subprocess.CompletedProcess(
            [], 0,
            stdout=(
                "Requirement already satisfied: numpy==1.24.0\n"
                "Installed requests-2.31.0\n"
                "Updated torch-2.1.0\n"
            ),
            stderr="",
        )
        installed, skipped = UnifiedDepResolver._parse_install_output(result)
        assert len(installed) == 2  # "Installed" + "Updated"
        assert len(skipped) == 1   # "already satisfied"

    def test_empty_output(self):
        result = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        installed, skipped = UnifiedDepResolver._parse_install_output(result)
        assert installed == []
        assert skipped == []

    def test_unrecognized_lines_ignored(self):
        result = subprocess.CompletedProcess(
            [], 0,
            stdout="Resolving dependencies...\nDownloading numpy-1.24.0.whl\n",
            stderr="",
        )
        installed, skipped = UnifiedDepResolver._parse_install_output(result)
        assert installed == []
        assert skipped == []


# ===========================================================================
# resolve_and_install: general Exception path
# ===========================================================================

class TestResolveAndInstallExceptionPath:
    def test_unexpected_exception_returns_error_result(self, tmp_path):
        """Non-UvNotAvailableError exceptions should be caught and returned."""
        p = _make_node_pack(str(tmp_path), "pack_a", "numpy\n")
        r = _resolver([p])

        with mock.patch.object(
            r, "collect_requirements",
            side_effect=RuntimeError("unexpected disk failure"),
        ):
            result = r.resolve_and_install()

        assert not result.success
        assert "unexpected disk failure" in result.error

    def test_unexpected_exception_during_compile(self, tmp_path):
        """Exception in compile_lockfile should be caught by resolve_and_install."""
        p = _make_node_pack(str(tmp_path), "pack_a", "numpy\n")
        r = _resolver([p])

        with mock.patch.object(r, "_get_uv_cmd", return_value=["uv"]):
            with mock.patch.object(
                r, "compile_lockfile",
                side_effect=OSError("permission denied"),
            ):
                result = r.resolve_and_install()

        assert not result.success
        assert "permission denied" in result.error
