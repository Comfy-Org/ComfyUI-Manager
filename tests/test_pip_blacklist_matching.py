"""pip_blacklist and downgrade_blacklist apply however a requirement is written.

tests/test_pip_package_names.py covers the '-', '_' and letter-case spellings of a name
(issue #3458). This file covers the other forms of a requirement, the version rules,
and the paths that install one.

The checks are the functions taken from the source of manager_core.py and
prestartup_script.py, run against the real manager_util. The install paths of
manager_core run in a child process that imports the real module (see
test_install_flags_config).
"""

import ast
import logging
import os
import re
import subprocess
from types import SimpleNamespace

import pytest

from manager_test_utils import GLOB_DIR, load_manager_util
from test_install_flags_config import _run_child
from test_version_suffix import fix_broken  # noqa: F401 -- fixture

MANAGER_UTIL = load_manager_util()
CM_GLOBAL = SimpleNamespace(pip_blacklist=set(), pip_downgrade_blacklist=[], pip_overrides={})
PRESTARTUP_SCRIPT = GLOB_DIR.resolve().parent / 'prestartup_script.py'


# What `pip list` prints. The installed-package lookup is built from this output.
PIP_LIST = '''\
Package         Version
--------------- ------------
numpy           2.2.0
opencv-python   5.0.0.93
ruamel.yaml     0.18.6
transformers    4.57.0
triton-windows  3.5.0
xformers        0.0.30+cu126
'''


@pytest.fixture
def set_lists(monkeypatch):
    """Replace the `pip list` output and return a setter for the two lists."""
    monkeypatch.setattr(MANAGER_UTIL, 'make_pip_cmd', lambda cmd: ['python', '-m', 'pip', *cmd])
    monkeypatch.setattr(MANAGER_UTIL, 'subprocess', SimpleNamespace(
        check_output=lambda *args, **kwargs: PIP_LIST, CalledProcessError=subprocess.CalledProcessError))
    monkeypatch.setattr(MANAGER_UTIL, 'pip_map', None)

    def set_lists(blacklist=(), downgrade_blacklist=()):
        monkeypatch.setattr(CM_GLOBAL, 'pip_blacklist', set(blacklist))
        monkeypatch.setattr(CM_GLOBAL, 'pip_downgrade_blacklist', list(downgrade_blacklist))

    set_lists()
    return set_lists


def load_functions(source, wanted, **module_globals):
    """Load functions from a source file that cannot be imported outside ComfyUI."""
    functions = [node for node in ast.parse(source.read_text(encoding='utf-8')).body
                 if isinstance(node, ast.FunctionDef) and node.name in wanted]
    assert {node.name for node in functions} == set(wanted)
    scope = {'os': os, 're': re, 'manager_util': MANAGER_UTIL, 'cm_global': CM_GLOBAL, **module_globals}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec'), scope)
    return scope


def load_prestartup(**module_globals):
    """Load the startup install functions; importing prestartup_script would run the startup."""
    if not PRESTARTUP_SCRIPT.exists():
        pytest.skip('MANAGER_GLOB_DIR points at a glob directory without prestartup_script.py beside it')
    return load_functions(
        PRESTARTUP_SCRIPT,
        {'is_installed', 'remap_pip_package', 'execute_lazy_install_script', 'execute_startup_script'},
        **module_globals)


def load_check(implementation):
    """Return the implementation's check. True means the requirement is not installed."""
    if implementation == 'prestartup':
        return load_prestartup()['is_installed']
    return load_functions(GLOB_DIR / 'manager_core.py', {'is_blacklisted'})['is_blacklisted']


@pytest.fixture(params=['core', 'prestartup'])
def is_blocked(request, set_lists):
    """Every check that skips a listed requirement."""
    return load_check(request.param)


@pytest.fixture
def is_blacklisted(set_lists):
    """The check whose False means exactly 'not blocked by the lists'."""
    return load_check('core')


