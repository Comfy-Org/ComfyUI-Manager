"""Regression suite for the settings writer and the install-denial messages.

Two behaviours are pinned here, both of which used to be wrong in ways a user
only notices after losing data or acting on misleading advice:

* ``write_config()`` MERGES onto what is on disk. It used to rebuild the
  ``[default]`` section from the process-lifetime cache, so a hand edit made
  while the server was up, a key that ``read_config`` reads but the writer
  never writes, and any non-``[default]`` section were all silently destroyed
  by the next settings write. Those are the four merge rows below.
* the install-denial MESSAGES name the condition that actually failed. A
  denial can be caused by the dedicated flag OR by the network mode, and a
  message that names only one of them sends the user to change a setting that
  will not help.

A later group covers a silent read failure: an existing but
UNREADABLE ``config.ini`` used to fall through the same else-branch as "no
config yet", so the writer treated it as a fresh bootstrap and overwrote the
file it could not read.

RUN IT PINNED. A non-editable ``comfyui_manager`` can live in site-packages,
and the console-script ``pytest`` does not put cwd on ``sys.path``, so an
unpinned run silently exercises the stale installed copy:

    PYTHONPATH=<repo abs path> pytest tests/test_config_write_and_install_denial.py

``test_import_origin_is_this_tree`` fails loudly when the run is unpinned,
so a misleading pass or failure cannot go unnoticed.

Harness: the in-repo ``tests/_install_flags_testutil.py``, parameterized over
BOTH config readers. ``manager_server`` is NEVER imported — importing that
module starts a network thread — so the message rows assert against parsed
SOURCE rather than against an imported constant.
"""

from __future__ import annotations

import ast
import configparser
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _install_flags_testutil import import_context, import_reader  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
READERS = ("glob", "legacy")

LEGACY_SERVER = os.path.join(REPO_ROOT, "comfyui_manager", "legacy", "manager_server.py")
SHARED_MESSAGES = os.path.join(REPO_ROOT, "comfyui_manager", "common", "security_messages.py")

#: the keys ``write_config()`` owns, per tree. Deliberately spelled
#: out rather than read back from the implementation: this is the CONTRACT the
#: code must satisfy, not a mirror of whatever the code currently does.
OWNED_KEYS = {
    "legacy": (
        "git_exe", "use_uv", "channel_url", "share_option", "bypass_ssl",
        "file_logging", "update_policy", "windows_selector_event_loop_policy",
        "model_download_by_agent", "downgrade_blacklist", "security_level",
        "always_lazy_install", "network_mode", "db_mode",
        "allow_git_url_install", "allow_pip_install",
    ),
    "glob": (
        "git_exe", "use_uv", "use_unified_resolver", "channel_url",
        "share_option", "bypass_ssl", "file_logging", "update_policy",
        "windows_selector_event_loop_policy", "model_download_by_agent",
        "downgrade_blacklist", "security_level", "always_lazy_install",
        "network_mode", "db_mode", "verbose",
        "allow_git_url_install", "allow_pip_install",
    ),
}

#: read by both readers, written by neither — a settings write must leave
#: them alone.
UNWRITTEN_KEYS = ("http_channel_enabled", "default_cache_as_channel_url")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(params=READERS)
def reader_core(request):
    """(reader_name, manager_core) for BOTH readers, cache isolated per test."""
    core = import_reader(request.param)
    saved = getattr(core, "cached_config", None)
    setattr(core, "cached_config", None)
    yield request.param, core
    setattr(core, "cached_config", saved)


@pytest.fixture
def point_config(monkeypatch):
    """Point ``context.manager_config_path`` at a path (resolved at call time
    by read_config AND write_config, so this redirects both readers)."""
    ctx = import_context()

    def _point(path):
        monkeypatch.setattr(ctx, "manager_config_path", str(path))

    return _point


def _write_ini(path, body: str):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    return path


def _read_raw(path) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _parse_disk(path) -> configparser.ConfigParser:
    cp = configparser.ConfigParser(strict=False)
    cp.read(str(path))
    return cp


