"""`print` of the two `manager_core` modules writes its text as it is.

The cases take what binds the name `print` out of a `manager_core.py`, an
import or a function, and call it.
"""
import ast
import io

import pytest

from legacy_html_testutil import PACKAGE


@pytest.fixture(params=["glob", "legacy"])
def printed(request):
    source = (PACKAGE / request.param / "manager_core.py").read_text(encoding="utf-8")
    nodes = [node for node in ast.parse(source).body
             if isinstance(node, (ast.Import, ast.ImportFrom)) and "rich" in ast.unparse(node)
             or isinstance(node, ast.FunctionDef) and node.name == "print"]
    namespace = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<manager_core print>", "exec"), namespace)

    def printed(*objects, **options):
        out = io.StringIO()
        namespace["print"](*objects, file=out, **options)
        return out.getvalue()

    return printed


@pytest.mark.parametrize("text", [
    "Install(git-clone) error: https://example.com/a[/b] / failed",
    "## ComfyUI-Manager: EXECUTE => ['python', '-m', 'pip', 'install', 'diffusers[torch]']",
    "skip black listed pip installation: 'requests[socks]'",
    "Uninstall: custom_nodes/pack:100:backup",
    "Download: git clone 'https://github.com/" + "a" * 120 + "'",
], ids=["closing tag", "list with an extra", "extra", "emoji code", "longer than 80 columns"])
def test_text_is_written_as_it_is(printed, text):
    assert printed(text) == text + "\n"


def test_objects_are_written_as_their_text(printed):
    assert printed("Update error:", ValueError("no section [/x]"), 3) == "Update error: no section [/x] 3\n"


def test_end_and_sep_are_kept(printed):
    assert printed("a", "b", sep="-", end="") == "a-b"
