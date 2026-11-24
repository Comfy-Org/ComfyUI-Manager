"""[goal265 step4] Out-of-scope GUARD tests + structural frontend-copy
assertion for the dedicated install flags GOAL.

Two populations in this module (intentionally different RED/GREEN states):

1. GUARD rows (SC-25C, SC-26, SC-27, SC-28) — regression-intent '=' rows:
   they assert the out-of-scope FREEZE (goal265-spec.md §5) and are expected
   to PASS both TODAY and AFTER Step 6. A failure at any point means the
   implementation leaked outside the locked scope.

2. SC-23 frontend arm — Δ row, EXPECTED TO FAIL TODAY (RED): the
   js/common.js 403 error copy must name the responsible flag after Step 6
   (spec §1.4, Q2 in scope). Do NOT weaken it to pass against today's code.

Placement per spec §4 rows 4-5 ('existing glob suite extension or unit' /
'structural — copy-string assertion'): authored as a NEW unit/structural
module so the pre-existing suite stays untouched (Step-4 acceptance bar (d));
layout follows the Step-2 hand-off recommendation
(goal265-scenarios.md §6: test_install_flags_guards.py).

Functional rows import the GLOB copy of the gate matrix
(comfyui_manager/glob/utils/security_utils.py) with the lightweight runtime
stubs from tests/_install_flags_testutil.py; the legacy copy of the same
matrix is exercised end-to-end by tests/e2e/test_e2e_secgate_legacy_flags.py
(SC-25A/B) under a real server.
"""

from __future__ import annotations

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _install_flags_testutil import (  # noqa: E402
    REPO_ROOT,
    import_glob_security_utils,
)

GLOB_SERVER_PATH = os.path.join(
    REPO_ROOT, "comfyui_manager", "glob", "manager_server.py")
CM_CLI_PATH = os.path.join(REPO_ROOT, "cm_cli", "__main__.py")
COMMON_JS_PATH = os.path.join(REPO_ROOT, "comfyui_manager", "js", "common.js")

FLAG_KEYS = ("allow_git_url_install", "allow_pip_install")


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _extract_js_function(source: str, name: str) -> str:
    """Slice an `export async function <name>` block out of common.js
    (up to the next exported/function declaration or EOF)."""
    m = re.search(
        rf"export\s+async\s+function\s+{re.escape(name)}\b.*?"
        r"(?=\nexport\s|\nfunction\s|\Z)",
        source,
        re.DOTALL,
    )
    assert m, f"could not locate function {name!r} in js/common.js"
    return m.group(0)


# ---------------------------------------------------------------------------
# SC-27 — glob route-table absence (guard, '=')
# ---------------------------------------------------------------------------

def test_sc27_glob_registers_no_git_url_or_pip_install_route():
    """SC-27 (guard): glob/manager_server.py must register NO
    /v2/customnode/install/git_url or /v2/customnode/install/pip route —
    no new glob HTTP surface under this GOAL (Q4 settled; spec §5 item 5).
    Structural: route-decorator scan of the glob server source."""
    src = _read(GLOB_SERVER_PATH)
    for path in ("/v2/customnode/install/git_url",
                 "/v2/customnode/install/pip"):
        pattern = rf"routes\.(post|get|put|delete)\(\s*[\"']{re.escape(path)}[\"']"
        assert not re.search(pattern, src), (
            f"SC-27: glob manager_server registers {path} — Q4 forbids a "
            "new glob surface for these capabilities under this GOAL"
        )


# ---------------------------------------------------------------------------
# SC-26 — cm-cli path stays ungated (guard, '=')
# ---------------------------------------------------------------------------

def test_sc26_cm_cli_install_path_has_no_gate():
    """SC-26 (guard): the cm-cli install path (install_node ->
    core.gitclone_install, cm_cli/__main__.py) is a local operator tool —
    it must consult NEITHER the security_level gate NOR the new flags
    (spec §5 item 4: cm-cli untouched). Static source assertion — no clone
    is executed."""
    src = _read(CM_CLI_PATH)
    assert "is_allowed_security_level" not in src, (
        "SC-26: cm_cli/__main__.py grew a security_level gate — cm-cli "
        "must stay ungated under this GOAL"
    )
    for key in FLAG_KEYS:
        assert key not in src, (
            f"SC-26: cm_cli/__main__.py consults {key!r} — the dedicated "
            "flags must not gate the local operator CLI"
        )


# ---------------------------------------------------------------------------
# SC-25C — glob comfyui_switch_version stays high+ security_level-coupled
# (guard, '=') — structural arm
# ---------------------------------------------------------------------------

def test_sc25c_glob_switch_version_keeps_high_plus_gate():
    """SC-25C (guard, structural arm): the glob comfyui_switch_version
    handler keeps its is_allowed_security_level('high+') guard and does not
    consult the new flags (spec §5 item 1). The functional arm (high+ denies
    at sl=normal regardless of flags) is test_sc25c_sc28_* below."""
    src = _read(GLOB_SERVER_PATH)
    m = re.search(
        r"@routes\.post\(\s*[\"']/v2/comfyui_manager/comfyui_switch_version[\"']\s*\)"
        r".*?(?=\n@routes\.|\Z)",
        src,
        re.DOTALL,
    )
    assert m, "SC-25C: comfyui_switch_version route not found in glob server"
    handler = m.group(0)
    assert re.search(
        r"is_allowed_security_level\(\s*[\"']high\+[\"']", handler), (
        "SC-25C: comfyui_switch_version no longer carries the "
        "is_allowed_security_level('high+') guard — out-of-scope gate "
        "changed (spec §5 freeze item 1)"
    )
    for key in FLAG_KEYS:
        assert key not in handler, (
            f"SC-25C: comfyui_switch_version consults {key!r} — the new "
            "flags must not affect this surface"
        )


