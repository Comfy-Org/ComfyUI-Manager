import ast
import json
import logging
import os
import shutil
import subprocess
import sys
import types
import zipfile

import pytest

from manager_test_utils import GLOB_DIR, load_manager_util
from test_install_flags_config import _CHILD_PREAMBLE, REPO_ROOT

PRESTARTUP_SCRIPT = GLOB_DIR.resolve().parent / 'prestartup_script.py'
OTHER_ENCODING = {'LC_ALL': 'C', 'PYTHONUTF8': '0', 'PYTHONCOERCECLOCALE': '0'}


def download_url(url, directory, name, member='__init__.py'):
    with zipfile.ZipFile(os.path.join(directory, name), 'w') as archive:
        archive.writestr(member, 'VERSION = 2')


def download_that_is_not_a_zip(url, directory, name):
    with open(os.path.join(directory, name), 'w') as file:
        file.write('<html></html>')


def startup_functions(set_module, download=download_url, **module_globals):
    """Importing prestartup_script would run the start-up."""
    cli_args = types.ModuleType('comfy.cli_args')
    cli_args.args = types.SimpleNamespace(listen='127.0.0.1')
    set_module('comfy', types.ModuleType('comfy'))
    set_module('comfy.cli_args', cli_args)

    functions = [node for node in ast.parse(PRESTARTUP_SCRIPT.read_text(encoding='utf-8')).body
                 if isinstance(node, ast.FunctionDef) and node.name in ('execute_lazy_cnr_switch', 'execute_lazy_install_script', 'execute_startup_script')]
    scope = {'os': os, 'ast': ast, 'logging': logging, 'default_conf': {}, 'manager_util': load_manager_util(),
             'manager_downloader': types.SimpleNamespace(download_url=download), **module_globals}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(PRESTARTUP_SCRIPT), 'exec'), scope)
    return scope


def reserved_switch(set_module, download=download_url):
    return startup_functions(set_module, download)['execute_lazy_cnr_switch']


@pytest.fixture
def switch(monkeypatch):
    return reserved_switch(lambda name, module: monkeypatch.setitem(sys.modules, name, module))


def old_version(custom_nodes, directory, *tracked):
    old = custom_nodes / directory
    old.mkdir(parents=True)
    for name in ('__init__.py', 'removed.py'):
        (old / name).write_text('VERSION = 1')
    (old / '.tracking').write_text('\n'.join(('__init__.py', *tracked)), encoding='utf-8')
    (custom_nodes / 'removed.py').write_text('a file that is not of the pack')
    return old


def switch_at_once(custom_nodes, encoding=(), member='__init__.py', not_a_zip=False):
    script = _CHILD_PREAMBLE.format(glob_path=str(REPO_ROOT / 'glob')) + '''
import pathlib, zipfile
from types import SimpleNamespace
from unittest.mock import Mock
core = manager_core
custom_nodes = pathlib.Path(%r)
member, not_a_zip = %r, %r

def download(url, directory, name):
    if not_a_zip:
        (pathlib.Path(directory) / name).write_text('<html></html>')
        return
    with zipfile.ZipFile(pathlib.Path(directory) / name, 'w') as archive:
        archive.writestr(member, 'VERSION = 2')

core.get_default_custom_nodes_path = lambda: str(custom_nodes)
core.manager_downloader.basic_download_url = download
manager = core.UnifiedManager()
manager.active_nodes['fixture'] = ('1.0.0', str(custom_nodes / 'fixture'))
manager.execute_install_script = Mock(return_value=True)
version = SimpleNamespace(version='2.0.0', download_url='https://example.invalid/fixture.zip', status='NodeVersionStatusActive')
print(json.dumps(manager._cnr_switch_version('fixture', version, instant_execution=True, no_deps=True).result))
''' % (str(custom_nodes), member, not_a_zip)
    child = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, cwd=str(REPO_ROOT), env={**os.environ, **dict(encoding)})
    assert child.returncode == 0, child.stderr[-600:]
    return json.loads(child.stdout.strip().splitlines()[-1])