@pytest.mark.parametrize('entry', ['ruamel.yaml', 'ruamel-yaml', 'Ruamel_Yaml'])
@pytest.mark.parametrize('requirement', ['ruamel.yaml<0.18', 'ruamel-yaml<0.18', 'ruamel_yaml<0.18'])
def test_dots_are_name_separators(set_lists, is_blocked, entry, requirement):
    set_lists(downgrade_blacklist=[entry])
    assert is_blocked(requirement) is True


@pytest.mark.parametrize('requirement', [
    'triton-windows<3.5',
    'transformers',
    'transformers<4.50',
    'transformers~=4.57.0',
    'transformers===4.0.0',
    'transformers == 4.0.0',
    'transformers[torch]==4.0.0',
    'transformers<=4.57.0,>=4.0',
    'transformers>=4.0,<4.50',       # the lower bound comes first
    'transformers (>=4.0,<4.50)',
    'transformers==4.*',
    'transformers==4.0.0; python_version > "3.8"',
    'transformers ; python_version > "3.8"',
    'transformers==4.0.0 --index-url https://example.invalid/simple',
    'opencv-python<5',               # 5.0.0.93 is newer than 5
    'xformers==0.0.20',              # installed with a local version label
])
def test_downgrade_blacklist_blocks_possible_downgrades(set_lists, is_blocked, caplog, requirement):
    set_lists(downgrade_blacklist=['transformers', 'triton-windows', 'opencv-python', 'xformers'])
    with caplog.at_level(logging.ERROR):
        assert is_blocked(requirement) is True
    # These versions can be compared, so nothing is reported as uncomparable.
    assert caplog.text == ''


@pytest.mark.parametrize('requirement', [
    'transformers>=4.60',
    'transformers>=4.0',             # a lower bound below the installed version
    'transformers>4.0',
    'transformers!=4.0.0',
    'transformers==4.58.0',          # newer than installed
    'transformers<5',                # the installed version already satisfies it
    'transformers == 5.0',
    'transformers[torch]==5.0',
    'transformers<=5.0,>=4.0',
    'transformers>=4.0,<5',
    'transformers==5.*',
    'transformers==5.0; python_version > "3.8"',
    'transformers==5.0 --index-url https://example.invalid/simple',
    'transformers-stream==0.1',      # a different package
    # With extras pip keeps the installed version and adds the extras' dependencies.
    'transformers[sentencepiece]',
    'transformers[sentencepiece]==4.57.0',
    'transformers[sentencepiece]~=4.57.0',
    'transformers[sentencepiece]>=4.0,<5',
])
def test_downgrade_blacklist_allows_other_requirements(set_lists, is_blacklisted, caplog, requirement):
    set_lists(downgrade_blacklist=['transformers'])
    with caplog.at_level(logging.ERROR):
        assert is_blacklisted(requirement) is False
    # A misread version would be reported as uncomparable.
    assert caplog.text == ''


@pytest.mark.parametrize('requirement', [
    'torch==2.0.0', 'torch == 2.0.0', 'Torch', 'torch[opt]>=2.0',
    'torch==', 'torch=2.0', 'torch=>2.0',    # malformed version clauses
    'torch @ https://example.invalid/torch-2.0.0-py3-none-any.whl',
    'torch (>=2.0)', 'torch(>=2.0)',
])
def test_blacklist_matches_every_requirement_form(set_lists, is_blocked, requirement):
    set_lists(blacklist={'torch'})
    assert is_blocked(requirement) is True


@pytest.mark.parametrize('requirement', ['torchvision', 'torch-audio==2.0', 'opencv-python-headless'])
def test_blacklist_does_not_match_other_packages(set_lists, is_blacklisted, requirement):
    set_lists(blacklist={'torch', 'opencv-python'})
    assert is_blacklisted(requirement) is False


