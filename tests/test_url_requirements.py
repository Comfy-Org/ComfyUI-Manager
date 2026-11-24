"""A reserved install does not install a URL requirement again when its package is installed from that URL.

A line such as 'git+https://host/repo' names no package, so the installed-package list
cannot answer for it. pip and uv record where a distribution came from in its
direct_url.json (PEP 610), and that record answers (issue #3575).

A fix is the way to have such a package installed again: it installs it by force from
its URL, and then what it needs.

The records below are what pip 26.3 and uv 0.13.9 wrote for each form on 2026-11-21,
with another host. Three tests install with the real pip from a local git repository,
and one with the real uv.
"""

import ast
import importlib.metadata
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_install_flags_config import _run_child
from test_pip_blacklist_matching import MANAGER_UTIL, load_prestartup, set_lists  # noqa: F401 -- fixture

REPO = 'https://example.invalid/packs/proto'
COMMIT = 'f34797bf21972d6c0f7429911a476aaa1810ae52'
WHEEL = 'https://example.invalid/files/proto_dist-1.0-py3-none-any.whl'
DIRECTORY = 'file:///home/user/src/proto'
SHA256 = '4bc89822243270757f4c272934e2521ad4b41f0cdcdce82672eeacf01ca3d5f1'
OTHER = 'git+https://example.invalid/packs/other'

RECORDS = {
    'pip': {
        'no revision': '{"url": "%s", "vcs_info": {"commit_id": "%s", "vcs": "git"}}' % (REPO, COMMIT),
        'revision v1': '{"url": "%s", "vcs_info": {"commit_id": "%s", "requested_revision": "v1", "vcs": "git"}}' % (REPO, COMMIT),
        'with .git': '{"url": "%s.git", "vcs_info": {"commit_id": "%s", "vcs": "git"}}' % (REPO, COMMIT),
        'subdirectory': '{"subdirectory": "sub", "url": "%s", "vcs_info": {"commit_id": "%s", "vcs": "git"}}' % (REPO, COMMIT),
        'archive': '{"archive_info": {"hash": "sha256=%s", "hashes": {"sha256": "%s"}}, "url": "%s"}' % (SHA256, SHA256, WHEEL),
        'directory': '{"dir_info": {}, "url": "%s"}' % DIRECTORY,
    },
    'uv': {
        'no revision': '{"url":"%s","vcs_info":{"vcs":"git","commit_id":"%s"}}' % (REPO, COMMIT),
        'revision v1': '{"url":"%s","vcs_info":{"vcs":"git","commit_id":"%s","requested_revision":"v1"}}' % (REPO, COMMIT),
        'with .git': '{"url":"%s.git","vcs_info":{"vcs":"git","commit_id":"%s"}}' % (REPO, COMMIT),
        'subdirectory': '{"url":"%s","vcs_info":{"vcs":"git","commit_id":"%s"},"subdirectory":"sub"}' % (REPO, COMMIT),
        'archive': '{"url":"%s","archive_info":{}}' % WHEEL,
        'directory': '{"url":"%s","dir_info":{}}' % DIRECTORY,
    },
}


@pytest.fixture
def install(set_lists, monkeypatch, tmp_path):  # noqa: F811
    """Return install(name, direct_url): a distribution in a site directory of this interpreter.

    `listed=False` leaves it out of what `pip list` prints, and `folder` names its
    dist-info folder. Without a `direct_url` it has no record.
    """
    site = tmp_path / 'site'
    site.mkdir()
    monkeypatch.syspath_prepend(str(site))
    names = []
    monkeypatch.setattr(MANAGER_UTIL, 'subprocess', SimpleNamespace(
        check_output=lambda *args, **kwargs: 'Package Version\n------- -------\n' + ''.join(f'{name} 1.0\n' for name in names),
        CalledProcessError=subprocess.CalledProcessError))

    def install(name, direct_url=None, listed=True, folder=None, version='1.0'):
        info = site / (folder or f'{name}-{version}.dist-info')
        info.mkdir(exist_ok=True)
        (info / 'METADATA').write_text(f'Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n', encoding='utf-8')
        if direct_url is not None:
            (info / 'direct_url.json').write_bytes(direct_url if isinstance(direct_url, bytes) else direct_url.encode('utf-8'))
        if listed and name not in names:
            names.append(name)
        monkeypatch.setattr(MANAGER_UTIL, 'pip_map', None)

    return install


