"""[goal265 step4 — RED] Dual-reader config contract for the dedicated
install flags ``allow_git_url_install`` / ``allow_pip_install``.

TARGET CONTRACT (NOT YET IMPLEMENTED — goal265-spec.md §3, LOCKED):

  - Keys: ``allow_git_url_install``, ``allow_pip_install`` in
    config.ini ``[default]``.
  - BOTH readers carry the keys (read dict + write_config list +
    exception-fallback dict — 3 anchors each):
      * ``comfyui_manager/glob/manager_core.py``
      * ``comfyui_manager/legacy/manager_core.py``
    (dual-reader rule — the gated endpoints resolve through the LEGACY
    reader; a glob-only registration would silently never reach the gates.)
  - Only case-insensitive string "true" is truthy on read; anything else
    (including "1", "yes") reads False.
  - Missing key reads False — the shared ``get_bool(key, default)`` quirk:
    the ``default`` param is IGNORED, missing key -> always False.
  - Missing file / missing [default] section -> exception-fallback dict
    returns False for both keys.
  - Activation is restart-only (module-level ``cached_config``).

These tests are EXPECTED TO FAIL against current code (the keys are not
registered in either reader yet) — RED confirmation is goal265 Step 5.

SC rows covered (goal265-scenarios.md):
  SC-19  missing keys -> False (both readers)
  SC-20  malformed values -> only "true"/"TRUE"/"True" truthy (both readers)
  SC-21  write_config round-trip persistence (both readers)
  SC-22  cached_config staleness — restart-only activation (reader-level arm)
  SC-29  no config.ini / no [default] section -> fallback False (both readers)

Fixtures (spec §4 binding): tmp config.ini + monkeypatch
``context.manager_config_path`` + per-reader ``cached_config`` reset.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _install_flags_testutil import import_context, import_reader  # noqa: E402

FLAG_KEYS = ("allow_git_url_install", "allow_pip_install")
READERS = ("glob", "legacy")


def _reset_cache(core) -> None:
    """Clear the reader's module-level cached_config (simulates restart)."""
    setattr(core, "cached_config", None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(params=READERS)
def reader_core(request):
    """Yield (reader_name, manager_core module) for BOTH readers, with the
    module-level cached_config saved/cleared around each test so one test's
    cache never leaks into another (or into other test modules)."""
    core = import_reader(request.param)
    saved = getattr(core, "cached_config", None)
    _reset_cache(core)
    yield request.param, core
    setattr(core, "cached_config", saved)


@pytest.fixture
def point_config(monkeypatch):
    """Return a function that points context.manager_config_path at a path.

    Both readers resolve ``context.manager_config_path`` at CALL time
    (``config.read(context.manager_config_path)``), so monkeypatching the
    context attribute redirects glob AND legacy alike."""
    ctx = import_context()

    def _point(path):
        monkeypatch.setattr(ctx, "manager_config_path", str(path))

    return _point


def _write_ini(tmp_path, body: str):
    ini = tmp_path / "config.ini"
    ini.write_text(body, encoding="utf-8")
    return ini


# ---------------------------------------------------------------------------
# SC-19 — missing keys read False (get_bool quirk: missing key -> False)
# ---------------------------------------------------------------------------

def test_sc19_missing_keys_read_false(reader_core, point_config, tmp_path):
    """SC-19: config.ini WITHOUT either new key -> read_config returns
    allow_git_url_install == False AND allow_pip_install == False.

    This is the observable manifestation of the shared ``get_bool(key,
    default)`` quirk (spec §3): the ``default`` parameter is IGNORED —
    a missing key always reads False, never the passed default. The quirk
    is documented, NOT fixed, by this GOAL (spec §5 freeze item 9)."""
    reader, core = reader_core
    point_config(_write_ini(tmp_path, "[default]\nsecurity_level = normal\n"))

    cfg = core.read_config()

    for key in FLAG_KEYS:
        assert key in cfg, (
            f"RED: {reader} read_config() does not register {key!r} "
            "(goal265-spec.md §3 reader registration)"
        )
        assert cfg[key] is False, f"{reader}: missing {key} must read False"


# ---------------------------------------------------------------------------
# SC-20 — malformed values: only case-insensitive "true" is truthy
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("true", True),
        ("TRUE", True),
        ("True", True),
        ("1", False),
        ("yes", False),
        ("false", False),
        ("garbage", False),
    ],
    ids=["true", "TRUE", "True", "1", "yes", "false", "garbage"],
)
@pytest.mark.parametrize("flag_key", FLAG_KEYS)
def test_sc20_only_case_insensitive_true_is_truthy(
        reader_core, point_config, tmp_path, flag_key, raw_value, expected):
    """SC-20: key present with malformed values -> only case-insensitive
    "true" reads True; "1"/"yes"/"false"/"garbage" read False (both flags,
    both readers)."""
    reader, core = reader_core
    point_config(_write_ini(
        tmp_path,
        f"[default]\nsecurity_level = normal\n{flag_key} = {raw_value}\n",
    ))

    cfg = core.read_config()

    assert flag_key in cfg, (
        f"RED: {reader} read_config() does not register {flag_key!r}"
    )
    assert cfg[flag_key] is expected, (
        f"{reader}: {flag_key} = {raw_value!r} must read {expected}"
    )


