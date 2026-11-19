import ast
import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest
from aiohttp import web

from manager_test_utils import GLOB_DIR

LEVELS = ["strong", "normal", "normal-", "weak"]
SERVER = {"is_allowed_security_level", "security_403_response", "_reject_non_json_content_type", "comfyui_switch_version"}
CORE = {"parse_semver", "is_comfyui_downgrade"}


class GitCommandError(Exception):
    pass


def functions(name, names):
    source = (GLOB_DIR / name).read_text(encoding="utf-8")
    nodes = [node for node in ast.parse(source).body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
             or isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "").startswith("SECURITY_MESSAGE_")]
    assert names <= {getattr(node, "name", None) for node in nodes}
    return compile(ast.Module(body=nodes, type_ignores=[]), name, "exec")


def load(security_level, loopback, described="v0.3.60"):
    def describe(*args):
        if described is None:
            raise GitCommandError("fatal: No names found, cannot describe anything.")
        return described

    git = SimpleNamespace(Repo=lambda path: SimpleNamespace(git=SimpleNamespace(describe=describe)),
                          GitCommandError=GitCommandError)
    core = {"re": re, "git": git, "comfy_path": "comfyui"}
    exec(functions("manager_core.py", CORE), core)

    switched = []
    server = {
        "routes": web.RouteTableDef(), "web": web, "logging": logging, "sys": sys,
        "is_local_mode": loopback,
        "core": SimpleNamespace(get_config=lambda: {"security_level": security_level},
                                is_comfyui_downgrade=core["is_comfyui_downgrade"], switch_comfyui=switched.append),
        "manager_migration": SimpleNamespace(has_system_user_api=lambda: True),
    }
    exec(functions("manager_server.py", SERVER), server)
    return server["comfyui_switch_version"], switched


def call(handler, body):
    async def read_json():
        return body

    try:
        response = asyncio.run(handler(SimpleNamespace(json=read_json, content_type="application/json")))
    except Exception:
        return 500, None
    return response.status, json.loads(response.text) if response.text else None


REFUSED = (403, {"error": "security_level"})


@pytest.mark.parametrize("loopback", [True, False], ids=["loopback", "not loopback"])
@pytest.mark.parametrize("security_level", LEVELS)
def test_an_older_release_needs_normal_minus_on_loopback_and_weak_otherwise(security_level, loopback):
    comfyui_switch_version, switched = load(security_level, loopback)

    answer = call(comfyui_switch_version, {"ver": "v0.3.59"})

    if security_level == "weak" or loopback and security_level == "normal-":
        assert answer == (200, None)
        assert switched == ["v0.3.59"]
    else:
        assert answer == REFUSED
        assert switched == []


@pytest.mark.parametrize("loopback", [True, False], ids=["loopback", "not loopback"])
@pytest.mark.parametrize("security_level", LEVELS)
@pytest.mark.parametrize("version", ["nightly", "v0.3.60", "v0.3.61", "v0.4.0", "v1.0.0"],
                         ids=["nightly", "the same release", "a newer patch", "a newer minor", "a newer major"])
def test_an_update_is_not_held_to_a_level(version, security_level, loopback):
    comfyui_switch_version, switched = load(security_level, loopback)

    assert call(comfyui_switch_version, {"ver": version}) == (200, None)
    assert switched == [version]


@pytest.mark.parametrize("described, version, older", [
    ("v0.3.60-12-gabc1234", "v0.3.60", True), ("v0.3.60-12-gabc1234", "v0.3.61", False),
    ("v0.3.60-12-gabc1234", "v0.3.59", True), ("v0.3.60-1-gabc1234", "v0.3.60", True),
    ("v0.45.0-32-g0123abc", "v0.45.0", True), ("v0.45.0-32-g0123abc", "v0.45.4", False),
    ("v0.9.0", "v0.10.0", False), ("v0.10.0", "v0.9.0", True), ("v0.10.0", "v0.9.99", True),
    ("v1.0.0", "v0.99.99", True), ("v0.3.60", "v0.3.060", False), ("v0.3.60", "v0.2.61", True),
], ids=["commits after a release, that release", "commits after a release, a newer one", "commits after a release, an older one",
        "one commit after a release, that release", "nightly, the first release of its minor", "nightly, a later patch release",
        "a two-digit minor is newer", "a one-digit minor is older", "a higher patch of a lower minor",
        "a lower major", "leading zeros", "a higher patch of an older minor"])
def test_releases_are_compared_by_their_numbers(described, version, older):
    comfyui_switch_version, switched = load("strong", True, described)

    answer = call(comfyui_switch_version, {"ver": version})

    assert (answer, switched) == ((REFUSED, []) if older else ((200, None), [version]))


@pytest.mark.parametrize("version", [
    "master", "HEAD~100", "abc1234", "0.3.61", "v0.3", "v0.3.61.1", "v0.3.61-rc1", "V0.3.61", " v0.3.61", "v0.3.61 ",
    "refs/tags/v0.3.61", "latest", "Nightly", "v0.3.61\n", "v0.3.61\nv0.3.59", "\nv0.3.61", "",
], ids=["a branch", "an ancestor", "a commit", "no v", "two numbers", "four numbers", "a suffix", "upper case",
        "a leading space", "a trailing space", "a full ref", "another name", "nightly in another case", "a trailing newline",
        "two lines", "a leading newline", "empty"])
