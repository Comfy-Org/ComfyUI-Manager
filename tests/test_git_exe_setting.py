import ast
import configparser
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

import git
import pytest

from _install_flags_testutil import GIT_LOCATION, import_context, import_reader
from legacy_html_testutil import PACKAGE, load_functions

pytestmark = pytest.mark.skipif(os.name == "nt", reason="the executables of the cases are shell scripts")

COMMON = PACKAGE / "common"
NOT_A_GIT = {
    "a path that does not exist": None,
    "a program that fails": "#!/bin/sh\nexit 3\n",
    "a program that is not git": "#!/bin/sh\necho hello\n",
    "a program that waits": "#!/bin/sh\nexec sleep 30\n",
    "a program that prints bytes that are not text": "#!/bin/sh\nprintf '\\377\\376'\n",
    "a file that cannot be run": "not a program\n",
}
IMPORT = """
import json, sys
sys.path.insert(0, {common!r})
import git_compat
git_compat.find_git_executable.__defaults__ = (2,)
used = None
if not git_compat.USE_PYGIT2:
    import git
    git.Repo.init({repo!r})
    used = git.Git.GIT_PYTHON_GIT_EXECUTABLE
print(json.dumps({{"pygit2": git_compat.USE_PYGIT2, "git": used}}))
"""


@pytest.fixture(autouse=True)
def git_finds_its_repository_by_the_directory(monkeypatch):
    for name in (*GIT_LOCATION, 'GIT_EXE_PATH', 'GIT_PYTHON_GIT_EXECUTABLE'):
        monkeypatch.delenv(name, raising=False)


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


@pytest.fixture
def imported(tmp_path):
    def imported(git_exe=None, git_on_path=True, pygit2=False):
        env = {key: value for key, value in os.environ.items()
               if key not in ("GIT_EXE_PATH", "GIT_PYTHON_GIT_EXECUTABLE", "GIT_PYTHON_REFRESH", "CM_USE_PYGIT2")}
        if git_exe is not None:
            env["GIT_EXE_PATH"] = git_exe
        if not git_on_path:
            (tmp_path / "no-git").mkdir()
            env["PATH"] = str(tmp_path / "no-git")
        if pygit2:
            env["CM_USE_PYGIT2"] = "1"
        code = IMPORT.format(common=str(COMMON), repo=str(tmp_path / "repo"))
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout.strip().splitlines()[-1]), result.stderr

    return imported


def test_configured_git_is_run(imported, recording_git):
    assert imported(recording_git.path)[0] == {"pygit2": False, "git": recording_git.path}
    assert any(line.startswith("init") for line in recording_git.calls())


def test_configured_git_is_run_without_a_git_on_path(imported, recording_git):
    assert imported(recording_git.path, git_on_path=False)[0] == {"pygit2": False, "git": recording_git.path}
    assert any(line.startswith("init") for line in recording_git.calls())


@pytest.mark.parametrize("git_exe", [None, ""])
def test_no_setting_keeps_the_default_git(imported, git_exe):
    state, reported = imported(git_exe)

    assert state == {"pygit2": False, "git": "git"}
    assert "git_exe" not in reported


def test_setting_that_is_no_git_is_reported_and_the_default_kept(imported, not_a_git):
    state, reported = imported(not_a_git)

    assert state == {"pygit2": False, "git": "git"}
    assert not_a_git in reported


LATE = """
import json, os, sys
import git
sys.path.insert(0, {common!r})
import git_compat
git_compat.setup_git_environment(os.environ["GIT_EXE_PATH"])
git.Repo.init({repo!r})
print(json.dumps(git.Git.GIT_PYTHON_GIT_EXECUTABLE))
"""


def test_configured_git_is_run_when_gitpython_was_imported_first(recording_git, tmp_path):
    env = {key: value for key, value in os.environ.items() if key not in ("GIT_PYTHON_GIT_EXECUTABLE", "CM_USE_PYGIT2")}
    env["GIT_EXE_PATH"] = recording_git.path
    code = LATE.format(common=str(COMMON), repo=str(tmp_path / "repo"))
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == recording_git.path
    assert any(line.startswith("init") for line in recording_git.calls())