def _boot(core):
    """Simulate process start: populate the module-level config cache once."""
    setattr(core, "cached_config", None)
    return core.get_config()


def _settings_change(core, key, value):
    """The real caller shape: mutate the cache, then write."""
    core.get_config()[key] = value
    core.write_config()


def _message_constants(source_path):
    """Module-level ``SECURITY_MESSAGE_* = "..."`` assignments -> {name: text}.

    Parsed from source: importing ``manager_server`` starts a network thread.
    """
    tree = ast.parse(_read_raw(source_path), filename=source_path)
    out = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id.startswith("SECURITY_MESSAGE_"):
                out[target.id] = node.value.value
    return out


def _flag_message_emissions(source_path):
    """Every ``logging.error(SECURITY_MESSAGE_FLAG_*...)`` site.

    Returns [(lineno, const_name, formatted: bool)]. ``formatted`` is True only
    when the argument is ``SECURITY_MESSAGE_FLAG_*.format(listen=args.listen)``.
    """
    tree = ast.parse(_read_raw(source_path), filename=source_path)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "error"):
            continue
        if not node.args:
            continue
        arg = node.args[0]
        # bare constant:  logging.error(SECURITY_MESSAGE_FLAG_GIT_URL)
        if isinstance(arg, ast.Name) and arg.id.startswith("SECURITY_MESSAGE_FLAG_"):
            found.append((node.lineno, arg.id, False))
            continue
        # formatted:  logging.error(SECURITY_MESSAGE_FLAG_GIT_URL.format(listen=...))
        if (isinstance(arg, ast.Call)
                and isinstance(arg.func, ast.Attribute)
                and arg.func.attr == "format"
                and isinstance(arg.func.value, ast.Name)
                and arg.func.value.id.startswith("SECURITY_MESSAGE_FLAG_")):
            kwargs = {kw.arg for kw in arg.keywords}
            listen_kw = "listen" in kwargs
            found.append((node.lineno, arg.func.value.id, listen_kw))
    return sorted(found)


# ---------------------------------------------------------------------------
# import-origin guard
# ---------------------------------------------------------------------------

def test_import_origin_is_this_tree():
    """The suite must exercise THIS checkout, not the site-packages copy.

    Unpinned, the console-script ``pytest`` resolves ``comfyui_manager`` to the
    non-editable 4.2.2 install and every other verdict in this file becomes
    meaningless. Measured once on the pre-existing suites: an unpinned run
    reported 18 failed / 73 passed where a pinned run reported 91 passed.
    """
    core = import_reader("legacy")
    origin = getattr(core, "__file__", None)
    assert origin, "comfyui_manager.legacy.manager_core has no __file__ to check"
    resolved = os.path.abspath(origin)
    assert resolved.startswith(REPO_ROOT + os.sep), (
        "IMPORT-ORIGIN GUARD: comfyui_manager resolved to %r, which is OUTSIDE this "
        "checkout (%r). The run is UNPINNED and is testing a different copy of "
        "the package. Re-run as: PYTHONPATH=%s pytest tests/test_config_write_and_install_denial.py"
        % (resolved, REPO_ROOT, REPO_ROOT)
    )


# ---------------------------------------------------------------------------
# write_config merges onto disk
# ---------------------------------------------------------------------------

