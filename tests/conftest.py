"""Test-runner guard for the GOAL #32 tests/ modules.

WHY THIS FILE EXISTS (collection hazard, not test logic):

The repo root contains ``__init__.py`` — the ComfyUI plugin entrypoint —
which at import time appends ``glob/`` to sys.path and imports
``manager_server`` (which needs ``folder_paths`` / ``comfy.cli_args`` /
a constructed ``PromptServer``). pytest 8 collects any ancestor
directory that carries an ``__init__.py`` as a ``Package`` node and
IMPORTS that ``__init__.py`` during test setup (observed module name:
``__init__``). Outside a live ComfyUI process that import can never
succeed, so EVERY test under tests/ errors at setup — including the
pre-existing tests/test_csrf_content_type_helper.py — whenever pytest's
rootdir ends up at or above the repo root (e.g. running inside a git
worktree nested under the parent checkout).

The guard below pre-seeds ``sys.modules`` with an inert stub whose
``__file__`` matches the real path, so pytest's
``import_path(<repo-root>/__init__.py)`` resolves to the stub without
executing the plugin entrypoint. Conftest files load before the setup
phase, so the stub is always in place in time. This does NOT touch
production code and does NOT alter what the tests import themselves
(they use AST-extraction / subprocess isolation per the
tests/test_csrf_content_type_helper.py precedent — ``glob/`` is never
added to the runner's sys.path).
"""
import sys
import types
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ROOT_INIT = _REPO_ROOT / "__init__.py"

if _ROOT_INIT.exists() and "__init__" not in sys.modules:
    _stub = types.ModuleType("__init__")
    _stub.__file__ = str(_ROOT_INIT)
    _stub.__doc__ = (
        "Inert stand-in for the ComfyUI-Manager plugin entrypoint; "
        "see tests/conftest.py for rationale."
    )
    sys.modules["__init__"] = _stub
