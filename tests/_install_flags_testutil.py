"""Shared test-support for the goal265 dedicated-install-flag test modules.

NOT a test module (no ``test_`` prefix — pytest does not collect it).

Provides minimal runtime stubs so ``comfyui_manager`` package modules can be
imported in a plain dev venv (outside a real ComfyUI runtime):

- ``comfy.cli_args.args`` — consumed by ``comfyui_manager/__init__.py`` at
  package import time (``from comfy.cli_args import args``). The stub pins
  ``listen='127.0.0.1'`` (loopback) which matches the default precondition of
  every scenario row (goal265-scenarios.md §0 preamble).
- ``folder_paths`` — consumed by ``comfyui_manager/common/context.py`` at
  import time to derive the manager user directory. The stub redirects it to
  a throwaway temp dir so importing the package NEVER creates directories
  inside the repository checkout.

SUITE-ORDER INDEPENDENCE (goal265 FU, task #293): every public ``import_*``
entry point is self-sufficient — it repairs whatever ``sys.modules`` state
earlier test modules left behind, instead of assuming a pristine interpreter:

- Other test modules legitimately install FAKE ``comfyui_manager`` lineage
  entries at module level (e.g. tests/test_unified_dep_resolver.py:63-73
  registers a plain ``types.ModuleType("comfyui_manager")`` — NOT a package,
  no ``__path__`` — to host a file-loaded module under a dotted name). Those
  modules are imported at pytest COLLECTION time, so under full-suite
  ordering the fake is already in ``sys.modules`` before any fixture here
  runs, and ``import comfyui_manager.glob.manager_core`` dies with
  ``ModuleNotFoundError: 'comfyui_manager' is not a package``.
- ``_purge_fake_comfyui_manager()`` therefore validates the cached lineage
  against the REAL package directory on disk and drops fake/broken entries
  before importing. Dropping ``sys.modules`` entries is safe for the other
  test modules: they hold direct object references to what they loaded;
  they do not re-resolve through ``sys.modules``.
- ``ensure_comfy_stubs()`` likewise repairs half-formed ``comfy`` /
  ``folder_paths`` entries (present but missing the attributes we need)
  rather than only handling the absent case.

Used by:
- tests/test_install_flags_config.py   (dual-reader config tests)
- tests/test_install_flags_guards.py   (out-of-scope guard tests)

Spec SoT: ~/.claude/pair-cowork/scratch/gm-team/goal265-spec.md §4
(test surface contract — binding for Step-4 test authoring).
"""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
import types

#: repo root (parent of tests/)
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

#: the real on-disk package directory the cached lineage must resolve to
_REAL_PKG_DIR = os.path.join(REPO_ROOT, "comfyui_manager")


def ensure_comfy_stubs() -> None:
    """Install or REPAIR minimal ``comfy``/``folder_paths`` stubs (idempotent).

    Handles three prior states per module:
    - absent                  -> install a fresh stub
    - present but inadequate  -> patch the missing attributes in place
      (another test's stub, or a partially-initialized real module)
    - present and adequate    -> leave untouched (e.g. real ComfyUI runtime)
    """
    # --- comfy.cli_args.args ------------------------------------------------
    comfy = sys.modules.get("comfy")
    if comfy is None:
        comfy = types.ModuleType("comfy")
        sys.modules["comfy"] = comfy

    cli_args = sys.modules.get("comfy.cli_args")
    if cli_args is None:
        cli_args = getattr(comfy, "cli_args", None)
        if not isinstance(cli_args, types.ModuleType):
            cli_args = types.ModuleType("comfy.cli_args")
        sys.modules["comfy.cli_args"] = cli_args

    args = getattr(cli_args, "args", None)
    if args is None or not hasattr(args, "listen"):
        setattr(cli_args, "args", types.SimpleNamespace(
            listen="127.0.0.1",
            enable_manager=True,
            enable_manager_legacy_ui=False,
        ))
    # re-link parent attr idempotently (a bare ``comfy`` stub from another
    # test may lack the submodule attribute even when both entries exist)
    setattr(comfy, "cli_args", cli_args)

    # --- folder_paths -------------------------------------------------------
    fp = sys.modules.get("folder_paths")
    if fp is None:
        fp = types.ModuleType("folder_paths")
        sys.modules["folder_paths"] = fp
    if not hasattr(fp, "get_system_user_directory"):
        base = tempfile.mkdtemp(prefix="cm-flags-test-user-")
        setattr(fp, "get_system_user_directory",
                lambda name: os.path.join(base, name))


def _module_is_real(mod: types.ModuleType) -> bool:
    """True when a cached ``comfyui_manager*`` module resolves to the real
    on-disk package tree (by ``__path__`` for packages, ``__file__`` for
    leaf modules)."""
    real_root = os.path.abspath(_REAL_PKG_DIR)
    paths = getattr(mod, "__path__", None)
    if paths is not None:
        return any(os.path.abspath(p).startswith(real_root) for p in paths)
    file = getattr(mod, "__file__", None)
    if file is not None:
        return os.path.abspath(file).startswith(real_root)
    # neither __path__ nor __file__: a bare ModuleType fake
    return False


def _purge_fake_comfyui_manager() -> None:
    """Drop fake/broken ``comfyui_manager`` lineage entries from
    ``sys.modules`` so a subsequent real-package import succeeds.

    Uniform rule — an entry is dropped iff it does NOT resolve to the real
    on-disk package tree:

    - A fake top-level entry (bare ``ModuleType`` without ``__path__`` —
      'not a package') is dropped so the real package can import.
    - Fake SUBentries injected under dotted names (e.g.
      ``comfyui_manager.common.manager_util`` replaced by a stub) are
      dropped; the import machinery re-imports the real module on next
      access.
    - REAL-file modules registered under dotted names by other test
      modules (e.g. ``comfyui_manager.common.unified_dep_resolver`` loaded
      via spec_from_file_location by tests/test_unified_dep_resolver.py)
      are KEPT: those tests later resolve the SAME cached entry through
      ``mock.patch("comfyui_manager.common.unified_dep_resolver.X")``;
      evicting it would make mock.patch import a fresh second instance and
      silently patch the wrong module object.
    """
    lineage = [n for n in list(sys.modules)
               if n == "comfyui_manager" or n.startswith("comfyui_manager.")]
    for name in lineage:
        mod = sys.modules.get(name)
        if mod is None or not _module_is_real(mod):
            del sys.modules[name]


def _import_real(dotted: str):
    """ensure stubs -> purge fakes -> import; shared by all entry points."""
    ensure_comfy_stubs()
    _purge_fake_comfyui_manager()
    return importlib.import_module(dotted)


def import_reader(reader: str):
    """Import and return ``comfyui_manager.<reader>.manager_core``.

    ``reader`` is ``"glob"`` or ``"legacy"`` — the two independent config
    reader implementations sharing one config.ini (dual-reader rule,
    goal265-mm.md §1.1 / goal265-spec.md §3).
    """
    assert reader in ("glob", "legacy"), reader
    return _import_real(f"comfyui_manager.{reader}.manager_core")


def import_context():
    """Import and return ``comfyui_manager.common.context`` (holds
    ``manager_config_path``, consumed by both readers at call time)."""
    return _import_real("comfyui_manager.common.context")


def import_glob_security_utils():
    """Import and return ``comfyui_manager.glob.utils.security_utils``
    (the glob copy of the security_level gate matrix — guard rows
    SC-25C / SC-28)."""
    return _import_real("comfyui_manager.glob.utils.security_utils")
