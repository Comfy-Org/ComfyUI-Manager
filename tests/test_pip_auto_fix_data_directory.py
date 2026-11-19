import ast
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from manager_test_utils import GLOB_DIR, load_manager_util

MANAGER_UTIL = load_manager_util()
PRESTARTUP = Path(os.environ.get("MANAGER_PRESTARTUP") or (Path(__file__).resolve().parent.parent / "prestartup_script.py"))
LISTED = "a-package==2.0\nanother==1.5 --index-url https://index.example/simple\n"


@pytest.fixture
def fix_broken(monkeypatch, tmp_path):
    def run(manager_files_path, installed):
        packages = {"torchvision": "0.20.1", "torchaudio": "2.5.1", "comfyui_frontend_package": "1.30.6", **installed}
        pip_list = "Package Version\n------- -------\n" + "".join(f"{name} {version}\n" for name, version in packages.items())
        commands = []

        def check_output(cmd, **_):
            if cmd[-1] == "list":
                return pip_list
            commands.append(" ".join(cmd[3:]))
            return ""

        monkeypatch.setattr(MANAGER_UTIL, "make_pip_cmd", lambda cmd: ["python", "-m", "pip", *cmd])
        monkeypatch.setattr(MANAGER_UTIL, "subprocess", SimpleNamespace(
            check_output=check_output, CalledProcessError=subprocess.CalledProcessError))
        monkeypatch.setattr(MANAGER_UTIL, "pip_map", None)
        (tmp_path / "pip_auto_fix.list").write_text(LISTED, encoding="utf-8")

        previous = MANAGER_UTIL.get_installed_packages(True)
        MANAGER_UTIL.PIPFixer(previous, str(tmp_path), manager_files_path and str(tmp_path)).fix_broken()
        return commands

    return run


def test_with_a_data_directory_the_listed_packages_are_restored(fix_broken):
    assert fix_broken(True, {"a-package": "1.0"}) == [
        "install a-package==2.0", "install another==1.5 --index-url https://index.example/simple"]


@pytest.mark.parametrize("installed", [{"a-package": "1.0"}, {}, {"a-package": "2.0", "another": "1.5"}],
                         ids=["another version installed", "not installed", "as listed"])
def test_without_a_data_directory_nothing_is_restored_from_a_list(fix_broken, installed):
    assert fix_broken(None, installed) == []


@pytest.mark.parametrize("data_directory", [True, None], ids=["with a data directory", "without one"])
def test_a_repair_that_uses_no_list_runs_either_way(fix_broken, data_directory):
    assert fix_broken(data_directory, {"comfy": "0.0.1", "a-package": "2.0", "another": "1.5"}) == ["uninstall comfy"]


def directory_given_at_start(has_system_user_api):
    statements = [node for node in ast.parse(PRESTARTUP.read_text(encoding="utf-8")).body
                  if isinstance(node, ast.Assign) and "PIPFixer(" in ast.unparse(node)]
    assert len(statements) == 1
    given = []
    namespace = {
        "manager_util": SimpleNamespace(get_installed_packages=dict, PIPFixer=lambda previous, comfy_path, path: given.append(path)),
        "comfy_path": "comfyui", "manager_files_path": "the data directory", "_has_system_user_api": has_system_user_api,
    }
    exec(compile(ast.Module(body=statements, type_ignores=[]), str(PRESTARTUP), "exec"), namespace)
    return given


def test_a_start_with_the_system_user_api_gives_the_data_directory():
    assert directory_given_at_start(True) == ["the data directory"]


def test_a_start_on_an_older_comfyui_gives_no_data_directory():
    assert directory_given_at_start(False) == [None]


def directories_given_by_the_server(has_system_user_api):
    path = GLOB_DIR / "manager_core.py"
    statements = [node for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
                  if isinstance(node, ast.Assign) and "PIPFixer(" in ast.unparse(node)]
    given = []
    namespace = {
        "manager_util": SimpleNamespace(get_installed_packages=dict, PIPFixer=lambda previous, comfy_path, path: given.append(path)),
        "manager_migration": SimpleNamespace(has_system_user_api=lambda: has_system_user_api),
        "comfy_path": "comfyui", "manager_files_path": "the data directory",
    }
    exec(compile(ast.Module(body=statements, type_ignores=[]), str(path), "exec"), namespace)
    return given


def test_an_install_with_the_system_user_api_gives_the_data_directory():
    assert directories_given_by_the_server(True) == ["the data directory", "the data directory"]


def test_an_install_on_an_older_comfyui_gives_no_data_directory():
    assert directories_given_by_the_server(False) == [None, None]
