"""PIPFixer brings the installed OpenCV packages to one version.

The four OpenCV packages all install the `cv2` module, and the one installed last
provides it. When they are installed at different versions, PIPFixer reinstalls the
older ones at the newest installed version, without their dependencies, and leaves
`cv2` to the preferred one: a headless package rather than one with the GUI, and within
each kind the one with the contrib modules. Which package was the older one makes no
difference. OpenCV packages listed in pip_auto_fix.list are left to that list.
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
    """Run PIPFixer.fix_broken() against a given `pip list` and return the pip commands it ran, in order."""
    import_context()
    from comfyui_manager.common import manager_util

    def run(installed, pip_auto_fix=None):
        pip_list = 'Package Version\n------- -------\n' + ''.join(
            f'{name} {version}\n' for name, version in {**OTHER_PACKAGES, **installed}.items())
        commands = []

        def check_output(cmd, **_):
            if cmd[-1] == 'list':
                return pip_list
            commands.append(' '.join(cmd[3:]))
            return ''

        monkeypatch.setattr(manager_util, 'make_pip_cmd', lambda cmd: ['python', '-m', 'pip', *cmd])
        monkeypatch.setattr(manager_util, 'subprocess', SimpleNamespace(
            check_output=check_output, CalledProcessError=subprocess.CalledProcessError))
        monkeypatch.setattr(manager_util, 'pip_map', None)
        if pip_auto_fix is not None:
            (tmp_path / 'pip_auto_fix.list').write_text(pip_auto_fix, encoding='utf-8')

        previous = manager_util.get_installed_packages(True)
        manager_util.PIPFixer(previous, str(tmp_path), str(tmp_path)).fix_broken()
        return commands

    return run


def test_older_packages_are_raised_to_the_newest_installed_version(fix_broken):
    """The preferred package, opencv-contrib-python-headless, is installed last."""
    assert fix_broken({
        'opencv-python': '4.11.0.86',
        'opencv-python-headless': '4.10.0.84',
        'opencv-contrib-python': '4.10.0.84',
        'opencv-contrib-python-headless': '4.9.0.80',
    }) == [
        'install --no-deps opencv-contrib-python==4.11.0.86',
        'install --no-deps opencv-python-headless==4.11.0.86',
        'install --no-deps opencv-contrib-python-headless==4.11.0.86',
    ]


@pytest.mark.parametrize('gui, headless', [
    ('opencv-python', 'opencv-python-headless'),
    ('opencv-contrib-python', 'opencv-python-headless'),
    ('opencv-contrib-python', 'opencv-contrib-python-headless'),
])
def test_headless_package_provides_cv2_beside_a_gui_package(fix_broken, gui, headless):
    """A package with the GUI needs system libraries that Linux may lack, so it must not replace a headless `cv2`.

    The result is the same whichever of the two was the older one.
    """
    assert fix_broken({gui: '4.13.0.92', headless: '4.10.0.84'}) == [f'install --no-deps {headless}==4.13.0.92']
    assert fix_broken({gui: '4.10.0.84', headless: '4.13.0.92'}) == [
        f'install --no-deps {gui}==4.13.0.92',
        f'install --no-deps --force-reinstall {headless}==4.13.0.92',
    ]


@pytest.mark.parametrize('plain, contrib', [
    ('opencv-python', 'opencv-contrib-python'),
    ('opencv-python-headless', 'opencv-contrib-python-headless'),
])
def test_contrib_package_provides_cv2_beside_the_plain_one_of_its_kind(fix_broken, plain, contrib):
    """Raising the plain package replaces the `cv2` of the contrib one, which must be put back."""
    assert fix_broken({plain: '4.11.0.86', contrib: '4.10.0.84'}) == [f'install --no-deps {contrib}==4.11.0.86']
    assert fix_broken({plain: '4.10.0.84', contrib: '4.11.0.86'}) == [
        f'install --no-deps {plain}==4.11.0.86',
        f'install --no-deps --force-reinstall {contrib}==4.11.0.86',
    ]


def test_fourth_version_component_is_compared_as_a_number(fix_broken):
    """4.11.0.100 is newer than 4.11.0.86; compared as text it would be older."""
    assert fix_broken({
        'opencv-python': '4.11.0.100',
        'opencv-contrib-python': '4.11.0.86',
    }) == ['install --no-deps opencv-contrib-python==4.11.0.100']


def test_opencv_packages_listed_in_pip_auto_fix_are_left_to_that_list(fix_broken):
    """Raising a package pinned there would be undone by the pip_auto_fix.list step, at every startup."""
    assert fix_broken({
        'opencv-python': '4.10.0.84',
        'opencv-contrib-python': '4.11.0.86',
    }, pip_auto_fix='opencv-python==4.10.0.84\n') == []


def test_other_packages_in_pip_auto_fix_do_not_stop_the_repair(fix_broken):
    assert fix_broken({
        'opencv-python': '4.10.0.84',
        'opencv-python-headless': '4.11.0.86',
    }, pip_auto_fix='torch>=2.5.0\n') == [
        'install --no-deps opencv-python==4.11.0.86',
        'install --no-deps --force-reinstall opencv-python-headless==4.11.0.86',
    ]


@pytest.mark.parametrize('installed', [
    {'opencv-python': '4.11.0.86', 'opencv-python-headless': '4.11.0.86'},
    {'opencv-python-rolling': '5.0.0.20221015', 'opencv-python': '4.11.0.86', 'opencv-python-headless': '4.11.0.86'},
], ids=['same version', 'package with a longer name'])
def test_nothing_is_installed_when_the_versions_already_agree(fix_broken, installed):
    """The order of preference is applied only when a package has to be raised."""
    assert fix_broken(installed) == []