@pytest.mark.parametrize('installer', ['pip', 'uv'])
@pytest.mark.parametrize('record,requirement,installed', [
    ('no revision', f'git+{REPO}', True),
    ('no revision', f'Proto-Dist @ git+{REPO}', True),
    ('no revision', f'proto_dist @ git+{REPO}', True),
    ('no revision', f'Other-Name @ git+{REPO}', False),          # the package at the URL has another name
    ('no revision', f'git+{REPO}@{COMMIT}', True),               # the commit that is installed
    ('no revision', f'git+{REPO} ; python_version >= "3.8"', True),
    ('no revision', f'git+{REPO}@v1', False),                    # not known to be v1
    ('no revision', OTHER, False),
    ('no revision', f'git+{REPO}-extra', False),
    ('no revision', f'git+{REPO[:-2]}', False),
    ('no revision', f'git+{REPO.upper()}', False),
    ('no revision', f'git+{REPO}/', False),
    ('no revision', f'git+{REPO}?ref=1', False),
    ('no revision', f'hg+{REPO}', False),
    ('no revision', REPO, False),                                # the same URL as an archive
    ('no revision', f'Proto-Dist[extra] @ git+{REPO}', False),   # extras to add: pip decides
    ('no revision', 'git+https://[::1/proto', False),            # not a URL
    ('no revision', f'git+{REPO}#egg=proto-dist', True),         # a record has the URL without its fragment
    ('no revision', f'git+{REPO}@{COMMIT}#egg=proto-dist', True),
    ('no revision', f'git+{REPO}#subdirectory=sub', False),      # another package of that repository
    ('no revision', f'git+{REPO}.git', True),                    # both spellings name one repository
    ('no revision', f'git+{REPO}.git@{COMMIT}', True),
    ('no revision', f'git+{REPO}.git.git', False),
    ('with .git', f'git+{REPO}.git', True),
    ('with .git', f'git+{REPO}', True),
    ('with .git', f'git+{REPO}@v1', False),
    ('with .git', f'{REPO}.git', False),
    ('revision v1', f'git+{REPO}@v1', True),
    ('revision v1', f'git+{REPO}', True),                        # any revision meets a URL that names none
    ('revision v1', f'git+{REPO}@v2', False),
    ('subdirectory', f'git+{REPO}', False),                      # another package of that repository
    ('subdirectory', f'git+{REPO}#subdirectory=sub', True),
    ('subdirectory', f'git+{REPO}#egg=proto-dist&subdirectory=sub', True),
    ('subdirectory', f'git+{REPO}#subdirectory=sub&egg=proto-dist', True),
    ('subdirectory', f'git+{REPO}#subdirectory=sub/other', False),
    ('subdirectory', f'git+{REPO}#not-subdirectory=sub', False),
    ('archive', WHEEL, True),
    ('archive', f'Proto-Dist @ {WHEEL}', True),
    ('archive', f'Other-Name @ {WHEEL}', False),
    ('archive', f'{WHEEL} ; sys_platform != "none"', True),
    ('archive', f'{WHEEL}#sha256={SHA256}', True),
    ('archive', f'{WHEEL}.git', False),
    ('archive', WHEEL.replace('1.0', '1.1'), False),
    ('archive', f'git+{WHEEL}', False),
    ('directory', DIRECTORY, False),                             # edited in place
])
def test_url_requirement_is_installed_when_its_record_says_so(install, installer, record, requirement, installed):
    install('Proto-Dist', RECORDS[installer][record])

    assert load_prestartup()['is_installed'](requirement) is installed


@pytest.mark.parametrize('record', [
    b'{"url": "' + REPO.encode(),                                # cut short
    b'[]',
    b'null',
    ('{"url": "%s", "vcs_info": "git"}' % REPO).encode(),
    ('{"url": "%s", "note": "\xe9"}' % REPO).encode('latin-1'),  # not UTF-8
], ids=['cut short', 'a list', 'null', 'vcs_info is text', 'not UTF-8'])
def test_record_that_cannot_be_read_is_passed_over(install, record):
    install('Broken', record)
    assert load_prestartup()['is_installed'](f'git+{REPO}') is False

    install('Proto-Dist', RECORDS['pip']['no revision'])
    assert load_prestartup()['is_installed'](f'git+{REPO}') is True


def test_each_distribution_of_a_repository_is_asked(install):
    install('Proto-One', RECORDS['pip']['revision v1'])
    install('Proto-Two', RECORDS['pip']['revision v1'].replace('"v1"', '"v2"'))

    assert load_prestartup()['is_installed'](f'git+{REPO}@v1') is True
    assert load_prestartup()['is_installed'](f'git+{REPO}@v2') is True
    assert load_prestartup()['is_installed'](f'Proto-One @ git+{REPO}') is True
    assert load_prestartup()['is_installed'](f'Proto-Two @ git+{REPO}') is True


def test_what_an_uninstall_left_behind_is_not_installed(install):
    """pip renames what it removes to a name with '~' first, and does not list what it could not finish removing."""
    install('Proto-Dist', RECORDS['pip']['no revision'], listed=False, folder='~roto_dist-1.0.dist-info')

    assert load_prestartup()['is_installed'](f'git+{REPO}') is False


@pytest.mark.parametrize('from_the_url,other', [('1.0', '9.0'), ('9.0', '1.0')])
def test_two_versions_of_a_name_are_left_to_the_installer(install, from_the_url, other):
    """An upgrade or a downgrade that was cut short leaves the dist-info of the URL install beside that of another version."""
    install('Proto-Dist', RECORDS['pip']['no revision'], version=from_the_url)
    install('Proto-Dist', version=other)

    assert load_prestartup()['is_installed'](f'git+{REPO}') is False
    assert load_prestartup()['is_installed'](f'Proto-Dist @ git+{REPO}') is False


def test_two_versions_with_one_record_are_left_to_the_installer(install):
    """uv records an archive without a hash, so two versions from one URL have the same record."""
    install('Proto-Dist', RECORDS['uv']['archive'])
    install('Proto-Dist', RECORDS['uv']['archive'], version='9.0')

    assert load_prestartup()['is_installed'](WHEEL) is False


def test_distribution_that_is_found_twice_is_one(install, monkeypatch, tmp_path):
    """A folder that is on the path twice gives each of its distributions twice."""
    install('Proto-Dist', RECORDS['pip']['no revision'])
    monkeypatch.syspath_prepend(str(tmp_path / 'site'))

    assert load_prestartup()['is_installed'](f'git+{REPO}') is True


