"""Minimal tests for git_helper standalone execution and get_backup_branch_name.

git_helper.py runs as a subprocess on Windows and must NOT import comfyui_manager.
Tests validate: (1) no forbidden imports via AST, (2) subprocess-level standalone
execution, (3) get_backup_branch_name behavioural correctness, for the copy in
git_helper.py and the copy in timestamp_utils.py that both cores call, (4) the name
each core gets for a real repository.
"""

import ast
import importlib.util
import pathlib
import subprocess
import sys
import textwrap

import pytest

_GIT_HELPER_PATH = pathlib.Path(__file__).resolve().parents[2] / "comfyui_manager" / "common" / "git_helper.py"


def _load_common_module(name):
    """Load a standalone module of comfyui_manager/common without importing the package."""
    spec = importlib.util.spec_from_file_location(name, _GIT_HELPER_PATH.with_name(f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# 1. No comfyui_manager imports (AST check — no execution)
# ---------------------------------------------------------------------------

def test_no_comfyui_manager_import():
    """git_helper.py must be free of comfyui_manager imports (Windows subprocess safety)."""
    tree = ast.parse(_GIT_HELPER_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "comfyui_manager" in node.module:
            pytest.fail(f"Forbidden import at line {node.lineno}: from {node.module}")


# ---------------------------------------------------------------------------
# 2. Standalone subprocess execution (mirrors the actual Windows bug scenario)
# ---------------------------------------------------------------------------

def test_standalone_subprocess_can_load(tmp_path):
    """git_helper.py must load in a subprocess without comfyui_manager on sys.path."""
    (tmp_path / "folder_paths.py").touch()

    # Run git_helper.py in a clean subprocess with stripped sys.path.
    # git_helper.py has a module-level sys.argv dispatcher that calls sys.exit,
    # so we set argv to --check with a dummy path to avoid IndexError, then
    # catch the SystemExit to verify the function loaded successfully.
    script = textwrap.dedent(f"""\
        import sys, os
        sys.path = [p for p in sys.path
                    if "comfyui_manager" not in p and "comfyui-manager" not in p]
        os.environ["COMFYUI_PATH"] = {str(tmp_path)!r}

        import importlib.util
        spec = importlib.util.spec_from_file_location("git_helper", {str(_GIT_HELPER_PATH)!r})
        mod = importlib.util.module_from_spec(spec)

        # Intercept sys.exit from module-level argv dispatcher
        real_exit = sys.exit
        exit_code = [None]
        def fake_exit(code=0):
            exit_code[0] = code
            raise SystemExit(code)
        sys.exit = fake_exit

        try:
            spec.loader.exec_module(mod)
        except SystemExit:
            pass
        finally:
            sys.exit = real_exit

        # The function must be defined regardless of argv dispatcher outcome
        assert hasattr(mod, "get_backup_branch_name"), "Function not defined"
        name = mod.get_backup_branch_name()
        assert name.startswith("backup_"), f"Bad name: {{name}}"
        print(f"OK: {{name}}")
    """)

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "OK: backup_" in result.stdout


# ---------------------------------------------------------------------------
# 3. get_backup_branch_name behavioural tests, for both copies of the function
# ---------------------------------------------------------------------------

@pytest.fixture(params=["git_helper", "timestamp_utils"])
def _get_backup_branch_name(request, monkeypatch):
    """Return get_backup_branch_name from git_helper.py or from timestamp_utils.py."""
    import time

    # Branch setup and the function call must use the same second.
    strftime = time.strftime
    fixed_time = time.struct_time((2026, 9, 17, 12, 0, 0, 3, 260, -1))
    monkeypatch.setattr(time, "strftime", lambda fmt, *args: strftime(fmt, args[0] if args else fixed_time))

    if request.param == "timestamp_utils":
        timestamp_utils = _load_common_module("timestamp_utils")
        monkeypatch.setattr(timestamp_utils, "get_timestamp_for_filename", lambda: time.strftime("%Y%m%d_%H%M%S"))
        return timestamp_utils.get_backup_branch_name

    # git_helper.py runs its command line on import, so the function is compiled from its source.
    source = _GIT_HELPER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "get_backup_branch_name":
            func_source = ast.get_source_segment(source, node)
            assert func_source is not None
            ns = {}
            exec(compile(ast.parse(func_source), "<test>", "exec"), ns)  # noqa: S102
            return ns["get_backup_branch_name"]

    pytest.fail("get_backup_branch_name not found in git_helper.py")


class _FakeHead:
    def __init__(self, name):
        self.name = name


class _FakeRepo:
    def __init__(self, branch_names):
        self._heads = [_FakeHead(n) for n in branch_names]

    def list_heads(self):
        return self._heads


def test_basic_name_format(_get_backup_branch_name):
    import time
    assert _get_backup_branch_name() == f"backup_{time.strftime('%Y%m%d_%H%M%S')}"


def test_no_collision(_get_backup_branch_name):
    import time
    repo = _FakeRepo(["main", "dev"])
    assert _get_backup_branch_name(repo) == f"backup_{time.strftime('%Y%m%d_%H%M%S')}"


def test_single_collision(_get_backup_branch_name):
    import time
    ts = time.strftime("%Y%m%d_%H%M%S")
    repo = _FakeRepo(["main", f"backup_{ts}"])
    name = _get_backup_branch_name(repo)
    assert name == f"backup_{ts}_1"


def test_multi_collision(_get_backup_branch_name):
    import time
    ts = time.strftime("%Y%m%d_%H%M%S")
    repo = _FakeRepo([f"backup_{ts}", f"backup_{ts}_1", f"backup_{ts}_2"])
    name = _get_backup_branch_name(repo)
    assert name == f"backup_{ts}_3"


def test_repo_list_heads_exception_returns_base(_get_backup_branch_name):
    """When listing branches fails, return the timestamp without a suffix."""
    import time

    class _BrokenRepo:
        def list_heads(self):
            raise RuntimeError("simulated git error")

    name = _get_backup_branch_name(_BrokenRepo())
    assert name == f"backup_{time.strftime('%Y%m%d_%H%M%S')}"


def test_uuid_fallback_on_full_collision(_get_backup_branch_name):
    """When all 99 suffixes are taken, fall back to UUID."""
    import time
    ts = time.strftime("%Y%m%d_%H%M%S")
    # All names from backup_TS through backup_TS_99 are taken
    taken = [f"backup_{ts}"] + [f"backup_{ts}_{i}" for i in range(1, 100)]
    repo = _FakeRepo(taken)
    name = _get_backup_branch_name(repo)
    assert name.startswith(f"backup_{ts}_")
    # UUID suffix is 6 hex chars
    suffix = name[len(f"backup_{ts}_"):]
    assert len(suffix) == 6, f"Expected 6-char UUID suffix, got: {suffix}"


# ---------------------------------------------------------------------------
# 4. The name each core gets for a real repository
# ---------------------------------------------------------------------------

def _open_as_legacy_core(path):
    """The legacy core opens GitPython's git.Repo, which has `heads` and no `list_heads()`."""
    import git
    return git.Repo(path)


def _open_as_glob_core(path):
    """The glob core opens the repository through git_compat."""
    return _load_common_module("git_compat").open_repo(str(path))


@pytest.mark.parametrize("open_repo", [_open_as_legacy_core, _open_as_glob_core], ids=["legacy core", "glob core"])
def test_real_repository_with_a_backup_from_the_same_second(open_repo, tmp_path, monkeypatch):
    """A backup branch of the same second exists, so the next free name is returned."""
    git = pytest.importorskip("git")
    timestamp_utils = _load_common_module("timestamp_utils")
    monkeypatch.setattr(timestamp_utils, "get_timestamp_for_filename", lambda: "20260917_120000")

    with git.Repo.init(tmp_path) as repo:
        repo.index.commit("initial")
        repo.create_head("backup_20260917_120000")

    with open_repo(tmp_path) as repo:
        assert timestamp_utils.get_backup_branch_name(repo) == "backup_20260917_120000_1"
