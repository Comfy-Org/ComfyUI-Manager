"""The update route queues the ComfyUI update that `update_policy` names.

Each case runs the real `update_comfyui` of `glob/manager_server.py` with the
real request models; `core` and the task queue are replaced, so nothing is
updated.
"""
import asyncio
import importlib.util
import sys
from types import SimpleNamespace

import pytest
from aiohttp import web
from pydantic import ValidationError

from legacy_html_testutil import PACKAGE, load_functions

SERVER = PACKAGE / "glob/manager_server.py"


def module(path):
    spec = importlib.util.spec_from_file_location("_" + path.stem, path)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded  # pydantic resolves the models' annotations through it
    spec.loader.exec_module(loaded)
    return loaded


def update(policy, **query):
    """The status the route answers, and whether the update it queued is the stable one."""
    models = module(PACKAGE / "data_models/generated_models.py")
    queued = []
    route = lambda path: lambda handler: handler  # noqa: E731
    handler = load_functions(SERVER, {"update_comfyui"}, {
        "web": web, "ValidationError": ValidationError,
        "routes": SimpleNamespace(post=route),
        "security_utils": module(PACKAGE / "common/manager_security.py"),
        "core": SimpleNamespace(get_config=lambda: {"update_policy": policy}),
        "UpdateComfyUIQueryParams": models.UpdateComfyUIQueryParams,
        "UpdateComfyUIParams": models.UpdateComfyUIParams,
        "QueueTaskItem": models.QueueTaskItem, "OperationType": models.OperationType,
        "task_queue": SimpleNamespace(put=queued.append),
    })["update_comfyui"]
    request = SimpleNamespace(content_type="application/json", rel_url=SimpleNamespace(query=query))
    status = asyncio.run(handler(request)).status
    return status, [task.params.is_stable for task in queued]


WHO = {"client_id": "c", "ui_id": "u"}


@pytest.mark.parametrize("policy, stable", [("stable-comfyui", True), ("stable", True),
                                            ("nightly-comfyui", False), ("nightly", False)])
def test_request_without_stable_follows_the_policy(policy, stable):
    assert update(policy, **WHO) == (200, [stable])


@pytest.mark.parametrize("policy", ["stable-comfyui", "nightly-comfyui"])
@pytest.mark.parametrize("given, stable", [("true", True), ("false", False)])
@pytest.mark.parametrize("name", ["stable", "is_stable"])
def test_request_that_names_the_version_line_decides_itself(name, policy, given, stable):
    assert update(policy, **{name: given}, **WHO) == (200, [stable])


def test_stable_is_read_before_is_stable():
    assert update("stable-comfyui", stable="false", is_stable="true", **WHO) == (200, [False])


def test_request_without_a_client_is_refused():
    assert update("stable-comfyui", ui_id="u") == (400, [])