def test_what_was_refused_at_the_import_is_not_selected_or_reported_again(tmp_path):
    fails = tmp_path / "fails"
    fails.write_text("#!/bin/sh\nexit 3\n")
    fails.chmod(0o755)
    env = {key: value for key, value in os.environ.items() if key not in ("GIT_PYTHON_GIT_EXECUTABLE", "CM_USE_PYGIT2")}
    env["GIT_EXE_PATH"] = str(fails)
    code = LATE.format(common=str(COMMON), repo=str(tmp_path / "repo"))
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == "git"
    assert result.stderr.count(str(fails)) == 1


def test_git_compat_is_imported_without_any_git(tmp_path):
    (tmp_path / "no-git").mkdir()
    (tmp_path / "no-pygit2").mkdir()
    (tmp_path / "no-pygit2" / "pygit2.py").write_text("raise ImportError('pygit2 is not installed')\n")
    env = {key: value for key, value in os.environ.items()
           if key not in ("GIT_EXE_PATH", "GIT_PYTHON_GIT_EXECUTABLE", "GIT_PYTHON_REFRESH", "CM_USE_PYGIT2")}
    env["PATH"] = str(tmp_path / "no-git")
    code = (f"import sys; sys.path[:0] = [{str(tmp_path / 'no-pygit2')!r}, {str(COMMON)!r}]\n"
            "import git_compat, git\n"
            "try:\n    git.Git().version()\nexcept git.GitCommandNotFound:\n    print('fails at use')\n")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "fails at use"
    assert "no git" in result.stderr.lower()


def test_gitpython_can_be_imported_beside_the_pygit2_backend_without_a_git(tmp_path):
    pytest.importorskip("pygit2")
    (tmp_path / "no-git").mkdir()
    env = {key: value for key, value in os.environ.items()
           if key not in ("GIT_EXE_PATH", "GIT_PYTHON_GIT_EXECUTABLE", "GIT_PYTHON_REFRESH", "CM_USE_PYGIT2")}
    env["PATH"] = str(tmp_path / "no-git")
    code = f"import sys; sys.path.insert(0, {str(COMMON)!r})\nimport git_compat, git\nprint(git_compat.USE_PYGIT2)\n"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "True"


def test_configured_git_is_run_when_pygit2_is_asked_for_but_not_installed(recording_git, tmp_path):
    (tmp_path / "no-git").mkdir()
    (tmp_path / "no-pygit2").mkdir()
    (tmp_path / "no-pygit2" / "pygit2.py").write_text("raise ImportError('pygit2 is not installed')\n")
    env = {key: value for key, value in os.environ.items() if key not in ("GIT_PYTHON_GIT_EXECUTABLE", "GIT_PYTHON_REFRESH")}
    env.update(PATH=str(tmp_path / "no-git"), GIT_EXE_PATH=recording_git.path, CM_USE_PYGIT2="1")
    code = (f"import json, os, sys; sys.path[:0] = [{str(tmp_path / 'no-pygit2')!r}, {str(COMMON)!r}]\n"
            "import git_compat, git\n"
            "git_compat.setup_git_environment(os.environ['GIT_EXE_PATH'])\n"
            f"git.Repo.init({str(tmp_path / 'repo')!r})\n"
            "print(json.dumps([git_compat.USE_PYGIT2, git.Git.GIT_PYTHON_GIT_EXECUTABLE]))\n")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == [False, recording_git.path]
    assert any(line.startswith("init") for line in recording_git.calls())


def test_gitpython_is_imported_by_prestartup_after_the_setting_is_handed_on():
    body = ast.parse((PACKAGE / "prestartup_script.py").read_text(encoding="utf-8")).body
    steps = []
    for node in body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and ast.unparse(node.value.func) == "set_git_executable":
            steps.append("setting")
        elif isinstance(node, (ast.Import, ast.ImportFrom)) and any(name in ast.unparse(node) for name in ("git_compat", "context", "import git")):
            steps.append("GitPython")

    assert steps == ["setting", "GitPython"]


