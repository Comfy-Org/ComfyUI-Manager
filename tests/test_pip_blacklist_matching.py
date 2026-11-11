"""pip_blacklist and downgrade_blacklist apply however a requirement is written.

tests/test_pip_package_names.py covers the '-', '_' and letter-case spellings of a name
(issue #3458). This file covers the other forms of a requirement, the version rules,
and the paths that install one.
"""

import ast
import logging
import os
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from _install_flags_testutil import import_context, import_reader


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
    import_context()
    from comfyui_manager.common import cm_global, manager_util

    monkeypatch.setattr(manager_util, 'make_pip_cmd', lambda cmd: ['python', '-m', 'pip', *cmd])
    monkeypatch.setattr(manager_util, 'subprocess', SimpleNamespace(
        check_output=lambda *args, **kwargs: PIP_LIST, CalledProcessError=subprocess.CalledProcessError))
    monkeypatch.setattr(manager_util, 'pip_map', None)
    monkeypatch.setattr(cm_global, 'pip_overrides', {}, raising=False)

    def set_lists(blacklist=(), downgrade_blacklist=()):
        monkeypatch.setattr(cm_global, 'pip_blacklist', set(blacklist), raising=False)
        monkeypatch.setattr(cm_global, 'pip_downgrade_blacklist', list(downgrade_blacklist), raising=False)

    set_lists()
    return set_lists


def load_prestartup(**module_globals):
    """Load the startup install functions; importing prestartup_script would run the startup."""
    from comfyui_manager.common import cm_global, manager_util

    source = Path(manager_util.__file__).parents[1] / 'prestartup_script.py'
    wanted = {'is_installed', 'remap_pip_package', 'execute_lazy_install_script'}
    functions = [node for node in ast.parse(source.read_text(encoding='utf-8')).body
                 if isinstance(node, ast.FunctionDef) and node.name in wanted]
    scope = {'os': os, 're': re, 'manager_util': manager_util, 'cm_global': cm_global, **module_globals}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec'), scope)
    return scope


def load_check(implementation):
    """Return the implementation's check. True means the requirement is not installed."""
    if implementation == 'prestartup':
        return load_prestartup()['is_installed']
    return import_reader(implementation).is_blacklisted


@pytest.fixture(params=['glob', 'legacy', 'prestartup'])
def is_blocked(request, set_lists):
    """Every check that skips a listed requirement."""
    return load_check(request.param)


@pytest.fixture(params=['glob', 'legacy'])
def is_blacklisted(request, set_lists):
    """The checks whose False means exactly 'not blocked by the lists'."""
    return load_check(request.param)


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


@pytest.mark.parametrize('entry_point', [
    'glob function', 'glob manager', 'legacy function', 'legacy manager', 'startup',
])
def test_requirements_file_lines_are_checked_before_install(set_lists, monkeypatch, tmp_path, entry_point):
    """From a pack's requirements.txt to the pip commands that are run."""
    set_lists(blacklist={'torch'}, downgrade_blacklist=['opencv-python'])
    (tmp_path / 'requirements.txt').write_text(REQUIREMENTS_TXT, encoding='utf-8')
    executed = []

    if entry_point == 'startup':
        # Reserved installs, which is every server-requested install on Windows, run here.
        startup = load_prestartup(
            process_wrap=lambda cmd, cwd=None, **kwargs: executed.append(cmd) or 0,
            processed_install=set(), _unified_resolver_succeeded=False)
        startup['execute_lazy_install_script'](str(tmp_path), 'python')
    else:
        tree, caller = entry_point.split()
        core = import_reader(tree)
        monkeypatch.setattr(core.manager_funcs, 'run_script', lambda cmd, cwd='.': executed.append(cmd) or 0)
        monkeypatch.setattr(core.manager_util, 'PIPFixer', lambda *args: SimpleNamespace(fix_broken=lambda: None))
        monkeypatch.setattr(core.manager_util, 'use_unified_resolver', False)
        monkeypatch.setattr(core.unified_manager, 'processed_install', set())
        target = core if caller == 'function' else core.unified_manager
        target.execute_install_script(None, str(tmp_path), instant_execution=True)

    requirements = [' '.join(cmd[cmd.index('install') + 1:]) for cmd in executed]
    assert requirements == ['scipy --index-url https://example.invalid/simple', 'pyyaml>=6']


# Every base command make_pip_cmd() can produce.
PIP_COMMANDS = [
    ['python', '-m', 'pip'], ['python', '-s', '-m', 'pip'],
    ['python', '-m', 'uv', 'pip'], ['python', '-s', '-m', 'uv', 'pip'], ['uv', 'pip'],
]


@pytest.mark.parametrize('tree', ['glob', 'legacy'])
@pytest.mark.parametrize('pip', PIP_COMMANDS, ids=' '.join)
@pytest.mark.parametrize('arguments,blocked', [
    (['torch'], True),
    (['torch', '--index-url', 'https://example.invalid/simple'], True),
    (['numpy', '--index-url', 'https://example.invalid/simple'], False),
    (['-r', 'requirements.txt'], False),
])
def test_immediate_install_checks_the_requirement(set_lists, monkeypatch, tree, pip, arguments, blocked):
    core = import_reader(tree)
    set_lists(blacklist={'torch'})
    executed = []
    monkeypatch.setattr(core.manager_funcs, 'run_script', lambda cmd, cwd='.': executed.append(cmd) or 0)

    install_cmd = [*pip, 'install', *arguments]
    assert core.try_install_script(None, '.', install_cmd, instant_execution=True) is True
    assert executed == ([] if blocked else [install_cmd])


@pytest.mark.parametrize('pip', PIP_COMMANDS, ids=' '.join)
def test_reserved_pip_command_requirement(set_lists, pip):
    """The startup loop passes this value to is_installed() instead of the last argument."""
    from comfyui_manager.common import manager_util

    url = 'https://example.invalid/simple'
    assert manager_util.pip_install_requirement([*pip, 'install', 'torch', '--index-url', url]) == 'torch'
    assert manager_util.pip_install_requirement([*pip, 'install', 'torch==2.0.0']) == 'torch==2.0.0'
    assert manager_util.pip_install_requirement(['python', 'install.py']) is None
    assert manager_util.pip_install_requirement([*pip, 'install']) is None
