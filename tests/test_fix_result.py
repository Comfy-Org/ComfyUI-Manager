from types import SimpleNamespace

import pytest

from _install_flags_testutil import import_reader
from test_pip_blacklist_matching import set_lists  # noqa: F401 -- fixture


@pytest.fixture(params=['glob', 'legacy'])
def fix(request, set_lists, monkeypatch, tmp_path):  # noqa: F811
    core = import_reader(request.param)
    pack = tmp_path / 'pack'
    pack.mkdir()
    (pack / 'requirements.txt').write_text('first\nsecond\n', encoding='utf-8')
    (pack / 'install.py').write_text('', encoding='utf-8')
    monkeypatch.setattr(core.manager_util, 'PIPFixer', lambda *args: SimpleNamespace(fix_broken=lambda: None))
    monkeypatch.setattr(core.manager_util, 'use_unified_resolver', False)
    monkeypatch.setattr(core.context, 'manager_startup_script_path', str(tmp_path))
    monkeypatch.setattr(core.unified_manager, 'processed_install', set())
    monkeypatch.setattr(core.unified_manager, 'unknown_active_nodes', {'pack': ('https://example.invalid/pack', str(pack))})

    def fix(fails=(), node='pack', system='Linux', always_lazy_install=False):
        monkeypatch.setattr(core.manager_funcs, 'run_script', lambda cmd, cwd='.': int(cmd[-1] in fails))
        monkeypatch.setattr(core.platform, 'system', lambda: system)
        monkeypatch.setattr(core, 'get_config', lambda: {'always_lazy_install': always_lazy_install})
        result = core.unified_manager.unified_fix(node, 'unknown')
        return result.result, result.msg

    return fix


def test_fix_whose_commands_all_run_succeeds(fix):
    assert fix() == (True, None)


@pytest.mark.parametrize('fails', ['second', 'install.py'])
def test_fix_fails_when_a_command_of_its_install_script_fails(fix, fails):
    assert fix(fails=[fails]) == (False, 'Failed to execute install script: pack@unknown')


@pytest.mark.parametrize('reserved', [{'always_lazy_install': True}, {'system': 'Windows'}])
def test_fix_that_is_reserved_succeeds_before_its_commands_run(fix, reserved):
    assert fix(fails=['second'], **reserved) == (True, None)


def test_fix_of_a_nodepack_that_is_not_there_fails(fix):
    assert fix(node='missing') == (False, 'not found: missing@unknown')
