"""`comfyui_versions` answers 400 when the versions of ComfyUI cannot be read.

Each case runs the real handler of `glob/manager_server.py`; `core` is replaced.
"""
import ast
import asyncio
import logging
import sys
from types import SimpleNamespace

from aiohttp import web

from manager_test_utils import GLOB_DIR


def fail():
    raise RuntimeError("not a git repository")


def answer(get_comfyui_versions):
    """The status and text `comfyui_versions` answers."""
    source = (GLOB_DIR / "manager_server.py").read_text(encoding="utf-8")
    handler = [node for node in ast.parse(source).body
               if isinstance(node, ast.AsyncFunctionDef) and node.name == "comfyui_versions"]
    assert len(handler) == 1
    namespace = {"web": web, "logging": logging, "sys": sys,
                 "core": SimpleNamespace(get_comfyui_versions=get_comfyui_versions),
                 "routes": SimpleNamespace(get=lambda path: lambda handler: handler)}
    exec(compile(ast.Module(body=handler, type_ignores=[]), "<comfyui_versions>", "exec"), namespace)
    response = asyncio.run(namespace["comfyui_versions"](None))
    return response.status, response.text


def test_version_list_that_cannot_be_read_is_answered_with_400(caplog):
    assert answer(fail) == (400, None)
    assert "ComfyUI update fail: not a git repository" in caplog.text


def test_version_list_is_answered_with_the_versions():
    assert answer(lambda: (["nightly", "v0.3.1"], "v0.3.1", "v0.3.1")) == (
        200, '{"versions": ["nightly", "v0.3.1"], "current": "v0.3.1"}')
