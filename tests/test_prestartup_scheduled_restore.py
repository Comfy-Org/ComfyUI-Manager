import ast
import locale
import os
import sys
import types
from pathlib import Path

import pytest

PRESTARTUP = Path(os.environ.get("MANAGER_PRESTARTUP") or (Path(__file__).resolve().parent.parent / "prestartup_script.py"))
SNAPSHOT = '{"comfyui": null, "git_custom_nodes": {}, "cnr_custom_nodes": {}, "file_custom_nodes": [], "pips": {}}'


def start(monkeypatch, tmp_path, has_system_user_api, scheduled=True, exit_code=0):
    statements = [node for node in ast.parse(PRESTARTUP.read_text(encoding="utf-8")).body
                  if isinstance(node, ast.If) and "'restore-snapshot'" in ast.unparse(node)]
    assert len(statements) == 1

    cli_args = types.ModuleType("comfy.cli_args")
    cli_args.args = types.SimpleNamespace(listen="127.0.0.1")
    monkeypatch.setitem(sys.modules, "comfy", types.ModuleType("comfy"))
    monkeypatch.setitem(sys.modules, "comfy.cli_args", cli_args)

    path = tmp_path / "startup-scripts" / "restore-snapshot.json"
    if scheduled:
        path.parent.mkdir()
        path.write_text(SNAPSHOT, encoding="utf-8")
    commands = []

    def process_wrap(command, cwd, handler=None, env=None):
        commands.append(command)
        return exit_code

    namespace = {
        "os": os, "sys": sys, "locale": locale, "_has_system_user_api": has_system_user_api,
        "restore_snapshot_path": str(path), "comfy_path": str(tmp_path), "custom_nodes_base_path": str(tmp_path),
        "cm_cli_path": "cm-cli.py", "default_conf": {}, "process_wrap": process_wrap,
        "manager_util": types.SimpleNamespace(is_loopback_listener=lambda listen: True),
        "folder_paths": types.SimpleNamespace(__file__=str(tmp_path / "folder_paths.py"), get_user_directory=lambda: str(tmp_path / "user")),
    }
    exec(compile(ast.Module(body=statements, type_ignores=[]), str(PRESTARTUP), "exec"), namespace)
    return commands, path.exists()


@pytest.mark.parametrize("exit_code", [0, 1], ids=["cm-cli succeeds", "cm-cli fails"])
def test_with_the_system_user_api_a_scheduled_restore_runs_once(monkeypatch, tmp_path, exit_code):
    commands, left = start(monkeypatch, tmp_path, has_system_user_api=True, exit_code=exit_code)

    assert [command[:4] for command in commands] == [
        [sys.executable, "cm-cli.py", "restore-snapshot", str(tmp_path / "startup-scripts" / "restore-snapshot.json")]]
    assert left is False


def test_on_an_older_comfyui_a_scheduled_restore_does_not_run(monkeypatch, tmp_path, capsys):
    commands, left = start(monkeypatch, tmp_path, has_system_user_api=False)

    assert commands == []
    assert left is True
    assert "blocked on old ComfyUI" in capsys.readouterr().out


@pytest.mark.parametrize("has_system_user_api", [True, False], ids=["with the System User API", "older ComfyUI"])
def test_without_a_scheduled_restore_nothing_runs(monkeypatch, tmp_path, has_system_user_api, capsys):
    commands, left = start(monkeypatch, tmp_path, has_system_user_api, scheduled=False)

    assert commands == []
    assert left is False
    assert capsys.readouterr().out == ""
