"""restore_pip_snapshot decides success from pip's exit status.

The pip packages of a snapshot are restored in three groups, each chosen by its own
option: packages named by version, packages given by a remote URL, and packages given
by a local `file:` URL. The first group is installed in one pip run, and only when that
run fails is each package installed by itself without dependencies. A package is
reported as failed only when pip exits with an error for it.
"""

import subprocess
from types import SimpleNamespace

import pytest

from manager_test_utils import load_manager_util

MANAGER_UTIL = load_manager_util()


PIPS = {
    'alpha==1.0': '',
    'beta==2.0': '',
    'gamma @ https://example.com/gamma.whl': 'https://example.com/gamma.whl',
    'delta @ file:///wheels/delta.whl': 'file:///wheels/delta.whl',
    'torch==2.5.1': '',
}


@pytest.fixture
def restore(monkeypatch, capsys):
    """Run restore_pip_snapshot() with pip replaced; return the pip commands and the reported failures."""
    manager_util = MANAGER_UTIL

    def run(options, failing=()):
        commands = []

        def check_call(cmd, **_):
            commands.append(cmd[3:])
            if any(name in arg for arg in cmd for name in failing):
                raise subprocess.CalledProcessError(1, cmd)
            return 0

        def check_output(cmd, **_):
            # pip's output, as the real check_output returns it: never an exit status.
            return check_call(cmd) or b'Successfully installed\n'

        monkeypatch.setattr(manager_util, 'make_pip_cmd', lambda cmd: ['python', '-m', 'pip', *cmd])
        monkeypatch.setattr(manager_util, 'subprocess', SimpleNamespace(
            check_call=check_call, check_output=check_output,
            CalledProcessError=subprocess.CalledProcessError))

        manager_util.restore_pip_snapshot(PIPS, options)
        report = capsys.readouterr().out.strip().splitlines()[-1]
        return commands, report

    return run


def test_packages_installed_in_one_run_get_no_second_run(restore):
    commands, report = restore(['--pip-non-url'])

    assert commands == [['install', 'alpha==1.0', 'beta==2.0']]
    assert report == 'Installation failed for pip packages: []'


def test_failed_run_falls_back_to_one_package_at_a_time(restore):
    commands, report = restore(['--pip-non-url'], failing=['beta'])

    assert commands == [
        ['install', 'alpha==1.0', 'beta==2.0'],
        ['install', '--no-deps', 'alpha==1.0'],
        ['install', '--no-deps', 'beta==2.0'],
    ]
    assert report == "Installation failed for pip packages: ['beta==2.0']"


@pytest.mark.parametrize('option, url', [
    ('--pip-non-local-url', 'https://example.com/gamma.whl'),
    ('--pip-local-url', 'file:///wheels/delta.whl'),
])
def test_url_package_is_reported_only_when_pip_fails(restore, option, url):
    commands, report = restore([option])
    assert commands == [['install', '--no-deps', url]]
    assert report == 'Installation failed for pip packages: []'

    commands, report = restore([option], failing=[url])
    assert commands == [['install', '--no-deps', url]]
    assert report == f"Installation failed for pip packages: ['{url}']"


def test_every_failed_package_is_reported(restore):
    urls = ['https://example.com/gamma.whl', 'file:///wheels/delta.whl']

    commands, report = restore(['--pip-non-url', '--pip-non-local-url', '--pip-local-url'],
                               failing=['alpha', 'beta', *urls])

    assert commands == [
        ['install', 'alpha==1.0', 'beta==2.0'],
        ['install', '--no-deps', 'alpha==1.0'],
        ['install', '--no-deps', 'beta==2.0'],
        ['install', '--no-deps', urls[0]],
        ['install', '--no-deps', urls[1]],
    ]
    assert report == f"Installation failed for pip packages: {['alpha==1.0', 'beta==2.0', *urls]}"


def test_group_without_its_option_is_left_alone(restore):
    commands, report = restore([])

    assert commands == []
    assert report == 'Installation failed for pip packages: []'
