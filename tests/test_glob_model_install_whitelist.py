"""The glob server installs only models that are in the model list.

Each case hands a model to the real `do_install_model`, the worker step that
queue/install_model and queue/task both reach, with the real
`check_whitelist_for_model`. The downloaders are replaced by a recorder, so
nothing is fetched.
"""
import ast
import asyncio
import importlib.util
import logging
import sys
from types import SimpleNamespace

import pytest

from legacy_html_testutil import PACKAGE, load_functions

SAFETENSORS = {"name": "a", "type": "checkpoint", "base": "SDXL", "save_path": "checkpoints",
               "filename": "a.safetensors", "url": "https://huggingface.co/a/resolve/main/a.safetensors"}
PICKLE = {"name": "b", "type": "upscale", "base": "upscale", "save_path": "upscale_models",
          "filename": "b.pth", "url": "https://huggingface.co/b/resolve/main/b.pth"}
OTHER_URL = "http://other.example/x.bin"


def load_data_models(monkeypatch):
    spec = importlib.util.spec_from_file_location("_generated_models", PACKAGE / "data_models/generated_models.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def install(monkeypatch, item, channel_models, default_models, local_models=(), high_plus=False):
    """What the worker answers for `item`, and the downloads it started.

    The three arguments are the model lists of the configured channel, of the default
    channel, and of the local file; None stands for a list file without `models`.
    """
    models = load_data_models(monkeypatch)
    monkeypatch.setitem(sys.modules, "comfyui_manager.data_models", models)

    async def get_data_by_mode(mode, filename, channel_url=None):
        listed = {"cache": default_models if channel_url == "default" else channel_models, "local": local_models}[mode]
        return {} if listed is None else {"models": list(listed)}

    downloads = []
    core = SimpleNamespace(get_data_by_mode=get_data_by_mode, get_config=lambda: {"model_download_by_agent": True})
    whitelist = load_functions(PACKAGE / "glob/utils/model_utils.py", {"check_whitelist_for_model"}, {"core": core})
    namespace = {
        "logging": logging, "core": core,
        "ModelMetadata": models.ModelMetadata, "OperationResult": models.OperationResult,
        "ManagerDatabaseSource": models.ManagerDatabaseSource,
        "SECURITY_MESSAGE_NORMAL_MINUS_MODEL": "",
        "security_utils": SimpleNamespace(is_allowed_security_level=lambda level: level != "high+" or high_plus),
        "model_utils": SimpleNamespace(check_whitelist_for_model=whitelist["check_whitelist_for_model"],
                                       get_model_path=lambda data: f"{data['save_path']}/{data['filename']}"),
        "download_url_with_agent": lambda url, path: downloads.append((url, path)) or True,
    }
    path = PACKAGE / "glob/manager_server.py"
    nodes = [node for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
             if isinstance(node, ast.AsyncFunctionDef) and node.name == "do_install_model"]
    assert len(nodes) == 1
    exec(compile(ast.Module(nodes, []), str(path), "exec"), namespace)

    result = asyncio.run(namespace["do_install_model"](models.ModelMetadata.model_validate(item)))
    return result, downloads


def test_listed_model_is_downloaded_from_its_listed_url(monkeypatch):
    result, downloads = install(monkeypatch, PICKLE, [SAFETENSORS, PICKLE], [SAFETENSORS, PICKLE])
    assert result == "success"
    assert downloads == [(PICKLE["url"], "upscale_models/b.pth")]


@pytest.mark.parametrize("change", [
    {"url": OTHER_URL},
    {"save_path": "custom_nodes/SomePack"},
    {"filename": "__init__.py"},
], ids=["other url", "other folder", "other filename"])
def test_unlisted_model_is_not_downloaded(monkeypatch, change):
    result, downloads = install(monkeypatch, {**SAFETENSORS, **change}, [SAFETENSORS, PICKLE], [SAFETENSORS, PICKLE])
    assert result != "success"
    assert downloads == []


@pytest.mark.parametrize("high_plus, expected", [(False, []), (True, [(PICKLE["url"], "upscale_models/b.pth")])],
                         ids=["high+ not allowed", "high+ allowed"])
def test_pickle_model_outside_the_default_channel_needs_high_plus(monkeypatch, high_plus, expected):
    result, downloads = install(monkeypatch, PICKLE, [SAFETENSORS, PICKLE], [SAFETENSORS], high_plus=high_plus)
    assert (result == "success") == bool(expected)
    assert downloads == expected


def test_pickle_model_is_refused_when_the_default_list_has_no_models(monkeypatch):
    result, downloads = install(monkeypatch, PICKLE, [SAFETENSORS, PICKLE], None)
    assert isinstance(result, str) and result != "success"
    assert downloads == []


def test_model_listed_only_in_the_local_file_is_downloaded(monkeypatch):
    result, downloads = install(monkeypatch, SAFETENSORS, [], [], local_models=[SAFETENSORS])
    assert result == "success"
    assert downloads == [(SAFETENSORS["url"], "checkpoints/a.safetensors")]


def test_safetensors_model_outside_the_default_channel_is_downloaded(monkeypatch):
    result, downloads = install(monkeypatch, SAFETENSORS, [SAFETENSORS], [])
    assert result == "success"
    assert downloads == [(SAFETENSORS["url"], "checkpoints/a.safetensors")]
