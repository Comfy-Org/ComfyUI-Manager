"""Handler-gate tests for the dedicated install flags.

Three layers, each covering what the others can't:

  1. SCInstallGateMirrorTest — a slim mirror of the batch-install handler
     (`install_custom_node`, S-C) wired to the REAL extracted gate
     primitives. Covers the handler *composition* that the pure predicate
     test cannot: risky-level routing, the load-bearing public canary
     (the entry gate has no network term, so the deny must come from the
     predicate's loopback term), block-arm unconditionality, the
     security_level entry gate, and the CNR/middle false-pass guards.
  2. DenialConstantsTest — content of the flag denial constants and the
     `security_403_response` precedence, asserted directly (no server).
  3. BindingProofTest — AST proof that the REAL handlers (S-A/S-B/S-C) are
     wired to the predicate and that the old `is_allowed_security_level('high')`
     gate is gone from S-A/S-B (closes the mirror-vs-real gap).

The direct S-A/S-B allow/deny behavior is covered by the binding proof
(wiring) plus the real-server E2E suite (behavior); the mirror here
focuses on S-C, whose multi-arm branching is the genuine logic risk.

Harness: glob/manager_server.py is not importable under the runner
(`from comfy.cli_args import args`, PromptServer), so we AST-extract the
gate primitives and exec them into a stub namespace — `glob/` is never
added to sys.path (the dir name shadows stdlib glob).
"""
import ast
import asyncio
import contextlib
import inspect
import json
import logging
import unittest
from pathlib import Path
from typing import Any

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

REPO_ROOT = Path(__file__).resolve().parent.parent
MANAGER_SERVER_PATH = REPO_ROOT / "glob" / "manager_server.py"

_WANTED_FUNCS = {
    "is_loopback",
    "is_dedicated_install_allowed",
    "is_allowed_security_level",
    "security_403_response",
}
_WANTED_CONSTS = {
    "SECURITY_MESSAGE_MIDDLE_OR_BELOW",
    "SECURITY_MESSAGE_NORMAL_MINUS",
    "SECURITY_MESSAGE_GENERAL",
    "SECURITY_MESSAGE_FLAG_GIT_URL",
    "SECURITY_MESSAGE_FLAG_PIP",
}
_HANDLER_NAMES = {
    "install_custom_node_git_url",   # S-A
    "install_custom_node_pip",       # S-B
    "install_custom_node",           # S-C
}


class _MigrationStub:
    def __init__(self):
        self.system_user_api = True

    def has_system_user_api(self):
        return self.system_user_api


class _CoreStub:
    """Stand-in for `core` consulted by is_allowed_security_level."""

    def __init__(self):
        self.security_level = "normal"

    def get_config(self):
        return {"security_level": self.security_level}


