"""Regression tests for the restart command rebuild (#3339).

On Windows os.execv joins the argv list with plain spaces and no quoting,
so an argument containing spaces used to arrive at the child split in two
(an ``--extra-model-path-config`` pointing at a directory with a space in
its name became two arguments). build_restart_cmds pre-quotes each element
the way subprocess.list2cmdline would.
"""

import os
import subprocess
import sys

from manager_test_utils import load_manager_util

MANAGER_UTIL = load_manager_util()


def test_spaces_survive_the_roundtrip_on_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    dir_with_space = "my" + chr(32) + "configs"
    argv = [
        "C:" + os.sep + "python" + os.sep + "python.exe",
        "C:" + os.sep + "ComfyUI" + os.sep + "main.py",
        "--extra-model-path-config",
        "C:" + os.sep + dir_with_space + os.sep + "extra.yaml",
    ]
    cmds = MANAGER_UTIL.build_restart_cmds(argv)
    # sys.executable is prepended; every element is pre-quoted exactly the
    # way list2cmdline quotes it (execv's join then reconstructs argv)
    assert len(cmds) == len(argv) + 1
    assert cmds[0] == subprocess.list2cmdline([sys.executable])
    for raw, cmd in zip(argv[:-1], cmds[1:-1]):
        assert cmd == raw, (raw, cmd)
    assert cmds[-1] == subprocess.list2cmdline([argv[-1]])
    assert dir_with_space in cmds[-1]
    # and the joined command line must survive a list2cmdline-style re-split
    joined = " ".join(cmds)
    assert subprocess.list2cmdline([dir_with_space]) in joined or dir_with_space in joined


def test_standalone_build_flag_is_dropped(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    argv = ["python.exe", "main.py", "--windows-standalone-build", "--cpu"]
    cmds = MANAGER_UTIL.build_restart_cmds(argv)
    assert not any("standalone" in c for c in cmds)
    assert cmds[-1] == "--cpu"


def test_posix_stays_a_plain_list(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    argv = ["/usr/bin/python3", "/opt/ComfyUI/main.py", "--port", "8188"]
    # the original code prepends sys.executable and keeps argv[0] after it
    assert MANAGER_UTIL.build_restart_cmds(argv) == [sys.executable] + argv


def test_module_invocation_uses_m_form(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    argv = ["/opt/ComfyUI/site-packages/ComfyUI/__main__.py", "--port", "8188"]
    cmds = MANAGER_UTIL.build_restart_cmds(argv)
    assert cmds[0] == sys.executable
    # module_name is the parent dir's basename, exactly as the original code
    assert cmds[1:3] == ["-m", "ComfyUI"]
