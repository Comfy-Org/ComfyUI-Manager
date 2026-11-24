"""Versions with a suffix are read: node pack versions, and pip versions in pip_auto_fix.list (#3431).

A node pack installed from the registry has its version in pyproject.toml. The registry holds
versions such as `1.8.0-beta.1`, and a pack may write `0.1.3.post1`. pip reports versions such
as `2.5.1+cu124` and `4.41.0rc1`.
"""
import logging

import pytest

from _install_flags_testutil import import_context, import_reader
from test_pip_fixer_opencv import fix_broken  # noqa: F401 -- fixture


@pytest.fixture(params=["glob", "legacy"])
def resolve(request, tmp_path):
    """Returns what the installed-pack scan of each core reads for a registry pack of a given version."""
    import_context()
    manager = import_reader(request.param).UnifiedManager()
    manager.cnr_map["some-pack"] = {"id": "some-pack"}

    def run(version):
        path = tmp_path / "some-pack"
        path.mkdir(exist_ok=True)
        (path / ".tracking").write_text("", encoding="utf-8")
        (path / "pyproject.toml").write_text(
            f'[project]\nname = "some-pack"\nversion = "{version}"\n', encoding="utf-8")
        return manager.resolve_from_path(str(path))

    return run


@pytest.mark.parametrize("written, read", [
    ("1.2.3", "1.2.3"),
    ("2.5", "2.5.0"),
    ("3", "3.0.0"),
    ("0.7.2-b2", "0.7.2-b2"),
    ("1.8.0-beta.1", "1.8.0-beta.1"),
    ("2.0.0-inprogress", "2.0.0-inprogress"),
    ("0.1.3.post1", "0.1.3-post1"),
    ("0.1.3-post1", "0.1.3-post1"),  # what the scan itself writes for 0.1.3.post1
])
def test_a_registry_pack_is_read_with_its_version(resolve, written, read):
    info = resolve(written)

    assert info["id"] == "some-pack"
    assert info["ver"] == read


@pytest.mark.parametrize("written", ["", "abc", "1.x", "1.2.x", "1.2.3-", "2.5-beta", "1.0.0rc1", "1.0.3+local"])
def test_a_pack_without_a_readable_version_is_not_a_registry_pack(resolve, written):
    assert resolve(written) is None


@pytest.mark.parametrize("installed, listed", [
    ("2.5.1+cu124", "torch==2.5.1"),
    ("2.5.1+cu124", "torch>=2.5.0"),
    ("2.5.1+cu124", "torch<=2.5.1"),
    ("2.5.1+cu124", "torch~=2.5.0"),
    ("2.5.1", "torch~=2.5.1"),
    ("2.6.0.dev20241112", "torch>2.5.1"),
    ("2.5.1rc1", "torch!=2.5.1"),
])
def test_a_listed_requirement_that_the_installed_version_meets_is_left_alone(fix_broken, caplog, installed, listed):  # noqa: F811
    with caplog.at_level(logging.ERROR):
        commands = fix_broken({"torch": installed, "torchvision": "0.20.1", "torchaudio": "2.5.1"}, pip_auto_fix=listed + "\n")

    assert commands == []
    assert "Failed to restore" not in caplog.text


@pytest.mark.parametrize("installed, listed", [
    ("2.5.0+cu124", "torch==2.5.1"),
    ("2.5.1rc1", "torch>=2.5.1"),
    ("2.5.1rc1", "torch<2.5.1"),  # as pip reads it: `<` leaves out the pre-releases of that version
    ("2.5.1+cu124", "torch<2.5.1"),
    ("2.5.1+cu124", "torch!=2.5.1"),
    ("2.6.0", "torch~=2.5.1"),
    ("2.5.0", "torch~=2.5.1"),
])
def test_a_listed_requirement_that_the_installed_version_misses_is_installed(fix_broken, installed, listed):  # noqa: F811
    assert fix_broken({"torch": installed, "torchvision": "0.20.1", "torchaudio": "2.5.1"},
                      pip_auto_fix=listed + "\n") == ["install " + listed]


def test_the_index_url_of_a_listed_requirement_is_passed_to_pip(fix_broken):  # noqa: F811
    index = "https://download.pytorch.org/whl/cu124"

    assert fix_broken({"torch": "2.5.0+cu124", "torchvision": "0.20.1", "torchaudio": "2.5.1"},
                      pip_auto_fix=f"torch==2.5.1 --index-url {index}\n") == [f"install torch==2.5.1 --index-url {index}"]