def test_files_that_the_new_version_lacks_are_removed_from_the_pack(switch, tmp_path):
    custom_nodes = tmp_path / 'custom_nodes'
    old, new = old_version(custom_nodes, 'fixture@1_0_0', 'removed.py'), custom_nodes / 'fixture@2_0_0'

    assert switch('fixture', 'https://example.invalid/fixture.zip', str(old), str(new), False, str(custom_nodes), 'NodeVersionStatusActive')

    assert (custom_nodes / 'removed.py').exists()
    assert sorted(os.listdir(new)) == ['.tracking', '__init__.py']
    assert (new / '__init__.py').read_text() == 'VERSION = 2'


@pytest.mark.parametrize('name', ['../removed.py', '{custom_nodes}/removed.py'])
def test_reserved_switch_leaves_a_file_outside_the_pack(switch, tmp_path, name):
    custom_nodes = tmp_path / 'custom_nodes'
    old, new = old_version(custom_nodes, 'fixture@1_0_0', name.format(custom_nodes=custom_nodes)), custom_nodes / 'fixture@2_0_0'

    assert switch('fixture', 'https://example.invalid/fixture.zip', str(old), str(new), False, str(custom_nodes), 'NodeVersionStatusActive')

    assert (custom_nodes / 'removed.py').exists()
    assert sorted(os.listdir(new)) == ['.tracking', '__init__.py', 'removed.py']


@pytest.mark.parametrize('name, inside', [
    ('removed.py', True), ('nodes/removed.py', True), ('nodes/', True), ('nodes/../removed.py', True), ('', True),
    ('..', False), ('../removed.py', False), ('nodes/../../removed.py', False), ('{pack}/../removed.py', False),
    ('{pack}/removed.py', True), ('{pack}@2/removed.py', False),
])
def test_name_of_a_file_of_the_pack(tmp_path, name, inside):
    pack = tmp_path / 'custom_nodes/fixture'
    pack.mkdir(parents=True)

    assert load_manager_util().is_inside(str(pack), name.format(pack=pack)) is inside


@pytest.mark.parametrize('name', ['removed.py', '../removed.py', '{custom_nodes}/removed.py'])
def test_switch_at_once_removes_the_files_of_the_pack_alone(tmp_path, name):
    custom_nodes = tmp_path / 'custom_nodes'
    pack = old_version(custom_nodes, 'fixture', name.format(custom_nodes=custom_nodes))

    assert switch_at_once(custom_nodes) is True

    assert (custom_nodes / 'removed.py').exists()
    assert sorted(os.listdir(pack)) == (['.tracking', '__init__.py'] if name == 'removed.py' else ['.tracking', '__init__.py', 'removed.py'])


def test_reserved_switch_keeps_a_file_that_the_new_archive_names_in_another_way(monkeypatch, tmp_path):
    """`__init__.py` and `./__init__.py` are extracted to the same file."""
    custom_nodes = tmp_path / 'custom_nodes'
    old, new = old_version(custom_nodes, 'fixture@1_0_0', 'removed.py'), custom_nodes / 'fixture@2_0_0'
    switch = reserved_switch(lambda name, module: monkeypatch.setitem(sys.modules, name, module),
                             lambda url, directory, name: download_url(url, directory, name, './__init__.py'))

    assert switch('fixture', 'https://example.invalid/fixture.zip', str(old), str(new), False, str(custom_nodes), 'NodeVersionStatusActive')

    assert (new / '__init__.py').read_text() == 'VERSION = 2'
    assert sorted(os.listdir(new)) == ['.tracking', '__init__.py']