def test_hand_edit_survives(reader_core, point_config, tmp_path):
    """A hand edit made while the server is UP survives an
    unrelated settings change.

    ``write_config()`` rebuilds ``[default]`` from the process-lifetime
    startup snapshot, so the edit is overwritten with the stale cached value —
    the user follows the denial message, edits config.ini, touches any Manager
    setting, and is denied again after restart.
    """
    reader, core = reader_core
    ini = tmp_path / "config.ini"
    _write_ini(ini, "[default]\nsecurity_level = normal\nallow_git_url_install = false\n")
    point_config(ini)

    _boot(core)  # startup snapshot: flag False
    # user hand-edits config.ini while ComfyUI is running
    _write_ini(ini, "[default]\nsecurity_level = normal\nallow_git_url_install = true\n")
    _settings_change(core, "db_mode", "local")

    on_disk = _parse_disk(ini)["default"].get("allow_git_url_install", "<ABSENT>")
    assert str(on_disk).lower() == "true", (
        "expected the hand-edited allow_git_url_install=true to SURVIVE "
        "an unrelated settings change; observed %r on disk (%s reader). "
        "write_config() re-wrote the key from the startup snapshot.\nfile:\n%s"
        % (on_disk, reader, _read_raw(ini))
    )


def test_unwritten_keys_survive(reader_core, point_config, tmp_path):
    """Keys read_config reads but write_config never writes.

    ``http_channel_enabled`` gates the insecure-channel warning and
    ``default_cache_as_channel_url`` steers channel resolution; every settings
    write deletes both from the file.
    """
    reader, core = reader_core
    ini = tmp_path / "config.ini"
    _write_ini(
        ini,
        "[default]\nsecurity_level = normal\n"
        "http_channel_enabled = true\ndefault_cache_as_channel_url = true\n",
    )
    point_config(ini)

    _boot(core)
    _settings_change(core, "db_mode", "local")

    section = _parse_disk(ini)["default"]
    missing = [k for k in UNWRITTEN_KEYS if k not in section]
    assert not missing, (
        "expected the read-but-never-written keys %s to SURVIVE a "
        "settings write; observed %s DELETED from the file (%s reader). "
        "write_config() rebuilds [default] from its own key list.\nfile:\n%s"
        % (list(UNWRITTEN_KEYS), missing, reader, _read_raw(ini))
    )


def test_foreign_section_survives(reader_core, point_config, tmp_path):
    """A non-[default] section survives a settings write.

    ``write_config()`` builds a FRESH parser, assigns only
    ``config['default']`` and opens the file ``'w'``, erasing every other section.
    """
    reader, core = reader_core
    ini = tmp_path / "config.ini"
    _write_ini(
        ini,
        "[default]\nsecurity_level = normal\n\n"
        "[my_custom_section]\nfoo = bar\nbaz = 1\n",
    )
    point_config(ini)

    _boot(core)
    _settings_change(core, "db_mode", "local")

    disk = _parse_disk(ini)
    assert disk.has_section("my_custom_section"), (
        "expected the foreign section [my_custom_section] to SURVIVE a "
        "settings write; observed it ERASED (%s reader).\nfile:\n%s"
        % (reader, _read_raw(ini))
    )
    assert disk["my_custom_section"].get("foo") == "bar", (
        "[my_custom_section] survived but lost its content (%s reader).\nfile:\n%s"
        % (reader, _read_raw(ini))
    )


def test_no_reclobber_after_persist(reader_core, point_config, tmp_path):
    """A key changed once through the API, then hand-edited,
    is NOT re-clobbered by the next unrelated write.

    This is the residual clobber that upstream's first attempt at the merge
    left behind, later fixed with ``dirty_keys.difference_update(keys)``:
    without the post-write reset the key stays dirty for the life of the
    process and every later write overlays the stale cached value again.
    """
    reader, core = reader_core
    ini = tmp_path / "config.ini"
    _write_ini(ini, "[default]\nsecurity_level = normal\ndb_mode = cache\n")
    point_config(ini)

    _boot(core)
    _settings_change(core, "db_mode", "local")      # persisted through the API
    assert _parse_disk(ini)["default"].get("db_mode") == "local", (
        "precondition failed: the API change did not reach disk (%s reader)" % reader
    )

    # user now hand-edits that SAME key while the server is up
    raw = _read_raw(ini).replace("db_mode = local", "db_mode = remote")
    _write_ini(ini, raw)

    _settings_change(core, "share_option", "none")  # UNRELATED settings change

    on_disk = _parse_disk(ini)["default"].get("db_mode", "<ABSENT>")
    assert on_disk == "remote", (
        "expected the later hand-edit db_mode=remote to SURVIVE an "
        "unrelated settings change; observed %r (%s reader) — the previously "
        "API-changed key was written again from the stale cache.\nfile:\n%s"
        % (on_disk, reader, _read_raw(ini))
    )


