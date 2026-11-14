"""Versions with a suffix are read: node pack versions, and the pip versions that Manager compares (#3431).

A node pack installed from the registry has its version in pyproject.toml. The registry holds
versions such as `1.8.0-beta.1`, and a pack may write `0.1.3.post1`. pip reports versions such
as `2.5.1+cu124`, `4.41.0rc1` and `0.0.28.post1`.

The installed-pack scan and the pip checks of manager_core run in a child process that imports
the real module (see test_install_flags_config). The pip check of prestartup_script is the
function taken from its source, and pip_auto_fix.list goes through the real PIPFixer.
"""
import ast
import logging
import re
import subprocess
from types import SimpleNamespace

import pytest

from manager_test_utils import GLOB_DIR, load_manager_util
from test_install_flags_config import _run_child

MANAGER_UTIL = load_manager_util()

# What the installed-pack scan reads for a registry pack whose pyproject.toml has the version on the left.
READ_VERSIONS = [
    ("1.2.3", "1.2.3"),
    ("2.5", "2.5.0"),
    ("3", "3.0.0"),
    ("0.7.2-b2", "0.7.2-b2"),
    ("1.8.0-beta.1", "1.8.0-beta.1"),
    ("2.0.0-inprogress", "2.0.0-inprogress"),
    ("0.1.3.post1", "0.1.3-post1"),
    ("0.1.3-post1", "0.1.3-post1"),  # what the scan itself writes for 0.1.3.post1
]
UNREADABLE_VERSIONS = ["", "abc", "1.x", "1.2.x", "1.2.3-", "2.5-beta", "1.0.0rc1", "1.0.3+local"]

# (installed version, requirement, whether the requirement counts as installed). `somepkg` is in no blacklist.
INSTALLED_CASES = [
    (None, "somepkg>=1.0.0", False),  # not installed
    ("1.0.0", "somepkg", True),
    ("1.0.0", "somepkg>=1.0.0", True),
    ("0.9.0", "somepkg>=1.0.0", False),
    ("1.0.0", "somepkg==1.0.0", True),
    ("1.0.0", "somepkg==1.0.1", False),
    ("1.0.0+cu124", "somepkg>=1.0.0", True),
    ("1.0.0+cu124", "somepkg==1.0.0", True),
    ("1.0.0+cu124", "somepkg~=1.0.0", True),
    ("0.9.0+cu124", "somepkg>=1.0.0", False),
    ("0.9.0+cu124", "somepkg==1.0.0", False),
    ("1.0.0rc1", "somepkg>=1.0.0", False),  # a pre-release is older than its release
    ("1.0.0rc1", "somepkg>=0.9.0", True),
    ("1.0.0", "somepkg>=1.0.0rc1", True),
    ("1.0.0.post1", "somepkg>=1.0.0", True),  # a post-release is newer than its release
    ("4.11.0.86", "somepkg>=4.11.0", True),
    ("1.0.0.dev20241112+cu124", "somepkg>=1.0.0", False),
]

# (installed version, requirement, whether it is refused). `transformers` is protected from a downgrade:
# a requirement with an upper bound is refused when the installed version is at or above that bound.
DOWNGRADE_CASES = [
    ("4.41.0", "transformers", True),
    ("4.41.0", "transformers==4.41.0", True),
    ("4.40.0", "transformers==4.41.0", False),
    ("4.41.0", "transformers>=4.41.0", False),
    ("4.41.0+local", "transformers==4.41.0", True),
    ("4.41.0+local", "transformers<4.42.0", False),
    ("4.41.0rc1", "transformers==4.41.0", False),  # installing 4.41.0 over its pre-release is not a downgrade
    ("4.41.0rc1", "transformers<=4.40.0", True),
    ("4.41.0.post1", "transformers==4.41.0", True),
    ("4.41.0", "transformers==4.41.0rc1", True),
    ("4.41.0", "transformers~=4.41.0", True),
]


def key(installed, requirement):
    return f"{installed} | {requirement}"


@pytest.fixture(scope="module")
def core():
    """What the real manager_core answers for every case above."""
    return _run_child(f"""
import contextlib, io, pathlib, re
import cm_global, manager_util

READ = {[written for written, _ in READ_VERSIONS] + UNREADABLE_VERSIONS!r}
INSTALLED = {[(installed, requirement) for installed, requirement, _ in INSTALLED_CASES]!r}
DOWNGRADE = {[(installed, requirement) for installed, requirement, _ in DOWNGRADE_CASES]!r}

cm_global.pip_blacklist = set()
cm_global.pip_downgrade_blacklist = ['transformers']

def answer(function, *args):
    printed = io.StringIO()
    try:
        with contextlib.redirect_stdout(printed):
            return [function(*args), printed.getvalue()]
    except Exception as e:
        return [type(e).__name__ + ': ' + str(e), printed.getvalue()]

manager = manager_core.UnifiedManager()
manager.cnr_map['some-pack'] = {{'id': 'some-pack'}}
path = pathlib.Path(tmp) / 'some-pack'
path.mkdir()
(path / '.tracking').write_text('', encoding='utf-8')

def resolve(version):
    (path / 'pyproject.toml').write_text(f'[project]\\nname = "some-pack"\\nversion = "{{version}}"\\n', encoding='utf-8')
    info = manager.resolve_from_path(str(path))
    return info and [info['id'], info['ver']]

def pip_check(function, installed, requirement):
    manager_util.pip_map = {{re.split('[<>=~!]', requirement)[0]: installed}} if installed else {{}}
    return answer(function, requirement)

print(json.dumps({{
    'resolve': {{version: answer(resolve, version)[0] for version in READ}},
    'is_installed': {{f'{{i}} | {{r}}': pip_check(manager_core.is_installed, i, r) for i, r in INSTALLED + DOWNGRADE}},
    'is_blacklisted': {{f'{{i}} | {{r}}': pip_check(manager_core.is_blacklisted, i, r) for i, r in DOWNGRADE}},
}}))
""")


