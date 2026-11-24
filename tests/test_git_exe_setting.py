import ast
import configparser
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
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
    function = [node for node in ast.parse(path.read_text(encoding="utf-8")).body
                if isinstance(node, ast.FunctionDef) and node.name == name]
    assert len(function) == 1
    exec(compile(ast.Module(body=function, type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


@pytest.fixture
def manager_util(monkeypatch):
    module = load_manager_util()
    find = module.find_git_executable
    monkeypatch.setattr(module, "find_git_executable", lambda git_exe, timeout=2: find(git_exe, timeout=timeout))
    return module


@pytest.fixture(autouse=True)
def default_git(monkeypatch):
    for name in (*GIT_LOCATION, 'GIT_PYTHON_GIT_EXECUTABLE'):
        monkeypatch.delenv(name, raising=False)
    # GitPython keeps the git that the variable of the shell named when it last looked
    git.refresh()
    yield
    # the variables a case set are removed before GitPython looks for its git again
    monkeypatch.undo()
    git.refresh()


@pytest.fixture
def recording_git(tmp_path):
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


def set_git_executable(manager_util, monkeypatch, git_exe, protected=True):
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


def test_gitpython_is_imported_without_a_git_on_path(manager_util, monkeypatch, recording_git, tmp_path):
    """GitPython looks for its git when it is imported, and the import fails when it finds none."""
    set_git_executable(manager_util, monkeypatch, recording_git.path)
    (tmp_path / "empty").mkdir()
    recording_git.forget()

    imported = subprocess.run([sys.executable, "-c", "import git, sys; git.Repo.init(sys.argv[1])", str(tmp_path / "repository")],
                              env={**os.environ, "PATH": str(tmp_path / "empty")}, capture_output=True, text=True)

    assert imported.returncode == 0, imported.stderr
    assert any(call.startswith("init") for call in recording_git.calls())


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


def test_git_named_by_a_command_on_path_is_run_by_its_full_path(manager_util, tmp_path, monkeypatch):
    """GitPython takes a name without a directory as a file of the current directory."""
    monkeypatch.chdir(tmp_path)

    setup_git_executable(manager_util, "git")

    assert git.Git.GIT_PYTHON_GIT_EXECUTABLE == shutil.which("git")
    git.Repo.init(tmp_path / "repo")
    assert (tmp_path / "repo" / ".git").is_dir()


def test_git_named_by_a_command_is_not_taken_from_the_current_directory(manager_util, recording_git, tmp_path, monkeypatch):
    """Windows looks for a command in the current directory first. Here it is PATH that names that directory."""
    default = shutil.which("git")
    shutil.copy(recording_git.path, tmp_path / "git")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", os.pathsep.join([".", os.environ["PATH"]]))

    setup_git_executable(manager_util, "git")

    assert git.Git.GIT_PYTHON_GIT_EXECUTABLE == default
    assert recording_git.calls() == []


def test_check_does_not_wait_for_a_program_that_the_setting_started(manager_util, tmp_path):
    """With a pipe for the answer, the check would wait for every program that holds the pipe: on Windows also after its time is up."""
    executable = tmp_path / "starts-a-program"
    executable.write_text(f'#!/bin/sh\nsleep 30 &\necho $! > "{tmp_path}/pid"\n')
    executable.chmod(0o755)
    started = time.monotonic()

    try:
        assert manager_util.find_git_executable(str(executable), timeout=20) is None
        assert time.monotonic() - started < 10
    finally:
        os.kill(int((tmp_path / "pid").read_text()), signal.SIGTERM)


def test_setting_saved_beside_a_git_exe_with_a_percent_sign_keeps_it():
    saved = _run_child(r'''
        write_ini("[default]\ngit_exe = %LOCALAPPDATA%\\Git\\bin\\git.exe\ndb_mode = local\n")
        cfg = fresh_read()
        cfg["db_mode"] = "remote"
        manager_core.write_config()
        print(json.dumps(sorted(line for line in open(CONFIG_PATH).read().splitlines() if line.startswith(("git_exe", "db_mode")))))
    ''')

    assert saved == ["db_mode = remote", "git_exe = %LOCALAPPDATA%\\Git\\bin\\git.exe"]


def test_git_helper_runs_the_git_of_the_process_that_starts_it(recording_git, tmp_path):
    result = _run_child(f'''
        import pathlib, subprocess
        write_ini("[default]\\ngit_exe = {recording_git.path}\\n")
        fresh_read()
        manager_core.manager_migration.has_system_user_api = lambda: True
        manager_core.setup_git_executable()
        work = pathlib.Path({str(tmp_path)!r})
        (work / "folder_paths.py").touch()

        def git(where, *args):
            return subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args],
                                  cwd=where, check=True, capture_output=True, text=True).stdout.strip()

        (work / "origin").mkdir()
        git(work / "origin", "init", "-q")
        git(work / "origin", "commit", "-q", "--allow-empty", "-m", "first")
        git(work, "clone", "-q", str(work / "origin"), "pack")
        git(work / "origin", "commit", "-q", "--allow-empty", "-m", "second")
        (work / "calls").unlink(missing_ok=True)
        helper = subprocess.run([sys.executable, manager_core.git_script_path, "--pull", str(work / "pack")], cwd=str(work),
                                env={{**manager_core.get_script_env(), "COMFYUI_PATH": str(work)}}, capture_output=True)
        print(json.dumps([helper.returncode, git(work / "pack", "rev-parse", "HEAD") == git(work / "origin", "rev-parse", "HEAD")]))
    ''')

    assert result == [0, True]
    assert any(line.startswith("pull") for line in recording_git.calls())
