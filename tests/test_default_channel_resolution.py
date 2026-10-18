"""`get_risky_level` must not hardcode the upstream data channel.

`glob/manager_server.py:get_risky_level` fetches the `default` channel's
`custom-node-list.json` to classify a node pack as high/middle/block. It
used to pass the literal URL
`https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main`, so the
request ignored `channels.list` / `config.ini` entirely: a user behind a
mirror or proxy (mirror-prefixed channel entries, custom fork, offline
network) still hit the upstream host for every risk check, and on failure
silently lost the `default` half of the data set.

`glob/manager_core.py:get_default_channel_url()` now resolves that URL:

  1. the `default` entry of `channels.list`
  2. `config.ini` `channel_url` (the channel used when a request names none)
  3. `DEFAULT_CHANNEL` (upstream - the legacy hardcoded value)

Harness: neither `glob/manager_core.py` nor `glob/manager_server.py` is
importable under the test runner (`import git` / `from comfy.cli_args
import args`, and the dir name shadows the stdlib `glob`), so - following
the tests/test_install_flag_predicate.py precedent - the wanted pure def
is AST-extracted and executed in isolation with stubbed collaborators
(`get_channel_dict` / `get_config`); `glob/` is never added to sys.path.
The wiring guards pin the exact call shape via AST.
"""
import ast
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
MANAGER_CORE_PATH = REPO_ROOT / "glob" / "manager_core.py"
MANAGER_SERVER_PATH = REPO_ROOT / "glob" / "manager_server.py"

UPSTREAM = "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main"
MIRROR = "https://mirror.example.com/" + UPSTREAM
FORK = "https://raw.githubusercontent.com/some-fork/ComfyUI-Manager/main"

_RESOLVER_DEF = None


def _resolver_node():
    """AST node of `get_default_channel_url` from manager_core.py."""
    global _RESOLVER_DEF
    if _RESOLVER_DEF is None:
        tree = ast.parse(MANAGER_CORE_PATH.read_text())
        node = next(
            (n for n in tree.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
             and n.name == "get_default_channel_url"),
            None,
        )
        if node is None:
            raise AssertionError("get_default_channel_url not found in manager_core.py")
        _RESOLVER_DEF = node
    return _RESOLVER_DEF


class ChannelListStub:
    """Mimics `get_channel_dict()`: `error` = unreadable channels.list."""

    def __init__(self, mapping=None, error=None):
        self.mapping = mapping if mapping is not None else {}
        self.error = error


def _make_resolver(channels: ChannelListStub, config_channel_url: Any = None,
                   http_channel_enabled: bool = False):
    """Exec only `get_default_channel_url` with stubbed collaborators."""
    if channels.error is not None:
        def get_channel_dict():
            raise channels.error
    else:
        def get_channel_dict():
            return dict(channels.mapping)

    ns: dict = {
        "DEFAULT_CHANNEL": UPSTREAM,
        "get_channel_dict": get_channel_dict,
        "get_config": lambda: {
            "channel_url": config_channel_url,
            "http_channel_enabled": http_channel_enabled,
        },
    }
    module = ast.Module(body=[_resolver_node()], type_ignores=[])
    exec(compile(module, "manager_core_resolver", "exec"), ns)
    return ns["get_default_channel_url"]


class DefaultChannelResolutionTest(unittest.TestCase):
    """Resolution order: channels.list `default` -> config `channel_url` -> upstream."""

    def test_mirror_prefixed_default_is_used_verbatim(self):
        resolve = _make_resolver(ChannelListStub({"default": MIRROR, "tutorial": UPSTREAM + "/node_db/tutorial"}))
        self.assertEqual(resolve(), MIRROR)

    def test_custom_fork_default_replaces_upstream(self):
        resolve = _make_resolver(ChannelListStub({"default": FORK}))
        self.assertEqual(resolve(), FORK)

    def test_trailing_slash_is_trimmed(self):
        """get_data_by_mode appends '/<filename>'; never emit '//'."""
        resolve = _make_resolver(ChannelListStub({"default": MIRROR + "/"}))
        self.assertEqual(resolve(), MIRROR)

    def test_missing_default_falls_back_to_config_channel_url(self):
        resolve = _make_resolver(ChannelListStub({"tutorial": UPSTREAM + "/node_db/tutorial"}), MIRROR)
        self.assertEqual(resolve(), MIRROR)

    def test_missing_default_and_config_set_falls_back_to_upstream(self):
        resolve = _make_resolver(ChannelListStub({"tutorial": UPSTREAM + "/node_db/tutorial"}), UPSTREAM)
        self.assertEqual(resolve(), UPSTREAM)

    def test_no_default_and_no_config_channel_url_falls_back_to_upstream(self):
        resolve = _make_resolver(ChannelListStub({}), None)
        self.assertEqual(resolve(), UPSTREAM)

    def test_empty_config_channel_url_falls_back_to_upstream(self):
        resolve = _make_resolver(ChannelListStub({}), "")
        self.assertEqual(resolve(), UPSTREAM)

    def test_unreadable_channels_list_does_not_raise(self):
        """A broken channels.list must degrade, not break the install path."""
        resolve = _make_resolver(ChannelListStub(error=OSError("permission denied")), MIRROR)
        self.assertEqual(resolve(), MIRROR)

    def test_upstream_default_round_trips_unchanged(self):
        """channels.list still pointing at upstream resolves to upstream."""
        resolve = _make_resolver(ChannelListStub({"default": UPSTREAM}))
        self.assertEqual(resolve(), UPSTREAM)