@pytest.mark.parametrize('requirement', [
    'git+https://example.invalid/torch.git',
    'https://example.invalid/torch-2.0.0-py3-none-any.whl',
    './wheels/torch-2.0.0-py3-none-any.whl',
    '--extra-index-url https://example.invalid/simple',
])
def test_lines_that_do_not_name_a_package_have_no_name_to_match(set_lists, is_blacklisted, requirement):
    """A known limit: a bare URL, path or option states no package name."""
    set_lists(blacklist={'torch'})
    assert is_blacklisted(requirement) is False


def test_identical_blacklist_entry_applies_to_such_lines(set_lists, is_blacklisted):
    set_lists(blacklist={'git+https://example.invalid/pack.git'})
    assert is_blacklisted('git+https://example.invalid/pack.git') is True


@pytest.mark.parametrize('requirement,installed', [
    ('transformers=>4.0', '4.57.0'),
    ('transformers==', '4.57.0'),
    ('transformers @ https://example.invalid/transformers.whl', '4.57.0'),   # no version to compare
])
def test_uncomparable_version_is_blocked_with_an_explanation(set_lists, is_blocked, caplog, requirement, installed):
    set_lists(downgrade_blacklist=['transformers'])
    with caplog.at_level(logging.ERROR):
        assert is_blocked(requirement) is True
    errors = [record.getMessage() for record in caplog.records if record.levelno == logging.ERROR]
    assert len(errors) == 1
    # What was skipped, why, and how to proceed.
    assert f"Skipped '{requirement}'" in errors[0]
    assert f"installed version ({installed}) cannot be compared with the requested version" in errors[0]
    assert 'Install it manually' in errors[0] and 'downgrade_blacklist in config.ini' in errors[0]


def test_startup_check_reports_downgrade_protection(set_lists, capsys):
    is_installed = load_check('prestartup')
    set_lists(blacklist={'torch'}, downgrade_blacklist=['opencv-python'])

    assert is_installed('torch==2.0.0') is True
    assert 'skip black listed' not in capsys.readouterr().out

    assert is_installed('opencv-python~=4.8.1.78') is True
    assert "skip black listed pip installation: 'opencv-python~=4.8.1.78'" in capsys.readouterr().out


@pytest.mark.parametrize('requirement,skipped', [
    ('scipy', False),                        # not installed
    ('numpy', True),                         # installed, no version requested
    ('numpy>=3.0', False),                   # needs an upgrade
    ('numpy==1.26.4', True),                 # would be a downgrade
    ('numpy >= 1.20', True),                 # spaces around the operator
    ('OpenCV_Python==4.8.1.78', True),       # a hyphenated name is found and not downgraded
    ('opencv-python>=6', False),
    ('opencv-python~=5.1', False),           # older than the compatible release
    ('opencv-python~=5.0.0', True),
    ('numpy>2.2.0', False),                  # `>` excludes the installed version
    ('numpy>2.1', True),
    ('ruamel-yaml>=0.17', True),             # listed by pip as ruamel.yaml
    ('xformers>=0.0.20', True),              # installed with a local version label
    ('opencv-python[extra]', False),         # extras to add: pip decides
    ('opencv-python @ https://example.invalid/opencv.whl', False),   # no version: pip decides
])
def test_startup_check_for_packages_on_neither_list(set_lists, requirement, skipped):
    """The general rule: install what is missing or too old, and never downgrade."""
    assert load_check('prestartup')(requirement) is skipped


REQUIREMENTS_TXT = '''\
torch --index-url https://example.invalid/simple
opencv-python~=4.8.1.78  # pinned by the pack
scipy --index-url https://example.invalid/simple
pyyaml>=6
'''