def test_switch_at_once_keeps_a_file_that_the_new_archive_names_in_another_way(tmp_path):
    custom_nodes = tmp_path / 'custom_nodes'
    pack = old_version(custom_nodes, 'fixture', 'removed.py')

    assert switch_at_once(custom_nodes, member='./__init__.py') is True

    assert (pack / '__init__.py').read_text() == 'VERSION = 2'
    assert sorted(os.listdir(pack)) == ['.tracking', '__init__.py']


def two_names_of_one_file(pack):
    try:
        (pack / 'alias').symlink_to('.', target_is_directory=True)
    except OSError:
        pytest.skip('a link cannot be made here')


def test_reserved_switch_keeps_a_file_that_the_old_list_names_in_a_way_of_its_own(switch, tmp_path):
    custom_nodes = tmp_path / 'custom_nodes'
    old, new = old_version(custom_nodes, 'fixture@1_0_0', 'alias/__init__.py'), custom_nodes / 'fixture@2_0_0'
    two_names_of_one_file(old)

    assert switch('fixture', 'https://example.invalid/fixture.zip', str(old), str(new), False, str(custom_nodes), 'NodeVersionStatusActive')

    assert (new / '__init__.py').read_text() == 'VERSION = 2'


def test_switch_at_once_keeps_a_file_that_the_old_list_names_in_a_way_of_its_own(tmp_path):
    custom_nodes = tmp_path / 'custom_nodes'
    pack = old_version(custom_nodes, 'fixture', 'alias/__init__.py')
    two_names_of_one_file(pack)

    assert switch_at_once(custom_nodes) is True

    assert (pack / '__init__.py').read_text() == 'VERSION = 2'


def test_reserved_switch_removes_a_folder_that_the_new_version_lacks(switch, tmp_path):
    custom_nodes = tmp_path / 'custom_nodes'
    old, new = old_version(custom_nodes, 'fixture@1_0_0', 'olddir/', 'olddir/old.py', 'removed.py'), custom_nodes / 'fixture@2_0_0'
    (old / 'olddir').mkdir()
    (old / 'olddir/old.py').write_text('VERSION = 1')

    assert switch('fixture', 'https://example.invalid/fixture.zip', str(old), str(new), False, str(custom_nodes), 'NodeVersionStatusActive')

    assert sorted(os.listdir(new)) == ['.tracking', '__init__.py']


def modules_that_were_imported(pack):
    """`olddir/a/b/c/d/old.py`, and what Python and numba write beside a module that is imported, which no list names."""
    (pack / 'olddir/a/b/c/d/__pycache__').mkdir(parents=True)
    (pack / 'olddir/__pycache__').mkdir()
    (pack / 'olddir/a/b/c/d/old.py').write_text('VERSION = 1')
    for cache in (pack / 'olddir/a/b/c/d/__pycache__', pack / 'olddir/__pycache__'):
        for name in ('old.cpython-312.pyc', 'old.run-3.py312.nbi', 'old.run-3.py312.1.nbc'):
            (cache / name).write_bytes(b'')


TRACKED = pytest.mark.parametrize('tracked', [
    ('olddir/a/b/c/d/old.py',),
    ('olddir/', 'olddir/a/', 'olddir/a/b/', 'olddir/a/b/c/', 'olddir/a/b/c/d/', 'olddir/a/b/c/d/old.py'),
], ids=['the list names the files alone', 'the list names the folders as well'])


@TRACKED
def test_reserved_switch_removes_the_folders_that_the_old_files_leave_empty(switch, tmp_path, tracked):
    custom_nodes = tmp_path / 'custom_nodes'
    old, new = old_version(custom_nodes, 'fixture@1_0_0', *tracked, 'removed.py'), custom_nodes / 'fixture@2_0_0'
    modules_that_were_imported(old)

    assert switch('fixture', 'https://example.invalid/fixture.zip', str(old), str(new), False, str(custom_nodes), 'NodeVersionStatusActive')

    assert sorted(os.listdir(new)) == ['.tracking', '__init__.py']


