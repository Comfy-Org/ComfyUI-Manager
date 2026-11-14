"""A channel response that is not JSON does not empty a list (#3480).

The channel is a local HTTP server. The startup cache update and `get_data_by_mode`
are the real functions of each server, run against a temporary cache directory and a
temporary bundled list. The Manager is laid out as an installed package, so the lists
are read from the cache that the startup cache update writes.
"""
import asyncio
import json
import logging
import os
import traceback
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from _install_flags_testutil import import_context
from legacy_html_testutil import PACKAGE, load_functions

FILENAME = "model-list.json"
STARTUP_FILES = 5
BUNDLED = {"models": [{"name": "bundled with the Manager"}]}
SERVED = {"models": [{"name": "served by the channel"}]}
NOT_JSON = [
    pytest.param(200, "<html><body>Access blocked</body></html>", id="block page"),
    pytest.param(404, "404: Not Found", id="missing file"),
]
SERVERS = ["glob", "legacy"]


@pytest.fixture(autouse=True)
def reach_the_channel_directly(monkeypatch):
    # get_data() honors the proxy variables of the environment.
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")


@pytest.fixture
def manager_util(tmp_path, monkeypatch):
    import_context()
    from comfyui_manager.common import manager_util

    monkeypatch.setattr(manager_util, "comfyui_manager_path", str(tmp_path / "manager"))
    monkeypatch.setattr(manager_util, "cache_dir", str(tmp_path / "cache"))
    os.makedirs(manager_util.comfyui_manager_path)
    os.makedirs(manager_util.cache_dir)
    with open(os.path.join(manager_util.comfyui_manager_path, FILENAME), "w", encoding="utf-8") as f:
        json.dump(BUNDLED, f)
    return manager_util


def load_server(server, manager_util, channel_url):
    """The startup cache update and `get_data_by_mode` of `server`, set to read `channel_url`."""
    async def loaded(*args, **kwargs):
        pass

    config = {"channel_url": channel_url, "network_mode": "public", "default_cache_as_channel_url": True}
    core = SimpleNamespace(get_config=lambda: config, refresh_channel_dict=lambda: None,
                           unified_manager=SimpleNamespace(reload=loaded, get_custom_nodes=loaded))
    remote = SimpleNamespace(remote=SimpleNamespace(value="remote"))
    startup = load_functions(PACKAGE / server / "manager_server.py", {"default_cache_update"}, {
        "os": os, "json": json, "logging": logging, "traceback": traceback, "asyncio": asyncio,
        "manager_util": manager_util, "core": core, "ManagerDatabaseSource": remote})
    reader = load_functions(PACKAGE / server / "manager_core.py", {"get_data_by_mode"}, {
        "os": os, "json": json, "manager_util": manager_util,
        "get_config": lambda: config, "get_channel_dict": lambda: {}})
    return startup["default_cache_update"], reader["get_data_by_mode"]


class Channel:
    def __init__(self):
        self.requests = 0
        self.serve(200, json.dumps(SERVED))

    def serve(self, status, text):
        self.status, self.text = status, text

    async def handle(self, request):
        self.requests += 1
        return web.Response(status=self.status, text=self.text)


def run(scenario):
    async def main():
        channel = Channel()
        app = web.Application()
        app.router.add_get("/main/{name}", channel.handle)
        server = TestServer(app)
        await server.start_server()
        try:
            return await scenario(channel, str(server.make_url("/main")))
        finally:
            await server.close()

    return asyncio.run(main())


@pytest.mark.parametrize("status, text", NOT_JSON)
def test_response_that_is_not_json_is_an_error(manager_util, status, text):
    async def scenario(channel, channel_url):
        channel.serve(status, text)
        with pytest.raises(json.JSONDecodeError):
            await manager_util.get_data(f"{channel_url}/{FILENAME}")

    run(scenario)


@pytest.mark.parametrize("server", SERVERS)
@pytest.mark.parametrize("status, text", NOT_JSON)
def test_bundled_list_is_used_and_nothing_is_cached(manager_util, server, status, text):
    async def scenario(channel, channel_url):
        start, get_data_by_mode = load_server(server, manager_util, channel_url)
        channel.serve(status, text)
        await start()
        return await get_data_by_mode("cache", FILENAME), os.listdir(manager_util.cache_dir), channel.requests

    result, cached, requests = run(scenario)

    assert requests == STARTUP_FILES
    assert result == BUNDLED
    assert cached == []


@pytest.mark.parametrize("server", SERVERS)
@pytest.mark.parametrize("status, text", NOT_JSON)
def test_list_cached_by_an_earlier_start_is_kept(manager_util, server, status, text):
    async def scenario(channel, channel_url):
        start, get_data_by_mode = load_server(server, manager_util, channel_url)
        await start()
        channel.serve(status, text)
        await start()
        return await get_data_by_mode("cache", FILENAME)

    assert run(scenario) == SERVED


@pytest.mark.parametrize("server", SERVERS)
@pytest.mark.parametrize("status, text", NOT_JSON)
def test_next_start_reads_the_list_from_the_channel(manager_util, server, status, text):
    async def scenario(channel, channel_url):
        start, get_data_by_mode = load_server(server, manager_util, channel_url)
        channel.serve(status, text)
        await start()
        channel.serve(200, json.dumps(SERVED))
        await start()
        return await get_data_by_mode("cache", FILENAME)

    assert run(scenario) == SERVED


@pytest.mark.parametrize("server", SERVERS)
def test_list_from_the_channel_is_read_from_the_cache(manager_util, server):
    async def scenario(channel, channel_url):
        start, get_data_by_mode = load_server(server, manager_util, channel_url)
        await start()
        first = await get_data_by_mode("cache", FILENAME)
        second = await get_data_by_mode("cache", FILENAME)
        return first, second, channel.requests

    assert run(scenario) == (SERVED, SERVED, STARTUP_FILES)


def test_unreadable_local_file_still_reads_as_empty(manager_util):
    async def scenario(channel, channel_url):
        path = os.path.join(manager_util.comfyui_manager_path, "broken.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{")
        return await manager_util.get_data(path)

    assert run(scenario) == {}
