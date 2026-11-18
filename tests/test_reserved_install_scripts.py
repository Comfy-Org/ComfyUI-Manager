import json
import os
import subprocess
import sys

from test_install_flags_config import _CHILD_PREAMBLE, REPO_ROOT

BODY = '''
import ast, pathlib
core = manager_core
core.manager_startup_script_path = tmp
core.get_default_custom_nodes_path = lambda: tmp
path = str(pathlib.Path(tmp) / '한글 node pack')

def reserved():
    with open(pathlib.Path(tmp) / 'install-scripts.txt', encoding='utf-8') as file:
        return [ast.literal_eval(line) for line in file]
'''


def run(tmp_path, body):
    # from a file: with this locale a command line cannot hold the name of the node pack
    (tmp_path / 'reserve.py').write_text(_CHILD_PREAMBLE.format(glob_path=str(REPO_ROOT / 'glob')) + BODY + body, encoding='utf-8')
    child = subprocess.run([sys.executable, str(tmp_path / 'reserve.py')], capture_output=True, text=True, cwd=str(REPO_ROOT),
                           env={**os.environ, 'LC_ALL': 'C', 'PYTHONUTF8': '0', 'PYTHONCOERCECLOCALE': '0'})
    assert child.returncode == 0, child.stderr[-600:]
    return json.loads(child.stdout.strip().splitlines()[-1])


def test_install_script_of_a_pack_whose_path_the_locale_cannot_write_is_reserved(tmp_path):
    assert run(tmp_path, '''
core.reserve_script(path, ['install.py'])
print(json.dumps(reserved() == [[path, 'install.py']]))
''') is True


def test_switch_of_a_pack_whose_path_the_locale_cannot_write_is_reserved(tmp_path):
    assert run(tmp_path, '''
core.UnifiedManager().reserve_cnr_switch('fixture', 'https://example.invalid/fixture.zip', path, path, False)
entry, = reserved()
print(json.dumps(entry[3:5] == [path, path]))
''') is True