@pytest.mark.parametrize('beside,installed', [(None, False), (RECORDS['pip']['no revision'], True)], ids=['from an index', 'from the URL'])
def test_what_pip_set_aside_is_not_what_is_installed(install, beside, installed):
    """pip renames what it replaces to a name with '~' first, and that folder stays when pip is cut short: the installers pass it over."""
    install('Proto-Dist', RECORDS['pip']['no revision'], folder='~roto_dist-1.0.dist-info')
    install('Proto-Dist', beside)

    assert load_prestartup()['is_installed'](f'git+{REPO}') is installed


def test_metadata_that_cannot_be_read_is_passed_over(install, tmp_path):
    install('Proto-Dist', RECORDS['pip']['no revision'])
    install('Latin')
    (tmp_path / 'site' / 'Latin-1.0.dist-info' / 'METADATA').write_bytes(b'Metadata-Version: 2.1\nName: Latin\nVersion: 1.0\nAuthor: Caf\xe9\n')

    assert load_prestartup()['is_installed'](f'git+{REPO}') is True


def test_distribution_without_metadata_is_passed_over(install, monkeypatch, tmp_path):
    """Python 3.15 raises MetadataNotFound, a FileNotFoundError, for a folder without METADATA. It is raised here on every version."""
    install('Proto-Dist', RECORDS['pip']['no revision'])
    (tmp_path / 'site' / 'junk-1.0.dist-info').mkdir()
    read = importlib.metadata.Distribution.metadata

    def metadata(self):
        if self.read_text('METADATA') is None:
            raise FileNotFoundError('No package metadata was found.')
        return read.__get__(self, type(self))

    monkeypatch.setattr(importlib.metadata.Distribution, 'metadata', property(metadata))

    assert load_prestartup()['is_installed'](f'git+{REPO}') is True


BACKEND = '''\
import os
import zipfile

INFO = 'url_requirement_demo-1.0.dist-info'
NEEDS = os.path.join(os.path.dirname(__file__), 'needs.txt')
FILES = {
    'url_requirement_demo.py': 'VALUE = 1\\n',
    INFO + '/METADATA': 'Metadata-Version: 2.1\\nName: url-requirement-demo\\nVersion: 1.0\\n' + (
        'Requires-Dist: ' + open(NEEDS).read() + '\\n' if os.path.exists(NEEDS) else ''),
    INFO + '/WHEEL': 'Wheel-Version: 1.0\\nGenerator: test\\nRoot-Is-Purelib: true\\nTag: py3-none-any\\n',
}


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    name = 'url_requirement_demo-1.0-py3-none-any.whl'
    with zipfile.ZipFile(os.path.join(wheel_directory, name), 'w') as wheel:
        for path, text in FILES.items():
            wheel.writestr(path, text)
        wheel.writestr(INFO + '/RECORD', ''.join(path + ',,\\n' for path in [*FILES, INFO + '/RECORD']))
    return name
'''


REMOTE = 'https://example.invalid/packs/url-requirement-demo'


def commit(repo, text, needs=None):
    """Commit a change to the repository of the package, and return the commit."""
    git = ['git', '-c', 'user.name=test', '-c', 'user.email=test@example.invalid', '-c', 'commit.gpgsign=false', '-C', str(repo)]
    if not (repo / 'backend.py').exists():
        subprocess.run([*git, 'init', '-q'], check=True, capture_output=True)
        (repo / 'pyproject.toml').write_text(
            '[build-system]\nrequires = []\nbuild-backend = "backend"\nbackend-path = ["."]\n', encoding='utf-8')
        (repo / 'backend.py').write_text(BACKEND, encoding='utf-8')
    (repo / 'note.txt').write_text(text, encoding='utf-8')
    if needs:
        (repo / 'needs.txt').write_text(needs, encoding='utf-8')
    elif (repo / 'needs.txt').exists():
        (repo / 'needs.txt').unlink()
    for arguments in (['add', '-A'], ['commit', '-q', '-m', text]):
        subprocess.run([*git, *arguments], check=True, capture_output=True)
    return subprocess.run([*git, 'rev-parse', 'HEAD'], check=True, capture_output=True, text=True).stdout.strip()


def git_reads(repo):
    """The environment in which git reads the local repository for REMOTE."""
    return {**os.environ, 'PIP_NO_INDEX': '1', 'GIT_CONFIG_COUNT': '1',
            'GIT_CONFIG_KEY_0': f'url.{repo.as_posix()}.insteadOf', 'GIT_CONFIG_VALUE_0': REMOTE}


@pytest.fixture(scope='module')
def pip_installed(tmp_path_factory):
    """A package the real pip installed from a git URL: (the site directory, the URL).

    git reads a local repository for the URL, and the repository builds with a backend
    of its own, so nothing is fetched.
    """
    if shutil.which('git') is None:
        pytest.skip('no git on PATH')
    pip = [sys.executable, '-m', 'pip']
    if subprocess.run([*pip, '--version'], capture_output=True).returncode != 0:
        pytest.skip('no pip for this interpreter')

    root = tmp_path_factory.mktemp('url-requirement')
    repo = root / 'repo'
    repo.mkdir()
    commit(repo, 'one')
    site = root / 'site'
    done = subprocess.run([*pip, 'install', '--no-deps', '--target', str(site), f'git+{REMOTE}'],
                          capture_output=True, text=True, env=git_reads(repo))
    assert done.returncode == 0, done.stdout + done.stderr
    if not any(site.glob('*.dist-info')):
        pytest.skip('pip installed nothing: it runs as a dry run here')
    return site, f'git+{REMOTE}'


