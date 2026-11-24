import asyncio
import json
import logging
from types import SimpleNamespace

import pytest
from aiohttp import web

from legacy_html_testutil import PACKAGE, load_functions


def load():
    cloned, installed = [], []

    async def gitclone_install(url):
        cloned.append(url)
        return SimpleNamespace(action="install", result=True, target=url, msg="")

    namespace = {
        "routes": web.RouteTableDef(), "web": web, "logging": logging,
        "core": SimpleNamespace(gitclone_install=gitclone_install, pip_install=installed.append),
        "manager_security": SimpleNamespace(reject_non_json_post=lambda request: None),
        "_dedicated_install_allowed": lambda flag: True,
    }
    load_functions(PACKAGE / "legacy/manager_server.py", {"install_custom_node_git_url", "install_custom_node_pip"}, namespace)
    return namespace["install_custom_node_git_url"], namespace["install_custom_node_pip"], cloned, installed


def post(handler, text):
    async def read_json():
        return json.loads(text)

    return asyncio.run(handler(SimpleNamespace(json=read_json))).status


def test_a_git_url_is_installed_from_the_url_field():
    git_url, _, cloned, _ = load()

    assert post(git_url, '{"url": "https://github.com/someone/a-pack"}') == 200
    assert cloned == ["https://github.com/someone/a-pack"]


@pytest.mark.parametrize("text, packages", [
    ('{"packages": "a-package"}', ["a-package"]),
    ('{"packages": "a-package another==1.0"}', ["a-package", "another==1.0"]),
], ids=["one package", "two packages"])
def test_pip_packages_are_installed_from_the_packages_field(text, packages):
    _, pip, _, installed = load()

    assert post(pip, text) == 200
    assert installed == [packages]


@pytest.mark.parametrize("text", ["", "https://github.com/someone/a-pack", "{", '{"other": 1}', "{}", "[]", '"a-pack"', "null", "5",
                                  '{"url": 5, "packages": 5}', '{"url": null, "packages": null}', '{"url": ["a"], "packages": ["a"]}',
                                  '{"url": {"a": 1}, "packages": {"a": 1}}', '{"url": true, "packages": true}'],
                         ids=["empty", "plain text", "cut off", "another field", "no field", "a list", "a string", "null", "a number",
                              "the field a number", "the field null", "the field a list", "the field an object", "the field a boolean"])
@pytest.mark.parametrize("route", [0, 1], ids=["git_url", "pip"])
def test_a_body_without_the_field_is_a_bad_request_and_installs_nothing(route, text):
    handlers = load()

    assert post(handlers[route], text) == 400
    assert handlers[2] == [] and handlers[3] == []
