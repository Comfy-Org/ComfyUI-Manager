"""Form factor the CNR client reports to the registry."""

import pytest

from _install_flags_testutil import import_context


@pytest.fixture
def cnr_utils():
    import_context()
    from comfyui_manager.common import cnr_utils

    return cnr_utils


@pytest.mark.parametrize(
    ('system', 'desktop', 'expected'),
    [
        ('Windows', True, 'desktop-win'),
        ('Darwin', True, 'desktop-mac'),
        ('Linux', True, 'desktop-linux'),
        ('FreeBSD', True, 'other'),
        ('Windows', False, 'git-windows'),
        ('Darwin', False, 'git-mac'),
        ('Linux', False, 'git-linux'),
        ('FreeBSD', False, 'other'),
    ],
)
def test_form_factor(cnr_utils, monkeypatch, system, desktop, expected):
    monkeypatch.setattr(cnr_utils.platform, 'system', lambda: system)
    if desktop:
        monkeypatch.setenv('__COMFYUI_DESKTOP_VERSION__', '1.0.0')
    else:
        monkeypatch.delenv('__COMFYUI_DESKTOP_VERSION__', raising=False)

    assert cnr_utils.get_form_factor() == expected