# Every base command make_pip_cmd() can produce.
PIP_COMMANDS = [
    ['python', '-m', 'pip'], ['python', '-s', '-m', 'pip'],
    ['python', '-m', 'uv', 'pip'], ['python', '-s', '-m', 'uv', 'pip'], ['uv', 'pip'],
]
INSTALL_ARGUMENTS = [
    (['torch'], True),
    (['torch', '--index-url', 'https://example.invalid/simple'], True),
    (['numpy', '--index-url', 'https://example.invalid/simple'], False),
    (['-r', 'requirements.txt'], False),
]


@pytest.fixture(scope='module')
def core_installs():
    """What the install paths of the real manager_core run, with the pip commands recorded instead."""
    return _run_child(f"""
import pathlib, subprocess
from types import SimpleNamespace
import cm_global, manager_util

PIP_LIST = {PIP_LIST!r}
manager_util.make_pip_cmd = lambda cmd: ['python', '-m', 'pip', *cmd]
manager_util.subprocess = SimpleNamespace(
    check_output=lambda *args, **kwargs: PIP_LIST, CalledProcessError=subprocess.CalledProcessError)
manager_util.pip_map = None
manager_util.PIPFixer = lambda *args: SimpleNamespace(fix_broken=lambda: None)
cm_global.pip_overrides = {{}}
executed = []
manager_core.manager_funcs.run_script = lambda cmd, cwd='.': executed.append(cmd) or 0

# from a pack's requirements.txt to the pip commands that are run
cm_global.pip_blacklist = {{'torch'}}
cm_global.pip_downgrade_blacklist = ['opencv-python']
requirements = {{}}
for caller, target in (('function', manager_core), ('manager', manager_core.unified_manager)):
    pack = pathlib.Path(tmp) / caller
    pack.mkdir()
    (pack / 'requirements.txt').write_text({REQUIREMENTS_TXT!r}, encoding='utf-8')
    manager_core.unified_manager.processed_install = set()
    del executed[:]
    target.execute_install_script(None, str(pack), instant_execution=True)
    requirements[caller] = [' '.join(cmd[cmd.index('install') + 1:]) for cmd in executed]

# one pip install command
cm_global.pip_downgrade_blacklist = []
immediate = {{}}
for pip in {PIP_COMMANDS!r}:
    for arguments, _ in {INSTALL_ARGUMENTS!r}:
        install_cmd = [*pip, 'install', *arguments]
        del executed[:]
        result = manager_core.try_install_script(None, '.', install_cmd, instant_execution=True)
        immediate[' '.join(install_cmd)] = [result, executed == [install_cmd], executed == []]

print(json.dumps({{'requirements': requirements, 'immediate': immediate}}))
""")


@pytest.mark.parametrize('entry_point', ['function', 'manager', 'startup'])
def test_requirements_file_lines_are_checked_before_install(set_lists, tmp_path, request, entry_point):
    """From a pack's requirements.txt to the pip commands that are run."""
    if entry_point == 'startup':
        # Reserved installs, which is every server-requested install on Windows, run here.
        set_lists(blacklist={'torch'}, downgrade_blacklist=['opencv-python'])
        (tmp_path / 'requirements.txt').write_text(REQUIREMENTS_TXT, encoding='utf-8')
        executed = []
        startup = load_prestartup(
            process_wrap=lambda cmd, cwd=None, **kwargs: executed.append(cmd) or 0, processed_install=set())
        startup['execute_lazy_install_script'](str(tmp_path), 'python')
        requirements = [' '.join(cmd[cmd.index('install') + 1:]) for cmd in executed]
    else:
        requirements = request.getfixturevalue('core_installs')['requirements'][entry_point]

    assert requirements == ['scipy --index-url https://example.invalid/simple', 'pyyaml>=6']


@pytest.mark.parametrize('pip', PIP_COMMANDS, ids=' '.join)
@pytest.mark.parametrize('arguments,blocked', INSTALL_ARGUMENTS)
def test_immediate_install_checks_the_requirement(core_installs, pip, arguments, blocked):
    result, ran_the_command, ran_nothing = core_installs['immediate'][' '.join([*pip, 'install', *arguments])]

    assert result is True
    assert (ran_nothing if blocked else ran_the_command) is True