# ---------------------------------------------------------------------------
# SC-28 (+ SC-25C functional arm) — security_level matrix untouched
# (guard, '=')
# ---------------------------------------------------------------------------

# Frozen truth table of is_allowed_security_level at loopback listen,
# network_mode=public (verified against legacy/manager_server.py:97-122 and
# glob/utils/security_utils.py:22-48 as of base 01799f8c). The new flags
# must leave every cell unchanged.
_EXPECTED_MATRIX = {
    # (level, security_level): allowed
    ("block", "weak"): False,
    ("block", "normal"): False,
    ("high+", "weak"): True,
    ("high+", "normal-"): True,
    ("high+", "normal"): False,
    ("high+", "strong"): False,
    ("high", "weak"): True,
    ("high", "normal-"): True,
    ("high", "normal"): False,
    ("high", "strong"): False,
    ("middle+", "weak"): True,
    ("middle+", "normal-"): True,
    ("middle+", "normal"): True,
    ("middle+", "strong"): False,
    ("middle", "weak"): True,
    ("middle", "normal-"): True,
    ("middle", "normal"): True,
    ("middle", "strong"): False,
}


@pytest.mark.parametrize("flags_value", [True, False],
                         ids=["flags-on", "flags-off"])
def test_sc25c_sc28_security_level_matrix_unchanged_by_flags(
        monkeypatch, flags_value):
    """SC-28 (guard): the is_allowed_security_level truth table for the
    non-target levels (middle/middle+/high/high+/block) is byte-identical
    whether both new flags are true or false — security_level semantics
    untouched (spec §5 item 2; MM §3).

    SC-25C (functional arm): the ('high+', 'normal') -> False cell is the
    switch_version deny — it must hold for BOTH flag combinations.

    Exercises the GLOB copy of the matrix (importable without a ComfyUI
    runtime); config access is monkeypatched at the consumer module so no
    real config.ini is read."""
    su = import_glob_security_utils()

    fake_config = {
        "network_mode": "public",
        "allow_git_url_install": flags_value,
        "allow_pip_install": flags_value,
    }
    current_level = {"value": "normal"}

    def fake_get_config():
        return {**fake_config, "security_level": current_level["value"]}

    monkeypatch.setattr(su.core, "get_config", fake_get_config)
    monkeypatch.setattr(su.args, "listen", "127.0.0.1")

    observed = {}
    for (level, sl) in _EXPECTED_MATRIX:
        current_level["value"] = sl
        observed[(level, sl)] = su.is_allowed_security_level(level)

    mismatches = {
        cell: (got, _EXPECTED_MATRIX[cell])
        for cell, got in observed.items()
        if got is not _EXPECTED_MATRIX[cell]
    }
    assert not mismatches, (
        f"SC-28(flags={flags_value}): security_level matrix drifted — "
        f"{{cell: (got, expected)}} = {mismatches!r}. The dedicated-flag "
        "GOAL must not alter is_allowed_security_level semantics."
    )


# ---------------------------------------------------------------------------
# SC-23 frontend arm — js/common.js error copy names the flag (Δ — RED today)
# ---------------------------------------------------------------------------

class TestSc23FrontendCopy:
    """SC-23 (frontend arm, structural — spec §1.4 / Q2 in scope): on a
    non-200 install response, the user-visible copy must name the
    responsible flag, replacing the 'security level' framing.
    Copy-string assertion on js/common.js — not an executed-browser test
    (goal265-scenarios.md §6 note). EXPECTED TO FAIL TODAY (RED)."""

    def test_sc23_install_pip_error_copy_names_pip_flag(self):
        """install_pip error branch (~:213 call site) names
        allow_pip_install and drops the security-level framing."""
        block = _extract_js_function(_read(COMMON_JS_PATH), "install_pip")
        assert "allow_pip_install" in block, (
            "SC-23: js/common.js install_pip error copy does not name "
            "allow_pip_install (spec §1.4 frontend copy contract)"
        )
        assert "security level" not in block.lower(), (
            "SC-23: js/common.js install_pip still carries the misleading "
            "'security level' framing"
        )

    def test_sc23_install_git_url_error_copy_names_git_flag(self):
        """install_via_git_url error branch (~:248 call site) names
        allow_git_url_install and drops the security-level framing."""
        block = _extract_js_function(
            _read(COMMON_JS_PATH), "install_via_git_url")
        assert "allow_git_url_install" in block, (
            "SC-23: js/common.js install_via_git_url error copy does not "
            "name allow_git_url_install (spec §1.4 frontend copy contract)"
        )
        assert "security level" not in block.lower(), (
            "SC-23: js/common.js install_via_git_url still carries the "
            "misleading 'security level' framing"
        )
