"""Regression tests for restore_pip_snapshot's success handling (#3259-class
found during audit): check_output returns the child's OUTPUT, not an exit
code, so `res != 0` was always true — every bulk install was retried package
by package with --no-deps and the summary always claimed total failure."""

import subprocess
from unittest.mock import patch

from manager_test_utils import load_manager_util

MANAGER_UTIL = load_manager_util()


def test_bulk_success_does_not_reinstall_per_package():
    calls = []
    with patch.object(MANAGER_UTIL.subprocess, "check_call", side_effect=lambda cmd: calls.append(cmd) or 0):
        MANAGER_UTIL.restore_pip_snapshot({"alpha": "", "beta": ""}, ["--pip-non-url"])
    assert len(calls) == 1, "bulk install succeeded; no per-package --no-deps retries expected"


def test_bulk_failure_falls_back_per_package():
    calls = []
    state = {"n": 0}

    def flaky(cmd):
        calls.append(cmd)
        state["n"] += 1
        if state["n"] == 1:
            raise subprocess.CalledProcessError(1, cmd)
        return 0

    with patch.object(MANAGER_UTIL.subprocess, "check_call", side_effect=flaky):
        MANAGER_UTIL.restore_pip_snapshot({"alpha": "", "beta": ""}, ["--pip-non-url"])
    assert len(calls) == 3, "one bulk attempt plus one --no-deps call per package"


def test_per_package_failure_is_reported():
    with patch.object(MANAGER_UTIL.subprocess, "check_call", side_effect=subprocess.CalledProcessError(1, "pip")):
        # must not raise; the failure lands in the printed summary
        MANAGER_UTIL.restore_pip_snapshot({"alpha": "", "beta": ""}, ["--pip-non-url"])
