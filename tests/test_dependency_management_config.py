"""config.ini's `dependency_management` reaches manager_util through both config readers, as cm-cli reads it."""
import pytest

from _install_flags_testutil import import_context, import_reader


@pytest.mark.parametrize("reader", ["glob", "legacy"])
@pytest.mark.parametrize("environment, expected", [(None, False), ("on", True)])
def test_config_value_is_applied_unless_the_environment_says_otherwise(reader, environment, expected, monkeypatch, tmp_path):
    core = import_reader(reader)
    path = tmp_path / "config.ini"
    path.write_text("[default]\ndependency_management = off\n", encoding="utf-8")
    monkeypatch.setattr(import_context(), "manager_config_path", str(path))
    monkeypatch.setattr(core, "cached_config", None)
    monkeypatch.setattr(core.manager_util, "dependency_management_enabled", True)
    if environment is None:
        monkeypatch.delenv("COMFYUI_MANAGER_DEPENDENCY_MANAGEMENT", raising=False)
    else:
        monkeypatch.setenv("COMFYUI_MANAGER_DEPENDENCY_MANAGEMENT", environment)

    core.get_config()

    assert core.manager_util.dependency_management_enabled is expected
