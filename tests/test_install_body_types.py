"""The two direct install routes answer 400 to a body they cannot use.

Each case runs the real handler of `glob/manager_server.py` with the install
allowed; `core` is replaced and records what it is asked to install.
"""
import ast
import asyncio
import json
import logging
from types import SimpleNamespace

import pytest
from aiohttp import web

from manager_test_utils import GLOB_DIR

GIT_URL, PIP = "install_custom_node_git_url", "install_custom_node_pip"


def post(name, body):
    """The status the handler answers for the raw request body, and what it asked `core` to install."""
    source = (GLOB_DIR / "manager_server.py").read_text(encoding="utf-8")
    handler = [node for node in ast.parse(source).body
               if isinstance(node, ast.AsyncFunctionDef) and node.name == name]
    assert len(handler) == 1
    asked = []

    async def gitclone_install(url):
        asked.append(url)
        return SimpleNamespace(action="install-git", result=True, target=url, msg="")

    namespace = {
        "web": web, "logging": logging, "_reject_non_json_content_type": lambda request: None,
        "routes": SimpleNamespace(post=lambda path: lambda handler: handler),
        "is_dedicated_install_allowed": lambda flag, listen: True,
        "args": SimpleNamespace(listen="127.0.0.1"),
        "core": SimpleNamespace(get_config=lambda: {"allow_git_url_install": True, "allow_pip_install": True},
                                gitclone_install=gitclone_install, pip_install=asked.append),
    }
    exec(compile(ast.Module(body=handler, type_ignores=[]), "<install handler>", "exec"), namespace)

    async def read():
        return json.loads(body)

    return asyncio.run(namespace[name](SimpleNamespace(json=read))).status, asked


NOT_AN_OBJECT = ["[]", '"text"', "7", "null"]
NOT_A_STRING = ["7", "null", '["a"]', '{"a": 1}']


def test_git_url_is_installed():
    assert post(GIT_URL, '{"url": "https://github.com/a/b"}') == (200, ["https://github.com/a/b"])


def test_packages_are_installed():
    assert post(PIP, '{"packages": "numpy scipy"}') == (200, [["numpy", "scipy"]])


@pytest.mark.parametrize("name", [GIT_URL, PIP])
@pytest.mark.parametrize("body", NOT_AN_OBJECT + ["{}", "not json"])
def test_body_without_the_field_is_answered_with_400(name, body):
    assert post(name, body) == (400, [])


@pytest.mark.parametrize("value", NOT_A_STRING)
def test_url_that_is_not_a_string_is_answered_with_400(value):
    assert post(GIT_URL, '{"url": %s}' % value) == (400, [])


@pytest.mark.parametrize("value", NOT_A_STRING)
def test_packages_that_are_not_a_string_are_answered_with_400(value):
    assert post(PIP, '{"packages": %s}' % value) == (400, [])
