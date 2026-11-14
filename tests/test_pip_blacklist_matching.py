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
from packaging.specifiers import Specifier

from _install_flags_testutil import import_context, import_reader


# What `pip list` prints. The installed-package lookup is built from this output.
PIP_LIST = '''\
Package         Version
--------------- ------------
einops          0.8.0.post1
numpy           2.2.0
opencv-python   5.0.0.93
ruamel.yaml     0.18.6
safetensors     0.5.0.dev1
tokenizers      0.21.0rc1
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
    # The installed version is excluded and nothing newer is allowed, so pip has only older versions.
    'transformers<=4.57.0,!=4.57.0',
    'transformers[torch]<=4.57.0,!=4.57.0',
    'transformers[torch]!=4.57.*,<=4.57.0',
    'transformers[torch]>=4.50,<=4.57.0,!=4.57.0',
    'transformers<4.58,!=4.57.*',            # the excluded range reaches the upper bound
    'transformers[torch]<4.58,!=4.57.*',
    'transformers[torch]~=4.57.0,!=4.57.*',
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
    # A clause allows the installed version, but another sets a minimum above it: an upgrade.
    'transformers==4.*,>=4.58.0',
    'transformers~=4.57.0,>4.57.0',
    # The installed version is excluded, but newer versions are allowed: which version is left to pip.
    'transformers!=4.57.0',
    'transformers~=4.57.0,!=4.57.0',
    'transformers==4.*,!=4.57.0',
    'transformers[torch]==4.*,!=4.57.0',
    'transformers[torch]<5,!=4.57.0',
    'transformers[torch]~=4.57.0,!=4.57.0',
    'transformers<4.57.1,!=4.57.0',          # a post-release of 4.57.0 is left
    'transformers<4.57.0.1,!=4.57',          # 4.57.0.0.1 is left: versions are written at one length
    'transformers<4.59,!=4.57.*',            # 4.58 is left
    'transformers!=4.57.*,!=4.58.*,<5',      # 4.59 is left
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
    ('numpy>2.2.0,<2.2.1', False),           # 2.2.0.1 is left; `>` leaves out the post-releases of 2.2.0
    ('numpy>2.2,<2.2.0.1', False),           # 2.2.0.0.1 is left: versions are written at one length
    ('numpy>2.2.0,<=2.2.0', True),           # nothing newer is left
    ('ruamel-yaml>=0.17', True),             # listed by pip as ruamel.yaml
    ('xformers>=0.0.20', True),              # installed with a local version label
    ('xformers>=0.0.30', True),
    ('xformers>0.0.30', True),               # an installed local build is left alone
    ('xformers!=0.0.30', True),
    ('xformers~=0.0.30,!=0.0.30+cu126', True),
    ('xformers>=0.0.31', False),             # a minimum above it is still installed
    ('einops>=0.8.0', True),                 # installed as a post-release
    ('einops>0.8.0', False),                 # `>` also excludes a post-release of that version
    ('einops>0.7', True),
    ('tokenizers==0.21.*', True),            # installed as a pre-release, which the wildcard includes
    ('tokenizers>=0.21.0rc1', True),
    ('tokenizers>=0.21.0', False),           # a pre-release is older than its release
    ('tokenizers==0.21.0', False),
    # `!=` excludes the installed version: pip installs another one, unless only older ones are left.
    ('numpy!=2.2.0', False),
    ('numpy>=2.2.0,!=2.2.0', False),
    ('numpy~=2.2.0,!=2.2.0', False),
    ('numpy==2.*,!=2.2.*', False),
    ('numpy<3,!=2.2.0', False),
    ('numpy!=2.1.0', True),                  # another version is excluded
    ('numpy<=2.2.0,!=2.2.0', True),          # nothing newer is allowed
    ('numpy==2.2.0,!=2.2.0', True),
    ('numpy<2.2.0,!=2.2.0', True),           # the upper bound is below the installed version
    ('numpy<2.3,!=2.2.*', True),             # the excluded range reaches the upper bound
    ('numpy<2.4,!=2.2.*', False),
    ('einops<0.8.0.post3,!=0.8.0.post1', False),     # the next post-release is left
    ('numpy<2.2.0.post2,!=2.2.0', False),            # a post-release of 2.2.0 is left
    ('tokenizers<=0.21.0rc2,!=0.21.0rc1', False),    # the next pre-release is left, and `<=` names one
    ('tokenizers<0.21.0rc3,!=0.21.0rc1', True),      # only `<` names one: pip before 25.0 would install an older release
    ('safetensors>=0.5.0.dev1,!=0.5.0.dev1,<0.5.0.dev3', False),     # the next development release is left
    ('tokenizers<=0.21.0,!=0.21.0,!=0.21.0rc1', True),       # only a pre-release is left, which pip would not take
    ('einops>0.8.0rc1,<=0.8.0.post1', True),         # `>` leaves out 0.8.0.post1, and only 0.8.0 is left
    ('opencv-python[extra]', False),         # extras to add: pip decides
    ('opencv-python @ https://example.invalid/opencv.whl', False),   # no version: pip decides
])
def test_startup_check_for_packages_on_neither_list(set_lists, requirement, skipped):
    """The general rule: install what is missing or too old, and never downgrade."""
    assert load_check('prestartup')(requirement) is skipped


def test_an_installed_local_build_is_not_replaced_on_the_new_grounds(set_lists, is_blocked):
    """A local build, such as a CUDA build, is given up only for a minimum above it or a build that the requirement names."""
    set_lists(downgrade_blacklist=['xformers'])

    # pip would most often find the build without a label, which is older than the installed one
    assert is_blocked('xformers==0.0.30,!=0.0.30+cu126') is True
    assert is_blocked('xformers[extra]<=0.0.30,!=0.0.30+cu126') is True
    assert is_blocked('xformers~=0.0.30,!=0.0.30') is True
    assert is_blocked('xformers[extra]~=0.0.30,!=0.0.30') is True
    assert is_blocked('xformers==0.*,>=0.0.31') is True
    # `!=` alone leaves the choice to pip, which may replace the build with any other
    assert is_blocked('xformers!=0.0.30') is True
    assert is_blocked('xformers<1,!=0.0.30+cu126') is True

    assert is_blocked('xformers>=0.0.31') is False
    assert is_blocked('xformers>=0.0.31,!=0.0.30') is False
    assert is_blocked('xformers==0.0.30+cu128,!=0.0.30+cu126') is False


def test_a_requirement_that_leaves_only_an_older_version_to_pip_is_blocked(set_lists, is_blocked):
    """What counts is the version pip would install, read as pip reads the requirement."""
    set_lists(downgrade_blacklist=['tokenizers', 'einops', 'safetensors'])

    # pip takes a pre-release only when the requirement names one; here it would take an older release
    assert is_blocked('tokenizers<=0.21.0,!=0.21.0,!=0.21.0rc1') is True
    assert is_blocked('tokenizers<=0.21.0rc2,!=0.21.0rc1') is False
    assert is_blocked('tokenizers>=0.21.0rc1,!=0.21.0rc1,<0.21.0rc3') is False        # 0.21.0rc2 is left
    assert is_blocked('safetensors>=0.5.0.dev1,!=0.5.0.dev1,<0.5.0.dev3') is False    # 0.5.0.dev2 is left
    # pip before 25.0 does not take one that only `<` or `>` names
    assert is_blocked('tokenizers<0.21.0rc3,!=0.21.0rc1') is True
    assert is_blocked('safetensors!=0.5.0.dev1,<0.5.0.dev3') is True

    # `>0.8.0` leaves out the installed 0.8.0.post1, and no version is left
    assert is_blocked('einops>0.8.0,<=0.8.0.post1') is True
    assert is_blocked('einops[extra]>0.8.0,<=0.8.0.post1') is True
    assert is_blocked('einops>0.8.0,<=0.8.1') is False


def test_a_post_release_that_greater_than_leaves_out_is_not_replaced_by_its_release(set_lists, is_blocked, is_blacklisted):
    """packaging before 26.1 reads `>0.8.0rc1` as leaving out 0.8.0.post1 while allowing 0.8.0, which is older."""
    set_lists(downgrade_blacklist=['einops'])
    left_out = not Specifier('>0.8.0rc1').contains('0.8.0.post1', prereleases=True)

    assert is_blocked('einops>0.8.0rc1,<=0.8.0.post1') is True       # left out or not, nothing newer is allowed
    # Where it is not left out, the requirement is met: pip keeps the version and adds the extras.
    assert is_blocked('einops[extra]>0.8.0rc1,<=0.8.0.post1') is left_out
    assert is_blocked('einops[extra]>0.8.0rc1,<=0.8.0.post2') is left_out    # the upper bound is above the installed version
    assert is_blacklisted('einops>0.8.0rc1,<=0.8.0.post2') is left_out
    assert is_blacklisted('einops>0.8.0rc1,<0.9') is False           # 0.8.1 is allowed


def test_startup_check_agrees_with_downgrade_protection_on_an_excluded_version(set_lists):
    """A protected package whose installed version is excluded is installed at startup as it is immediately."""
    set_lists(downgrade_blacklist=['transformers'])
    is_installed = load_check('prestartup')

    assert is_installed('transformers~=4.57.0,!=4.57.0') is False
    assert is_installed('transformers!=4.57.0') is False
    assert is_installed('transformers<=4.57.0,!=4.57.0') is True     # only older versions are left: skipped


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