@TRACKED
def test_reserved_switch_puts_a_file_where_the_old_version_has_a_folder(monkeypatch, tmp_path, tracked):
    custom_nodes = tmp_path / 'custom_nodes'
    old, new = old_version(custom_nodes, 'fixture@1_0_0', *tracked), custom_nodes / 'fixture@2_0_0'
    modules_that_were_imported(old)
    switch = reserved_switch(lambda name, module: monkeypatch.setitem(sys.modules, name, module),
                             lambda url, directory, name: download_url(url, directory, name, member='olddir'))

    assert switch('fixture', 'https://example.invalid/fixture.zip', str(old), str(new), False, str(custom_nodes), 'NodeVersionStatusActive')

    assert (new / 'olddir').read_text() == 'VERSION = 2'


def test_reserved_switch_keeps_a_folder_with_a_file_that_is_not_of_the_old_version(switch, tmp_path):
    custom_nodes = tmp_path / 'custom_nodes'
    old, new = old_version(custom_nodes, 'fixture@1_0_0', 'olddir/a/old.py', 'removed.py'), custom_nodes / 'fixture@2_0_0'
    (old / 'olddir/a').mkdir(parents=True)
    (old / 'olddir/a/old.py').write_text('VERSION = 1')
    (old / 'olddir/made by the user.txt').write_text('kept')

    assert switch('fixture', 'https://example.invalid/fixture.zip', str(old), str(new), False, str(custom_nodes), 'NodeVersionStatusActive')

    assert sorted(os.listdir(new / 'olddir')) == ['made by the user.txt']


def test_reserved_switch_removes_an_empty_folder_that_the_list_names(switch, tmp_path):
    custom_nodes = tmp_path / 'custom_nodes'
    old, new = old_version(custom_nodes, 'fixture@1_0_0', 'olddir/', 'removed.py'), custom_nodes / 'fixture@2_0_0'
    (old / 'olddir').mkdir()

    assert switch('fixture', 'https://example.invalid/fixture.zip', str(old), str(new), False, str(custom_nodes), 'NodeVersionStatusActive')

    assert sorted(os.listdir(new)) == ['.tracking', '__init__.py']


def test_reserved_switch_keeps_a_folder_that_is_in_the_cache(switch, tmp_path):
    custom_nodes = tmp_path / 'custom_nodes'
    old, new = old_version(custom_nodes, 'fixture@1_0_0', 'olddir/old.py', 'removed.py'), custom_nodes / 'fixture@2_0_0'
    (old / 'olddir/__pycache__/made by the user').mkdir(parents=True)
    (old / 'olddir/old.py').write_text('VERSION = 1')
    (old / 'olddir/__pycache__/made by the user/kept.txt').write_text('kept')

    assert switch('fixture', 'https://example.invalid/fixture.zip', str(old), str(new), False, str(custom_nodes), 'NodeVersionStatusActive')

    assert (new / 'olddir/__pycache__/made by the user/kept.txt').read_text() == 'kept'


def link_of_a_folder(link, target, junction):
    """A symbolic link, or a junction, which Windows makes without a privilege."""
    if junction:
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], check=True, capture_output=True)
        return
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip('a link cannot be made here')


@pytest.mark.parametrize('junction', [False, pytest.param(True, marks=pytest.mark.skipif(os.name != 'nt', reason='a junction is of Windows'))],
                         ids=['symbolic link', 'junction'])
@pytest.mark.parametrize('link, cache', [('olddir', 'olddir/__pycache__'), ('olddir/__pycache__', 'olddir/__pycache__'), ('olddir', 'olddir/a/__pycache__')],
                         ids=['the folder is a link', 'the cache is a link', 'the folder is behind a link'])
