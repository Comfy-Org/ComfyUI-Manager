"""Structural (grep/AST) guards for the dedicated install flags.

Cheap source-level guards that complement the behavioral tests:

  - Frontend 403 copy: both install surfaces in js/common.js name their
    responsible flag, and the generic fallback copy stays unchanged.
  - No new HTTP install surface is added.
  - cm-cli stays an ungated local operator tool.
  - The migration module never references the flags (no auto-seed —
    explicit opt-in only).

Harness: read/grep + AST over glob/*.py, cm-cli.py and js/*.js. No
imports of `glob/` modules (the dir name shadows stdlib glob).
"""
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANAGER_SERVER_PATH = REPO_ROOT / "glob" / "manager_server.py"
MANAGER_MIGRATION_PATH = REPO_ROOT / "glob" / "manager_migration.py"
CM_CLI_PATH = REPO_ROOT / "cm-cli.py"
JS_COMMON_PATH = REPO_ROOT / "js" / "common.js"

GENERIC_403_COPY = "This action is not allowed with this security level configuration."
FLAG_TOKENS = ("allow_git_url_install", "allow_pip_install")


def _js_function_block(source, func_name):
    """Slice an `export async function <name>` block (up to the next
    export or EOF)."""
    start = source.find("export async function %s" % func_name)
    if start < 0:
        raise AssertionError("function %s not found in js source" % func_name)
    next_export = source.find("export ", start + 1)
    return source[start: next_export if next_export > 0 else len(source)]


def _handle403_call_args(source):
    """All handle403Response(...) CALL argument strings (def/import lines
    excluded)."""
    calls = []
    for match in re.finditer(r"handle403Response\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)", source):
        line_start = source.rfind("\n", 0, match.start()) + 1
        line = source[line_start: source.find("\n", match.start())]
        if "function handle403Response" in line or line.lstrip().startswith("import"):
            continue
        calls.append(match.group(1).strip())
    return calls


class JsCopyStructuralTest(unittest.TestCase):
    """Frontend honest-copy contract."""

    @classmethod
    def setUpClass(cls):
        cls.common_src = JS_COMMON_PATH.read_text()

    def test_surface_messages_name_their_flag(self):
        """Both install 403 branches pass a flag-naming defaultMessage."""
        for func, flag in (
            ("install_via_git_url", "allow_git_url_install"),
            ("install_pip", "allow_pip_install"),
        ):
            with self.subTest(func=func):
                block = _js_function_block(self.common_src, func)
                two_arg_calls = [a for a in _handle403_call_args(block) if "," in a]
                self.assertTrue(
                    two_arg_calls,
                    "%s must call handle403Response with a defaultMessage" % func,
                )
                self.assertIn(flag, block)
                self.assertIn("config.ini", block)

    def test_generic_fallback_and_frozen_callers_unchanged(self):
        """The generic fallback copy stays (exactly its two occurrences in
        handle403Response), and no other handle403Response caller across
        js/ gains a defaultMessage."""
        self.assertEqual(self.common_src.count(GENERIC_403_COPY), 2)
        surface_blocks = "".join(
            _js_function_block(self.common_src, name)
            for name in ("install_pip", "install_via_git_url")
        )
        allowed_two_arg = {a for a in _handle403_call_args(surface_blocks) if "," in a}
        for js_file in sorted((REPO_ROOT / "js").glob("*.js")):
            source = js_file.read_text()
            for args in _handle403_call_args(source):
                if "," in args:
                    self.assertIn(
                        args, allowed_two_arg,
                        "frozen handle403Response caller in %s gained a "
                        "defaultMessage: handle403Response(%s)" % (js_file.name, args),
                    )


class StructuralSecurityGuardsTest(unittest.TestCase):
    """Source-level guards against scope bleed."""

    def test_no_new_install_route_surface(self):
        """No new HTTP surface for git-URL/pip install."""
        source = MANAGER_SERVER_PATH.read_text()
        routes = set(re.findall(r"@routes\.post\(\"([^\"]+)\"\)", source))
        expected_surfaces = {
            "/customnode/install/git_url",
            "/customnode/install/pip",
            "/manager/queue/install",
            "/manager/queue/reinstall",
        }
        self.assertTrue(expected_surfaces.issubset(routes))
        install_like = {r for r in routes if "install" in r}
        self.assertEqual(
            install_like,
            expected_surfaces
            | {"/manager/queue/uninstall", "/manager/queue/install_model"},
            "install-like route set drifted — no new install surface allowed",
        )

    def test_cm_cli_ungated(self):
        """cm-cli stays a local operator tool — no gate, no flag lookup."""
        source = CM_CLI_PATH.read_text()
        for token in FLAG_TOKENS + ("is_allowed_security_level", "is_dedicated_install_allowed"):
            self.assertNotIn(token, source, "cm-cli.py must stay ungated")

    def test_no_autoseed_in_migration(self):
        """The migration module never references the flags (explicit
        opt-in only — no auto-seed from security_level)."""
        source = MANAGER_MIGRATION_PATH.read_text()
        for token in FLAG_TOKENS:
            self.assertNotIn(
                token, source,
                "manager_migration.py must not seed/translate the new flags",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
