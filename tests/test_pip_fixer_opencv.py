"""PIPFixer brings the installed OpenCV packages to one version.

The four OpenCV packages all install the `cv2` module. When they are installed at
different versions, PIPFixer reinstalls the older ones at the newest installed version,
without their dependencies.
"""

import subprocess
from types import SimpleNamespace

import pytest

from _install_flags_testutil import import_context


# Packages PIPFixer looks at besides OpenCV; listed so that only the OpenCV step acts.
OTHER_PACKAGES = {
    'torch': '2.5.1',
    'torchvision': '0.20.1',
    'torchaudio': '2.5.1',
    'comfyui_frontend_package': '1.30.6',
}


@pytest.fixture
def fix_broken(monkeypatch, tmp_path):
    """Run PIPFixer.fix_broken() against a given `pip list` and return the pip commands it ran."""
    import_context()
    from comfyui_manager.common import manager_util

    def run(installed):
        packages = {**OTHER_PACKAGES, **installed}
        pip_list = 'Package Version\n------- -------\n' + ''.join(
            f'{name} {version}\n' for name, version in packages.items())
        commands = []

        def check_output(cmd, **_):
            if cmd[-1] == 'list':
                return pip_list
            commands.append(cmd)
            return ''

        monkeypatch.setattr(manager_util, 'make_pip_cmd', lambda cmd: ['python', '-m', 'pip', *cmd])
        monkeypatch.setattr(manager_util, 'subprocess', SimpleNamespace(
            check_output=check_output, CalledProcessError=subprocess.CalledProcessError))
        monkeypatch.setattr(manager_util, 'pip_map', None)

        previous = manager_util.get_installed_packages(True)
        manager_util.PIPFixer(previous, str(tmp_path), str(tmp_path)).fix_broken()
        return sorted(' '.join(cmd[3:]) for cmd in commands)

    return run


def test_older_packages_are_raised_to_the_newest_installed_version(fix_broken):
    assert fix_broken({
        'opencv-python': '4.11.0.86',
        'opencv-python-headless': '4.10.0.84',
        'opencv-contrib-python': '4.10.0.84',
        'opencv-contrib-python-headless': '4.9.0.80',
    }) == [
        'install --no-deps opencv-contrib-python-headless==4.11.0.86',
        'install --no-deps opencv-contrib-python==4.11.0.86',
        'install --no-deps opencv-python-headless==4.11.0.86',
    ]


def test_fourth_version_component_is_compared_as_a_number(fix_broken):
    """4.11.0.100 is newer than 4.11.0.86; compared as text it would be older."""
    assert fix_broken({
        'opencv-python': '4.11.0.100',
        'opencv-python-headless': '4.11.0.86',
    }) == ['install --no-deps opencv-python-headless==4.11.0.100']


@pytest.mark.parametrize('installed', [
    {'opencv-python': '4.11.0.86'},
    {'opencv-python': '4.11.0.86', 'opencv-python-headless': '4.11.0.86'},
    {'opencv-python-rolling': '5.0.0.20221015', 'opencv-python': '4.11.0.86', 'opencv-python-headless': '4.11.0.86'},
], ids=['one installed', 'same version', 'package with a longer name'])
def test_nothing_is_installed_when_the_versions_already_agree(fix_broken, installed):
    assert fix_broken(installed) == []