def test_bootstrap_seeds_owned_keys(reader_core, point_config, tmp_path):
    """No config.ini at all: the bootstrap path seeds the full
    owned key set.

    A guard: the merge rework must not break first-launch bootstrap.
    """
    reader, core = reader_core
    ini = tmp_path / "config.ini"
    point_config(ini)
    assert not os.path.exists(ini), "precondition: config.ini must be absent"

    _boot(core)
    core.write_config()

    assert os.path.exists(ini), (
        "bootstrap did not create config.ini (%s reader)" % reader
    )
    section = _parse_disk(ini)["default"]
    missing = [k for k in OWNED_KEYS[reader] if k not in section]
    assert not missing, (
        "bootstrap seeded an incomplete [default] for the %s reader — "
        "missing %s.\nfile:\n%s"
        % (reader, missing, _read_raw(ini))
    )


def test_malformed_ini_does_not_raise(reader_core, point_config, tmp_path):
    """An unparsable config.ini must not make a settings change
    raise; the file is rewritten from the current settings.

    A guard. Deliberately does NOT assert survival of unwritten keys or
    foreign sections: an unparsable file is exactly where the merge narrows,
    and asserting survival here would pin a behavior the design does not
    promise.
    """
    reader, core = reader_core
    ini = tmp_path / "config.ini"
    _write_ini(ini, "this is not an ini file\n[[[unclosed\n= = =\n")
    point_config(ini)

    _boot(core)
    try:
        _settings_change(core, "db_mode", "local")
    except Exception as exc:  # noqa: BLE001 — the point of the row
        pytest.fail(
            "a settings change raised %s on an unparsable config.ini "
            "(%s reader): %s" % (type(exc).__name__, reader, exc)
        )

    disk = _parse_disk(ini)
    assert disk.has_section("default"), (
        "after the fallback rewrite the file has no [default] section "
        "(%s reader).\nfile:\n%s" % (reader, _read_raw(ini))
    )


def test_unowned_key_not_persisted(reader_core, point_config, tmp_path):
    """Dirtying a key write_config does NOT own must not
    persist it (unchanged from today's behavior).

    A guard: ownership alone decides what a write persists.
    """
    reader, core = reader_core
    ini = tmp_path / "config.ini"
    _write_ini(ini, "[default]\nsecurity_level = normal\n")
    point_config(ini)

    _boot(core)
    core.get_config()["http_channel_enabled"] = True   # unowned
    _settings_change(core, "db_mode", "local")         # owned

    section = _parse_disk(ini)["default"]
    assert "http_channel_enabled" not in section, (
        "the unowned key http_channel_enabled was persisted (%s reader); "
        "write_config() must persist only keys it owns.\nfile:\n%s"
        % (reader, _read_raw(ini))
    )


def test_unowned_dirty_marker_survives(reader_core, point_config, tmp_path):
    """A dirty marker for a key this write did NOT persist
    must SURVIVE the write.

    Rests on the ``DirtyTrackingConfig`` cache, and pins
    ``difference_update(keys)`` over ``clear()``: a blanket clear would drop the
    marker for a key the write never persisted, so the change the user made to
    it would never reach disk.
    """
    reader, core = reader_core
    ini = tmp_path / "config.ini"
    _write_ini(ini, "[default]\nsecurity_level = normal\n")
    point_config(ini)

    cached = _boot(core)
    cached["http_channel_enabled"] = True              # unowned -> never persisted
    _settings_change(core, "db_mode", "local")         # owned   -> persisted

    dirty = getattr(core.get_config(), "dirty_keys", None)
    assert dirty is not None, (
        "the cached config exposes no dirty_keys (%s reader) — the cache is no "
        "longer a DirtyTrackingConfig, so write_config() cannot know what "
        "actually changed and falls back to rewriting every owned key from the "
        "startup snapshot."
        % reader
    )
    assert "http_channel_enabled" in dirty, (
        "the dirty marker for the UNPERSISTED key http_channel_enabled "
        "was dropped by the write (%s reader); the post-write reset must "
        "difference_update() exactly the persisted keys, never clear() "
        ". dirty_keys=%r" % (reader, dirty)
    )
    assert "db_mode" not in dirty, (
        "db_mode was persisted by this write but is still marked dirty "
        "(%s reader) — without the reset it stays dirty for the life of the "
        "process and re-clobbers a later hand-edit. dirty_keys=%r"
        % (reader, dirty)
    )


