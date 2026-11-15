"""The command line ComfyUI is restarted with keeps every argument as it was (#3339).

The reboot endpoints and the prestartup restart after an install re-exec ComfyUI with
os.execv. On Windows os.execv joins its arguments with spaces and quotes nothing, so
`--output-directory "D:\\My Outputs"` used to reach the new process as two arguments.
manager_util.build_restart_command quotes each argument there; other platforms get
the list unchanged. A ComfyUI started as a module is restarted with `python -m`.
"""

import ast
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


PACKAGE_DIR = Path(__file__).resolve().parent.parent / "comfyui_manager"
MANAGER_UTIL_PATH = PACKAGE_DIR / "common" / "manager_util.py"

TRICKY_ARGS = [
    "--browser-profile", "Profile 1",
    "--output-directory", "C:\\my dir\\",
    "--note", 'say "hi"',
    "--empty", "",
    "--port", "8188",
]


def load_manager_util():
    # By path: importing the package needs a running ComfyUI
    spec = importlib.util.spec_from_file_location("_manager_util_under_test", MANAGER_UTIL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MANAGER_UTIL = load_manager_util()


def test_windows_quotes_only_what_needs_quoting(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", "C:\\Program Files\\python.exe")

    cmds = MANAGER_UTIL.build_restart_command(["C:\\Comfy UI\\main.py"] + TRICKY_ARGS)

    assert cmds == [
        '"C:\\Program Files\\python.exe"',
        '"C:\\Comfy UI\\main.py"',
        "--browser-profile", '"Profile 1"',
        "--output-directory", '"C:\\my dir\\\\"',
        "--note", '"say \\"hi\\""',
        "--empty", '""',
        "--port", "8188",
    ]


def test_posix_passes_arguments_through(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "executable", "/usr/bin/python3")

    argv = ["/opt/Comfy UI/main.py"] + TRICKY_ARGS

    assert MANAGER_UTIL.build_restart_command(argv) == ["/usr/bin/python3"] + argv


def test_module_entry_point_uses_dash_m(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "executable", "/usr/bin/python3")

    cmds = MANAGER_UTIL.build_restart_command(["/opt/site-packages/comfy/__main__.py", "--port", "8188"])

    assert cmds == ["/usr/bin/python3", "-m", "comfy", "--port", "8188"]


def test_module_entry_point_is_quoted_on_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", "C:\\Program Files\\python.exe")

    # Forward slashes: the module name is then found by both the POSIX and the Windows os.path
    cmds = MANAGER_UTIL.build_restart_command(
        ["C:/site packages/comfy/__main__.py", "--browser-profile", "Profile 1"])

    assert cmds == ['"C:\\Program Files\\python.exe"', "-m", "comfy", "--browser-profile", '"Profile 1"']


def test_drop_args_removes_only_listed_arguments(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "executable", "/usr/bin/python3")
    argv = ["main.py", "--windows-standalone-build", "--cpu"]

    assert MANAGER_UTIL.build_restart_command(argv) == ["/usr/bin/python3"] + argv
    assert MANAGER_UTIL.build_restart_command(argv, drop_args=("--windows-standalone-build",)) == \
        ["/usr/bin/python3", "main.py", "--cpu"]
    assert argv == ["main.py", "--windows-standalone-build", "--cpu"]  # caller's list is untouched
    assert MANAGER_UTIL.build_restart_command(argv + ["--windows-standalone-build"], drop_args=("--windows-standalone-build",)) == \
        ["/usr/bin/python3", "main.py", "--cpu"]  # every occurrence
    assert MANAGER_UTIL.build_restart_command(["main.py", "--cpu"], drop_args=("--windows-standalone-build",)) == \
        ["/usr/bin/python3", "main.py", "--cpu"]  # nothing to drop


def run_restart_site(path, execv):
    """Run the restart code of `path` as it is written, up to `os.execv`, which is replaced by `execv`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    if path.name == "prestartup_script.py":
        nodes = [node for node in tree.body if isinstance(node, ast.If) and ast.unparse(node.test) == "script_executed"]
    else:
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "restart"]
    assert len(nodes) == 1, f"restart code not found in {path}"

    allow = SimpleNamespace(reject_simple_form_post=lambda request: None, is_allowed_security_level=lambda level: True)
    namespace = {
        "os": SimpleNamespace(environ={}, path=os.path, execv=execv),  # not a comfy-cli session
        "sys": sys,
        "manager_util": MANAGER_UTIL,
        "script_executed": True,
        "security_utils": allow, "manager_security": allow, "is_allowed_security_level": allow.is_allowed_security_level,
    }
    for node in nodes:
        if isinstance(node, ast.FunctionDef):
            node.decorator_list = []
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    if "restart" in namespace:
        namespace["restart"](None)


# ComfyUI opens a browser when it starts with --windows-standalone-build. A reboot endpoint
# restarts a ComfyUI whose page is already open, so it drops the flag (#1160). The prestartup
# restart happens before ComfyUI has opened anything, so the flag must stay there.
@pytest.mark.parametrize("site, drops_the_flag", [
    ("glob/manager_server.py", True),
    ("legacy/manager_server.py", True),
    ("prestartup_script.py", False),
])
def test_restart_site_runs_the_built_command(monkeypatch, site, drops_the_flag):
    flag = "--windows-standalone-build"
    for platform, executable, quoted_executable, directory, quoted_directory in [
        ("win32", "C:\\Program Files\\python.exe", '"C:\\Program Files\\python.exe"', "D:\\My Outputs", '"D:\\My Outputs"'),
        ("linux", "/usr/bin/python3", "/usr/bin/python3", "/data/My Outputs", "/data/My Outputs"),
    ]:
        for started_with_flag in (True, False):  # most installs do not start with the flag
            monkeypatch.setattr(sys, "platform", platform)
            monkeypatch.setattr(sys, "executable", executable)
            monkeypatch.setattr(sys, "argv", ["main.py"] + [flag] * started_with_flag + ["--output-directory", directory])
            calls = []

            run_restart_site(PACKAGE_DIR / site, lambda *args: calls.append(args))

            kept = [flag] * (started_with_flag and not drops_the_flag)
            assert calls == [(executable, [quoted_executable, "main.py"] + kept + ["--output-directory", quoted_directory])]


LAUNCHER = """
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location("_manager_util_under_test", sys.argv[1])
manager_util = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager_util)
os.execv(sys.executable, manager_util.build_restart_command(sys.argv[2:]))
"""

CHILD = """
import json, os, sys
with open(sys.argv[1] + ".tmp", "w", encoding="utf-8") as f:
    json.dump(sys.argv[2:], f)
os.replace(sys.argv[1] + ".tmp", sys.argv[1])
"""


def test_arguments_survive_a_real_execv(tmp_path):
    """End to end on the running platform: what the re-exec'ed process sees must equal what was sent."""
    work_dir = tmp_path / "dir with spaces"
    work_dir.mkdir()
    child = work_dir / "main entry.py"
    child.write_text(CHILD, encoding="utf-8")
    result_file = work_dir / "argv seen.json"

    subprocess.run(
        [sys.executable, "-c", LAUNCHER, str(MANAGER_UTIL_PATH), str(child), str(result_file)] + TRICKY_ARGS,
        check=True, timeout=60,
    )

    # On Windows os.execv returns control to the caller before the new process is done.
    deadline = time.time() + 30
    while not result_file.exists():
        if time.time() > deadline:
            pytest.fail("re-exec'ed process never reported its arguments")
        time.sleep(0.1)

    assert json.loads(result_file.read_text(encoding="utf-8")) == TRICKY_ARGS
