import ast
import os
import sys
import types
from pathlib import Path

import pytest

PRESTARTUP = Path(os.environ.get("MANAGER_PRESTARTUP") or (Path(__file__).resolve().parent.parent / "prestartup_script.py"))


def start(tmp_path, has_system_user_api, legacy):
    statements = [node for node in ast.parse(PRESTARTUP.read_text(encoding="utf-8")).body
                  if isinstance(node, ast.If) and "execute_lazy_install_script(comfy_path" in ast.unparse(node)]
    assert len(statements) == 1

    directory = tmp_path / "user" / "default" / "ComfyUI-Manager"
    if legacy is not None:
        directory.mkdir(parents=True)
        for name in legacy:
            (directory / name).write_text("", encoding="utf-8")
    installed = []

    namespace = {
        "os": os, "sys": sys, "_has_system_user_api": has_system_user_api, "comfy_path": "comfyui",
        "folder_paths": types.SimpleNamespace(get_user_directory=lambda: str(tmp_path / "user")),
        "execute_lazy_install_script": lambda repo_path, executable: installed.append((repo_path, executable)),
    }
    exec(compile(ast.Module(body=statements, type_ignores=[]), str(PRESTARTUP), "exec"), namespace)
    return installed


def test_the_first_start_after_the_update_installs_the_requirements_of_comfyui(tmp_path, capsys):
    assert start(tmp_path, True, ["config.ini"]) == [("comfyui", sys.executable)]
    assert "installing the requirements of ComfyUI" in capsys.readouterr().out


@pytest.mark.parametrize("legacy", [None, [], ["channels.list"]],
                         ids=["no legacy directory", "an empty legacy directory", "a legacy directory without config.ini"])
def test_a_start_that_is_not_the_first_after_the_update_installs_nothing(tmp_path, legacy, capsys):
    assert start(tmp_path, True, legacy) == []
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("legacy", [None, ["config.ini"]], ids=["no data directory yet", "with its config.ini"])
def test_an_old_comfyui_installs_nothing_at_the_start(tmp_path, legacy):
    assert start(tmp_path, False, legacy) == []
