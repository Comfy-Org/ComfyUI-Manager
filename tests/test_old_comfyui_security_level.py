import ast
import configparser
import json
import subprocess
import sys
import textwrap
from types import SimpleNamespace

import pytest

from manager_test_utils import GLOB_DIR

LEVELS = ["strong", "normal", "normal-", "weak"]
SOURCE = (GLOB_DIR / "manager_server.py").read_text(encoding="utf-8")
GATE = next(node for node in ast.parse(SOURCE).body
            if isinstance(node, ast.FunctionDef) and node.name == "is_allowed_security_level")


def allowed(needed, security_level, loopback, has_system_user_api):
    namespace = {
        "is_local_mode": loopback,
        "core": SimpleNamespace(get_config=lambda: {"security_level": security_level}),
        "manager_migration": SimpleNamespace(has_system_user_api=lambda: has_system_user_api),
    }
    exec(compile(ast.Module(body=[GATE], type_ignores=[]), "manager_server.py", "exec"), namespace)
    return namespace["is_allowed_security_level"](needed)


@pytest.mark.parametrize("loopback", [True, False], ids=["loopback", "not loopback"])
@pytest.mark.parametrize("security_level", LEVELS + ["", "a level that Manager does not know"])
@pytest.mark.parametrize("needed", ["middle", "high", "block", "low", ""])
def test_an_old_comfyui_is_refused_at_every_level_of_config_ini(needed, security_level, loopback):
    assert allowed(needed, security_level, loopback, has_system_user_api=False) is False


@pytest.mark.parametrize("loopback", [True, False], ids=["loopback", "not loopback"])
@pytest.mark.parametrize("security_level", LEVELS)
def test_with_the_system_user_api_the_level_of_config_ini_decides(security_level, loopback):
    api = dict(security_level=security_level, loopback=loopback, has_system_user_api=True)
    assert allowed("block", **api) is False
    assert allowed("middle", **api) is (security_level != "strong")
    assert allowed("high", **api) is (security_level == "weak" or security_level == "normal-" and loopback)
    assert allowed("low", **api) is True


CHILD = textwrap.dedent(
    """
    import sys, types, tempfile, os, json
    tmp = tempfile.mkdtemp(prefix="cm_old_comfyui_")
    stub = types.ModuleType("folder_paths")
    stub.get_user_directory = lambda: tmp
    if {has_system_user_api!r}:
        stub.get_system_user_directory = lambda *a, **k: os.path.join(tmp, "sysuser")
    sys.modules["folder_paths"] = stub
    sys.path.insert(0, {glob_dir!r})
    import manager_core
    path = os.path.join(tmp, "config.ini")
    manager_core.manager_config_path = path
    manager_core.cached_config = None
    written = {written!r}
    if written is not None:
        with open(path, "w") as f:
            f.write(written)
    read = manager_core.get_config()["security_level"]
    for key, value in {changes!r}:
        manager_core.get_config()[key] = value
    manager_core.write_config()
    with open(path) as f:
        print(json.dumps({{"read": read, "file": f.read()}}))
    """
)


def config_after_a_write(has_system_user_api, written, changes=()):
    script = CHILD.format(has_system_user_api=has_system_user_api, glob_dir=str(GLOB_DIR), written=written, changes=list(changes))
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=180)
    assert done.returncode == 0, done.stderr[-2000:]
    result = json.loads(done.stdout.strip().splitlines()[-1])
    config = configparser.ConfigParser(strict=False)
    config.read_string(result["file"])
    return result["read"], dict(config["default"])


@pytest.mark.parametrize("has_system_user_api", [True, False], ids=["with the API", "an older ComfyUI"])
def test_the_first_config_ini_is_written_with_the_default_level(has_system_user_api):
    read, written = config_after_a_write(has_system_user_api, None)
    assert read == "normal"
    assert written["security_level"] == "normal"


@pytest.mark.parametrize("has_system_user_api", [True, False], ids=["with the API", "an older ComfyUI"])
@pytest.mark.parametrize("security_level", LEVELS)
def test_the_level_of_config_ini_is_read_and_kept_as_the_user_wrote_it(security_level, has_system_user_api):
    text = f"[default]\nsecurity_level = {security_level}\ndb_mode = cache\n"
    read, written = config_after_a_write(has_system_user_api, text, changes=[("db_mode", "local")])
    assert read == security_level
    assert written["security_level"] == security_level
    assert written["db_mode"] == "local"


@pytest.mark.parametrize("has_system_user_api", [True, False], ids=["with the API", "an older ComfyUI"])
def test_a_config_ini_without_a_level_is_not_given_one_by_another_setting(has_system_user_api):
    read, written = config_after_a_write(has_system_user_api, "[default]\ndb_mode = cache\n", changes=[("db_mode", "local")])
    assert read == "normal"
    assert "security_level" not in written


@pytest.mark.parametrize("has_system_user_api", [True, False], ids=["with the API", "an older ComfyUI"])
def test_a_config_ini_that_cannot_be_parsed_is_rewritten_with_the_default_level(has_system_user_api):
    read, written = config_after_a_write(has_system_user_api, "security_level = weak\n")
    assert read == "normal"
    assert written["security_level"] == "normal"