def test_what_is_not_a_release_tag_is_held_like_an_older_release(version):
    comfyui_switch_version, switched = load("normal", True)
    assert call(comfyui_switch_version, {"ver": version}) == REFUSED
    assert switched == []

    comfyui_switch_version, switched = load("normal-", True)
    assert call(comfyui_switch_version, {"ver": version}) == (200, None)
    assert switched == [version]


@pytest.mark.parametrize("described", [None, "", "latest", "latest-3-gabc1234", "0.3.60", "v0.3"],
                         ids=["no tag", "nothing", "another tag", "commits after another tag", "no v", "two numbers"])
@pytest.mark.parametrize("version", ["v0.3.61", "v9.9.9"])
def test_without_a_release_to_compare_with_every_release_is_held(described, version):
    comfyui_switch_version, switched = load("normal", True, described)
    assert call(comfyui_switch_version, {"ver": version}) == REFUSED
    assert switched == []

    comfyui_switch_version, switched = load("weak", False, described)
    assert call(comfyui_switch_version, {"ver": version}) == (200, None)
    assert switched == [version]


@pytest.mark.parametrize("described", [None, "latest"], ids=["no tag", "another tag"])
@pytest.mark.parametrize("security_level", LEVELS)
def test_nightly_needs_no_release_to_compare_with(security_level, described):
    comfyui_switch_version, switched = load(security_level, False, described)

    assert call(comfyui_switch_version, {"ver": "nightly"}) == (200, None)
    assert switched == ["nightly"]


@pytest.mark.parametrize("version", [None, 1, 0.3, ["v0.3.61"], {"v": "0.3.61"}, True],
                         ids=["null", "an integer", "a number", "a list", "an object", "a boolean"])
@pytest.mark.parametrize("security_level", LEVELS)
def test_a_version_that_is_not_text_switches_nothing(security_level, version):
    comfyui_switch_version, switched = load(security_level, True)

    status, _ = call(comfyui_switch_version, {"ver": version})

    assert status == 400
    assert switched == []


@pytest.mark.parametrize("body", [{}, {"version": "v0.3.59"}], ids=["no fields", "another field"])
@pytest.mark.parametrize("security_level", LEVELS)
def test_a_request_without_a_version_does_nothing(security_level, body):
    comfyui_switch_version, switched = load(security_level, False)

    assert call(comfyui_switch_version, body) == (200, None)
    assert switched == []


@pytest.mark.parametrize("security_level", ["", "STRONG", "middle", "high"])
def test_a_security_level_that_is_not_one_of_the_four_allows_no_older_release(security_level):
    comfyui_switch_version, switched = load(security_level, True)

    assert call(comfyui_switch_version, {"ver": "v0.3.59"}) == REFUSED
    assert call(comfyui_switch_version, {"ver": "v0.3.61"}) == (200, None)
    assert switched == ["v0.3.61"]


@pytest.fixture
def repository(tmp_path, monkeypatch):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    # git takes its repository from these when they are set, as they are under a git hook
    for name in [name for name in os.environ if name.startswith("GIT_")]:
        monkeypatch.delenv(name)

    def run(*args):
        subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=test", "-c", "user.email=test@example.invalid",
                        "-c", "commit.gpgsign=false", *args], check=True, capture_output=True)

    run("init", "-q")
    for release in ("v0.3.59", "v0.3.60"):
        run("commit", "-q", "--allow-empty", "-m", release)
        run("tag", release)
    return tmp_path, run


def is_downgrade(path, tag):
    core = {"re": re, "git": pytest.importorskip("git"), "comfy_path": str(path)}
    exec(functions("manager_core.py", CORE), core)
    return core["is_comfyui_downgrade"](tag)


@pytest.mark.parametrize("tag, older", [("v0.3.59", True), ("v0.3.60", False), ("v0.3.61", False), ("nightly", False),
                                        ("master", True)])
def test_in_a_repository_at_a_release_only_an_older_one_goes_back(repository, tag, older):
    path, _ = repository

    assert is_downgrade(path, tag) is older


@pytest.mark.parametrize("tag, older", [("v0.3.59", True), ("v0.3.60", True), ("v0.3.61", False), ("nightly", False)])
def test_in_a_repository_with_a_commit_after_the_release_that_release_goes_back(repository, tag, older):
    path, run = repository
    run("commit", "-q", "--allow-empty", "-m", "after the release")

    assert is_downgrade(path, tag) is older


@pytest.mark.parametrize("tag, older", [("v0.3.59", False), ("v0.3.60", False), ("v0.3.58", True)])
def test_in_a_repository_checked_out_at_an_earlier_release_the_later_one_does_not_go_back(repository, tag, older):
    path, run = repository
    run("checkout", "-q", "v0.3.59")

    assert is_downgrade(path, tag) is older


@pytest.mark.parametrize("tag, older", [("v0.3.60", True), ("nightly", False)])
def test_in_a_repository_without_a_release_tag_every_release_goes_back(repository, tag, older):
    path, run = repository
    run("tag", "-d", "v0.3.59", "v0.3.60")

    assert is_downgrade(path, tag) is older