def test_partial_write_leaves_file_intact(reader_core, point_config, tmp_path, monkeypatch):
    """A settings write that fails PART-WAY must leave config.ini byte-intact.

    The merge is what makes this matter. Foreign keys and foreign sections are
    carried across by reading them off the disk, so the file on disk is their
    ONLY home — nothing in the process holds a copy. A writer that truncates
    that file and then streams into it opens a window in which the content
    exists nowhere at all, and a crash, a kill, or a full disk inside the window
    leaves a half-written file and nothing to recover from. That is the same
    loss the merge exists to prevent, arriving through the writer instead.

    The failure has to be INJECTED because the window is invisible from
    outside: a write that completes closes it either way, so only interrupting
    one distinguishes "wrote elsewhere and renamed" from "truncated in place".
    The injection point is ``ConfigParser.write`` mid-output, which is where a
    real ENOSPC or SIGKILL would land.

    Two legs. The file is unchanged — the previous settings survive the failed
    attempt in full. And nothing is left behind: writing to a temporary file is
    only an improvement if the failed attempt cleans up after itself, otherwise
    the directory accumulates partial files that a later reader could mistake
    for the real one.
    """
    reader, core = reader_core
    ini = tmp_path / "config.ini"
    _write_ini(ini, "[default]\nsecurity_level = normal\ndb_mode = cache\n"
                    "http_channel_enabled = true\n\n[my_section]\nfoo = bar\n")
    point_config(ini)

    _boot(core)
    before = ini.read_bytes()

    def _partial_then_fail(self, fp, *args, **kwargs):
        fp.write("[default]\nsecurity_level = nor")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(configparser.ConfigParser, "write", _partial_then_fail)

    with pytest.raises(OSError):
        _settings_change(core, "db_mode", "local")

    after = ini.read_bytes()
    assert after == before, (
        "a settings write that failed mid-output changed config.ini (%s reader). "
        "The failed attempt must not touch the target at all — write a temporary "
        "file beside it and os.replace() it into place, so the file is either the "
        "old one or the complete new one.\nbefore:\n%s\nafter:\n%s"
        % (reader, before.decode("utf-8", "replace"), after.decode("utf-8", "replace"))
    )

    strays = sorted(p.name for p in tmp_path.iterdir() if p.name != "config.ini")
    assert not strays, (
        "the failed write left %s behind next to config.ini (%s reader). A "
        "partial file in the settings directory outlives the failure and can be "
        "picked up later; the writer must remove its temporary file when the "
        "write does not complete." % (strays, reader)
    )