# ---------------------------------------------------------------------------
# SC-21 — write_config round-trip (write list registration, both writers)
# ---------------------------------------------------------------------------

def test_sc21_write_config_round_trips_both_flags(
        reader_core, point_config, tmp_path):
    """SC-21: both flags true in cached config -> write_config -> reset the
    reader's cached_config -> read_config -> both keys persist as True.

    Failure mode this guards: keys registered in the read dict but NOT in
    the write_config persistence list — the value would silently drop on
    the next config save (spec §2 F3/F4 dual-anchor rule, residual risk R2)."""
    reader, core = reader_core
    ini = _write_ini(
        tmp_path,
        "[default]\nsecurity_level = normal\n"
        "allow_git_url_install = true\nallow_pip_install = true\n",
    )
    point_config(ini)

    loaded = core.get_config()
    for key in FLAG_KEYS:
        assert loaded.get(key) is True, (
            f"RED: {reader} get_config() did not load {key!r}=True "
            "from staged config.ini"
        )

    core.write_config()

    raw = ini.read_text(encoding="utf-8")
    for key in FLAG_KEYS:
        assert key in raw, (
            f"{reader}: write_config() dropped {key!r} — key missing from "
            "the write_config persistence list (spec §3 reader registration)"
        )

    _reset_cache(core)  # per-reader cache reset REQUIRED before re-read
    cfg = core.read_config()
    for key in FLAG_KEYS:
        assert cfg.get(key) is True, (
            f"{reader}: {key} did not survive the write/read round-trip"
        )


# ---------------------------------------------------------------------------
# SC-22 — cached_config staleness: restart-only activation (reader arm)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("flag_key", FLAG_KEYS)
def test_sc22_flag_edit_without_restart_stays_stale(
        reader_core, point_config, tmp_path, flag_key):
    """SC-22: process running with cached flag=false -> config.ini edited to
    flag=true WITHOUT restart -> the reader still serves False (module-level
    cached_config; identical semantics to security_level today, MM §1.5).
    Clearing the cache (= restart) then serves True."""
    reader, core = reader_core
    ini = _write_ini(
        tmp_path,
        f"[default]\nsecurity_level = normal\n{flag_key} = false\n",
    )
    point_config(ini)

    first = core.get_config()
    assert first.get(flag_key) is False, (
        f"RED: {reader} get_config() does not register {flag_key!r}"
    )

    # Edit config.ini on disk — NO cache reset (no restart).
    _write_ini(
        tmp_path,
        f"[default]\nsecurity_level = normal\n{flag_key} = true\n",
    )

    stale = core.get_config()
    assert stale.get(flag_key) is False, (
        f"{reader}: {flag_key} hot-reloaded — activation MUST be "
        "restart-only (cached_config, spec §3)"
    )

    _reset_cache(core)  # simulate restart
    fresh = core.get_config()
    assert fresh.get(flag_key) is True, (
        f"{reader}: {flag_key}=true not visible after cache reset (restart)"
    )


# ---------------------------------------------------------------------------
# SC-29 — exception-fallback path carries the new keys as False
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("breakage", ["missing_file", "no_default_section"])
def test_sc29_fallback_path_returns_false_for_both_flags(
        reader_core, point_config, tmp_path, breakage):
    """SC-29: NO config.ini present / config.ini WITHOUT [default] section ->
    read_config's exception-fallback dict returns False for BOTH new keys
    (fallback dicts are the third registration anchor per reader,
    spec §2 F3/F4)."""
    reader, core = reader_core
    if breakage == "missing_file":
        point_config(tmp_path / "does-not-exist" / "config.ini")
    else:
        point_config(_write_ini(tmp_path, "[other]\nsomething = 1\n"))

    cfg = core.read_config()

    for key in FLAG_KEYS:
        assert key in cfg, (
            f"RED: {reader} exception-fallback dict does not carry {key!r} "
            "(goal265-spec.md §3 'Reader registration' — fallback anchor)"
        )
        assert cfg[key] is False, (
            f"{reader}: fallback {key} must be False (secure by default)"
        )