def _load_surfaces():
    source = MANAGER_SERVER_PATH.read_text()
    tree = ast.parse(source)
    exec_nodes = []
    handler_nodes = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in _WANTED_FUNCS:
                node.decorator_list = []  # exec needs no aiohttp routing context
                exec_nodes.append(node)
            if node.name in _HANDLER_NAMES:
                handler_nodes[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in _WANTED_CONSTS:
                    exec_nodes.append(node)
    module = ast.Module(body=exec_nodes, type_ignores=[])
    ns: dict = {
        "web": web,
        "bool": bool,
        "manager_migration": _MigrationStub(),
        "core": _CoreStub(),
        "is_local_mode": True,
    }
    exec(compile(module, "manager_server_gate_surfaces", "exec"), ns)
    # Feature is implemented — these must resolve, else the extraction or
    # the production code regressed.
    for name in _WANTED_FUNCS | _WANTED_CONSTS:
        assert ns.get(name) is not None, "missing gate primitive: %s" % name
    for name in _HANDLER_NAMES:
        assert name in handler_nodes, "missing handler: %s" % name
    return ns, handler_nodes


NS, HANDLERS = _load_surfaces()
PREDICATE: Any = NS["is_dedicated_install_allowed"]
IS_LOOPBACK: Any = NS["is_loopback"]
IAS: Any = NS["is_allowed_security_level"]
SEC_403: Any = NS["security_403_response"]

CATALOG_URL = "https://github.com/catalog/listed-node"
UNKNOWN_URL = "https://github.com/x/not-in-catalog"
CATALOG_PIP = "torch"
UNKNOWN_PIP = "definitely-not-in-catalog-pkg"


def _body_unknown(files=None, pip=None):
    """version=='unknown' ingestion arm."""
    return {
        "version": "unknown",
        "selected_version": "unknown",
        "files": files or [UNKNOWN_URL],
        "pip": pip or [],
        "channel": "default",
        "mode": "cache",
        "ui_id": "test-row",
    }


def _body_cnr_latest():
    """non-nightly CNR arm — risky='low' set statically."""
    return {
        "version": "1.0.0",
        "selected_version": "latest",
        "id": "catalog-cnr-pack",
        "channel": "default",
        "mode": "cache",
        "ui_id": "test-row",
    }


class _TrackingFlags(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reads = []

    def __getitem__(self, key):
        self.reads.append(key)
        return super().__getitem__(key)


class GateEnv:
    """Injectable per-row environment for the mirror app."""

    def __init__(self, git=False, pip=False, listen="127.0.0.1", security_level="normal"):
        self.flags = _TrackingFlags(
            {"allow_git_url_install": git, "allow_pip_install": pip}
        )
        self.listen = listen
        self.security_level = security_level
        self.task_queue = []
        self.risky_calls = 0
        self.catalog_urls = {CATALOG_URL}
        self.catalog_pips = {CATALOG_PIP}

    def get_risky_level(self, files, pip_packages):
        """Mirror of get_risky_level: URL check precedes pip check."""
        self.risky_calls += 1
        for x in files or []:
            if x not in self.catalog_urls:
                return "high"
        for p in pip_packages or []:
            if p not in self.catalog_pips:
                return "block"
        return "middle"


_SC_DENY_TEXT = "A security error has occurred. Please check the terminal logs"


def _apply_env(env):
    """Retained gates use the is_local_mode snapshot + config stub."""
    NS["is_local_mode"] = IS_LOOPBACK(env.listen)
    NS["core"].security_level = env.security_level


def _make_sc_install(env):
    """Slim mirror of install_custom_node (S-C) in its post-change gate
    shape: security_level entry gate, then risky-level routing where the
    'high' (unknown-URL) arm goes through the dedicated predicate and the
    retained arms keep is_allowed_security_level."""

    async def sc_install(request):
        # ENTRY gate — UNCHANGED (security_level-governed)
        if not IAS("middle"):
            logging.error(NS["SECURITY_MESSAGE_MIDDLE_OR_BELOW"])
            return web.Response(status=403, text=_SC_DENY_TEXT)
        json_data = await request.json()
        risky_level = None
        git_url = None
        selected_version = json_data.get("selected_version")
        if json_data["version"] != "unknown" and selected_version != "unknown":
            if selected_version != "nightly":
                risky_level = "low"  # static — get_risky_level NOT called
            else:
                git_url = [json_data.get("repository")]
        else:
            git_url = json_data.get("files")
        if risky_level is None:
            risky_level = env.get_risky_level(git_url, json_data.get("pip", []))
        if risky_level == "high":
            # unknown-URL arm -> dedicated predicate (flag AND loopback)
            if not PREDICATE(env.flags["allow_git_url_install"], env.listen):
                logging.error(NS["SECURITY_MESSAGE_FLAG_GIT_URL"])
                return web.Response(status=404, text=_SC_DENY_TEXT)
        elif not IAS(risky_level):
            # 'block' is always False -> unconditional deny; 'middle'/'low'
            # retained UNCHANGED.
            logging.error(NS["SECURITY_MESSAGE_GENERAL"])
            return web.Response(status=404, text=_SC_DENY_TEXT)
        env.task_queue.append(("install", json_data.get("ui_id")))
        return web.Response(status=200)

    app = web.Application()
    app.router.add_post("/manager/queue/install", sc_install)
    return app


class _LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


@contextlib.contextmanager
def _capture_logs():
    handler = _LogCapture()
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        yield handler.messages
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)


class SCInstallGateMirrorTest(unittest.TestCase):
    """Batch-install (S-C) gate composition via a slim handler mirror."""

    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        self.loop.close()

    def _post(self, env, body):
        _apply_env(env)

        async def go():
            server = TestServer(_make_sc_install(env))
            client = TestClient(server)
            await client.start_server()
            try:
                resp = await client.post("/manager/queue/install", json=body)
                return resp.status, await resp.text()
            finally:
                await client.close()

        return self.loop.run_until_complete(go())

    def _installs(self, env):
        return [item for item in env.task_queue if item[0] == "install"]

    def _has(self, logs, const_name):
        return any(NS[const_name] in m for m in logs)

    def test_high_arm_allow(self):
        env = GateEnv(git=True, listen="127.0.0.1")
        with _capture_logs() as logs:
            status, _ = self._post(env, _body_unknown())
        self.assertEqual(status, 200)
        self.assertEqual(len(self._installs(env)), 1)
        self.assertFalse(self._has(logs, "SECURITY_MESSAGE_FLAG_GIT_URL"))

    def test_high_arm_flag_deny(self):
        env = GateEnv(git=False, listen="127.0.0.1")
        with _capture_logs() as logs:
            status, text = self._post(env, _body_unknown())
        self.assertEqual(status, 404)  # risky-position deny shape kept
        self.assertIn("A security error has occurred", text)
        self.assertEqual(self._installs(env), [])
        self.assertTrue(self._has(logs, "SECURITY_MESSAGE_FLAG_GIT_URL"))
        self.assertFalse(self._has(logs, "SECURITY_MESSAGE_NORMAL_MINUS"))

    def test_load_bearing_public_canary(self):
        """Entry gate passes on a public listener; the deny MUST come from
        the predicate's loopback term (the 'middle' set has no network
        term). 404 (risky deny), not 403 (entry deny)."""
        env = GateEnv(git=True, listen="0.0.0.0", security_level="normal")
        with _capture_logs() as logs:
            status, _ = self._post(env, _body_unknown())
        self.assertEqual(status, 404)
        self.assertEqual(self._installs(env), [])
        self.assertFalse(
            self._has(logs, "SECURITY_MESSAGE_MIDDLE_OR_BELOW"),
            "entry gate must PASS here — deny must come from the predicate",
        )
        self.assertTrue(self._has(logs, "SECURITY_MESSAGE_FLAG_GIT_URL"))

    def test_unknown_pip_block_unconditional(self):
        """Unknown-pip 'block' stays unconditional regardless of both flags
        (catalog URL + non-catalog pip; URL check precedes pip check)."""
        env = GateEnv(git=True, pip=True, listen="127.0.0.1")
        body = _body_unknown(files=[CATALOG_URL], pip=[UNKNOWN_PIP])
        with _capture_logs() as logs:
            status, _ = self._post(env, body)
        self.assertEqual(status, 404)
        self.assertEqual(self._installs(env), [])
        self.assertEqual(env.risky_calls, 1)
        self.assertTrue(self._has(logs, "SECURITY_MESSAGE_GENERAL"))
        self.assertEqual(env.flags.reads, [], "block arm must not consult the flags")

    def test_entry_gate_strong_denies_despite_flags(self):
        """The security_level entry gate stays in force; flags do NOT bypass it."""
        env = GateEnv(git=True, pip=True, listen="127.0.0.1", security_level="strong")
        with _capture_logs() as logs:
            status, _ = self._post(env, _body_unknown())
        self.assertEqual(status, 403)
        self.assertTrue(self._has(logs, "SECURITY_MESSAGE_MIDDLE_OR_BELOW"))
        self.assertEqual(self._installs(env), [])
        self.assertEqual(env.flags.reads, [], "entry deny must not consult the flags")

    def test_cnr_latest_arm_never_consults_flags(self):
        """non-nightly CNR sets risky='low' statically — get_risky_level and
        the flags are never consulted (false-pass guard)."""
        env = GateEnv(git=False, pip=False, listen="127.0.0.1")
        status, _ = self._post(env, _body_cnr_latest())
        self.assertEqual(status, 200)
        self.assertEqual(len(self._installs(env)), 1)
        self.assertEqual(env.risky_calls, 0)
        self.assertEqual(env.flags.reads, [], "flags must NOT be consulted on the CNR arm")

    def test_middle_arm_retained(self):
        """all-catalog body -> risky='middle'; consults security_level
        (UNCHANGED), not the flags."""
        env = GateEnv(git=False, pip=False, listen="127.0.0.1")
        body = _body_unknown(files=[CATALOG_URL], pip=[CATALOG_PIP])
        status, _ = self._post(env, body)
        self.assertEqual(status, 200)
        self.assertEqual(len(self._installs(env)), 1)
        self.assertEqual(env.risky_calls, 1)
        self.assertEqual(env.flags.reads, [], "flags must NOT be consulted on the middle arm")


class DenialConstantsTest(unittest.TestCase):
    """Denial-copy honesty + security_403_response precedence (no server)."""

    def _assert_honest_copy(self, const, flag_name):
        self.assertIn(flag_name, const, "constant must name the responsible flag")
        self.assertIn("config.ini", const, "constant must name config.ini")
        for cause_phrasing in (
            "is not allowed in this security_level",
            "set the security level",
            "a security_level of",
            "security level configuration",
        ):
            self.assertNotIn(cause_phrasing, const)
        self.assertNotEqual(const, NS["SECURITY_MESSAGE_NORMAL_MINUS"])
        self.assertNotEqual(const, NS["SECURITY_MESSAGE_GENERAL"])

    def test_flag_constants_content(self):
        self._assert_honest_copy(NS["SECURITY_MESSAGE_FLAG_GIT_URL"], "allow_git_url_install")
        self._assert_honest_copy(NS["SECURITY_MESSAGE_FLAG_PIP"], "allow_pip_install")

    def test_security_403_precedence(self):
        """outdated branch FIRST; flag_token names the flag; no-arg callers
        stay byte-identical."""
        self.assertIn("flag_token", inspect.signature(SEC_403).parameters)
        NS["manager_migration"].system_user_api = False
        try:
            resp = SEC_403(flag_token="allow_git_url_install")
            self.assertEqual(
                json.loads(resp.text), {"error": "comfyui_outdated"},
                "comfyui_outdated must take PRECEDENCE over flag_token",
            )
        finally:
            NS["manager_migration"].system_user_api = True
        resp = SEC_403(flag_token="allow_git_url_install")
        self.assertEqual(json.loads(resp.text), {"error": "allow_git_url_install"})
        resp = SEC_403()
        self.assertEqual(
            json.loads(resp.text), {"error": "security_level"},
            "no-arg callers must stay byte-identical",
        )


class BindingProofTest(unittest.TestCase):
    """AST proof that the REAL handlers are wired to the predicate (closes
    the mirror-vs-real gap)."""

    @staticmethod
    def _ias_literal_calls(node):
        out = []
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Name)
                and sub.func.id == "is_allowed_security_level"
                and sub.args
            ):
                arg = sub.args[0]
                out.append(arg.value if isinstance(arg, ast.Constant) else None)
        return out

    def test_handlers_bind_predicate(self):
        """S-A, S-B, S-C all gate via is_dedicated_install_allowed with the
        right flag + args.listen (request-time); S-C keeps the 'middle'
        entry gate and a variable-arg retained is_allowed_security_level path."""
        for name, flag in (
            ("install_custom_node_git_url", "allow_git_url_install"),
            ("install_custom_node_pip", "allow_pip_install"),
            ("install_custom_node", "allow_git_url_install"),
        ):
            with self.subTest(handler=name):
                src = ast.unparse(HANDLERS[name])
                self.assertIn("is_dedicated_install_allowed(", src)
                self.assertIn(flag, src)
                self.assertIn("args.listen", src)
        sc_literals = self._ias_literal_calls(HANDLERS["install_custom_node"])
        self.assertIn("middle", sc_literals, "entry gate must stay UNCHANGED")
        self.assertIn(None, sc_literals, "a variable-arg retained path must remain")

    def test_replace_no_high_literal_at_sa_sb(self):
        """REPLACE proof: no is_allowed_security_level('high') remains at
        S-A / S-B (the flag fully replaced the old security_level gate)."""
        for name in ("install_custom_node_git_url", "install_custom_node_pip"):
            with self.subTest(handler=name):
                self.assertNotIn(
                    "high", self._ias_literal_calls(HANDLERS[name]),
                    "%s still gates via is_allowed_security_level('high')" % name,
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
