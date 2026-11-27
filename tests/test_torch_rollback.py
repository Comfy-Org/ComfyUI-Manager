"""The restore of PyTorch after a nodepack (PIPFixer.fix_broken()), with torchaudio optional (#3388).

ComfyUI no longer needs torchaudio.
"""
import logging
import subprocess
from types import SimpleNamespace

import pytest

from manager_test_utils import load_manager_util

MANAGER_UTIL = load_manager_util()

PIP = ("python", "-m", "pip")
FRONTEND_INSTALLED = {"comfyui_frontend_package": "1.30.6"}

NO_LABEL = {"torch": "2.14.0", "torchvision": "0.29.0"}
NO_LABEL_TA = {**NO_LABEL, "torchaudio": "2.11.0"}

RESTORES = {
    "no label": dict(
        without_torchaudio=NO_LABEL,
        with_torchaudio=NO_LABEL_TA,
        command_without_torchaudio="install --force torch torchvision",
        command_with_torchaudio="install --force torch torchvision torchaudio"),
    "label in the table": dict(
        without_torchaudio={"torch": "2.6.0+cu124", "torchvision": "0.21.0+cu124"},
        with_torchaudio={"torch": "2.6.0+cu124", "torchvision": "0.21.0+cu124", "torchaudio": "2.6.0+cu124"},
        command_without_torchaudio="install torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124",
        command_with_torchaudio="install torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124"),
    "label newer than the table": dict(
        without_torchaudio={"torch": "2.14.0+cu130", "torchvision": "0.29.0+cu130"},
        with_torchaudio={"torch": "2.14.0+cu130", "torchvision": "0.29.0+cu130", "torchaudio": "2.11.0+cu130"},
        command_without_torchaudio="install --pre torch torchvision --index-url https://download.pytorch.org/whl/nightly/cu130",
        command_with_torchaudio="install --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/cu130"),
}


@pytest.fixture
def fix_broken(monkeypatch, tmp_path, caplog):
    def run(installed_before, left_by_the_nodepack):
        install_commands = []

        def check_output(cmd, **_):
            pip_args = cmd[len(PIP):]
            if pip_args == ["list"]:
                packages = {**FRONTEND_INSTALLED, **left_by_the_nodepack}
                return "Package Version\n------- -------\n" + "".join(f"{n} {v}\n" for n, v in packages.items())
            install_commands.append(" ".join(pip_args))
            return ""

        monkeypatch.setattr(MANAGER_UTIL, "make_pip_cmd", lambda cmd: [*PIP, *cmd])
        monkeypatch.setattr(MANAGER_UTIL, "subprocess", SimpleNamespace(
            check_output=check_output, CalledProcessError=subprocess.CalledProcessError))
        monkeypatch.setattr(MANAGER_UTIL, "pip_map", None)
        caplog.set_level(logging.INFO)
        MANAGER_UTIL.PIPFixer(dict(installed_before), str(tmp_path), None).fix_broken()
        return install_commands

    return run


def problems(caplog):
    return [(record.levelname, record.getMessage()) for record in caplog.records if record.levelno >= logging.WARNING]


def test_an_install_without_torchaudio_is_not_reported_as_without_pytorch(fix_broken, caplog):
    assert fix_broken(NO_LABEL, NO_LABEL) == []
    assert problems(caplog) == []


@pytest.mark.parametrize("before, after", [
    (NO_LABEL_TA, {**NO_LABEL_TA, "torchaudio": "2.11.1"}),
    (NO_LABEL_TA, NO_LABEL),
    (NO_LABEL, NO_LABEL_TA),
], ids=["torchaudio of another version", "torchaudio removed", "torchaudio added"])
def test_a_nodepack_that_changed_only_torchaudio_starts_no_restore(fix_broken, caplog, before, after):
    assert fix_broken(before, after) == []
    assert problems(caplog) == []


@pytest.mark.parametrize("torchaudio_before, torchaudio_after", [(False, False), (False, True), (True, True), (True, False)],
                         ids=["absent before and after", "added by the nodepack", "present before and after",
                              "removed by the nodepack"])
@pytest.mark.parametrize("restore", RESTORES)
def test_a_restore_names_torchaudio_when_the_install_has_it_before_or_after_the_nodepack(
        fix_broken, restore, torchaudio_before, torchaudio_after):
    case = RESTORES[restore]
    before = case["with_torchaudio" if torchaudio_before else "without_torchaudio"]
    after = {**case["with_torchaudio" if torchaudio_after else "without_torchaudio"], "torch": "2.13.0"}
    named = torchaudio_before or torchaudio_after
    assert fix_broken(before, after) == [case["command_with_torchaudio" if named else "command_without_torchaudio"]]
