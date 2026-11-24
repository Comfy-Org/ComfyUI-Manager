import ast
import asyncio
import importlib.util
import logging
import os
import re
import shutil
import subprocess
import sys
import traceback
from types import SimpleNamespace

import pytest

from legacy_html_testutil import PACKAGE, load_functions

LEVELS = ["strong", "normal", "normal-", "weak"]
LISTENERS = ["loopback", "personal_cloud", "public"]


def switch_allowed(security_level, listener):
    return security_level == "weak" and listener != "public" or security_level == "normal-" and listener == "loopback"


class Repo:
    def __init__(self, described):
        self.described = described

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def describe_tags(self):
        return self.described


def load(monkeypatch, security_level, listener, described="v0.3.60"):
    spec = importlib.util.spec_from_file_location("_generated_models", PACKAGE / "data_models/generated_models.py")
    models = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, models)
    spec.loader.exec_module(models)

    switched, updated = [], []
    downgrade = load_functions(PACKAGE / "glob/manager_core.py", {"parse_semver", "is_comfyui_downgrade"}, {
        "re": re, "context": SimpleNamespace(comfy_path="comfyui"), "open_repo": lambda path: Repo(described),
    })
    core = SimpleNamespace(
        get_config=lambda: {"security_level": security_level,
                            "network_mode": "personal_cloud" if listener == "personal_cloud" else "public"},
        is_comfyui_downgrade=downgrade["is_comfyui_downgrade"], switch_comfyui=switched.append,
        update_to_stable_comfyui=lambda path: updated.append(path) or ("skipped", None),
    )
    security = load_functions(PACKAGE / "glob/utils/security_utils.py", {"is_allowed_security_level"}, {
        "core": core, "args": SimpleNamespace(listen="127.0.0.1" if listener == "loopback" else "0.0.0.0"),
        "is_loopback": load_functions(PACKAGE / "common/manager_security.py", {"is_loopback"})["is_loopback"],
        "SecurityLevel": models.SecurityLevel, "RiskLevel": models.RiskLevel,
    })
    namespace = {
        "logging": logging, "traceback": traceback, "os": os,
        "folder_paths": SimpleNamespace(__file__="comfyui/folder_paths.py"), "core": core,
        "security_utils": SimpleNamespace(**security), "OperationResult": models.OperationResult,
        "UpdateComfyUIParams": models.UpdateComfyUIParams, "SECURITY_MESSAGE_HIGH_P": "",
    }
    path = PACKAGE / "glob/manager_server.py"
    nodes = [node for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
             if isinstance(node, ast.AsyncFunctionDef) and node.name == "do_update_comfyui"]
    assert len(nodes) == 1
    exec(compile(ast.Module(nodes, []), str(path), "exec"), namespace)

    def task(target_version):
        return asyncio.run(namespace["do_update_comfyui"](models.UpdateComfyUIParams(target_version=target_version)))

    return SimpleNamespace(task=task, switched=switched, updated=updated)


@pytest.mark.parametrize("listener", LISTENERS)
@pytest.mark.parametrize("security_level", LEVELS)
def test_a_task_for_an_older_release_needs_the_level_of_the_switch_route(monkeypatch, security_level, listener):
    glob = load(monkeypatch, security_level, listener)

    result = glob.task("v0.3.59")

    if switch_allowed(security_level, listener):
        assert result == "success-switched-v0.3.59"
        assert glob.switched == ["v0.3.59"]
    else:
        assert result == "failed"
        assert glob.switched == []
    assert glob.updated == []


@pytest.mark.parametrize("listener", LISTENERS)
@pytest.mark.parametrize("security_level", LEVELS)
@pytest.mark.parametrize("version", ["nightly", "v0.3.60", "v0.3.61", "v0.4.0", "v1.0.0"],
                         ids=["nightly", "the same release", "a newer patch", "a newer minor", "a newer major"])
