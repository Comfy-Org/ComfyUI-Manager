"""The legacy server installs a listed model only from its listed url (#3428).

Each case hands a request to the real `_install_model` with the real
`check_whitelist_for_model`; the route only queues, so nothing is fetched.
"""
import asyncio
import logging
from types import SimpleNamespace

import pytest
from aiohttp import web

from legacy_html_testutil import PACKAGE, load_functions

LISTED = {"name": "a", "type": "checkpoint", "base": "SDXL", "save_path": "checkpoints",
          "filename": "a.safetensors", "url": "https://huggingface.co/a/resolve/main/a.safetensors"}
OTHER = {**LISTED, "name": "b", "filename": "b.safetensors", "url": "https://huggingface.co/b/resolve/main/b.safetensors"}


def install(item):
    """The status `_install_model` answers for `item`, and what it queued."""
    async def get_data_by_mode(mode, filename, channel_url=None):
        return {"models": [LISTED, OTHER]}

    queued = []
    functions = load_functions(PACKAGE / "legacy/manager_server.py", {"check_whitelist_for_model", "_install_model"}, {
        "web": web, "logging": logging, "core": SimpleNamespace(get_data_by_mode=get_data_by_mode),
        "is_allowed_security_level": lambda level: level == "middle+", "temp_queue_batch": queued,
    })
    return asyncio.run(functions["_install_model"](item)).status, queued


def test_listed_model_is_queued_with_its_listed_url():
    status, queued = install({**LISTED, "ui_id": "u"})
    assert status == 200
    assert [(kind, item["url"]) for kind, (_, item) in queued] == [("install-model", LISTED["url"])]


@pytest.mark.parametrize("url", [{"url": OTHER["url"]}, {}], ids=["url of another entry", "no url"])
def test_listed_name_with_another_url_is_refused(url):
    status, queued = install({**{k: v for k, v in LISTED.items() if k != "url"}, **url, "ui_id": "u"})
    assert status == 400
    assert queued == []
