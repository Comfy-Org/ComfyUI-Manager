"""Unit tests for the dedicated-install-flag predicate.

Covers `is_dedicated_install_allowed(flag_value, listen_address)` in
glob/manager_server.py:

  - Truth table: allowed iff flag is true AND the listener is loopback.
  - REPLACE-by-construction: the 2-arg signature has no security_level /
    network_mode parameter and the body references no config machinery,
    so security_level cannot influence the outcome in either direction.
  - Cross-flag isolation: a single flag_value input cannot consult the
    other flag.
  - Request-time evaluation: the body must not read the import-time
    `is_local_mode` snapshot (callers pass args.listen per request).

Harness: glob/manager_server.py is not importable under the test runner
(`from comfy.cli_args import args`, PromptServer), so we AST-parse the
file and exec only the wanted pure defs — `glob/` is never added to
sys.path (the dir name shadows the stdlib `glob`).
"""
import ast
import inspect
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
MANAGER_SERVER_PATH = REPO_ROOT / "glob" / "manager_server.py"

_WANTED = {"is_loopback", "is_dedicated_install_allowed"}


def _load_predicates():
    """Parse manager_server.py; exec only the wanted pure function defs."""
    source = MANAGER_SERVER_PATH.read_text()
    tree = ast.parse(source)
    nodes = []
    node_by_name = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in _WANTED:
            nodes.append(node)
            node_by_name[node.name] = node
    missing = _WANTED - node_by_name.keys()
    assert not missing, f"expected pure defs missing from manager_server.py: {missing}"
    module = ast.Module(body=nodes, type_ignores=[])
    ns: dict = {"bool": bool}
    exec(compile(module, "manager_server_predicates", "exec"), ns)
    return ns, node_by_name


_NS, _NODES = _load_predicates()
IS_LOOPBACK: Any = _NS["is_loopback"]
PREDICATE: Any = _NS["is_dedicated_install_allowed"]
PREDICATE_NODE = _NODES["is_dedicated_install_allowed"]


class IsLoopbackBehaviorTest(unittest.TestCase):
    """Pins the loopback term the predicate composes."""

    def test_ipv4_loopback(self):
        self.assertTrue(IS_LOOPBACK("127.0.0.1"))

    def test_public_address(self):
        self.assertFalse(IS_LOOPBACK("0.0.0.0"))

    def test_ipv6_loopback(self):
        self.assertTrue(IS_LOOPBACK("::1"))

    def test_invalid_address_reads_false(self):
        # Non-IP strings deny-by-default (ValueError path).
        self.assertFalse(IS_LOOPBACK("localhost"))
        self.assertFalse(IS_LOOPBACK(""))


class DedicatedInstallPredicateTest(unittest.TestCase):
    """P-direct truth table + REPLACE-by-construction."""

    def test_truth_table(self):
        """allowed iff flag AND loopback."""
        cases = [
            # (flag_value, listen_address, expected)
            (True, "127.0.0.1", True),
            (False, "127.0.0.1", False),
            (True, "0.0.0.0", False),
            (False, "0.0.0.0", False),
            (True, "::1", True),
            (True, "not-an-ip", False),  # invalid listen -> deny
        ]
        for flag_value, listen, expected in cases:
            with self.subTest(flag=flag_value, listen=listen):
                result = PREDICATE(flag_value, listen)
                self.assertIsInstance(result, bool)
                self.assertEqual(result, expected)

    def test_falsy_flag_values_deny(self):
        """Secure-by-default: any falsy flag never allows."""
        for falsy in (False, None, 0, ""):
            with self.subTest(flag=falsy):
                self.assertFalse(PREDICATE(falsy, "127.0.0.1"))

    def test_signature_has_no_security_level(self):
        """Exactly (flag_value, listen_address) — no security_level term."""
        params = list(inspect.signature(PREDICATE).parameters)
        self.assertEqual(params, ["flag_value", "listen_address"])
        for name in params:
            self.assertNotIn("security", name)
            self.assertNotIn("network_mode", name)

    def test_body_free_of_config_machinery(self):
        """Body references no security_level plumbing, config reader, or the
        import-time `is_local_mode` snapshot (request-time evaluation)."""
        forbidden = {
            "is_allowed_security_level",
            "security_level",
            "get_config",
            "core",
            "is_local_mode",
            "network_mode",
            "args",
        }
        seen = set()
        for node in ast.walk(PREDICATE_NODE):
            if isinstance(node, ast.Name):
                seen.add(node.id)
            elif isinstance(node, ast.Attribute):
                seen.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                seen.add(node.value)
        self.assertEqual(
            seen & forbidden, set(),
            "predicate body must stay config-import-free",
        )

    def test_cross_flag_isolation_by_construction(self):
        """A single flag_value input cannot consult the other flag."""
        seen_strings = {
            node.value
            for node in ast.walk(PREDICATE_NODE)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        self.assertNotIn("allow_git_url_install", seen_strings)
        self.assertNotIn("allow_pip_install", seen_strings)
        self.assertTrue(PREDICATE(True, "127.0.0.1"))
        self.assertFalse(PREDICATE(False, "127.0.0.1"))

    def test_purity_deterministic(self):
        """Pure predicate — repeat calls identical."""
        for _ in range(3):
            self.assertTrue(PREDICATE(True, "127.0.0.1"))
            self.assertFalse(PREDICATE(True, "0.0.0.0"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