def test_a_task_for_an_update_is_not_held_to_a_level(monkeypatch, version, security_level, listener):
    glob = load(monkeypatch, security_level, listener)

    assert glob.task(version) == f"success-switched-{version}"
    assert glob.switched == [version]


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
def test_releases_are_compared_by_their_numbers(monkeypatch, described, version, older):
    glob = load(monkeypatch, "strong", "loopback", described)

    result = glob.task(version)

    assert (result, glob.switched) == (("failed", []) if older else (f"success-switched-{version}", [version]))


@pytest.mark.parametrize("version", [
    "master", "HEAD~100", "abc1234", "0.3.61", "v0.3", "v0.3.61.1", "v0.3.61-rc1", "V0.3.61", " v0.3.61", "v0.3.61 ",
    "refs/tags/v0.3.61", "latest", "Nightly", "v0.3.61\n", "v0.3.61\nv0.3.59", "\nv0.3.61",
], ids=["a branch", "an ancestor", "a commit", "no v", "two numbers", "four numbers", "a suffix", "upper case",
        "a leading space", "a trailing space", "a full ref", "another name", "nightly in another case", "a trailing newline",
        "two lines", "a leading newline"])
def test_what_is_not_a_release_tag_is_held_like_an_older_release(monkeypatch, version):
    glob = load(monkeypatch, "normal", "loopback")
    assert glob.task(version) == "failed"
    assert glob.switched == []

    glob = load(monkeypatch, "normal-", "loopback")
    assert glob.task(version) == f"success-switched-{version}"
    assert glob.switched == [version]


@pytest.mark.parametrize("described", [None, "", "latest", "latest-3-gabc1234", "0.3.60", "v0.3"],
                         ids=["no tag", "nothing", "another tag", "commits after another tag", "no v", "two numbers"])
@pytest.mark.parametrize("version", ["v0.3.61", "v9.9.9"])
def test_without_a_release_to_compare_with_every_release_is_held(monkeypatch, described, version):
    glob = load(monkeypatch, "normal", "loopback", described)
    assert glob.task(version) == "failed"
    assert glob.switched == []

    glob = load(monkeypatch, "weak", "personal_cloud", described)
    assert glob.task(version) == f"success-switched-{version}"
    assert glob.switched == [version]


@pytest.mark.parametrize("described", [None, "latest"], ids=["no tag", "another tag"])
@pytest.mark.parametrize("security_level", LEVELS)
def test_nightly_needs_no_release_to_compare_with(monkeypatch, security_level, described):
    glob = load(monkeypatch, security_level, "public", described)

    assert glob.task("nightly") == "success-switched-nightly"
    assert glob.switched == ["nightly"]


@pytest.mark.parametrize("target_version", [None, ""], ids=["no version", "an empty version"])
@pytest.mark.parametrize("security_level", LEVELS)
def test_an_update_without_a_version_is_as_before(monkeypatch, security_level, target_version):
    glob = load(monkeypatch, security_level, "public")

    assert glob.task(target_version) == "skip"
    assert glob.updated == ["comfyui"]
    assert glob.switched == []


@pytest.mark.parametrize("security_level", ["", "STRONG", "middle", "high+"])
def test_a_security_level_that_is_not_one_of_the_four_allows_no_older_release(monkeypatch, security_level):
    glob = load(monkeypatch, security_level, "loopback")

    assert glob.task("v0.3.59") == "failed"
    assert glob.task("v0.3.61") == "success-switched-v0.3.61"
    assert glob.switched == ["v0.3.61"]


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
    spec = importlib.util.spec_from_file_location("_git_compat", PACKAGE / "common/git_compat.py")
    git_compat = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(git_compat)
    core = load_functions(PACKAGE / "glob/manager_core.py", {"parse_semver", "is_comfyui_downgrade"}, {
        "re": re, "context": SimpleNamespace(comfy_path=str(path)), "open_repo": git_compat.open_repo,
    })
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