@pytest.fixture
def pip_site(set_lists, monkeypatch, pip_installed):  # noqa: F811
    """Make the site directory of `pip_installed` one of this interpreter and of `pip list`; return the URL."""
    site, url = pip_installed
    monkeypatch.syspath_prepend(str(site))
    monkeypatch.setattr(MANAGER_UTIL, 'subprocess', subprocess)
    monkeypatch.setattr(MANAGER_UTIL, 'make_pip_cmd', lambda cmd: [
        sys.executable, '-m', 'pip', *cmd, *(['--path', str(site)] if cmd == ['list'] else [])])
    monkeypatch.setattr(MANAGER_UTIL, 'pip_map', None)
    return url


def test_package_that_pip_installed_from_a_git_url_is_installed(pip_site):
    is_installed = load_prestartup()['is_installed']

    assert is_installed(pip_site) is True
    assert is_installed(f'url-requirement-demo @ {pip_site}') is True
    assert is_installed(pip_site + '-other') is False


def test_startup_does_not_install_a_url_requirement_again(pip_site, tmp_path):
    """From a pack's requirements.txt, and from a reserved pip command, to the pip commands that are run."""
    pack = tmp_path / 'pack'
    pack.mkdir()
    (pack / 'requirements.txt').write_text(f'{pip_site}\n{OTHER}\n', encoding='utf-8')
    script_list = tmp_path / 'install-scripts.txt'
    script_list.write_text(''.join(f'{line}\n' for line in [
        [str(pack), '#LAZY-INSTALL-SCRIPT', 'python'],
        [str(pack), 'python', '-m', 'pip', 'install', pip_site],
    ]), encoding='utf-8')
    executed = []
    startup = load_prestartup(
        ast=ast, logging=logging, comfy_path=str(pack), script_list_path=str(script_list), script_executed=False,
        processed_install=set(), process_wrap=lambda cmd, cwd=None, **kwargs: executed.append(cmd) or 0)

    startup['execute_startup_script']()

    assert [cmd[cmd.index('install') + 1:] for cmd in executed] == [[OTHER]]


def test_install_that_is_run_at_once_is_left_to_pip():
    """pip also installs what the package needs and has lost, so the command is run for an installed URL too."""
    ran = _run_child(f"""
import pathlib, subprocess
from types import SimpleNamespace
import cm_global, manager_util

manager_util.make_pip_cmd = lambda cmd: ['python', '-m', 'pip', *cmd]
manager_util.subprocess = SimpleNamespace(
    check_output=lambda *args, **kwargs: 'Package Version\\n------- -------\\nProto-Dist 1.0\\n', CalledProcessError=subprocess.CalledProcessError)
manager_util.pip_map = None
site = pathlib.Path(tmp) / 'site'
info = site / 'Proto_Dist-1.0.dist-info'
info.mkdir(parents=True)
(info / 'METADATA').write_text('Metadata-Version: 2.1\\nName: Proto-Dist\\nVersion: 1.0\\n', encoding='utf-8')
(info / 'direct_url.json').write_text({RECORDS['pip']['no revision']!r}, encoding='utf-8')
sys.path.insert(0, str(site))

cm_global.pip_blacklist, cm_global.pip_downgrade_blacklist, cm_global.pip_overrides = set(), [], {{}}
executed = []
manager_core.manager_funcs.run_script = lambda cmd, cwd='.': executed.append(cmd) or 0
result = manager_core.try_install_script(None, '.', ['python', '-m', 'pip', 'install', 'git+{REPO}'], instant_execution=True)
print(json.dumps([result, [cmd[-1] for cmd in executed]]))
""")

    assert ran == [True, [f'git+{REPO}']]


PIP = ['python', '-m', 'pip']
UV = ['python', '-m', 'uv', 'pip']
FORCED = {'pip': ['--force-reinstall', '--no-deps', '--no-cache-dir'],
          'uv': ['--force-reinstall', '--no-deps', '--no-cache', '--link-mode', 'copy']}
LATER = COMMIT.replace('f3', 'aa')


@pytest.fixture(params=['pip', 'uv'])
def installer(request, install, monkeypatch):
    """The base command of the installer in use, with Proto-Dist installed from REPO."""
    base = PIP if request.param == 'pip' else UV
    monkeypatch.setattr(MANAGER_UTIL, 'make_pip_cmd', lambda cmd: [*base, *cmd])
    monkeypatch.setattr(MANAGER_UTIL, 'is_git_remote_usable', lambda url: True)
    install('Proto-Dist', RECORDS[request.param]['no revision'])
    return SimpleNamespace(base=base, forced=FORCED[request.param], uv=request.param == 'uv', install=install,
                           records=RECORDS[request.param])


def recorder(result=lambda cmd: 0):
    """Return (run, commands): `run` records a command and returns what `result` gives for it."""
    commands = []
    return (lambda cmd: commands.append(cmd) or result(cmd)), commands


def test_fix_installs_a_url_requirement_by_force_and_other_requirements_as_ever(installer):
    assert MANAGER_UTIL.fix_cmd(f'git+{REPO}') == [*installer.base, 'install', f'git+{REPO}', *installer.forced]
    assert MANAGER_UTIL.fix_cmd(f'Proto-Dist @ git+{REPO}') == [*installer.base, 'install', f'Proto-Dist @ git+{REPO}', *installer.forced]
    assert MANAGER_UTIL.fix_cmd(WHEEL) == [*installer.base, 'install', WHEEL, *installer.forced]
    assert MANAGER_UTIL.fix_cmd('numpy>=1.20') == [*installer.base, 'install', 'numpy>=1.20']