# ---------------------------------------------------------------------------
# install-denial messages
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("const_name,flag_key", [
    ("SECURITY_MESSAGE_FLAG_GIT_URL", "allow_git_url_install"),
    ("SECURITY_MESSAGE_FLAG_PIP", "allow_pip_install"),
])
def test_flag_messages_state_both_conds(const_name, flag_key):
    """The denial message states BOTH gate conditions and
    carries a ``{listen}`` placeholder for the live value.

    Naming only the config flag would send a user to enable a flag that is
    often already enabled, while the real blocker is the network-position half
    of the predicate. The gate is
    ``flag AND (loopback OR network_mode == 'personal_cloud')`` — WIDER than
    upstream's loopback-only, so BOTH alternatives must appear.
    """
    consts = _message_constants(LEGACY_SERVER)
    assert const_name in consts, "%s not found in %s" % (const_name, LEGACY_SERVER)
    text = consts[const_name]
    lowered = text.lower()

    assert flag_key in text, (
        "%s no longer names its flag %r — the e2e denial-log assertions "
        "depend on it. text=%r" % (const_name, flag_key, text)
    )
    assert "{listen}" in text, (
        "expected %s to carry a {listen} placeholder so every emission "
        "can print the LIVE --listen value; observed none. text=%r"
        % (const_name, text)
    )
    assert ("loopback" in lowered or "127.0.0.1" in text), (
        "expected %s to state the loopback half of the gate "
        "(flag AND (loopback OR personal_cloud)); observed a flag-only message. "
        "text=%r" % (const_name, text)
    )
    assert "personal_cloud" in lowered, (
        "expected %s to state the network_mode = personal_cloud "
        "alternative — our predicate is WIDER than upstream's loopback-only "
        ", so omitting it makes the message contradict the gate. "
        "text=%r" % (const_name, text)
    )


def test_flag_message_emissions_format():
    """EVERY flag-message emission renders the live listen value.

    There are 3 emission sites in legacy/manager_server.py
    (the 404 arm of install_custom_node, plus the git_url and pip endpoints);
    each must emit ``.format(listen=args.listen)``.
    """
    emissions = _flag_message_emissions(LEGACY_SERVER)
    assert len(emissions) == 3, (
        "expected 3 flag-message emission sites in %s; found %d: %r"
        % (LEGACY_SERVER, len(emissions), emissions)
    )
    unformatted = [(line, name) for line, name, formatted in emissions if not formatted]
    assert not unformatted, (
        "these flag-denial emissions do not render the live listen value "
        "— expected SECURITY_MESSAGE_FLAG_*.format(listen=args.listen) at every "
        "site, observed a bare constant at %r. A user reading the log cannot tell "
        "which half of the gate denied them." % (unformatted,)
    )


def test_flag_messages_drop_seclevel_copy():
    """The flag messages must NOT carry the security-level copy.

    A guard. Two existing e2e tests assert this
    substring is ABSENT from flag-denial logs
    (tests/e2e/test_e2e_secgate_legacy_flags.py:471,
    tests/e2e/test_e2e_pip_url_form.py:286); the rewrite must not trip them.
    """
    consts = _message_constants(LEGACY_SERVER)
    offenders = {
        name: text
        for name, text in consts.items()
        if name.startswith("SECURITY_MESSAGE_FLAG_") and "security level to 'normal-'" in text
    }
    assert not offenders, (
        "flag-denial message(s) %s carry the substring "
        "\"security level to 'normal-'\", which the existing e2e suites assert is "
        "ABSENT from the denial log. The dedicated flags are decoupled from "
        "security_level, so the copy is also wrong." % sorted(offenders)
    )


# ---------------------------------------------------------------------------
# stale 'middle' security_level
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source_path", [
    # ids are repo-RELATIVE on purpose: the absolute path differs per checkout,
    # so an absolute id would give the same test a different node-id in every
    # checkout and defeat node-id comparison across test runs.
    pytest.param(LEGACY_SERVER, id=os.path.relpath(LEGACY_SERVER, REPO_ROOT)),
    pytest.param(SHARED_MESSAGES, id=os.path.relpath(SHARED_MESSAGES, REPO_ROOT)),
])
def test_no_middle_security_level_value(source_path):
    """No message may quote ``'middle'`` as a security_level.

    The message that motivated this row told the user to "set the security
    level to 'middle' or 'weak'", but no such value exists (valid: strong /
    normal / normal- / weak) — a user following that copy sets an unrecognised
    value and stays denied. Both remaining definition sites are covered: the
    shared module, and the per-flag messages that are still declared next to
    the legacy gate. The internal gate-LEVEL tokens ``is_allowed_security_level
    ('middle')`` are NOT security_level values and are deliberately out of
    scope — this row only inspects message CONSTANTS.
    """
    consts = _message_constants(source_path)
    assert consts, "no SECURITY_MESSAGE_* constants found in %s" % source_path
    offenders = {name: text for name, text in consts.items() if "'middle'" in text}
    assert not offenders, (
        "message constant(s) %s in %s quote 'middle' as a security_level "
        "value, which does not exist (valid: strong / normal / normal- / weak). "
        "A user following this copy sets an unrecognised value and stays denied."
        % (sorted(offenders), os.path.relpath(source_path, REPO_ROOT))
    )