@pytest.fixture
def prestartup_is_installed(monkeypatch, capsys):
    """`is_installed` of prestartup_script.py, run against one installed package."""
    path = GLOB_DIR.resolve().parent / "prestartup_script.py"
    if not path.exists():
        pytest.skip("MANAGER_GLOB_DIR points at a glob directory without prestartup_script.py beside it")
    functions = [node for node in ast.parse(path.read_text(encoding="utf-8")).body
                 if isinstance(node, ast.FunctionDef) and node.name == "is_installed"]
    assert len(functions) == 1
    namespace = {
        "re": re,
        "manager_util": MANAGER_UTIL,
        "cm_global": SimpleNamespace(pip_blacklist=set(), pip_downgrade_blacklist=["transformers"]),
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), namespace)

    def run(installed, requirement):
        name = re.split("[<>=~!]", requirement)[0]
        monkeypatch.setattr(MANAGER_UTIL, "pip_map", {name: installed} if installed else {})
        return namespace["is_installed"](requirement), capsys.readouterr().out

    return run


@pytest.fixture
def fix_broken(monkeypatch, tmp_path):
    """Run PIPFixer.fix_broken() against a given `pip list` and return the pip commands it ran, in order."""
    def run(installed, pip_auto_fix):
        packages = {"torchvision": "0.20.1", "torchaudio": "2.5.1", "comfyui_frontend_package": "1.30.6", **installed}
        pip_list = "Package Version\n------- -------\n" + "".join(
            f"{name} {version}\n" for name, version in packages.items())
        commands = []

        def check_output(cmd, **_):
            if cmd[-1] == "list":
                return pip_list
            commands.append(" ".join(cmd[3:]))
            return ""

        monkeypatch.setattr(MANAGER_UTIL, "make_pip_cmd", lambda cmd: ["python", "-m", "pip", *cmd])
        monkeypatch.setattr(MANAGER_UTIL, "subprocess", SimpleNamespace(
            check_output=check_output, CalledProcessError=subprocess.CalledProcessError))
        monkeypatch.setattr(MANAGER_UTIL, "pip_map", None)
        (tmp_path / "pip_auto_fix.list").write_text(pip_auto_fix, encoding="utf-8")

        previous = MANAGER_UTIL.get_installed_packages(True)
        MANAGER_UTIL.PIPFixer(previous, str(tmp_path), str(tmp_path)).fix_broken()
        return commands

    return run


@pytest.mark.parametrize("written, read", READ_VERSIONS)
def test_a_registry_pack_is_read_with_its_version(core, written, read):
    assert core["resolve"][written] == ["some-pack", read]


@pytest.mark.parametrize("written", UNREADABLE_VERSIONS)
def test_a_pack_without_a_readable_version_is_not_a_registry_pack(core, written):
    assert core["resolve"][written] is None


@pytest.mark.parametrize("installed, requirement, expected", INSTALLED_CASES)
def test_an_installed_pip_version_is_compared_with_the_requirement(core, prestartup_is_installed, installed, requirement, expected):
    assert core["is_installed"][key(installed, requirement)][0] is expected
    assert prestartup_is_installed(installed, requirement)[0] is expected


@pytest.mark.parametrize("installed, requirement, refused", DOWNGRADE_CASES)
def test_a_requirement_that_would_downgrade_a_protected_package_is_refused(core, prestartup_is_installed, installed, requirement, refused):
    assert core["is_blacklisted"][key(installed, requirement)][0] is refused

    # is_installed reports a refused requirement as installed, and says that it skipped it
    skipped = "skip black listed pip installation: 'transformers'"
    for result, printed in (core["is_installed"][key(installed, requirement)], prestartup_is_installed(installed, requirement)):
        if refused:
            assert result is True
        assert (skipped in printed) is (refused and requirement != "transformers")


@pytest.mark.parametrize("installed, listed", [
    ("2.5.1+cu124", "torch==2.5.1"),
    ("2.5.1+cu124", "torch>=2.5.0"),
    ("2.5.1+cu124", "torch<=2.5.1"),
    ("2.5.1+cu124", "torch~=2.5.0"),
    ("2.5.1", "torch~=2.5.1"),
    ("2.6.0.dev20241112", "torch>2.5.1"),
    ("2.5.1rc1", "torch!=2.5.1"),
])
def test_a_listed_requirement_that_the_installed_version_meets_is_left_alone(fix_broken, caplog, installed, listed):
    with caplog.at_level(logging.ERROR):
        commands = fix_broken({"torch": installed}, pip_auto_fix=listed + "\n")

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
def test_a_listed_requirement_that_the_installed_version_misses_is_installed(fix_broken, installed, listed):
    assert fix_broken({"torch": installed}, pip_auto_fix=listed + "\n") == ["install " + listed]


def test_the_index_url_of_a_listed_requirement_is_passed_to_pip(fix_broken):
    index = "https://download.pytorch.org/whl/cu124"

    assert fix_broken({"torch": "2.5.0+cu124"}, pip_auto_fix=f"torch==2.5.1 --index-url {index}\n") == \
        [f"install torch==2.5.1 --index-url {index}"]