@pytest.mark.parametrize('cmd,forced', [
    (['install', f'git+{REPO}', '--force-reinstall', '--no-deps'], True),
    (['install', f'Proto-Dist @ {WHEEL}', '--force-reinstall', '--no-deps', '--no-cache-dir'], True),
    (['install', f'git+{REPO}'], False),
    (['install', 'numpy', '--force-reinstall'], False),         # a name: nothing but a fix builds the forced command
    (['install', '--force-reinstall'], False),
    (['install', '--force-reinstall', f'git+{REPO}'], False),   # as `pip_install()` of the user builds it
    (['install.py'], False),
])
def test_forced_install_is_known_by_its_url_requirement_and_its_option(cmd, forced):
    assert MANAGER_UTIL.is_reinstall([*PIP, *cmd]) is forced


def test_fix_installs_the_requirement_as_an_install_does_and_then_the_package_by_force(installer, capsys):
    """The first resolves what the package needs and changes nothing when it cannot; the second puts a clean copy there."""
    run, commands = recorder()
    forced = MANAGER_UTIL.fix_cmd(f'git+{REPO}')

    assert MANAGER_UTIL.reinstall(forced, run) == 0
    assert commands == [[*installer.base, 'install', f'git+{REPO}'], forced]
    assert 'could not install' not in capsys.readouterr().out


def test_fix_forces_also_what_the_install_has_just_put_there(installer):
    """uv takes a commit it has built before from its cache while the remote answers: only the forced install is a clean copy."""
    forced = MANAGER_UTIL.fix_cmd(f'git+{REPO}')
    run, commands = recorder(lambda cmd: installer.install('Proto-Dist', installer.records['no revision'].replace(COMMIT, LATER)) or 0)

    assert MANAGER_UTIL.reinstall(forced, run) == 0
    assert commands == [[*installer.base, 'install', f'git+{REPO}'], forced]

    other = MANAGER_UTIL.fix_cmd(OTHER)
    run, commands = recorder(lambda cmd: installer.install('Other', installer.records['no revision'].replace(REPO, OTHER[4:])) or 0)

    assert MANAGER_UTIL.reinstall(other, run) == 0
    assert commands == [[*installer.base, 'install', OTHER], other]


def test_fix_keeps_what_is_installed_when_the_requirement_cannot_be_installed(installer):
    """What the new commit needs may not be there to install: the forced install would leave the package without it."""
    forced = MANAGER_UTIL.fix_cmd(f'git+{REPO}')
    run, commands = recorder(lambda cmd: 1)

    assert MANAGER_UTIL.reinstall(forced, run) == 1
    assert commands == [[*installer.base, 'install', f'git+{REPO}']]


def test_fix_goes_on_when_only_the_forced_install_fails(installer, capsys):
    """The requirement is met as an install meets it, so the other requirements of the pack are still fixed.

    Nothing is installed in place of the clean copy: that it failed does not say that the remote is out of reach.
    """
    forced = MANAGER_UTIL.fix_cmd(f'git+{REPO}')
    run, commands = recorder(lambda cmd: int(cmd == forced))

    assert MANAGER_UTIL.reinstall(forced, run) == 0
    assert commands == [[*installer.base, 'install', f'git+{REPO}'], forced]
    assert f"could not install 'git+{REPO}' again by force" in capsys.readouterr().out


@pytest.mark.parametrize('remote', ['out of reach', 'answers'])
@pytest.mark.parametrize('record,requirement,from_the_cache', [
    ('no revision', f'git+{REPO}', f'git+{REPO}@{COMMIT}'),
    ('no revision', f'Proto-Dist @ git+{REPO}', f'git+{REPO}@{COMMIT}'),
    ('with .git', f'git+{REPO}', f'git+{REPO}.git@{COMMIT}'),
    ('subdirectory', f'git+{REPO}#subdirectory=sub', f'git+{REPO}@{COMMIT}#subdirectory=sub'),
])
def test_fix_uses_the_cache_of_uv_only_when_the_remote_is_out_of_reach(installer, monkeypatch, remote, record, requirement, from_the_cache):
    """uv installs the commit that is installed from its cache; pip has no option to ask it with."""
    installer.install('Proto-Dist', installer.records[record])
    asked = []
    monkeypatch.setattr(MANAGER_UTIL, 'is_git_remote_usable', lambda url: asked.append(url) or remote == 'answers')
    forced = MANAGER_UTIL.fix_cmd(requirement)
    plain = [*installer.base, 'install', requirement]
    cached = [*installer.base, 'install', from_the_cache, '--force-reinstall', '--no-deps', '--offline']
    run, commands = recorder(lambda cmd: int(cmd == plain))

    code = MANAGER_UTIL.reinstall(forced, run)

    if installer.uv and remote == 'out of reach':
        assert (code, commands, asked) == (0, [plain, cached], [json.loads(installer.records[record])['url']])
    else:
        assert (code, commands) == (1, [plain])


def test_fix_does_not_take_a_package_of_another_name_from_the_cache(installer, monkeypatch):
    """A requirement that gives a name is met by a distribution of that name only."""
    monkeypatch.setattr(MANAGER_UTIL, 'is_git_remote_usable', lambda url: False)
    forced = MANAGER_UTIL.fix_cmd(f'Other-Name @ git+{REPO}')
    run, commands = recorder(lambda cmd: 1)

    assert MANAGER_UTIL.reinstall(forced, run) == 1
    assert commands == [[*installer.base, 'install', f'Other-Name @ git+{REPO}']]


