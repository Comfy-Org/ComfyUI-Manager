"""`git_exe` chooses the git executable that GitPython runs.

Each case runs a real function of the Manager with the real GitPython. The
configured executable is a script that records its arguments and then runs the
git of the test environment. `git_exe` is used only when the configuration file
is in a protected directory and the value is a working git.
"""
import ast
import configparser
import logging
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import git
import pytest

from manager_test_utils import GLOB_DIR, load_manager_util
from test_install_flags_config import GIT_LOCATION, _run_child

pytestmark = pytest.mark.skipif(os.name == "nt", reason="the executables of the cases are shell scripts")

ROOT = GLOB_DIR.parent
NOT_A_GIT = {
    "a path that does not exist": None,
    "a program that fails": "#!/bin/sh\nexit 3\n",
    "a program that is not git": "#!/bin/sh\necho hello\n",
    "a program that waits": "#!/bin/sh\nexec sleep 30\n",
    "a program that prints bytes that are not text": "#!/bin/sh\nprintf '\\377\\376'\n",
    "a file that cannot be run": "not a program\n",
}


def take(path, name, namespace):
    """Define the function of the file in the namespace and return it."""
    function = [node for node in ast.parse(path.read_text(encoding="utf-8")).body
                if isinstance(node, ast.FunctionDef) and node.name == name]
    assert len(function) == 1
    exec(compile(ast.Module(body=function, type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


@pytest.fixture
def manager_util(monkeypatch):
    module = load_manager_util()
    find = module.find_git_executable
    monkeypatch.setattr(module, "find_git_executable", lambda git_exe: find(git_exe, timeout=2))
    return module


@pytest.fixture(autouse=True)
def default_git(monkeypatch):
    # a git that a case runs is to find its repository by the directory it is run in,
    # and the git is the one that the case names, whatever the shell of the run names
    for name in (*GIT_LOCATION, 'GIT_EXE_PATH', 'GIT_PYTHON_GIT_EXECUTABLE'):
        monkeypatch.delenv(name, raising=False)
    # GitPython keeps the git that the variable of the shell named when it last looked
    git.refresh()
    yield
    # the variables a case set are removed before GitPython looks for its git again
    monkeypatch.undo()
    git.refresh()


@pytest.fixture
def recording_git(tmp_path):
    """A git executable that appends each command line to `calls`."""
    calls = tmp_path / "calls"
    executable = tmp_path / "recording-git"
    executable.write_text(f'#!/bin/sh\necho "$@" >> "{calls}"\nexec "{shutil.which("git")}" "$@"\n')
    executable.chmod(0o755)
    return SimpleNamespace(path=str(executable),
                           calls=lambda: calls.read_text().splitlines() if calls.exists() else [],
                           forget=lambda: calls.unlink(missing_ok=True))


@pytest.fixture(params=NOT_A_GIT)
def not_a_git(request, tmp_path):
    path = tmp_path / "not-a-git"
    if NOT_A_GIT[request.param] is not None:
        path.write_text(NOT_A_GIT[request.param])
        path.chmod(0o755)
    return str(path)


def setup_git_executable(manager_util, git_exe, protected=True):
    """Run `setup_git_executable` of `manager_core.py` with `git_exe` as the configured value."""
    take(GLOB_DIR / "manager_core.py", "setup_git_executable", {
        "git": git, "logging": logging, "manager_util": manager_util,
        "manager_migration": SimpleNamespace(has_system_user_api=lambda: protected),
        "get_config": lambda: {"git_exe": git_exe},
    })()


def test_configured_git_is_run(manager_util, recording_git, tmp_path):
    setup_git_executable(manager_util, recording_git.path)
    recording_git.forget()

    git.Repo.init(tmp_path / "repo")

    assert any(line.startswith("init") for line in recording_git.calls())
    assert (tmp_path / "repo" / ".git").is_dir()


def test_empty_setting_keeps_the_default_git(manager_util, recording_git, tmp_path, caplog):
    default = git.Git.GIT_PYTHON_GIT_EXECUTABLE

    with caplog.at_level(logging.WARNING):
        setup_git_executable(manager_util, "")

    assert caplog.text == ""
    assert git.Git.GIT_PYTHON_GIT_EXECUTABLE == default


def test_setting_that_is_no_git_is_reported_and_the_default_kept(manager_util, not_a_git, tmp_path, caplog):
    default = git.Git.GIT_PYTHON_GIT_EXECUTABLE
    flags = git.remote.FetchInfo._flag_map.copy()

    with caplog.at_level(logging.WARNING):
        setup_git_executable(manager_util, not_a_git)

    assert not_a_git in caplog.text
    assert git.Git.GIT_PYTHON_GIT_EXECUTABLE == default and git.remote.FetchInfo._flag_map == flags
    git.Repo.init(tmp_path / "repo")
    assert (tmp_path / "repo" / ".git").is_dir()


def test_setting_of_an_unprotected_configuration_is_not_used(manager_util, recording_git, tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        setup_git_executable(manager_util, recording_git.path, protected=False)

    git.Repo.init(tmp_path / "repo")

    assert recording_git.calls() == []
    assert "git_exe" in caplog.text


def test_git_is_chosen_before_the_first_git_command_of_the_server():
    """The module runs its start-up statements in the order of the file; the ComfyUI version is read with git."""
    body = ast.parse((GLOB_DIR / "manager_server.py").read_text(encoding="utf-8")).body
    calls = [ast.unparse(node.value.func) for node in body if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)]
    steps = [call for call in calls if call in ("core.setup_git_executable", "print_comfyui_version")]

    assert steps == ["core.setup_git_executable", "print_comfyui_version"]


def script_env_of(manager_util, git_exe):
    return take(GLOB_DIR / "manager_core.py", "get_script_env", {
        "os": os, "comfy_path": "/comfy", "manager_util": manager_util,
        "manager_migration": SimpleNamespace(has_system_user_api=lambda: True),
        "get_config": lambda: {"git_exe": git_exe}, "working_git_exe": {},
    })


@pytest.mark.parametrize("protected", [True, False])
def test_scripts_are_given_the_git_of_a_protected_configuration(manager_util, recording_git, protected):
    get_script_env = take(GLOB_DIR / "manager_core.py", "get_script_env", {
        "os": os, "comfy_path": "/comfy", "manager_util": manager_util,
        "manager_migration": SimpleNamespace(has_system_user_api=lambda: protected),
        "get_config": lambda: {"git_exe": recording_git.path}, "working_git_exe": {},
    })

    assert get_script_env().get("GIT_EXE_PATH") == (recording_git.path if protected else None)


@pytest.mark.parametrize("git_exe", ["", None])
def test_scripts_are_given_no_git_without_the_setting(manager_util, git_exe):
    get_script_env = script_env_of(manager_util, git_exe)

    assert get_script_env().get("GIT_EXE_PATH") is None


def test_scripts_are_given_no_git_that_is_not_one(manager_util, not_a_git):
    get_script_env = script_env_of(manager_util, not_a_git)

    assert get_script_env().get("GIT_EXE_PATH") is None


def test_git_for_scripts_is_checked_once(manager_util, recording_git):
    """Every command of an install asks for the environment; the check starts a process."""
    get_script_env = script_env_of(manager_util, recording_git.path)

    assert [get_script_env().get("GIT_EXE_PATH") for _ in range(3)] == [recording_git.path] * 3
    assert recording_git.calls() == ["version"]


def test_git_for_scripts_that_was_no_git_is_checked_again(manager_util, recording_git, tmp_path):
    later = tmp_path / "installed-later"
    get_script_env = script_env_of(manager_util, str(later))

    assert get_script_env().get("GIT_EXE_PATH") is None
    shutil.copy(recording_git.path, later)
    assert get_script_env().get("GIT_EXE_PATH") == str(later)


def set_git_executable(manager_util, monkeypatch, git_exe, protected=True):
    """Run `set_git_executable` of `prestartup_script.py`; the variable GitPython reads when it is imported."""
    # set and removed, so that the variable the function sets is removed after the case, also when there was none
    monkeypatch.setenv("GIT_PYTHON_GIT_EXECUTABLE", "")
    monkeypatch.delenv("GIT_PYTHON_GIT_EXECUTABLE")
    config = configparser.ConfigParser(strict=False)
    config.read_string("[default]\n" + ("" if git_exe is None else f"git_exe = {git_exe}\n"))
    take(ROOT / "prestartup_script.py", "set_git_executable", {
        "os": os, "manager_util": manager_util, "_has_system_user_api": protected, "default_conf": config["default"],
    })()
    return os.environ.get("GIT_PYTHON_GIT_EXECUTABLE")


def test_git_is_known_before_gitpython_is_imported(manager_util, monkeypatch, recording_git):
    assert set_git_executable(manager_util, monkeypatch, recording_git.path) == recording_git.path


def test_case_that_set_the_variable_left_the_default_git():
    """Runs after the case above, which makes the function set the variable that GitPython reads."""
    assert os.environ.get("GIT_PYTHON_GIT_EXECUTABLE") is None
    assert git.Git.GIT_PYTHON_GIT_EXECUTABLE in ("git", shutil.which("git"))


def test_git_in_a_directory_with_a_percent_sign_is_known(manager_util, monkeypatch, recording_git, tmp_path):
    """A path of Windows may hold a `%`, which the parser takes as the start of a reference."""
    (tmp_path / "100%").mkdir()
    path = shutil.copy(recording_git.path, tmp_path / "100%" / "git")

    assert set_git_executable(manager_util, monkeypatch, str(path)) == str(path)


def test_start_up_without_a_configuration_file_sets_nothing(manager_util, monkeypatch):
    monkeypatch.setenv("GIT_PYTHON_GIT_EXECUTABLE", "")
    monkeypatch.delenv("GIT_PYTHON_GIT_EXECUTABLE")
    take(ROOT / "prestartup_script.py", "set_git_executable", {
        "os": os, "manager_util": manager_util, "_has_system_user_api": True, "default_conf": {},
    })()

    assert os.environ.get("GIT_PYTHON_GIT_EXECUTABLE") is None


def test_setting_with_a_percent_sign_is_read_as_written_and_the_others_kept():
    config = _run_child(r'''
        write_ini("[default]\ngit_exe = %LOCALAPPDATA%\\Git\\bin\\git.exe\ndb_mode = local\nnetwork_mode = offline\n")
        cfg = fresh_read()
        print(json.dumps([cfg["git_exe"], cfg["db_mode"], cfg["network_mode"]]))
    ''')

    assert config == ["%LOCALAPPDATA%\\Git\\bin\\git.exe", "local", "offline"]


@pytest.mark.parametrize("git_exe", ["", None])
def test_no_setting_leaves_the_environment_alone(manager_util, monkeypatch, git_exe):
    assert set_git_executable(manager_util, monkeypatch, git_exe) is None


def test_setting_of_an_unprotected_configuration_is_not_put_in_the_environment(manager_util, monkeypatch, recording_git):
    assert set_git_executable(manager_util, monkeypatch, recording_git.path, protected=False) is None


def test_setting_that_is_no_git_is_not_put_in_the_environment(manager_util, monkeypatch, not_a_git):
    assert set_git_executable(manager_util, monkeypatch, not_a_git) is None


def helper_setup_environment(git_exe):
    take(ROOT / "git_helper.py", "setup_environment", {"git": git, "sys": sys, "git_exe_path": git_exe})()


def test_helper_runs_the_git_it_is_given(recording_git, tmp_path):
    helper_setup_environment(recording_git.path)
    recording_git.forget()

    git.Repo.init(tmp_path / "repo")

    assert any(line.startswith("init") for line in recording_git.calls())


@pytest.mark.parametrize("git_exe", ["", None])
def test_helper_without_a_git_keeps_the_default(git_exe, capsys):
    default = git.Git.GIT_PYTHON_GIT_EXECUTABLE

    helper_setup_environment(git_exe)

    assert capsys.readouterr().err == "" and git.Git.GIT_PYTHON_GIT_EXECUTABLE == default


@pytest.mark.parametrize("kind", [kind for kind in NOT_A_GIT if kind != "a program that waits"])
def test_helper_reports_what_is_no_git_and_keeps_the_default(kind, tmp_path, capsys):
    default = git.Git.GIT_PYTHON_GIT_EXECUTABLE
    path = tmp_path / "not-a-git"
    if NOT_A_GIT[kind] is not None:
        path.write_text(NOT_A_GIT[kind])
        path.chmod(0o755)

    helper_setup_environment(str(path))

    assert str(path) in capsys.readouterr().err
    assert git.Git.GIT_PYTHON_GIT_EXECUTABLE == default
    git.Repo.init(tmp_path / "repo")
    assert Path(tmp_path / "repo" / ".git").is_dir()


def test_git_named_by_a_command_on_path_is_run_by_its_full_path(manager_util, tmp_path, monkeypatch):
    """GitPython takes a name without a directory as a file of the current directory."""
    monkeypatch.chdir(tmp_path)

    setup_git_executable(manager_util, "git")

    assert git.Git.GIT_PYTHON_GIT_EXECUTABLE == shutil.which("git")
    git.Repo.init(tmp_path / "repo")
    assert (tmp_path / "repo" / ".git").is_dir()


def test_scripts_and_gitpython_are_given_the_full_path_of_a_command_on_path(manager_util, monkeypatch):
    get_script_env = script_env_of(manager_util, "git")

    assert get_script_env().get("GIT_EXE_PATH") == shutil.which("git")
    assert set_git_executable(manager_util, monkeypatch, "git") == shutil.which("git")


def test_setting_saved_beside_a_git_exe_with_a_percent_sign_keeps_it():
    saved = _run_child(r'''
        write_ini("[default]\ngit_exe = %LOCALAPPDATA%\\Git\\bin\\git.exe\ndb_mode = local\n")
        cfg = fresh_read()
        cfg["db_mode"] = "remote"
        manager_core.write_config()
        print(json.dumps(sorted(line for line in open(CONFIG_PATH).read().splitlines() if line.startswith(("git_exe", "db_mode")))))
    ''')

    assert saved == ["db_mode = remote", "git_exe = %LOCALAPPDATA%\\Git\\bin\\git.exe"]
