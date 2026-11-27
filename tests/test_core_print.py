"""`print` of `manager_core` writes its text as it is.

The cases take what binds the name `print` out of `glob/manager_core.py`, an
import or a function, and call it.
"""
import ast
import io

import pytest

from manager_test_utils import GLOB_DIR


def core_print():
    source = (GLOB_DIR / "manager_core.py").read_text(encoding="utf-8")
    nodes = [node for node in ast.parse(source).body
             if isinstance(node, (ast.Import, ast.ImportFrom)) and "rich" in ast.unparse(node)
             or isinstance(node, ast.FunctionDef) and node.name == "print"]
    namespace = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<manager_core print>", "exec"), namespace)
    return namespace["print"]


def printed(*objects, **options):
    out = io.StringIO()
    core_print()(*objects, file=out, **options)
    return out.getvalue()


@pytest.mark.parametrize("text", [
    "Install(git-clone) error: https://example.com/a[/b] / failed",
    "## ComfyUI-Manager: EXECUTE => ['python', '-m', 'pip', 'install', 'diffusers[torch]']",
    "skip black listed pip installation: 'requests[socks]'",
    "Uninstall: custom_nodes/pack:100:backup",
    "Download: git clone 'https://github.com/" + "a" * 120 + "'",
], ids=["closing tag", "list with an extra", "extra", "emoji code", "longer than 80 columns"])
def test_text_is_written_as_it_is(text):
    assert printed(text) == text + "\n"


def test_objects_are_written_as_their_text():
    assert printed("Update error:", ValueError("no section [/x]"), 3) == "Update error: no section [/x] 3\n"


def test_end_and_sep_are_kept():
    assert printed("a", "b", sep="-", end="") == "a-b"