def test_fix_with_a_run_that_raises_as_in_cm_cli(installer, monkeypatch):
    """What `run` raised for the install is raised again, unless the cache made the fix good."""
    monkeypatch.setattr(MANAGER_UTIL, 'is_git_remote_usable', lambda url: False)
    forced = MANAGER_UTIL.fix_cmd(f'git+{REPO}')
    plain = [*installer.base, 'install', f'git+{REPO}']
    commands = []

    def run(cmd):
        commands.append(cmd)
        if cmd == plain:
            raise subprocess.CalledProcessError(1, cmd)
        return 0

    if installer.uv:
        assert MANAGER_UTIL.reinstall(forced, run) == 0
    else:
        with pytest.raises(subprocess.CalledProcessError):
            MANAGER_UTIL.reinstall(forced, run)
    assert [cmd[-1] for cmd in commands] == [plain[-1], *(['--offline'] if installer.uv else [])]


def startup_runs(tmp_path, lines):
    """What the start of the server runs for the reserved lines."""
    script_list = tmp_path / 'install-scripts.txt'
    script_list.write_text(''.join(f'{line}\n' for line in lines), encoding='utf-8')
    executed = []
    startup = load_prestartup(
        ast=ast, logging=logging, comfy_path=str(tmp_path), script_list_path=str(script_list), script_executed=False,
        process_wrap=lambda cmd, cwd=None, **kwargs: executed.append(cmd) or 0)
    startup['execute_startup_script']()
    return executed


def test_startup_runs_the_forced_install_a_fix_reserved(installer, tmp_path):
    """The plain command for the same requirement is skipped: the package is installed."""
    forced = MANAGER_UTIL.fix_cmd(f'git+{REPO}')
    plain = [*installer.base, 'install', f'git+{REPO}']

    assert startup_runs(tmp_path, [[str(tmp_path), *plain], [str(tmp_path), *forced]]) == [plain, forced]


def test_command_the_user_forced_is_run_as_it_is(installer, tmp_path):
    """`pip_install()` reserves what the user typed with #FORCE; it is not a fix."""
    typed = [*installer.base, 'install', f'git+{REPO}', '--force-reinstall']

    assert startup_runs(tmp_path, [[str(tmp_path), '#FORCE', *typed]]) == [typed]


def test_blacklisted_requirement_is_not_installed_by_a_reserved_forced_install(installer, set_lists, tmp_path):  # noqa: F811
    set_lists(blacklist={f'git+{REPO}'})

    assert startup_runs(tmp_path, [[str(tmp_path), *MANAGER_UTIL.fix_cmd(f'git+{REPO}')]]) == []


CM_CLI_FIX = """
import asyncio, traceback
from typing import Annotated, List
from unittest.mock import Mock

commands = [node for node in ast.parse(pathlib.Path('cm-cli.py').read_text(encoding='utf-8')).body
            if isinstance(node, ast.FunctionDef) and node.name in ('for_each_nodes', 'fix_node', 'fix')]
for command in commands:
    command.decorator_list = []
scope = {'typer': Mock(), 'List': List, 'Annotated': Annotated, 'asyncio': asyncio, 'traceback': traceback, 'cmd_ctx': Mock(no_deps=False),
         'comfy_path': '', 'manager_util': manager_util, 'core': manager_core, 'unified_manager': manager}
exec(compile(ast.Module(body=commands, type_ignores=[]), 'cm-cli.py', 'exec'), scope)
fix = scope['fix']
"""


@pytest.fixture(scope='module')
def fixes():
    """What a fix of a pack runs at once and what it reserves, in the real manager_core, with the commands recorded."""
    return _run_child(f"""
import ast, pathlib, subprocess
from types import SimpleNamespace
import cm_global, manager_util

manager_util.make_pip_cmd = lambda cmd: ['python', '-m', 'pip', *cmd]
manager_util.subprocess = SimpleNamespace(
    check_output=lambda *args, **kwargs: 'Package Version\\n------- -------\\nProto-Dist 1.0\\n', CalledProcessError=subprocess.CalledProcessError)
manager_util.pip_map = None
manager_util.PIPFixer = lambda *args: SimpleNamespace(fix_broken=lambda: None)
site = pathlib.Path(tmp) / 'site'
info = site / 'Proto_Dist-1.0.dist-info'
info.mkdir(parents=True)
(info / 'METADATA').write_text('Metadata-Version: 2.1\\nName: Proto-Dist\\nVersion: 1.0\\n', encoding='utf-8')
(info / 'direct_url.json').write_text({RECORDS['pip']['no revision']!r}, encoding='utf-8')
sys.path.insert(0, str(site))
pack = pathlib.Path(tmp) / 'pack'
pack.mkdir()
(pack / 'requirements.txt').write_text('git+{REPO}\\nscipy\\n', encoding='utf-8')

cm_global.pip_blacklist, cm_global.pip_downgrade_blacklist, cm_global.pip_overrides = set(), [], {{}}
executed = []
manager_core.manager_funcs.run_script = lambda cmd, cwd='.': executed.append(cmd[3:]) or 0
manager_core.manager_startup_script_path = tmp
manager = manager_core.unified_manager
manager.unknown_active_nodes = {{'pack': ('https://example.invalid/pack', str(pack))}}

def ran(action):
    del executed[:]
    action()
    return list(executed)

manager.processed_install = set()
install = ran(lambda: manager.execute_install_script(None, str(pack), instant_execution=True))
after_the_install = ran(lambda: manager.unified_fix('pack', 'unknown', instant_execution=True))
cm_global.pip_blacklist = {{'git+{REPO}'}}
blacklisted = ran(lambda: manager.unified_fix('pack', 'unknown', instant_execution=True))
cm_global.pip_blacklist = set()
manager_core.get_config()['always_lazy_install'] = True
nothing = ran(lambda: manager.unified_fix('pack', 'unknown'))

def reserved():
    with open(pathlib.Path(tmp) / 'install-scripts.txt', encoding='utf-8') as file:
        return [ast.literal_eval(line)[4:] for line in file]

by_the_fix = reserved()
second = pathlib.Path(tmp) / 'second'
second.mkdir()
(second / 'requirements.txt').write_text('scipy\\ngit+{REPO}\\npillow\\n', encoding='utf-8')
manager.unknown_active_nodes['second'] = ('https://example.invalid/second', str(second))
manager.resolve_node_spec = lambda spec, guess_mode=None: (spec, 'unknown', False)
{CM_CLI_FIX}
fix(['pack', 'second'], None, None, None)
by_the_command = reserved()[len(by_the_fix):]
third = pathlib.Path(tmp) / 'third'
third.mkdir()
(third / 'requirements.txt').write_text('pillow\\nnumpy\\n', encoding='utf-8')
manager.execute_install_script(None, str(third))
print(json.dumps({{'install': install, 'after the install': after_the_install, 'blacklisted': blacklisted, 'nothing': nothing,
                  'reserved': by_the_fix, 'reserved by cm-cli': by_the_command,
                  'reserved by an install after it': reserved()[len(by_the_fix) + len(by_the_command):]}}))
""")


