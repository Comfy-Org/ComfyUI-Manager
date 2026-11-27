import pytest

from _install_flags_testutil import import_reader

VARIABLE = "COMFYUI_MANAGER_SKIP_MANAGER_REQUIREMENTS"


def pip_installs(core, comfyui_path, monkeypatch):
    (comfyui_path / "manager_requirements.txt").write_text("comfyui-manager==4.2.2\n")
    core = import_reader(core)
    commands = []
    monkeypatch.setattr(core.manager_util, "make_pip_cmd", lambda args: ["pip", *args])
    monkeypatch.setattr(core.subprocess, "run", commands.append)
    core.install_manager_requirements(str(comfyui_path))
    return commands


@pytest.mark.parametrize("core", ["glob", "legacy"])
def test_pin_of_comfyui_is_installed(core, monkeypatch, tmp_path):
    monkeypatch.delenv(VARIABLE, raising=False)

    assert pip_installs(core, tmp_path, monkeypatch) == [["pip", "install", "comfyui-manager==4.2.2"]]


@pytest.mark.parametrize("core", ["glob", "legacy"])
@pytest.mark.parametrize("value", ["1", "true", "YES"])
def test_variable_skips_the_pin(core, value, monkeypatch, tmp_path):
    monkeypatch.setenv(VARIABLE, value)

    assert pip_installs(core, tmp_path, monkeypatch) == []