class PlainHttpWarningTest(unittest.TestCase):
    """Plain-HTTP channels follow the existing `normalize_channel` policy:
    ignored unless `http_channel_enabled` is true; a warning is logged when
    they are used. The resolver never rewrites the user's URL itself."""

    def _resolve_capturing_output(self, channels, config_channel_url=None,
                                  http_channel_enabled=False):
        import contextlib
        import io
        resolve = _make_resolver(channels, config_channel_url,
                                 http_channel_enabled=http_channel_enabled)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            url = resolve()
        return url, buf.getvalue()

    def test_http_channel_ignored_when_http_disabled(self):
        """Mirrors normalize_channel: no http:// unless http_channel_enabled."""
        http_url = "http://lan-mirror.example.com/ComfyUI-Manager/main"
        url, output = self._resolve_capturing_output(ChannelListStub({"default": http_url}))
        self.assertEqual(url, UPSTREAM)
        self.assertIn("Ignoring plain-HTTP default channel", output)
        self.assertIn(http_url, output)

    def test_http_channel_used_with_warning_when_http_enabled(self):
        http_url = "http://lan-mirror.example.com/ComfyUI-Manager/main"
        url, output = self._resolve_capturing_output(
            ChannelListStub({"default": http_url}), http_channel_enabled=True)
        self.assertEqual(url, http_url)
        self.assertIn("unencrypted HTTP", output)
        self.assertIn(http_url, output)

    def test_mixed_case_http_scheme_is_gated_too(self):
        """`HtTp://` must hit the same guard as `http://`, otherwise it
        slips past http_channel_enabled and derails into local fallback."""
        weird_url = "HtTp://lan-mirror.example.com/ComfyUI-Manager/main"
        url, output = self._resolve_capturing_output(ChannelListStub({"default": weird_url}))
        self.assertEqual(url, UPSTREAM)
        self.assertIn("Ignoring plain-HTTP default channel", output)

        url, output = self._resolve_capturing_output(
            ChannelListStub({"default": weird_url}), http_channel_enabled=True)
        self.assertEqual(url, weird_url)
        self.assertIn("unencrypted HTTP", output)

    def test_https_channel_does_not_warn(self):
        url, output = self._resolve_capturing_output(ChannelListStub({"default": MIRROR}))
        self.assertEqual(url, MIRROR)
        self.assertNotIn("unencrypted HTTP", output)
        self.assertNotIn("Ignoring plain-HTTP", output)


class RiskyLevelWiringTest(unittest.TestCase):
    """Static guard: the risk check consumes the resolver, not a literal."""

    @classmethod
    def setUpClass(cls):
        cls.source = MANAGER_SERVER_PATH.read_text()
        cls.risky_level_src = None
        for node in ast.walk(ast.parse(cls.source)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "get_risky_level":
                cls.risky_level_src = ast.get_source_segment(cls.source, node)
                break

    def test_risky_level_calls_the_resolver(self):
        self.assertIsNotNone(self.risky_level_src, "get_risky_level not found in manager_server.py")
        self.assertIn("core.get_default_channel_url()", self.risky_level_src)

    def test_risky_level_has_no_hardcoded_channel(self):
        self.assertIsNotNone(self.risky_level_src, "get_risky_level not found in manager_server.py")
        self.assertNotIn("raw.githubusercontent.com", self.risky_level_src)

    def test_manager_server_has_no_hardcoded_data_channel(self):
        self.assertNotIn("raw.githubusercontent.com", self.source)


class ResolverIsExportedTest(unittest.TestCase):
    """`manager_core.get_default_channel_url` exists at module scope."""

    def test_function_exists(self):
        tree = ast.parse(MANAGER_CORE_PATH.read_text())
        names = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertIn("get_default_channel_url", names)


if __name__ == "__main__":
    unittest.main()
