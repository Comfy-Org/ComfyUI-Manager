import ast
import os
import sys
import types
from pathlib import Path

import pytest

PRESTARTUP = Path(__file__).resolve().parent.parent / "prestartup_script.py"
COMFY = os.path.join(os.sep, "opt", "ComfyUI")
LAUNCHER = os.path.join(os.sep, "opt", "launcher")
BASE = os.path.join(os.sep, "data", "comfy")


def restore(tmp_path, monkeypatch, environ):
    scheduled = tmp_path / "restore-snapshot.json"
    scheduled.write_text("{}")
    block = [node for node in ast.parse(PRESTARTUP.read_text(encoding="utf-8")).body
             if isinstance(node, ast.If) and ast.unparse(node.test) == "os.path.exists(restore_snapshot_path)"]
    assert len(block) == 1

    cli_args = types.ModuleType("comfy.cli_args")
    cli_args.args = types.SimpleNamespace(listen="127.0.0.1")
    monkeypatch.setitem(sys.modules, "comfy", types.ModuleType("comfy"))
    monkeypatch.setitem(sys.modules, "comfy.cli_args", cli_args)
    for name in ("COMFYUI_PATH", "COMFYUI_FOLDERS_BASE_PATH"):
        monkeypatch.delenv(name, raising=False)
    for name, value in environ.items():
        monkeypatch.setenv(name, value)

    started = []

    def process_wrap(cmd, cwd=None, handler=None, env=None):
        started.append((cmd, cwd, env))
        return 0

    exec(compile(ast.Module(body=block, type_ignores=[]), str(PRESTARTUP), "exec"), {
        "os": os, "sys": sys, "restore_snapshot_path": str(scheduled), "comfy_path": LAUNCHER,
        "cm_cli_path": "cm-cli.py", "custom_nodes_base_path": os.path.join(BASE, "custom_nodes"),
        "folder_paths": types.SimpleNamespace(__file__=os.path.join(COMFY, "folder_paths.py"),
                                              get_user_directory=lambda: os.path.join(BASE, "user")),
        "default_conf": {}, "manager_util": types.SimpleNamespace(is_loopback_listener=lambda listen: True),
        "process_wrap": process_wrap,
    })
    assert len(started) == 1 and not scheduled.exists()
    return started[0]


def test_cm_cli_is_given_the_comfyui_path(tmp_path, monkeypatch):
    _, _, env = restore(tmp_path, monkeypatch, {})
    assert env.get("COMFYUI_PATH") == COMFY


def test_cm_cli_is_given_the_directories_of_the_server(tmp_path, monkeypatch):
    cmd, _, _ = restore(tmp_path, monkeypatch, {})
    assert cmd[1:4] == ["cm-cli.py", "restore-snapshot", str(tmp_path / "restore-snapshot.json")]
    assert cmd[4:] == ["--user-directory", os.path.join(BASE, "user"),
                       "--restore-to", os.path.join(BASE, "custom_nodes")]


@pytest.mark.parametrize("name", ["COMFYUI_PATH", "COMFYUI_FOLDERS_BASE_PATH"])
def test_a_path_set_in_the_environment_is_kept(tmp_path, monkeypatch, name):
    _, _, env = restore(tmp_path, monkeypatch, {name: os.path.join(os.sep, "elsewhere")})
    assert env[name] == os.path.join(os.sep, "elsewhere")