def test_fix_of_a_pack_installs_its_url_requirement_again(fixes):
    """Also right after an install of the same pack, which has run the same lines in this session."""
    plain = ['install', f'git+{REPO}']
    forced = [*plain, '--force-reinstall', '--no-deps', '--no-cache-dir']

    assert fixes['install'] == [plain, ['install', 'scipy']]
    assert fixes['after the install'] == [plain, forced, ['install', 'scipy']]
    assert fixes['blacklisted'] == [['install', 'scipy']]
    assert fixes['nothing'] == []
    assert fixes['reserved'] == [forced, ['install', 'scipy']]


def test_fix_of_several_packs_by_one_command_runs_a_requirement_they_share_once(fixes):
    """`cm-cli fix` of two packs, after fixes of the first in the session: none of those holds a line back, the command itself does.

    An install after it leaves out what the fix has installed.
    """
    forced = ['install', f'git+{REPO}', '--force-reinstall', '--no-deps', '--no-cache-dir']

    assert fixes['reserved by cm-cli'] == [forced, ['install', 'scipy'], ['install', 'pillow']]
    assert fixes['reserved by an install after it'] == [['install', 'numpy']]


def test_cm_cli_says_each_command_before_the_command_writes():
    """cm-cli runs the installer on its own stdout, and a pipe keeps what is printed until it is flushed."""
    assert _run_child(f"""
from types import SimpleNamespace
import cm_global, manager_util

manager_util.make_pip_cmd = lambda cmd: ['python', '-m', 'pip', *cmd]
cm_global.pip_blacklist, cm_global.pip_downgrade_blacklist, cm_global.pip_overrides = set(), [], {{}}
written, out, said = [], [], []
manager_core.subprocess = SimpleNamespace(check_call=lambda cmd, **options: said.append(''.join(out)))
console = sys.stdout
sys.stdout = SimpleNamespace(write=written.append, flush=lambda: (out.extend(written), written.clear()))
try:
    result = manager_core.try_install_script(None, '.', manager_util.fix_cmd('git+{REPO}'), instant_execution=True)
finally:
    sys.stdout = console
print(json.dumps([result, [text.count('EXECUTE =>') for text in said]]))
""") == [True, [1, 2]]