def test_reserved_pip_installs_are_checked_at_startup(set_lists, tmp_path):
    """The startup loop checks the requirement of a reserved pip command, not its last argument."""
    set_lists(blacklist={'torch'})
    pack, url = str(tmp_path), 'https://example.invalid/simple'
    reserved = [
        [pack, 'python', '-m', 'pip', 'install', 'torch', '--index-url', url],        # blacklisted
        [pack, 'python', '-m', 'pip', 'install', 'numpy>=1.20', '--index-url', url],  # installed
        [pack, 'python', '-m', 'pip', 'install', 'scipy', '--index-url', url],        # not installed
        [pack, '#FORCE', 'python', '-m', 'pip', 'install', 'torch'],                  # not checked
    ]
    script_list = tmp_path / 'install-scripts.txt'
    script_list.write_text(''.join(f'{line}\n' for line in reserved), encoding='utf-8')
    executed = []
    startup = load_prestartup(
        ast=ast, logging=logging, comfy_path=pack, script_list_path=str(script_list), script_executed=False,
        process_wrap=lambda cmd, cwd=None, **kwargs: executed.append(cmd) or 0)

    startup['execute_startup_script']()

    assert executed == [
        ['python', '-m', 'pip', 'install', 'scipy', '--index-url', url],
        ['python', '-m', 'pip', 'install', 'torch'],
    ]
    assert not script_list.exists()


def test_pip_auto_fix_finds_the_package_however_its_name_is_written(fix_broken):  # noqa: F811
    """`pip list` prints ruamel.yaml; an entry may spell it with '-' or '_'."""
    assert fix_broken({'torch': '2.5.1', 'ruamel.yaml': '0.18.6'},
                      pip_auto_fix='ruamel-yaml>=0.17\nRuamel_Yaml>=0.17\n') == []


@pytest.mark.parametrize('pip', PIP_COMMANDS, ids=' '.join)
def test_reserved_pip_command_requirement(pip):
    """The startup loop passes this value to is_installed() instead of the last argument."""
    url = 'https://example.invalid/simple'
    assert MANAGER_UTIL.pip_install_requirement([*pip, 'install', 'torch', '--index-url', url]) == 'torch'
    assert MANAGER_UTIL.pip_install_requirement([*pip, 'install', 'torch==2.0.0']) == 'torch==2.0.0'
    assert MANAGER_UTIL.pip_install_requirement(['python', 'install.py']) is None
    assert MANAGER_UTIL.pip_install_requirement([*pip, 'install']) is None


def test_cm_cli_reads_downgrade_blacklist_from_config_ini():
    """cm-cli adds the packages that config.ini lists to the built-in ones."""
    cm_cli = GLOB_DIR.resolve().parent / 'cm-cli.py'
    if not cm_cli.exists():
        pytest.skip('MANAGER_GLOB_DIR points at a glob directory without cm-cli.py beside it')

    result = _run_child(f"""
import ast, pathlib
import cm_global

write_ini('[default]\\ndowngrade_blacklist = opencv-python, Triton_Windows\\n')
cm_global.pip_downgrade_blacklist = ['torch', 'transformers']
functions = [node for node in ast.parse(pathlib.Path({str(cm_cli)!r}).read_text(encoding='utf-8')).body
             if isinstance(node, ast.FunctionDef) and node.name == 'read_downgrade_blacklist']
scope = {{'core': manager_core, 'cm_global': cm_global}}
exec(compile(ast.Module(body=functions, type_ignores=[]), 'cm-cli.py', 'exec'), scope)
scope['read_downgrade_blacklist']()
print(json.dumps(sorted(cm_global.pip_downgrade_blacklist)))
""")

    assert result == ['Triton_Windows', 'opencv-python', 'torch', 'transformers']
