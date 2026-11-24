import ast
import os
import subprocess
import sys

import pytest

PACK = '한글 nodepack'


def reserved(tmp_path, core, call):
    tests = os.path.dirname(__file__)
    code = (f'import sys; sys.path[:0] = [{os.path.dirname(tests)!r}, {tests!r}]\n'
            'from _install_flags_testutil import import_reader\n'
            f'core = import_reader({core!r})\n'
            f'core.context.manager_startup_script_path = {str(tmp_path)!r}\n'
            f'core.get_default_custom_nodes_path = lambda: {str(tmp_path)!r}\n'
            f'{call}\n')
    # from a file: with this locale a command line cannot hold the name of the nodepack
    (tmp_path / 'reserve.py').write_text(code, encoding='utf-8')
    child = subprocess.run([sys.executable, str(tmp_path / 'reserve.py')], capture_output=True, text=True,
                           env={**os.environ, 'LC_ALL': 'C', 'PYTHONUTF8': '0', 'PYTHONCOERCECLOCALE': '0'})
    assert child.returncode == 0, child.stderr[-600:]
    with open(tmp_path / 'install-scripts.txt', encoding='utf-8') as file:
        return [ast.literal_eval(line) for line in file]


@pytest.mark.parametrize('core', ['glob', 'legacy'])
def test_install_script_of_a_pack_whose_path_the_locale_cannot_write_is_reserved(tmp_path, core):
    path = str(tmp_path / PACK)

    assert reserved(tmp_path, core, f"core.reserve_script({path!r}, ['install.py'])") == [[path, 'install.py']]


@pytest.mark.parametrize('core', ['glob', 'legacy'])
def test_switch_of_a_pack_whose_path_the_locale_cannot_write_is_reserved(tmp_path, core):
    path = str(tmp_path / PACK)
    call = f"core.UnifiedManager().reserve_cnr_switch('fixture', 'https://example.invalid/fixture.zip', {path!r}, {path!r}, False)"

    entry, = reserved(tmp_path, core, call)

    assert entry[3:5] == [path, path]
