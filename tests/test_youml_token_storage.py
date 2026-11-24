import ast

import pytest

from manager_test_utils import GLOB_DIR
from test_grid_highlight_escaping import browser  # noqa: F401 -- fixture
from test_share_dialog_matrix_password import EXTENSION, page  # noqa: F401 -- fixture


def test_the_server_has_no_route_for_the_token():
    source = (GLOB_DIR / "share_3rdparty.py").read_text(encoding="utf-8")
    paths = [decorator.args[0].value for node in ast.parse(source).body
             if isinstance(node, ast.AsyncFunctionDef) for decorator in node.decorator_list]

    assert "/manager/share" in paths
    assert [path for path in paths if "youml" in path] == []


def open_dialog(page, stored):  # noqa: F811
    page.evaluate("""async ({stored, module}) => {
        window.requested = [];
        localStorage.clear();
        if(stored !== null) localStorage.setItem('youml_token', stored);
        const { YouMLShareDialog } = await import(module);
        window.dialog = new YouMLShareDialog();
        await window.dialog.show([], []);
    }""", {"stored": stored, "module": EXTENSION + "comfyui-share-youml.js"})


@pytest.mark.parametrize("stored, shown", [(None, ""), ("", ""), ("the token", "the token")],
                         ids=["nothing stored", "an empty token", "a token"])
def test_the_dialog_opens_with_the_stored_token(page, stored, shown):  # noqa: F811
    open_dialog(page, stored)

    assert page.evaluate("dialog.apiTokenInput.value") == shown
    assert page.evaluate("window.requested") == []
    assert page.errors == []


def test_sharing_stores_the_token_in_the_browser(page):  # noqa: F811
    open_dialog(page, "an old token")

    page.evaluate("""async () => {
        dialog.apiTokenInput.value = 'a new token';
        await dialog.handleShareButtonClick();
    }""")

    assert page.evaluate("localStorage.getItem('youml_token')") == "a new token"
    assert [request for request in page.evaluate("window.requested") if "youml" in request["path"]] == []
