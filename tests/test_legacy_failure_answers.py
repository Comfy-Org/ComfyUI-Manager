"""The legacy server answers a failed ComfyUI version request, and a batch queues a ComfyUI update.

Each case runs the real handlers of `legacy/manager_server.py`; what they call
in `core` is replaced, so nothing is fetched, switched or updated.
"""
import ast
import asyncio
import importlib.util
import json
import logging
import sys
import threading
from types import SimpleNamespace

import pytest
from aiohttp import web

from legacy_html_testutil import PACKAGE, load_functions

SERVER = PACKAGE / "legacy/manager_server.py"
SECURITY = PACKAGE / "common/manager_security.py"
NAMES = {"comfyui_versions", "comfyui_switch_version", "queue_batch", "update_comfyui", "_update_comfyui"}
STABLE = ("update-comfyui", ("comfyui", True))
NIGHTLY = ("update-comfyui", ("comfyui", False))
POLICIES = [("stable-comfyui", STABLE), ("stable", STABLE), ("nightly-comfyui", NIGHTLY), ("nightly", NIGHTLY)]


def manager_security():
    spec = importlib.util.spec_from_file_location("_manager_security", SECURITY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fail(*args):
    raise RuntimeError("not a git repository")


def server(policy="stable-comfyui", **core):
    """The handlers under test and the list they queue to."""
    defined = {node.name for node in ast.parse(SERVER.read_text(encoding="utf-8")).body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    queued = []
    route = lambda path: lambda handler: handler  # noqa: E731
    handlers = load_functions(SERVER, NAMES & defined, {
        "web": web, "logging": logging, "json": json, "sys": sys,
        "routes": SimpleNamespace(get=route, post=route),
        "core": SimpleNamespace(get_config=lambda: {"update_policy": policy}, **core),
        "manager_security": manager_security(),
        "is_allowed_security_level": lambda level: True, "SECURITY_MESSAGE_HIGH_P": "",
        "temp_queue_batch": queued, "task_worker_lock": threading.Lock(),
        "finalize_temp_queue_batch": lambda batch, failed: None, "_queue_start": lambda: None,
    })
    return handlers, queued


def request(body=None, content_type="application/json"):
    async def read():
        return body

    return SimpleNamespace(json=read, content_type=content_type)


def answer(handler, *args):
    response = asyncio.run(handler(*args))
    return response.status, response.text


def test_version_list_that_cannot_be_read_is_answered_with_400(caplog):
    handlers, _ = server(get_comfyui_versions=fail)
    assert answer(handlers["comfyui_versions"], request()) == (400, None)
    assert "ComfyUI update fail: not a git repository" in caplog.text


def test_version_list_is_answered_with_the_versions():
    handlers, _ = server(get_comfyui_versions=lambda: (["nightly", "v0.3.1"], "v0.3.1", "v0.3.1"))
    assert answer(handlers["comfyui_versions"], request()) == (
        200, '{"versions": ["nightly", "v0.3.1"], "current": "v0.3.1"}')


def test_version_switch_that_fails_is_answered_with_400(caplog):
    handlers, _ = server(switch_comfyui=fail)
    assert answer(handlers["comfyui_switch_version"], request({"ver": "v0.3.0"})) == (400, None)
    assert "ComfyUI update fail: not a git repository" in caplog.text


def test_version_switch_is_passed_on_and_answered_with_200():
    switched = []
    handlers, _ = server(switch_comfyui=switched.append)
    assert answer(handlers["comfyui_switch_version"], request({"ver": "v0.3.0"})) == (200, None)
    assert switched == ["v0.3.0"]


@pytest.mark.parametrize("policy, update", POLICIES)
def test_batch_queues_the_comfyui_update_of_the_policy(policy, update):
    handlers, queued = server(policy)
    batch = {"batch_id": "b", "update_comfyui": True}
    assert answer(handlers["queue_batch"], request(batch)) == (200, '{"failed": []}')
    assert queued == [update]


@pytest.mark.parametrize("batch", [{"batch_id": "b"}, {"batch_id": "b", "update_comfyui": False}],
                         ids=["no update_comfyui", "update_comfyui false"])
def test_batch_that_asks_for_no_comfyui_update_queues_none(batch):
    handlers, queued = server()
    assert answer(handlers["queue_batch"], request(batch)) == (200, '{"failed": []}')
    assert queued == []


@pytest.mark.parametrize("policy, update", POLICIES)
def test_update_route_queues_the_comfyui_update_of_the_policy(policy, update):
    handlers, queued = server(policy)
    assert answer(handlers["update_comfyui"], request())[0] == 200
    assert queued == [update]


def test_update_route_still_refuses_a_form_post():
    handlers, queued = server()
    assert answer(handlers["update_comfyui"], request(content_type="application/x-www-form-urlencoded"))[0] == 400
    assert queued == []
