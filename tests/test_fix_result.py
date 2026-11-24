import pytest

from test_install_flags_config import _run_child


@pytest.fixture(scope='module')
def fixes():
    return _run_child("""
import pathlib
from types import SimpleNamespace
import cm_global, manager_util

manager_util.make_pip_cmd = lambda cmd: ['python', '-m', 'pip', *cmd]
manager_util.get_installed_packages = lambda renew=False: {}
manager_util.PIPFixer = lambda *args: SimpleNamespace(fix_broken=lambda: None)
cm_global.pip_blacklist, cm_global.pip_downgrade_blacklist, cm_global.pip_overrides = set(), [], {}
manager_core.manager_startup_script_path = tmp
manager = manager_core.unified_manager
pack = pathlib.Path(tmp) / 'pack'
pack.mkdir()
(pack / 'requirements.txt').write_text('first\\nsecond\\n', encoding='utf-8')
(pack / 'install.py').write_text('', encoding='utf-8')
manager.unknown_active_nodes = {'pack': ('https://example.invalid/pack', str(pack))}

def fix(fails=(), node='pack', system='Linux', always_lazy_install=False):
    manager_core.manager_funcs.run_script = lambda cmd, cwd='.': int(cmd[-1] in fails)
    manager_core.platform.system = lambda: system
    manager_core.get_config()['always_lazy_install'] = always_lazy_install
    manager.processed_install = set()
    result = manager.unified_fix(node, 'unknown')
    return [result.result, result.msg]

print(json.dumps({
    'every command runs': fix(),
    'a requirement cannot be installed': fix(fails=['second']),
    'install.py fails': fix(fails=['install.py']),
    'reserved by always_lazy_install': fix(fails=['second'], always_lazy_install=True),
    'reserved on Windows': fix(fails=['second'], system='Windows'),
    'no such nodepack': fix(node='missing'),
}))
""")


def test_fix_whose_commands_all_run_succeeds(fixes):
    assert fixes['every command runs'] == [True, None]


@pytest.mark.parametrize('case', ['a requirement cannot be installed', 'install.py fails'])
def test_fix_fails_when_a_command_of_its_install_script_fails(fixes, case):
    assert fixes[case] == [False, 'Failed to execute install script: pack@unknown']


@pytest.mark.parametrize('case', ['reserved by always_lazy_install', 'reserved on Windows'])
def test_fix_that_is_reserved_succeeds_before_its_commands_run(fixes, case):
    assert fixes[case] == [True, None]


def test_fix_of_a_nodepack_that_is_not_there_fails(fixes):
    assert fixes['no such nodepack'] == [False, 'not found: missing@unknown']