def test_reserved_switch_leaves_the_cache_behind_a_link(switch, tmp_path, link, cache, junction):
    custom_nodes = tmp_path / 'custom_nodes'
    old, new = old_version(custom_nodes, 'fixture@1_0_0', os.path.dirname(cache) + '/old.py', 'removed.py'), custom_nodes / 'fixture@2_0_0'
    kept = tmp_path / 'elsewhere' / cache[len(link) + 1:] / 'other.cpython-312.pyc'
    kept.parent.mkdir(parents=True)
    kept.write_bytes(b'')
    (old / link).parent.mkdir(exist_ok=True)
    link_of_a_folder(old / link, tmp_path / 'elsewhere', junction)

    assert switch('fixture', 'https://example.invalid/fixture.zip', str(old), str(new), False, str(custom_nodes), 'NodeVersionStatusActive')

    assert kept.exists()
    assert (new / link).is_dir()


def test_reserved_switch_leaves_a_folder_behind_a_link(switch, tmp_path):
    custom_nodes = tmp_path / 'custom_nodes'
    old, new = old_version(custom_nodes, 'fixture@1_0_0', 'olddir/a/old.py', 'removed.py'), custom_nodes / 'fixture@2_0_0'
    (tmp_path / 'elsewhere/a').mkdir(parents=True)
    (tmp_path / 'elsewhere/a/old.py').write_text('VERSION = 1')
    link_of_a_folder(old / 'olddir', tmp_path / 'elsewhere', False)

    assert switch('fixture', 'https://example.invalid/fixture.zip', str(old), str(new), False, str(custom_nodes), 'NodeVersionStatusActive')

    assert (tmp_path / 'elsewhere/a').is_dir()


def test_reserved_switch_removes_the_folders_of_a_pack_that_is_reached_through_a_link(switch, tmp_path):
    custom_nodes = tmp_path / 'custom_nodes'
    (tmp_path / 'elsewhere').mkdir()
    link_of_a_folder(custom_nodes, tmp_path / 'elsewhere', False)
    old, new = old_version(custom_nodes, 'fixture@1_0_0', 'olddir/a/b/c/d/old.py', 'removed.py'), custom_nodes / 'fixture@2_0_0'
    modules_that_were_imported(old)

    assert switch('fixture', 'https://example.invalid/fixture.zip', str(old), str(new), False, str(custom_nodes), 'NodeVersionStatusActive')

    assert sorted(os.listdir(new)) == ['.tracking', '__init__.py']


def file_that_cannot_be_removed(pack):
    (pack / 'olddir').mkdir()
    (pack / 'olddir/old.py').write_text('VERSION = 1')
    (pack / 'olddir').chmod(0o555)
    if os.access(pack / 'olddir', os.W_OK):
        pytest.skip('the file can be removed here, as by root or on Windows')


def archives(custom_nodes):
    return [name for name in os.listdir(custom_nodes) if name.endswith('.zip')]


def test_reserved_switch_goes_on_past_a_file_that_cannot_be_removed(switch, tmp_path):
    custom_nodes = tmp_path / 'custom_nodes'
    old, new = old_version(custom_nodes, 'fixture@1_0_0', 'olddir/old.py', 'removed.py'), custom_nodes / 'fixture@2_0_0'
    file_that_cannot_be_removed(old)

    assert switch('fixture', 'https://example.invalid/fixture.zip', str(old), str(new), False, str(custom_nodes), 'NodeVersionStatusActive')

    assert sorted(os.listdir(new)) == ['.tracking', '__init__.py', 'olddir']
    assert (new / '__init__.py').read_text() == 'VERSION = 2'
    assert archives(custom_nodes) == []


def test_switch_at_once_goes_on_past_a_file_that_cannot_be_removed(tmp_path):
    custom_nodes = tmp_path / 'custom_nodes'
    pack = old_version(custom_nodes, 'fixture', 'olddir/old.py', 'removed.py')
    file_that_cannot_be_removed(pack)

    assert switch_at_once(custom_nodes) is True

    assert sorted(os.listdir(pack)) == ['.tracking', '__init__.py', 'olddir']
    assert (pack / '__init__.py').read_text() == 'VERSION = 2'
    assert archives(custom_nodes) == []


