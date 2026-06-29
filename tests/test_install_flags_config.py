"""Config-contract tests for the dedicated install flags.

Drives the real glob/manager_core config reader/writer through a
subprocess-isolated harness and pins: missing keys read False
(secure-by-default), only case-insensitive "true" is truthy, write
round-trips losslessly, edits need a restart (cached_config), the
exception-fallback path supplies False, no auto-migration seeds the
flags from a legacy security_level, and the get_bool missing->False
quirk the flags rely on stays frozen.

Harness: the child process injects a stub `folder_paths` (routing
import-time side effects into a tmpdir, and making has_system_user_api()
True so force_security_level_if_needed does not force 'strong'), prepends
`glob/` to ITS OWN sys.path (shadowing of stdlib `glob` confined to the
child), points manager_core.manager_config_path at a tmp config.ini,
resets cached_config, runs the scenario, and prints one JSON line for the
parent to assert.
"""
import json
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_CHILD_PREAMBLE = textwrap.dedent(
    """
    import sys, types, tempfile, os, json
    tmp = tempfile.mkdtemp(prefix="cm_flags_cfg_")
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

    def fresh_read():
        manager_core.cached_config = None
        return manager_core.get_config()

    def flag_view(cfg):
        return {{
            "git": cfg.get("allow_git_url_install", "<ABSENT>"),
            "pip": cfg.get("allow_pip_install", "<ABSENT>"),
        }}
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
            "config-harness child failed (rc=%d). stderr tail:\n%s"
            % (proc.returncode, "\n".join(proc.stderr.strip().splitlines()[-8:]))
        )
    lines = proc.stdout.strip().splitlines()
    if not lines:
        raise AssertionError(
            "config-harness child exited 0 but produced no stdout. stderr tail:\n%s"
            % "\n".join(proc.stderr.strip().splitlines()[-8:])
        )
    last_line = lines[-1]
    try:
        return json.loads(last_line)
    except json.JSONDecodeError as e:
        raise AssertionError(
            "config-harness child emitted a non-JSON last line: %r\nfull stdout:\n%s"
            % (last_line, proc.stdout)
        ) from e


class InstallFlagsConfigContractTest(unittest.TestCase):
    def test_sc17_missing_keys_read_false(self):
        """Both keys absent from config.ini -> both flags read False
        (secure-by-default)."""
        payload = _run_child(
            """
            write_ini("[default]\\nsecurity_level = normal\\n")
            print(json.dumps(flag_view(fresh_read())))
            """
        )
        self.assertIs(payload["git"], False)
        self.assertIs(payload["pip"], False)

    def test_sc18_malformed_and_case_matrix(self):
        """Only case-insensitive "true" is truthy; malformed -> False."""
        payload = _run_child(
            """
            out = {}
            for raw in ["1", "yes", "TRUE", "true ", "true"]:
                write_ini("[default]\\nallow_git_url_install = %s\\nallow_pip_install = %s\\n" % (raw, raw))
                cfg = fresh_read()
                out[raw] = flag_view(cfg)
            print(json.dumps(out))
            """
        )
        expected = {
            "1": False,      # malformed: numeric truthiness NOT honored
            "yes": False,    # malformed: yes/no NOT honored
            "TRUE": True,    # case-insensitive read (:1724)
            "true ": True,   # configparser strips surrounding whitespace
            "true": True,
        }
        for raw, want in expected.items():
            with self.subTest(value=raw):
                self.assertIs(payload[raw]["git"], want)
                self.assertIs(payload[raw]["pip"], want)

    def test_sc19_write_round_trip(self):
        """write_config persists str(bool); round-trip is lossless."""
        payload = _run_child(
            """
            write_ini("[default]\\nsecurity_level = normal\\n")
            cfg = fresh_read()
            cfg["allow_git_url_install"] = True
            cfg["allow_pip_install"] = False
            manager_core.write_config()
            raw = open(CONFIG_PATH).read()
            reread = flag_view(fresh_read())
            print(json.dumps({
                "raw_has_git_true": "allow_git_url_install = True" in raw,
                "raw_has_pip_false": "allow_pip_install = False" in raw,
                "reread": reread,
            }))
            """
        )
        self.assertTrue(
            payload["raw_has_git_true"],
            "write_config must persist allow_git_url_install = True in [default]",
        )
        self.assertTrue(
            payload["raw_has_pip_false"],
            "write_config must persist allow_pip_install = False in [default]",
        )
        self.assertIs(payload["reread"]["git"], True)
        self.assertIs(payload["reread"]["pip"], False)

    def test_sc20_restart_only_activation(self):
        """Editing config.ini without restart has NO effect (cache wins);
        a reset (== restart) picks up the change."""
        payload = _run_child(
            """
            write_ini("[default]\\nallow_git_url_install = false\\n")
            first = manager_core.get_config()  # populates cached_config
            before_edit = flag_view(first)
            write_ini("[default]\\nallow_git_url_install = true\\n")
            cached = flag_view(manager_core.get_config())   # NO reset: cache must win
            after_restart = flag_view(fresh_read())          # reset == restart
            print(json.dumps({
                "before_edit": before_edit,
                "cached_after_edit": cached,
                "after_restart": after_restart,
            }))
            """
        )
        self.assertIs(payload["before_edit"]["git"], False)
        self.assertIs(
            payload["cached_after_edit"]["git"],
            False,
            "cached_config must NOT hot-reload the edited flag",
        )
        self.assertIs(payload["after_restart"]["git"], True)

    def test_sc21_exception_fallback_supplies_false(self):
        """Corrupted config.ini -> exception-fallback dict supplies flags False."""
        payload = _run_child(
            """
            # No [default] section header -> read_config raises inside try,
            # lands in the exception-fallback dict.
            write_ini("allow_git_url_install = true\\ngarbage without section\\n")
            cfg = fresh_read()
            print(json.dumps({
                "flags": flag_view(cfg),
                "fallback_marker_file_logging": cfg.get("file_logging"),
            }))
            """
        )
        # file_logging True proves the FALLBACK dict was used (the parse
        # path would yield False for a missing file_logging key).
        self.assertIs(
            payload["fallback_marker_file_logging"],
            True,
            "corrupted ini must route through the exception-fallback dict",
        )
        self.assertIs(payload["flags"]["git"], False)
        self.assertIs(payload["flags"]["pip"], False)

    def test_sc28_no_auto_migration_from_weak(self):
        """Legacy `security_level=weak` does NOT seed the flags (no auto-migration)."""
        payload = _run_child(
            """
            write_ini("[default]\\nsecurity_level = weak\\n")
            cfg = fresh_read()
            print(json.dumps({
                "flags": flag_view(cfg),
                "security_level": cfg.get("security_level"),
            }))
            """
        )
        self.assertEqual(payload["security_level"], "weak")
        self.assertIs(payload["flags"]["git"], False, "no auto-seed from weak")
        self.assertIs(payload["flags"]["pip"], False, "no auto-seed from weak")

    def test_sc42_get_bool_quirk_guard(self):
        """get_bool ignores its default param: missing `file_logging` reads
        False despite a True default. The flags rely on this missing->False
        quirk; this guard pins it."""
        payload = _run_child(
            """
            write_ini("[default]\\nsecurity_level = normal\\n")
            cfg = fresh_read()
            print(json.dumps({"file_logging": cfg.get("file_logging", "<ABSENT>")}))
            """
        )
        self.assertIs(
            payload["file_logging"],
            False,
            "get_bool quirk changed: missing key no longer reads False — "
            "new flags rely on missing->False",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