def test_git_named_by_a_command_on_path_is_run_by_its_full_path(imported, git_compat, tmp_path, monkeypatch):
    """GitPython takes a name without a directory as a file of the current directory."""
    assert imported("git")[0] == {"pygit2": False, "git": shutil.which("git")}

    monkeypatch.chdir(tmp_path)
    git_compat.setup_git_environment("git")

    assert git.Git.GIT_PYTHON_GIT_EXECUTABLE == shutil.which("git")


def test_git_named_by_a_command_is_not_taken_from_the_current_directory(git_compat, recording_git, tmp_path, monkeypatch):
    """Windows looks for a command in the current directory first. Here it is PATH that names that directory."""
    default = shutil.which("git")
    shutil.copy(recording_git.path, tmp_path / "git")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", os.pathsep.join([".", os.environ["PATH"]]))

    git_compat.setup_git_environment("git")

    assert git.Git.GIT_PYTHON_GIT_EXECUTABLE == default
    assert recording_git.calls() == []


def test_pygit2_backend_does_not_use_the_setting(imported, recording_git):
    pytest.importorskip("pygit2")

    assert imported(recording_git.path, pygit2=True)[0] == {"pygit2": True, "git": None}
    assert recording_git.calls() == []


@pytest.fixture
def git_compat(monkeypatch):
    for name in ("CM_USE_PYGIT2", "GIT_EXE_PATH"):
        monkeypatch.delenv(name, raising=False)
    spec = importlib.util.spec_from_file_location("_git_compat_under_test", COMMON / "git_compat.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert not module.USE_PYGIT2
    find = module.find_git_executable
    monkeypatch.setattr(module, "find_git_executable", lambda git_exe, timeout=2: find(git_exe, timeout=timeout))
    yield module
    git.refresh()


def test_git_given_after_the_import_is_run(git_compat, recording_git, tmp_path):
    git_compat.setup_git_environment(recording_git.path)
    recording_git.forget()

    git.Repo.init(tmp_path / "repo")

    assert any(line.startswith("init") for line in recording_git.calls())


@pytest.mark.parametrize("git_exe", ["", None])
def test_nothing_given_after_the_import_keeps_the_default(git_compat, git_exe, capsys):
    default = git.Git.GIT_PYTHON_GIT_EXECUTABLE
    capsys.readouterr()

    git_compat.setup_git_environment(git_exe)

    assert capsys.readouterr().err == "" and git.Git.GIT_PYTHON_GIT_EXECUTABLE == default


def test_what_is_no_git_given_after_the_import_is_reported(git_compat, not_a_git, tmp_path, capsys):
    default = git.Git.GIT_PYTHON_GIT_EXECUTABLE
    flags = git.remote.FetchInfo._flag_map.copy()

    git_compat.setup_git_environment(not_a_git)

    assert not_a_git in capsys.readouterr().err
    assert git.Git.GIT_PYTHON_GIT_EXECUTABLE == default and git.remote.FetchInfo._flag_map == flags
    git.Repo.init(tmp_path / "repo")
    assert (tmp_path / "repo" / ".git").is_dir()


def test_check_does_not_wait_for_a_program_that_the_setting_started(git_compat, tmp_path):
    """With a pipe for the answer, the check would wait for every program that holds the pipe: on Windows also after its time is up."""
    executable = tmp_path / "starts-a-program"
    executable.write_text(f'#!/bin/sh\nsleep 30 &\necho $! > "{tmp_path}/pid"\n')
    executable.chmod(0o755)
    started = time.monotonic()

    try:
        assert git_compat.find_git_executable(str(executable), timeout=20) is None
        assert time.monotonic() - started < 10
    finally:
        os.kill(int((tmp_path / "pid").read_text()), signal.SIGTERM)


PERCENT = "%LOCALAPPDATA%\\Git\\bin\\git.exe"


def set_git_executable(monkeypatch, git_exe):
    # set and removed, so that the variable the function sets is removed after the case, also when there was none
    monkeypatch.setenv("GIT_EXE_PATH", "")
    monkeypatch.delenv("GIT_EXE_PATH")
    config = configparser.ConfigParser(strict=False)
    config.read_string("[default]\n" + ("" if git_exe is None else f"git_exe = {git_exe}\n"))
    load_functions(PACKAGE / "prestartup_script.py", {"set_git_executable"}, {"os": os, "default_conf": config["default"]})["set_git_executable"]()
    return os.environ.get("GIT_EXE_PATH")


@pytest.mark.parametrize("git_exe, given", [("/opt/git/bin/git", "/opt/git/bin/git"), (PERCENT, PERCENT), ("", None), (None, None)])
def test_prestartup_hands_the_setting_to_git_compat(monkeypatch, git_exe, given):
    assert set_git_executable(monkeypatch, git_exe) == given


def test_prestartup_without_a_configuration_file_sets_nothing(monkeypatch):
    monkeypatch.setenv("GIT_EXE_PATH", "")
    monkeypatch.delenv("GIT_EXE_PATH")
    load_functions(PACKAGE / "prestartup_script.py", {"set_git_executable"}, {"os": os, "default_conf": {}})["set_git_executable"]()

    assert os.environ.get("GIT_EXE_PATH") is None


@pytest.mark.parametrize("core", ["glob", "legacy"])
def test_setting_with_a_percent_sign_is_read_as_written_and_the_others_kept(core, monkeypatch, tmp_path):
    """A path of Windows may hold a `%`, which the parser takes as the start of a reference."""
    (tmp_path / "config.ini").write_text(f"[default]\ngit_exe = {PERCENT}\ndb_mode = local\nnetwork_mode = offline\n")
    monkeypatch.setattr(import_context(), "manager_config_path", str(tmp_path / "config.ini"))

    config = import_reader(core).read_config()

    assert (config["git_exe"], config["db_mode"], config["network_mode"]) == (PERCENT, "local", "offline")


@pytest.mark.parametrize("core", ["glob", "legacy"])
def test_setting_saved_beside_a_git_exe_with_a_percent_sign_keeps_it(core, monkeypatch, tmp_path):
    path = tmp_path / "config.ini"
    path.write_text(f"[default]\ngit_exe = {PERCENT}\ndb_mode = local\n")
    monkeypatch.setattr(import_context(), "manager_config_path", str(path))
    module = import_reader(core)
    monkeypatch.setattr(module, "cached_config", None)

    module.get_config()["db_mode"] = "remote"
    module.write_config()

    assert sorted(line for line in path.read_text().splitlines() if line.startswith(("git_exe", "db_mode"))) == [
        "db_mode = remote", f"git_exe = {PERCENT}"]


@pytest.mark.parametrize("where", ["legacy/manager_server.py", "glob/utils/environment_utils.py"])
def test_callers_pass_the_setting_on(where):
    passed = []
    load_functions(PACKAGE / where, {"setup_environment"}, {
        "setup_git_environment": passed.append,
        "core": SimpleNamespace(get_config=lambda: {"git_exe": "/opt/git/bin/git"}),
    })["setup_environment"]()

    assert passed == ["/opt/git/bin/git"]


def test_git_helper_runs_the_git_of_the_process_that_starts_it(recording_git, tmp_path):
    origin, pack = tmp_path / "origin", tmp_path / "pack"

    def git(where, *args):
        return subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args],
                              cwd=where, check=True, capture_output=True, text=True).stdout.strip()

    origin.mkdir()
    git(origin, "init", "-q")
    git(origin, "commit", "-q", "--allow-empty", "-m", "first")
    git(tmp_path, "clone", "-q", str(origin), str(pack))
    git(origin, "commit", "-q", "--allow-empty", "-m", "second")
    (tmp_path / "folder_paths.py").touch()
    env = {key: value for key, value in os.environ.items() if key not in ("GIT_PYTHON_REFRESH", "CM_USE_PYGIT2")}
    env.update(GIT_EXE_PATH=recording_git.path, COMFYUI_PATH=str(tmp_path))

    helper = subprocess.run([sys.executable, str(COMMON / "git_helper.py"), "--pull", str(pack)], cwd=str(tmp_path), env=env, capture_output=True, timeout=60)

    assert helper.returncode == 0, helper.stdout + helper.stderr
    assert git(pack, "rev-parse", "HEAD") == git(origin, "rev-parse", "HEAD")
    assert any(line.startswith("fetch") for line in recording_git.calls())