@pytest.fixture(scope='module')
def pip_environment(tmp_path_factory):
    """A virtual environment with its own pip, and the package installed in it from a git URL.

    As for `pip_installed`, nothing is fetched. Returns the python of the environment, its
    site directory and the repository.
    """
    if shutil.which('git') is None:
        pytest.skip('no git on PATH')
    root = tmp_path_factory.mktemp('url-requirement-fix')
    if subprocess.run([sys.executable, '-m', 'venv', str(root / 'env')], capture_output=True).returncode != 0:
        pytest.skip('no venv with pip for this interpreter')
    python = str(root / 'env' / ('Scripts' if os.name == 'nt' else 'bin') / 'python')
    site = subprocess.run([python, '-c', "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                          check=True, capture_output=True, text=True).stdout.strip()
    repo = root / 'repo'
    repo.mkdir()
    commit(repo, 'one')
    done = subprocess.run([python, '-m', 'pip', 'install', f'git+{REMOTE}'], capture_output=True, text=True, env=git_reads(repo))
    assert done.returncode == 0, done.stdout + done.stderr
    if not any(Path(site).glob('url_requirement_demo-*.dist-info')):
        pytest.skip('pip installed nothing: it runs as a dry run here')
    return SimpleNamespace(python=python, site=site, repo=repo)


def test_fix_with_the_real_pip(set_lists, monkeypatch, pip_environment):  # noqa: F811
    """What is installed after each fix: a new commit of the same version, one whose needs cannot be had, no remote."""
    env, repo = git_reads(pip_environment.repo), pip_environment.repo
    monkeypatch.syspath_prepend(pip_environment.site)
    monkeypatch.setattr(MANAGER_UTIL, 'subprocess', subprocess)
    monkeypatch.setattr(MANAGER_UTIL, 'make_pip_cmd', lambda cmd: [pip_environment.python, '-m', 'pip', *cmd])
    monkeypatch.setattr(MANAGER_UTIL, 'pip_map', None)

    def fix():
        code = MANAGER_UTIL.reinstall(MANAGER_UTIL.fix_cmd(f'git+{REMOTE}'), lambda cmd: subprocess.run(cmd, capture_output=True, env=env).returncode)
        MANAGER_UTIL.clear_pip_cache()
        return code, MANAGER_UTIL.installed_from(f'git+{REMOTE}')['vcs_info']['commit_id']

    second = commit(repo, 'two')
    assert fix() == (0, second)                     # pip alone leaves the first commit: the version is the same

    commit(repo, 'three', needs='a-package-that-no-index-has')
    code, installed = fix()
    assert code != 0 and installed == second        # the commit that works is kept

    fourth = commit(repo, 'four')
    repo.rename(repo.with_name('away'))
    code, installed = fix()
    assert code != 0 and installed == second        # out of reach: kept

    repo.with_name('away').rename(repo)
    assert fix() == (0, fourth)


@pytest.fixture(scope='module')
def uv_environment(tmp_path_factory):
    """A virtual environment of uv with a cache of its own, and the package installed in it from a git URL.

    As for `pip_installed`, nothing is fetched. uv that is run as a module works on the
    environment of its interpreter, so UV_PYTHON names the one of the test. Returns its
    site directory, the repository and the environment variables for uv and git.
    """
    uv = [sys.executable, '-m', 'uv']
    if shutil.which('git') is None:
        pytest.skip('no git on PATH')
    if subprocess.run([*uv, '--version'], capture_output=True).returncode != 0:
        pytest.skip('no uv for this interpreter')
    root = tmp_path_factory.mktemp('url-requirement-uv')
    repo = root / 'repo'
    repo.mkdir()
    commit(repo, 'one')
    variables = {'UV_PYTHON': str(root / 'env' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')),
                 'UV_CACHE_DIR': str(root / 'cache'), 'UV_NO_INDEX': '1',
                 **{name: value for name, value in git_reads(repo).items() if name.startswith('GIT_CONFIG_')}}

    def run(*command):
        done = subprocess.run([*uv, *command], capture_output=True, text=True, env={**os.environ, **variables})
        assert done.returncode == 0, done.stdout + done.stderr
        return done.stdout

    run('venv', '--python', sys.executable, str(root / 'env'))
    assert run('pip', 'freeze') == '', 'uv does not work on the environment of the test'
    run('pip', 'install', f'git+{REMOTE}')
    return SimpleNamespace(site=next((root / 'env').glob('[Ll]ib/**/site-packages')), repo=repo, variables=variables)


def test_fix_with_the_real_uv(set_lists, monkeypatch, uv_environment):  # noqa: F811
    """As with pip, but uv has a cache to install from: only when the remote is out of reach."""
    repo, module = uv_environment.repo, uv_environment.site / 'url_requirement_demo.py'
    for name, value in uv_environment.variables.items():
        monkeypatch.setenv(name, value)
    monkeypatch.syspath_prepend(str(uv_environment.site))
    monkeypatch.setattr(MANAGER_UTIL, 'subprocess', subprocess)
    monkeypatch.setattr(MANAGER_UTIL, 'make_pip_cmd', lambda cmd: [sys.executable, '-m', 'uv', 'pip', *cmd])
    monkeypatch.setattr(MANAGER_UTIL, 'pip_map', None)

    def fix(clean_copy=True):
        """`clean_copy=False`: the install without the cache fails, as with a temporary folder that is full."""
        code = MANAGER_UTIL.reinstall(MANAGER_UTIL.fix_cmd(f'git+{REMOTE}'), lambda cmd: (
            subprocess.run(cmd, capture_output=True).returncode if clean_copy or '--no-cache' not in cmd else 1))
        MANAGER_UTIL.clear_pip_cache()
        return code, MANAGER_UTIL.installed_from(f'git+{REMOTE}')['vcs_info']['commit_id']

    second = commit(repo, 'two')
    assert fix() == (0, second)

    cached = list(Path(uv_environment.variables['UV_CACHE_DIR']).rglob(module.name))
    assert cached
    for copy in cached:
        copy.unlink()                                                  # the installed file may be a link to it
        copy.write_text('VALUE = "cached"\n', encoding='utf-8')
    with monkeypatch.context() as linked:
        if os.name != 'nt':                                            # a symlink needs a privilege there
            linked.setenv('UV_LINK_MODE', 'symlink')                   # uv refuses to link to a cache it does not keep
        assert fix() == (0, second) and module.read_text(encoding='utf-8') == 'VALUE = 1\n'   # the remote answers: not from the cache

    assert fix(clean_copy=False) == (0, second) and module.read_text(encoding='utf-8') == 'VALUE = 1\n'   # kept: nothing from the cache

    commit(repo, 'three', needs='a-package-that-no-index-has')
    module.unlink()
    code, installed = fix()
    assert code != 0 and installed == second and not module.exists()   # the remote answers: the cache is not asked

    fourth = commit(repo, 'four')
    repo.rename(repo.with_name('away'))
    assert fix() == (0, second) and module.read_text(encoding='utf-8') == 'VALUE = "cached"\n'   # out of reach: from the cache

    repo.with_name('away').rename(repo)
    assert fix() == (0, fourth)