def test_reserved_switch_goes_on_past_a_folder_that_cannot_be_removed(switch, tmp_path):
    custom_nodes = tmp_path / 'custom_nodes'
    old, new = old_version(custom_nodes, 'fixture@1_0_0', 'olddir/', 'removed.py'), custom_nodes / 'fixture@2_0_0'
    (old / 'olddir').mkdir(mode=0)
    if os.access(old / 'olddir', os.R_OK):
        pytest.skip('the folder can be read here, as by root or on Windows')

    try:
        assert switch('fixture', 'https://example.invalid/fixture.zip', str(old), str(new), False, str(custom_nodes), 'NodeVersionStatusActive')

        assert sorted(os.listdir(new)) == ['.tracking', '__init__.py', 'olddir']
        assert (new / '__init__.py').read_text() == 'VERSION = 2'
    finally:
        (next(pack for pack in (new, old) if pack.exists()) / 'olddir').chmod(0o700)


def test_reserved_switch_does_not_move_a_pack_that_keeps_its_directory(switch, monkeypatch, tmp_path):
    def move(source, target):
        raise PermissionError(13, 'Access is denied', source, 5, target)

    monkeypatch.setattr(shutil, 'move', move)
    custom_nodes = tmp_path / 'custom_nodes'
    pack = old_version(custom_nodes, 'fixture', 'removed.py')

    assert switch('fixture', 'https://example.invalid/fixture.zip', str(pack), str(pack), False, str(custom_nodes), 'NodeVersionStatusActive')

    assert sorted(os.listdir(pack)) == ['.tracking', '__init__.py']
    assert (pack / '.tracking').read_text() == '__init__.py'


def test_install_script_of_a_reserved_switch_runs_where_the_pack_was_moved_to(monkeypatch, tmp_path):
    custom_nodes = tmp_path / 'custom_nodes'
    old, new = old_version(custom_nodes, 'fixture@1_0_0', 'removed.py'), custom_nodes / 'fixture'
    commands = []
    startup = startup_functions(lambda name, module: monkeypatch.setitem(sys.modules, name, module),
                                lambda url, directory, name: download_url(url, directory, name, 'install.py'),
                                script_list_path=str(tmp_path / 'install-scripts.txt'), processed_install=set(), comfy_path=str(tmp_path),
                                process_wrap=lambda command, cwd=None, **options: commands.append((command, cwd)) or 0)
    (tmp_path / 'install-scripts.txt').write_text(repr(
        ['fixture', '#LAZY-CNR-SWITCH-SCRIPT', 'https://example.invalid/fixture.zip', str(old), str(new), False, str(custom_nodes), 'python', 'NodeVersionStatusActive']))

    startup['execute_startup_script']()

    assert commands == [(['python', 'install.py'], str(new))]


def test_reserved_switch_that_fails_leaves_no_archive(switch, tmp_path):
    custom_nodes = tmp_path / 'custom_nodes'
    old, new = old_version(custom_nodes, 'fixture@1_0_0'), custom_nodes / 'fixture@2_0_0'
    (old / '.tracking').unlink()

    with pytest.raises(FileNotFoundError):
        switch('fixture', 'https://example.invalid/fixture.zip', str(old), str(new), False, str(custom_nodes), 'NodeVersionStatusActive')

    assert archives(custom_nodes) == []


def test_switch_at_once_that_fails_leaves_no_archive(tmp_path):
    custom_nodes = tmp_path / 'custom_nodes'
    (old_version(custom_nodes, 'fixture') / '.tracking').unlink()

    with pytest.raises(AssertionError, match='FileNotFoundError'):
        switch_at_once(custom_nodes)

    assert archives(custom_nodes) == []