# ---------------------------------------------------------------------------
# Silent read failure — an existing config.ini that cannot be READ must not
# be mistaken for "no config yet"
# ---------------------------------------------------------------------------
#
# MECHANISM:
#   configparser.ConfigParser.read() SWALLOWS OSError — "if a file named in
#   filenames cannot be opened, that file will be ignored". On a chmod-0o000
#   config.ini it returns [] and raises nothing, so write_config()'s narrow
#   `except (configparser.Error, UnicodeDecodeError)` never fires, the parser
#   is empty, has_section('default') is False, and the BOOTSTRAP branch runs:
#   the file is rewritten from the startup snapshot and the settings call
#   returns success. The user's config.ini is destroyed and nothing says so.
#
# The distinction these rows pin: an ABSENT file may legitimately be seeded
# (the absent-file row below is allowed to seed), an UNREADABLE file may NOT —
# because "unreadable" means
# the content is unknown, not that there is no content.

#: chmod cannot make a file unreadable to root, so the scenario is unbuildable
#: there. Skip rather than assert a false pass.
_IS_ROOT = getattr(os, "geteuid", lambda: -1)() == 0
_root_skip = pytest.mark.skipif(
    _IS_ROOT or os.name != "posix",
    reason="Making a config unreadable with chmod requires POSIX and a non-root user.",
)

#: WRITE-ONLY (0o200), deliberately NOT 0o000.
#:
#: MEASURED against the unguarded writer, and this is the whole reason these
#: rows are worth having: under 0o000 the scenario did NOT reproduce the defect.
#: read() still swallowed the error and the bootstrap branch still ran, but a
#: writer that truncates the target in place ALSO hit PermissionError, so the
#: settings change raised and the file survived — for a reason that had nothing
#: to do with a guard. Both assertions below would have passed against the
#: unguarded writer, so a change could have "fixed" nothing and still passed.
#:
#: 0o200 removes that confound: the read fails silently, the write is fully
#: permitted, and the file is destroyed with the call reporting success. Any
#: raise observed under 0o200 therefore comes from a DELIBERATE check, never
#: from the OS.
_UNREADABLE_MODE = 0o200


def _run_settings_change_on_unreadable(core, ini):
    """Boot readable -> make unreadable-but-writable -> settings change.

    Returns ``(raised, before_bytes, after_bytes)``. Permissions are ALWAYS
    restored, including on failure, so tmp_path teardown can clean up.
    """
    _boot(core)                          # startup snapshot, taken while readable
    before = ini.read_bytes()
    os.chmod(ini, _UNREADABLE_MODE)      # perms tightened while the server is up
    raised = None
    try:
        _settings_change(core, "db_mode", "local")
    except Exception as exc:             # noqa: BLE001 — capturing IS the assertion
        raised = exc
    finally:
        os.chmod(ini, 0o600)             # restore before asserting, always
    return raised, before, ini.read_bytes()


