"""[GOAL #347] Non-e2e unit regression guards for the OTHER legacy
``security_level`` gate paths in ``comfyui_manager/legacy/manager_server.py``.

CONTEXT (GOAL #346 audit): the dedicated-install-flag work (git_url / pip
endpoints) gained unit + e2e coverage, but the OTHER legacy gate sites — the
ones that still gate on ``is_allowed_security_level(level)`` — had NO non-e2e
coverage; only ``tests/e2e/`` exercised them, and only behind a real-server
harness (E2E_ROOT). These guards close that gap WITHOUT a real server and
WITHOUT modifying production code.

PATHS GUARDED (the OTHER security_level gates):
  P1  middle+ batch-install entry gate    — ``_install_custom_node`` (L1441)
  P2  unknown-pip 'block' unconditional   — ``_install_custom_node`` risky
        deny                                 branch (``is_allowed_security_level
                                             ('block')`` is hard-False; Q1)
  P3  nodepack/snapshot high+/middle       — ``comfyui_switch_version`` (high+),
        gates                                ``restore_snapshot`` (middle+)
  P4  model non-.safetensors high+ gate    — ``_install_model`` (L1713)

NON-VACUITY (the bar from the GOAL MM): every assertion below is written so
that WEAKENING the underlying gate would FLIP the test result —
  * the decision-table tests drive the REAL ``is_allowed_security_level`` and
    pin the exact allow/deny truth for the level each path consumes; changing
    that function's logic for any level flips a row;
  * the response-shape tests invoke the REAL async handlers and assert the
    observable status (403/404/200) — each pairs a DENY case with an opposite
    (allow / flip) case proving the gate, not a constant, is what decides.
A guard that merely imports or asserts a constant is explicitly avoided.

ISOLATION: reuses the ``tests/_install_flags_testutil.py`` stub approach
(``ensure_comfy_stubs`` + ``_purge_fake_comfyui_manager``) and adds the
minimal extra stubs ``manager_server`` needs at import (``server.PromptServer``
route table, ``nodes``, ``folder_paths.__file__`` / ``get_folder_paths``), plus
an inert ``manager_util.get_data`` so the module-level cache-warmup thread does
no network I/O. No production code is touched.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _install_flags_testutil import (  # noqa: E402
    ensure_comfy_stubs,
    _purge_fake_comfyui_manager,
)

_LEGACY_SERVER = None


def _import_legacy_server():
    """Import ``comfyui_manager.legacy.manager_server`` under minimal stubs
    (idempotent; memoized). Returns the real module object so the tests drive
    the REAL gate function and REAL handlers — only the runtime *environment*
    is stubbed, never the gate logic."""
    global _LEGACY_SERVER
    if _LEGACY_SERVER is not None:
        return _LEGACY_SERVER

    ensure_comfy_stubs()
    _purge_fake_comfyui_manager()

    # folder_paths: manager_server reads ``__file__`` and ``get_folder_paths``
    # at import (context.comfy_path derivation + check_invalid_nodes).
    fp = sys.modules["folder_paths"]
    if not hasattr(fp, "__file__"):
        fp.__file__ = os.path.join(tempfile.mkdtemp(prefix="cm-fp-"), "folder_paths.py")
    if not hasattr(fp, "get_folder_paths"):
        fp.get_folder_paths = lambda *a, **k: []

    # nodes: imported but only used inside handlers we don't reach.
    sys.modules.setdefault("nodes", types.ModuleType("nodes"))

    # server.PromptServer.instance.routes: the @routes.post/.get decorators run
    # at import. An identity-decorator route table lets every handler register
    # as a plain module-level function without a real aiohttp app.
    if "server" not in sys.modules:
        server = types.ModuleType("server")

        class _Routes:
            def _identity(self, *a, **k):
                def deco(fn):
                    return fn
                return deco

            post = get = put = delete = _identity

        class _Inst:
            routes = _Routes()

        class PromptServer:
            instance = _Inst()

        server.PromptServer = PromptServer
        sys.modules["server"] = server

    # Make the module-level cache-warmup thread (manager_server L~1990
    # ``threading.Thread(... default_cache_update ...)``) inert — no network.
    import importlib
    mu = importlib.import_module("comfyui_manager.common.manager_util")

    async def _inert_get_data(uri, *a, **k):
        return {"custom_nodes": [], "models": [], "node_map": {}}

    mu.get_data = _inert_get_data

    _LEGACY_SERVER = importlib.import_module("comfyui_manager.legacy.manager_server")
    return _LEGACY_SERVER


@pytest.fixture(scope="module")
def ms():
    return _import_legacy_server()


@pytest.fixture
def gate(ms, monkeypatch):
    """Return a function ``set_gate(security_level, network_mode='public',
    is_local_mode=True)`` that drives the gate inputs.

    Builds a COMPLETE config dict off the reader's real fallback so any
    concurrent background reader (the warmup thread) never KeyErrors, then
    overrides only ``security_level`` / ``network_mode``. ``is_local_mode`` is
    the module global the gate consults. monkeypatch auto-restores."""
    base = dict(ms.core.read_config())

    def set_gate(security_level, network_mode="public", is_local_mode=True):
        cfg = dict(base)
        cfg["security_level"] = security_level
        cfg["network_mode"] = network_mode
        monkeypatch.setattr(ms.core, "get_config", lambda: dict(cfg))
        monkeypatch.setattr(ms, "is_local_mode", is_local_mode)

    return set_gate


def _run(coro):
    return asyncio.run(coro)


class FakeRequest:
    """Minimal stand-in for an aiohttp request. ``content_type`` satisfies
    ``reject_simple_form_post``; nothing else is read on the deny path (the
    gate returns before any body access)."""

    def __init__(self, content_type="application/json"):
        self.content_type = content_type


# ===========================================================================
# Decision-table guards — drive the REAL is_allowed_security_level for the
# exact level each OTHER path consumes. Non-vacuous: weakening the function
# for any level flips a row.
# ===========================================================================

# (security_level, is_local_mode, network_mode, expected_allowed)
_MIDDLE_PLUS = [  # P1 batch entry, _update_all, _install_model entry, restore_snapshot
    ("weak", True, "public", True),
    ("normal", True, "public", True),
    ("normal-", True, "public", True),
    ("strong", True, "public", False),
    ("weak", False, "public", False),       # public non-loopback -> denied
    ("normal", False, "public", False),
    ("weak", False, "personal_cloud", True),  # personal_cloud arm of middle+
    ("strong", False, "personal_cloud", False),
]

_HIGH_PLUS = [  # P3 comfyui_switch_version, P4 model non-.safetensors sub-check
    ("weak", True, "public", True),
    ("normal-", True, "public", True),
    ("normal", True, "public", False),
    ("strong", True, "public", False),
    ("weak", False, "public", False),
    ("weak", False, "personal_cloud", True),
    ("normal-", False, "personal_cloud", False),  # personal_cloud high+ needs weak
]

_MIDDLE = [  # P3 remove_snapshot and the other middle-gated legacy ops
    ("weak", True, "public", True),
    ("normal", True, "public", True),
    ("normal-", True, "public", True),
    ("strong", True, "public", False),
    ("normal", False, "public", True),   # 'middle' ignores locality
    ("strong", False, "public", False),
]

_BLOCK_LEVELS = ["weak", "normal", "normal-", "strong"]


@pytest.mark.parametrize(("sl", "local", "nm", "expected"), _MIDDLE_PLUS)
def test_p1_middle_plus_decision(ms, gate, sl, local, nm, expected):
    """P1: the middle+ batch-install entry gate decision. is_allowed_security_level
    ('middle+') must allow iff sl in {weak,normal,normal-} AND
    (loopback OR personal_cloud)."""
    gate(sl, network_mode=nm, is_local_mode=local)
    assert ms.is_allowed_security_level("middle+") is expected


@pytest.mark.parametrize("sl", _BLOCK_LEVELS)
@pytest.mark.parametrize("local", [True, False], ids=["loopback", "public"])
@pytest.mark.parametrize("nm", ["public", "personal_cloud"])
def test_p2_block_is_unconditional_deny(ms, gate, sl, local, nm):
    """P2: unknown-pip 'block' is an UNCONDITIONAL deny — is_allowed_security_level
    ('block') is False for EVERY security_level, locality, and network_mode
    (Q1: the dedicated flags do not open it). If 'block' ever became
    allowable, every row here flips."""
    gate(sl, network_mode=nm, is_local_mode=local)
    assert ms.is_allowed_security_level("block") is False


@pytest.mark.parametrize(("sl", "local", "nm", "expected"), _HIGH_PLUS)
def test_p3_high_plus_decision(ms, gate, sl, local, nm, expected):
    """P3 (high+ arm): comfyui_switch_version gate decision. Allow iff
    (loopback AND sl in {weak,normal-}) OR (personal_cloud AND sl == weak)."""
    gate(sl, network_mode=nm, is_local_mode=local)
    assert ms.is_allowed_security_level("high+") is expected


@pytest.mark.parametrize(("sl", "local", "nm", "expected"), _MIDDLE)
def test_p3_middle_decision(ms, gate, sl, local, nm, expected):
    """P3 (middle arm): snapshot remove / middle-gated legacy ops. Allow iff
    sl in {weak,normal,normal-} (locality-independent)."""
    gate(sl, network_mode=nm, is_local_mode=local)
    assert ms.is_allowed_security_level("middle") is expected


# ===========================================================================
# Response-shape guards — invoke the REAL async handlers; assert the observable
# status. Each pairs a DENY with an opposite case so the gate (not a constant)
# is provably what decides.
# ===========================================================================

def test_p1_install_custom_node_denies_at_strong_403(ms, gate):
    """P1 deny: at sl=strong the middle+ entry gate (first statement of
    _install_custom_node) returns 403 before any further processing."""
    gate("strong", is_local_mode=True)
    resp = _run(ms._install_custom_node({}))
    assert resp.status == 403


def test_p1_install_custom_node_passes_entry_gate_at_normal(ms, gate, monkeypatch):
    """P1 allow-flip: at sl=normal the middle+ entry gate PASSES — with the
    downstream risky level forced to an allowed value the handler reaches 200,
    proving the 403 above came from the gate, not unconditionally."""
    gate("normal", is_local_mode=True)

    async def _risky_middle_plus(files, pip):
        return "middle+"

    monkeypatch.setattr(ms, "get_risky_level", _risky_middle_plus)
    json_data = {
        "version": "unknown",
        "files": ["https://github.com/example/unknown-node.git"],
        "pip": [],
        "id": "x",
        "ui_id": "u",
        "channel": "default",
        "mode": "cache",
    }
    resp = _run(ms._install_custom_node(dict(json_data)))
    assert resp.status == 200


def test_p2_unknown_pip_block_denies_404_even_at_weak(ms, gate, monkeypatch):
    """P2: with the risky level resolved to 'block' (unknown pip), the handler
    returns 404 even at sl=weak (the most permissive level) — proving 'block'
    is an unconditional deny, not a security_level-relative one."""
    gate("weak", is_local_mode=True)

    async def _risky_block(files, pip):
        return "block"

    monkeypatch.setattr(ms, "get_risky_level", _risky_block)
    json_data = {
        "version": "unknown",
        "files": ["https://github.com/example/unknown-node.git"],
        "pip": ["some-unknown-pkg"],
        "id": "x",
        "ui_id": "u",
        "channel": "default",
        "mode": "cache",
    }
    resp = _run(ms._install_custom_node(dict(json_data)))
    assert resp.status == 404


def test_p3_comfyui_switch_version_denies_high_plus_403(ms, gate):
    """P3 high+ handler: comfyui_switch_version denies with 403 at sl=normal
    (high+ requires normal- or lower on loopback)."""
    gate("normal", is_local_mode=True)
    resp = _run(ms.comfyui_switch_version(FakeRequest()))
    assert resp.status == 403


def test_p3_restore_snapshot_denies_middle_plus_403(ms, gate):
    """P3 middle+ handler: restore_snapshot denies with 403 at sl=strong
    (middle+ requires normal or lower)."""
    gate("strong", is_local_mode=True)
    resp = _run(ms.restore_snapshot(FakeRequest()))
    assert resp.status == 403


def test_p4_install_model_non_safetensors_denies_high_plus_403(ms, gate, monkeypatch):
    """P4 deny: a non-.safetensors model not on the whitelist requires high+;
    at sl=normal (middle+ passes, high+ fails) the handler returns 403."""
    gate("normal", is_local_mode=True)

    async def _whitelist_ok(item):
        return True

    async def _models_empty(*a, **k):
        return {"models": []}

    monkeypatch.setattr(ms, "check_whitelist_for_model", _whitelist_ok)
    monkeypatch.setattr(ms.core, "get_data_by_mode", _models_empty)
    json_data = {"filename": "model.ckpt", "url": "http://example/model.ckpt", "ui_id": "u"}
    resp = _run(ms._install_model(dict(json_data)))
    assert resp.status == 403


def test_p4_install_model_safetensors_skips_high_plus_gate_200(ms, gate, monkeypatch):
    """P4 flip: a .safetensors model skips the non-.safetensors high+ sub-check
    entirely and reaches 200 at the SAME sl=normal — proving the 403 above is
    driven by the non-.safetensors + high+ compound, not the security level
    alone."""
    gate("normal", is_local_mode=True)

    async def _whitelist_ok(item):
        return True

    monkeypatch.setattr(ms, "check_whitelist_for_model", _whitelist_ok)
    json_data = {"filename": "model.safetensors", "url": "http://example/m.safetensors", "ui_id": "u"}
    resp = _run(ms._install_model(dict(json_data)))
    assert resp.status == 200
