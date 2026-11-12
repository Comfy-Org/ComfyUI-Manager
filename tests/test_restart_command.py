"""Regression tests for the restart command line (#3339).

Both restart paths (the reboot endpoint and the prestartup restart after a
dependency install) re-exec ComfyUI with os.execv. On Windows os.execv joins
its arguments with spaces and quotes nothing, so `--browser-profile "Profile 1"`
used to reach the new process as `--browser-profile Profile 1`.
"""
import ast
import json
import os
import subprocess
import sys
import time

import pytest

from manager_test_utils import GLOB_DIR, load_manager_util

MANAGER_UTIL = load_manager_util()

BACKSLASH = chr(92)
TRICKY_ARGS = [
    "--browser-profile", "Profile 1",
    "--output-directory", "C:" + BACKSLASH + "my dir" + BACKSLASH,
    "--note", 'say "hi"',
    "--empty", "",
    "--port", "8188",
]


def test_windows_quotes_only_what_needs_quoting(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", "C:" + BACKSLASH + "Program Files" + BACKSLASH + "python.exe")

    cmds = MANAGER_UTIL.build_restart_command(["C:" + BACKSLASH + "Comfy UI" + BACKSLASH + "main.py"] + TRICKY_ARGS)

    assert cmds == [
        '"C:' + BACKSLASH + 'Program Files' + BACKSLASH + 'python.exe"',
        '"C:' + BACKSLASH + 'Comfy UI' + BACKSLASH + 'main.py"',
        "--browser-profile", '"Profile 1"',
        "--output-directory", '"C:' + BACKSLASH + 'my dir' + BACKSLASH * 2 + '"',
        "--note", '"say ' + BACKSLASH + '"hi' + BACKSLASH + '""',
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
    monkeypatch.setattr(sys, "executable", "C:" + BACKSLASH + "Program Files" + BACKSLASH + "python.exe")

    # Forward slashes: the module name is then found by both the POSIX and the Windows os.path
    cmds = MANAGER_UTIL.build_restart_command(
        ["C:/site packages/comfy/__main__.py", "--browser-profile", "Profile 1"])

    assert cmds == [
        '"C:' + BACKSLASH + 'Program Files' + BACKSLASH + 'python.exe"',
        "-m", "comfy",
        "--browser-profile", '"Profile 1"',
    ]


def test_drop_args_removes_only_listed_arguments(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "executable", "/usr/bin/python3")
    argv = ["main.py", "--windows-standalone-build", "--cpu"]

    assert MANAGER_UTIL.build_restart_command(argv) == ["/usr/bin/python3"] + argv
    assert MANAGER_UTIL.build_restart_command(argv, drop_args=("--windows-standalone-build",)) == \
        ["/usr/bin/python3", "main.py", "--cpu"]
    assert argv == ["main.py", "--windows-standalone-build", "--cpu"]  # caller's list is untouched


def restart_call_drop_args(path):
    """The `drop_args` that the one restart site in `path` passes for `sys.argv`."""
    calls = [node for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
             if isinstance(node, ast.Call) and ast.unparse(node.func) == "manager_util.build_restart_command"]
    assert len(calls) == 1, f"expected one restart site in {path.name}"
    call = calls[0]
    assert ast.unparse(call.args[0]) == "sys.argv"

    drop_args = call.args[1:] + [keyword.value for keyword in call.keywords if keyword.arg == "drop_args"]
    assert len(call.args) + len(call.keywords) == 1 + len(drop_args), "unexpected argument"
    return tuple(ast.literal_eval(drop_args[0])) if drop_args else ()


def test_only_the_reboot_endpoint_drops_the_standalone_build_flag():
    # ComfyUI opens a browser when it starts with this flag. The reboot endpoint restarts a
    # ComfyUI whose page is already open, so it drops the flag (#1160).
    assert restart_call_drop_args(GLOB_DIR / "manager_server.py") == ("--windows-standalone-build",)

    prestartup_script = GLOB_DIR.resolve().parent / "prestartup_script.py"
    if os.environ.get("MANAGER_GLOB_DIR") and not prestartup_script.exists():
        pytest.skip("MANAGER_GLOB_DIR points at a glob directory without prestartup_script.py beside it")
    # The prestartup restart happens before ComfyUI has opened anything, so the flag must stay.
    assert restart_call_drop_args(prestartup_script) == ()


LAUNCHER = """
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location("_manager_util_under_test", sys.argv[1])
manager_util = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager_util)
os.execv(sys.executable, manager_util.build_restart_command(sys.argv[2:]))
"""

CHILD = """
import json, sys
with open(sys.argv[1] + ".tmp", "w", encoding="utf-8") as f:
    json.dump(sys.argv[2:], f)
import os
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
        [sys.executable, "-c", LAUNCHER, str(GLOB_DIR / "manager_util.py"), str(child), str(result_file)] + TRICKY_ARGS,
        check=True, timeout=60,
    )

    # On Windows os.execv returns control to the caller before the new process is done.
    deadline = time.time() + 30
    while not result_file.exists():
        if time.time() > deadline:
            pytest.fail("re-exec'ed process never reported its arguments")
        time.sleep(0.1)

    assert json.loads(result_file.read_text(encoding="utf-8")) == TRICKY_ARGS