@_root_skip
def test_unreadable_config_is_loud(reader_core, point_config, tmp_path):
    """A settings write against an UNREADABLE config.ini must
    fail LOUDLY rather than silently rewriting it.

    Without the guard the call returns success: read() ignores the
    PermissionError, the empty parser routes into the bootstrap branch, and the
    user is told nothing while their file is replaced by defaults. This row
    asserts the raise that closes that path.

    The file is write-only (0o200), not 0o000 — see ``_UNREADABLE_MODE``. Under
    0o000 this row passes against the UNFIXED code, because the OS blocks the
    destroying write for reasons unrelated to any guard.
    """
    reader, core = reader_core
    ini = tmp_path / "config.ini"
    _write_ini(ini, "[default]\nsecurity_level = normal\ndb_mode = cache\n"
                    "http_channel_enabled = true\n\n[my_section]\nfoo = bar\n")
    point_config(ini)

    raised, before, after = _run_settings_change_on_unreadable(core, ini)

    assert raised is not None, (
        "expected the settings change to RAISE on an unreadable "
        "config.ini; it returned success (%s reader). The file was %s. "
        "config.read() swallows the PermissionError, so the empty parser falls "
        "into the bootstrap branch and rewrites the file from the startup "
        "snapshot — silent data loss.\nbefore:\n%s\nafter:\n%s"
        % (reader,
           "DESTROYED" if after != before else "left intact",
           before.decode("utf-8", "replace"),
           after.decode("utf-8", "replace"))
    )


@_root_skip
def test_unreadable_config_file_intact(reader_core, point_config, tmp_path):
    """The unreadable config.ini must be left BYTE-UNTOUCHED.

    Separate node from the loudness row on purpose: "was it loud" and "was
    the file preserved" are independent failures, and a fix that only logs a
    warning satisfies loudness while still destroying the file. Keeping them
    apart means neither can be satisfied by sacrificing the other.
    """
    reader, core = reader_core
    ini = tmp_path / "config.ini"
    _write_ini(ini, "[default]\nsecurity_level = normal\ndb_mode = cache\n"
                    "http_channel_enabled = true\n\n[my_section]\nfoo = bar\n")
    point_config(ini)

    _raised, before, after = _run_settings_change_on_unreadable(core, ini)

    assert after == before, (
        "the unreadable config.ini was MODIFIED by a settings change "
        "(%s reader) — an unreadable file's content is UNKNOWN, so rewriting it "
        "destroys data the process never saw. Hand-maintained keys and foreign "
        "sections are gone.\nbefore:\n%s\nafter:\n%s"
        % (reader,
           before.decode("utf-8", "replace"),
           after.decode("utf-8", "replace"))
    )


def test_genuine_bootstrap_still_seeds(reader_core, point_config, tmp_path):
    """A genuinely ABSENT config.ini must still be seeded.

    The guard that keeps the read-failure check honest: it must distinguish
    "no file, so there is nothing to lose" from "unreadable file, so the
    content is unknown". A check that refuses BOTH breaks first-launch
    bootstrap; this row fails if it does.

    test_bootstrap_seeds_owned_keys already covers the seeding itself; what
    this row adds is the CONTRAST — it is the absent-file half of the same
    decision the two unreadable-file rows pin the other half of, so a future
    reader sees why one branch may write and the other may not.
    """
    reader, core = reader_core
    ini = tmp_path / "config.ini"
    point_config(ini)
    assert not os.path.exists(ini), "precondition: config.ini must be absent"

    _boot(core)
    try:
        core.write_config()
    except Exception as exc:  # noqa: BLE001 — the point of the row
        pytest.fail(
            "genuine bootstrap (absent config.ini) raised %s on the "
            "%s reader: %s. The read-failure guard must refuse UNREADABLE files "
            "without refusing ABSENT ones."
            % (type(exc).__name__, reader, exc)
        )

    assert os.path.exists(ini), (
        "bootstrap did not create config.ini (%s reader)" % reader
    )
    section = _parse_disk(ini)["default"]
    missing = [k for k in OWNED_KEYS[reader] if k not in section]
    assert not missing, (
        "bootstrap seeded an incomplete [default] for the %s reader "
        "— missing %s.\nfile:\n%s"
        % (reader, missing, _read_raw(ini))
    )
