"""GOAL #25 RED — write_config() clobbers hand-maintained config.ini content.

Reproduces the three clobber classes the frozen MM
(`scratch/gm3-team/g25-mm.md`) records, as born-RED pytest nodes, plus two
born-GREEN regression guards. Node ids are the RED contract: the GREEN step
must drive these SAME ids to PASS.

| node                                   | MM row | AC   | born  |
|----------------------------------------|--------|------|-------|
| test_t1_hand_edited_flag_survives      | T1     | [D1] | RED   |
| test_t3_unwritten_key_survives         | T3     | [D3] | RED   |
| test_t4_non_default_section_survives   | T4     | [D3] | RED   |
| test_t2_each_caller_key_persists       | T2     | [D2] | GREEN |
| test_t5_bootstrap_writes_defaults      | T5     | S4   | GREEN |

GOAL #53 adds one more node to the same harness:

| node                                   | AC   | born  |
|----------------------------------------|------|-------|
| test_t7_silent_read_failure_is_loud    | [D1] | RED   |

  T7 — `config.read()` SILENTLY suppresses OSError. A config.ini that exists
       but cannot be read leaves the parser empty, so the merge falls into the
       BOOTSTRAP branch and rewrites the file from defaults, destroying every
       foreign key and non-`[default]` section. The failure must be loud, and
       the file must be left untouched.

Why they fail today (MM State Model, measured at 30bd355e):
  T1 — `write_config()` sources 17 of its 18 keys from `get_config()`, the
       process-lifetime startup snapshot (`manager_core.py:1685-1704`), so a
       hand edit made after startup is overwritten with the stale value.
  T3 — `read_config()` returns 20 keys, `write_config()` persists 18;
       `http_channel_enabled` and `default_cache_as_channel_url` are read but
       never written, so every write deletes them.
  T4 — `write_config()` builds a FRESH `ConfigParser`, assigns only
       `config['default']`, and opens the file `'w'` (`:1715`), erasing every
       other section.

Harness: the subprocess-isolated child from `tests/test_install_flags_config.py`
— stub `folder_paths`, `glob/` on the CHILD's sys.path only, `manager_core`
imported (NEVER `manager_server`: module level starts a network thread at
`:2093`), `manager_config_path` pointed at a tmp file, `cached_config` reset.

`force_security_level_if_needed` (MM HAZARD C-1) is NOT stubbed — it runs on
the real `read_config` path. The `folder_paths` stub supplies a system-user
directory, so `has_system_user_api()` is True and the function takes its
no-force branch and returns without mutating. The alias-mutation branch is
therefore present but not exercised here; the GREEN step must keep it in view
when it pins the dirty-tracking wrap point.
"""
import json
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The real mutation shape every settings caller uses (MM Action Map): a
#: subscript assignment on the cached dict, then `write_config()`. Verified
#: exhaustive by AST at 30bd355e — 6 sites, no other shape.
_CALLER_KEYS = [
    ("db_mode", "local"),                 # manager_server.py:1779 -> :244
    ("component_policy", "higher"),       # manager_server.py:1793 -> :238
    ("update_policy", "nightly-comfyui"), # manager_server.py:1806 -> :241
    ("channel_url", "https://example.invalid/ch"),  # manager_server.py:1833 -> :1832
    ("share_option", "none"),             # share_3rdparty.py:60 -> :59
]

_CHILD_PREAMBLE = textwrap.dedent(
    """
    import sys, types, tempfile, os, json, configparser
    tmp = tempfile.mkdtemp(prefix="cm_wcfg_")
    stub = types.ModuleType("folder_paths")
    stub.get_user_directory = lambda: tmp
    stub.get_system_user_directory = lambda *a, **k: os.path.join(tmp, "sysuser")
    sys.modules["folder_paths"] = stub
    sys.path.insert(0, {glob_path!r})
    import manager_core
    CONFIG_PATH = os.path.join(tmp, "config.ini")
    manager_core.manager_config_path = CONFIG_PATH
    manager_core.cached_config = None

    def write_ini(text):
        with open(CONFIG_PATH, "w") as f:
            f.write(text)

    def read_raw():
        with open(CONFIG_PATH) as f:
            return f.read()

    def parse_disk():
        cp = configparser.ConfigParser(strict=False)
        cp.read(CONFIG_PATH)
        return cp

    def boot():
        \"\"\"Simulate process start: read config.ini once into the cache.\"\"\"
        manager_core.cached_config = None
        return manager_core.get_config()

    def settings_change(key, value):
        \"\"\"The real caller shape: mutate the cached dict, then write.\"\"\"
        manager_core.get_config()[key] = value
        manager_core.write_config()
    """
)