def test_reserved_switch_to_a_download_that_is_not_a_zip_leaves_the_pack_as_it_is(monkeypatch, tmp_path):
    custom_nodes = tmp_path / 'custom_nodes'
    old, new = old_version(custom_nodes, 'fixture@1_0_0', 'removed.py'), custom_nodes / 'fixture@2_0_0'
    switch = reserved_switch(lambda name, module: monkeypatch.setitem(sys.modules, name, module), download_that_is_not_a_zip)

    assert switch('fixture', 'https://example.invalid/fixture.zip', str(old), str(new), False, str(custom_nodes), 'NodeVersionStatusActive') is False

    assert not new.exists()
    assert sorted(os.listdir(old)) == ['.tracking', '__init__.py', 'removed.py']
    assert (old / '__init__.py').read_text() == 'VERSION = 1'
    assert archives(custom_nodes) == []


def test_switch_at_once_to_a_download_that_is_not_a_zip_leaves_the_pack_as_it_is(tmp_path):
    custom_nodes = tmp_path / 'custom_nodes'
    pack = old_version(custom_nodes, 'fixture', 'removed.py')

    assert switch_at_once(custom_nodes, not_a_zip=True) is False

    assert sorted(os.listdir(pack)) == ['.tracking', '__init__.py', 'removed.py']
    assert (pack / '__init__.py').read_text() == 'VERSION = 1'
    assert archives(custom_nodes) == []


def test_reserved_switch_reads_the_list_as_it_is_written(tmp_path):
    """The file with the Korean name is not there: the file system of the child cannot name it."""
    custom_nodes = tmp_path / 'custom_nodes'
    old, new = old_version(custom_nodes, 'fixture@1_0_0', '예제 사용자.json', 'removed.py'), custom_nodes / 'fixture@2_0_0'
    call = ('fixture', 'https://example.invalid/fixture.zip', str(old), str(new), False, str(custom_nodes), 'NodeVersionStatusActive')
    script = (f'import sys; sys.path.insert(0, {os.path.dirname(__file__)!r})\n'
              'import test_version_switch_old_files as cases\n'
              f'sys.exit(not cases.reserved_switch(sys.modules.__setitem__)(*{call!r}))\n')

    child = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, env={**os.environ, **OTHER_ENCODING})

    assert child.returncode == 0, child.stderr[-600:]
    assert sorted(os.listdir(new)) == ['.tracking', '__init__.py']


def test_switch_at_once_reads_the_list_as_it_is_written(tmp_path):
    custom_nodes = tmp_path / 'custom_nodes'
    pack = old_version(custom_nodes, 'fixture', '예제 사용자.json', 'removed.py')

    assert switch_at_once(custom_nodes, OTHER_ENCODING) is True

    assert sorted(os.listdir(pack)) == ['.tracking', '__init__.py']


def test_reserved_switch_reads_a_name_with_a_space_at_its_start_as_it_is_written(switch, tmp_path):
    """`removed.py` is not in the list: it is a file that someone put into the node pack."""
    custom_nodes = tmp_path / 'custom_nodes'
    old, new = old_version(custom_nodes, 'fixture@1_0_0', ' removed.py'), custom_nodes / 'fixture@2_0_0'
    (old / ' removed.py').write_text('VERSION = 1')

    assert switch('fixture', 'https://example.invalid/fixture.zip', str(old), str(new), False, str(custom_nodes), 'NodeVersionStatusActive')

    assert sorted(os.listdir(new)) == ['.tracking', '__init__.py', 'removed.py']


def test_switch_at_once_reads_a_name_with_a_space_at_its_start_as_it_is_written(tmp_path):
    custom_nodes = tmp_path / 'custom_nodes'
    pack = old_version(custom_nodes, 'fixture', ' removed.py')
    (pack / ' removed.py').write_text('VERSION = 1')

    assert switch_at_once(custom_nodes) is True

    assert sorted(os.listdir(pack)) == ['.tracking', '__init__.py', 'removed.py']