def _run_child(body):
    """Run a scenario body in the isolated child; return its JSON payload."""
    script = _CHILD_PREAMBLE.format(glob_path=str(REPO_ROOT / "glob")) + textwrap.dedent(body)
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(REPO_ROOT),
    )
    if proc.returncode != 0:
        raise AssertionError(
            "write-config-harness child failed (rc=%d). stderr tail:\n%s"
            % (proc.returncode, "\n".join(proc.stderr.strip().splitlines()[-8:]))
        )
    lines = proc.stdout.strip().splitlines()
    if not lines:
        raise AssertionError(
            "write-config-harness child exited 0 but produced no stdout. stderr tail:\n%s"
            % "\n".join(proc.stderr.strip().splitlines()[-8:])
        )
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError as e:
        raise AssertionError(
            "write-config-harness child emitted a non-JSON last line: %r\nfull stdout:\n%s"
            % (lines[-1], proc.stdout)
        ) from e


class WriteConfigPersistenceTest(unittest.TestCase):
    """MM Test Scenario Map T1-T5 (`scratch/gm3-team/g25-mm.md`)."""

    def test_t1_hand_edited_flag_survives(self):
        """T1 / [D1] — a hand edit made while running survives a settings change.

        BORN-RED. The user follows GOAL #8's denial copy, edits config.ini,
        then touches any Manager setting; `write_config()` re-writes the flag
        from the startup snapshot and the edit is gone.
        """
        payload = _run_child(
            """
            write_ini("[default]\\nsecurity_level = normal\\nallow_git_url_install = false\\n")
            boot()                      # startup snapshot: flag False
            # user hand-edits config.ini while the server is UP
            write_ini("[default]\\nsecurity_level = normal\\nallow_git_url_install = true\\n")
            settings_change("db_mode", "local")   # ordinary Manager settings change
            cp = parse_disk()
            print(json.dumps({
                "flag_on_disk": cp["default"].get("allow_git_url_install", "<ABSENT>"),
                "raw": read_raw(),
            }))
            """
        )
        self.assertEqual(
            "true", str(payload["flag_on_disk"]).lower(),
            "T1 [D1]: the hand-edited allow_git_url_install=true was reverted to "
            "%r by an unrelated settings change. write_config() sources 17 of 18 "
            "keys from the startup snapshot (manager_core.py:1685-1704), so the "
            "user is denied again after restarting despite following the denial "
            "message exactly. On-disk file:\n%s"
            % (payload["flag_on_disk"], payload["raw"]),
        )

    def test_t3_unwritten_key_survives(self):
        """T3 / [D3] — a key read_config reads but write_config never writes.

        BORN-RED. `http_channel_enabled` gates the security warning at
        `manager_core.py:1793`; every write deletes it from the file.
        """
        payload = _run_child(
            """
            write_ini(
                "[default]\\nsecurity_level = normal\\n"
                "http_channel_enabled = true\\ndefault_cache_as_channel_url = true\\n"
            )
            boot()
            settings_change("db_mode", "local")
            cp = parse_disk()
            print(json.dumps({
                "http_channel_enabled": cp["default"].get("http_channel_enabled", "<ABSENT>"),
                "default_cache_as_channel_url": cp["default"].get(
                    "default_cache_as_channel_url", "<ABSENT>"),
                "raw": read_raw(),
            }))
            """
        )
        # NOT subTest: pytest-subtests reports a SUBFAIL while leaving the
        # NODE status PASSED, which would break the node-id RED contract this
        # WI pins — the GREEN step keys on these ids. An aggregate assertion
        # keeps the per-key detail in the message AND fails the node.
        lost = [
            key for key in ("http_channel_enabled", "default_cache_as_channel_url")
            if payload[key] == "<ABSENT>"
        ]
        self.assertEqual(
            [], lost,
            "T3 [D3]: %r were present in config.ini and are GONE after an "
            "unrelated settings change. read_config() returns 20 keys, "
            "write_config() persists 18 — these keys are read but never "
            "written, so every write deletes them. On-disk file:\n%s"
            % (lost, payload["raw"]),
        )

    def test_t4_non_default_section_survives(self):
        """T4 / [D3] — a non-`default` section survives a settings change.

        BORN-RED. `write_config()` builds a fresh ConfigParser, assigns only
        `config['default']`, and opens `'w'` (`manager_core.py:1715`).
        """
        payload = _run_child(
            """
            write_ini(
                "[default]\\nsecurity_level = normal\\n\\n"
                "[my_section]\\nmy_key = keepme\\n"
            )
            boot()
            settings_change("db_mode", "local")
            cp = parse_disk()
            print(json.dumps({
                "sections": cp.sections(),
                "my_key": cp["my_section"].get("my_key", "<ABSENT>")
                          if cp.has_section("my_section") else "<SECTION GONE>",
                "raw": read_raw(),
            }))
            """
        )
        self.assertIn(
            "my_section", payload["sections"],
            "T4 [D3]: the user's [my_section] was erased by an unrelated "
            "settings change — write_config() writes only config['default'] "
            "into a fresh parser with mode 'w'. Sections left on disk: %r\n%s"
            % (payload["sections"], payload["raw"]),
        )
        self.assertEqual("keepme", payload["my_key"])

    def test_t2_each_caller_key_persists(self):
        """T2 / [D2] — regression guard, expected born-GREEN.

        Each settings caller's OWN key must reach disk with its new value. This
        is what a fix must not break; it is exercised at the manager_core layer
        with the same mutation + `write_config()` the handlers make, because
        importing `manager_server` starts a network thread (`:2093`).
        """
        payload = _run_child(
            """
            import json as _j
            cases = %s
            out = {}
            for key, value in cases:
                write_ini("[default]\\nsecurity_level = normal\\n")
                boot()
                settings_change(key, value)
                out[key] = parse_disk()["default"].get(key, "<ABSENT>")
            print(_j.dumps(out))
            """ % json.dumps(_CALLER_KEYS)
        )
        # NOT subTest — same reason as T3: a regression guard whose node
        # reports PASSED while a subtest fails cannot signal the regression
        # it exists to catch.
        wrong = {
            key: payload[key] for key, value in _CALLER_KEYS
            if payload[key] != value
        }
        self.assertEqual(
            {}, wrong,
            "T2 [D2]: these caller keys did not persist their new value: %r — "
            "a fix must not regress the write path it is narrowing."
            % (wrong,),
        )

    def test_t5_bootstrap_writes_defaults(self):
        """T5 / S4 — regression guard, expected born-GREEN.

        The 7th `write_config()` caller (`manager_server.py:2098`) is guarded by
        `if not os.path.exists(...)` (`:2096`) and runs only when config.ini is
        absent, so it cannot clobber. Its bootstrap write must still produce a
        usable defaults file.
        """
        payload = _run_child(
            """
            if os.path.exists(CONFIG_PATH):
                os.remove(CONFIG_PATH)
            manager_core.get_config()      # the bootstrap pair at :2097-2098
            manager_core.write_config()
            cp = parse_disk()
            print(json.dumps({
                "exists": os.path.exists(CONFIG_PATH),
                "security_level": cp["default"].get("security_level", "<ABSENT>"),
                "allow_git_url_install": cp["default"].get(
                    "allow_git_url_install", "<ABSENT>"),
                "key_count": len(cp["default"]),
            }))
            """
        )
        self.assertTrue(payload["exists"], "T5: bootstrap did not create config.ini")
        self.assertEqual("normal", payload["security_level"])
        self.assertEqual(
            "False", payload["allow_git_url_install"],
            "T5: the install flag must bootstrap secure-by-default",
        )
        self.assertEqual(
            18, payload["key_count"],
            "T5: bootstrap wrote %d keys; write_config persists 18 "
            "(manager_core.py:1685-1704). A change to that count is a scope "
            "signal, not a nit." % payload["key_count"],
        )

    def test_t6_persisted_key_is_not_reclobbered(self):
        """T6 / [D1] — a key stays writable by hand AFTER the UI has set it.

        BORN-RED. `dirty_keys` is add-only: `write_config()` never removes the
        keys it just persisted. So a key the user once changed through the UI
        remains dirty for the life of the process, and the NEXT unrelated
        settings write overlays its stale cached value back over whatever the
        user has since edited on disk — the same clobber class the merge-on-
        write fix removes, just deferred by one settings change.

        This is the residual case: T1 covers a key the UI never touched, which
        is why T1 passes while this fails.
        """
        payload = _run_child(
            """
            write_ini("[default]\\nsecurity_level = normal\\ndb_mode = cache\\n")
            boot()
            # 1. the user changes db_mode through the UI -> persisted, and the
            #    key is now marked dirty
            settings_change("db_mode", "local")
            after_ui = parse_disk()["default"].get("db_mode", "<ABSENT>")

            # 2. the user hand-edits THAT SAME key on disk, touching nothing else
            raw = read_raw()
            assert "db_mode = local" in raw, raw
            with open(CONFIG_PATH, "w") as f:
                f.write(raw.replace("db_mode = local", "db_mode = remote"))

            # 3. one UNRELATED settings change
            settings_change("component_policy", "higher")

            cp = parse_disk()
            print(json.dumps({
                "after_ui": after_ui,
                "db_mode_final": cp["default"].get("db_mode", "<ABSENT>"),
                "component_policy": cp["default"].get("component_policy", "<ABSENT>"),
                "raw": read_raw(),
            }))
            """
        )
        # Guard against a vacuous pass: step 1 must really have persisted, and
        # step 3's own key must really have landed. Without these, a
        # write_config() that wrote nothing at all would satisfy the assertion
        # below for the wrong reason.
        self.assertEqual("local", payload["after_ui"], "T6 precondition: the UI change did not persist")
        self.assertEqual(
            "higher", payload["component_policy"],
            "T6 precondition: the unrelated settings change did not persist",
        )
        self.assertEqual(
            "remote", payload["db_mode_final"],
            "T6 [D1]: the hand-edited db_mode=remote was reverted to %r by an "
            "unrelated component_policy change. `db_mode` stayed in dirty_keys "
            "after write_config() persisted it, so the stale cached value was "
            "overlaid onto the re-read file. Any key the user has ever changed "
            "through the UI becomes permanently un-hand-editable for the life "
            "of the process. On-disk file:\\n%s"
            % (payload["db_mode_final"], payload["raw"]),
        )

    def test_t7_silent_read_failure_is_loud(self):
        """T7 / GOAL #53 [D1] — an UNREADABLE config.ini must not be wiped.

        BORN-RED. `configparser.ConfigParser.read()` opens each filename inside
        a `try/except OSError` and just SKIPS the ones it could not open, so a
        file that EXISTS but denies reads leaves `read()` returning normally
        with an EMPTY parser. `write_config()` then sees no `[default]`, takes
        the BOOTSTRAP branch, and rewrites the file from the default set —
        silently destroying the foreign key and the user's `[my_section]`,
        while the settings endpoint answers 200.

        The scenario is gm3-solver's measured boundary (GOAL #52 D2): reads
        denied but writes allowed. When BOTH are denied the write itself
        raises, so the failure is already loud and the file already survives;
        this node pins the asymmetric case that is not.
        """
        payload = _run_child(
            """
            import builtins

            write_ini(
                "[default]\\nsecurity_level = normal\\ndb_mode = cache\\n"
                "http_channel_enabled = true\\n\\n"
                "[my_section]\\nmy_key = keepme\\n"
            )
            boot()
            before = read_raw()

            # Deny READS of config.ini while leaving WRITES allowed — the
            # asymmetric permission shape gm3-solver reproduced live. Reads go
            # through builtins.open, which is what configparser.read() calls
            # and whose OSError it swallows.
            _real_open = builtins.open
            deny = {"on": False}

            def guarded_open(file, mode="r", *args, **kwargs):
                is_read = "r" in mode and "w" not in mode and "a" not in mode
                if deny["on"] and is_read and os.path.abspath(str(file)) == os.path.abspath(CONFIG_PATH):
                    raise PermissionError(13, "Permission denied", str(file))
                return _real_open(file, mode, *args, **kwargs)

            builtins.open = guarded_open
            raised = None
            try:
                deny["on"] = True
                settings_change("db_mode", "local")
            except Exception as e:
                raised = "%s: %s" % (type(e).__name__, e)
            finally:
                deny["on"] = False
                builtins.open = _real_open

            after = read_raw()
            cp = parse_disk()
            print(json.dumps({
                "raised": raised,
                "unchanged": before == after,
                "before": before,
                "after": after,
                "sections": cp.sections(),
                "http_channel_enabled": cp["default"].get(
                    "http_channel_enabled", "<ABSENT>")
                    if cp.has_section("default") else "<NO DEFAULT>",
            }))
            """
        )
        self.assertIsNotNone(
            payload["raised"],
            "T7 [D1]: write_config() returned SUCCESSFULLY on a config.ini it "
            "could not read. config.read() suppressed the PermissionError, so "
            "the empty parser routed the write into the bootstrap branch and "
            "the settings change reports success while destroying the file. "
            "Sections left on disk: %r\nOn-disk file after the write:\n%s"
            % (payload["sections"], payload["after"]),
        )
        self.assertTrue(
            payload["unchanged"],
            "T7 [D1]: config.ini was MODIFIED by a settings change that could "
            "not read it. A write that cannot see the current contents must "
            "leave them alone.\n--- before ---\n%s\n--- after ---\n%s"
            % (payload["before"], payload["after"]),
        )
        # Spell out the two losses the byte-comparison above rolls up, so a
        # failure names the user-visible damage and not just "bytes differ".
        self.assertIn("my_section", payload["sections"], "T7 [D1]: [my_section] was erased")
        self.assertEqual(
            "true", str(payload["http_channel_enabled"]).lower(),
            "T7 [D1]: http_channel_enabled was erased",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
