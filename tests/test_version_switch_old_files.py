"""A switch of version removes the files of the old version from the node pack, and no file outside it.

The reserved switch is the real function of `prestartup_script.py`, run with the real `manager_util`
on a node pack of a temporary directory. The switch that is done at once runs in a child like that
of tests/test_install_flags_config.py, against the real glob/manager_core. Replaced: the download,
which writes the archive of the new version, and the install script of the switch that is done at once.
"""

import ast
import json
import logging
import ntpath
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
# as on Windows, where the encoding of the system is not UTF-8
OTHER_ENCODING = {'LC_ALL': 'C', 'PYTHONUTF8': '0', 'PYTHONCOERCECLOCALE': '0'}


def download_url(url, directory, name, member='__init__.py'):
    """The archive of the new version, which holds `__init__.py` alone."""
    with zipfile.ZipFile(os.path.join(directory, name), 'w') as archive:
        archive.writestr(member, 'VERSION = 2')


def startup_functions(set_module, download=download_url, **module_globals):
    """The functions of the start-up script for a reserved switch. Importing prestartup_script would run the start-up."""
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
    """A node pack at version 1 whose `.tracking` names `tracked`, and a file beside it in `custom_nodes`."""
    old = custom_nodes / directory
    old.mkdir(parents=True)
    for name in ('__init__.py', 'removed.py'):
        (old / name).write_text('VERSION = 1')
    (old / '.tracking').write_text('\n'.join(('__init__.py', *tracked)), encoding='utf-8')
    (custom_nodes / 'removed.py').write_text('a file that is not of the pack')
    return old


def switch_at_once(custom_nodes, encoding=(), member='__init__.py'):
    """Whether the switch of `fixture` to version 2 succeeded, in a child with the real glob/manager_core."""
    script = _CHILD_PREAMBLE.format(glob_path=str(REPO_ROOT / 'glob')) + '''
import pathlib, zipfile
from types import SimpleNamespace
from unittest.mock import Mock
core = manager_core
custom_nodes = pathlib.Path(%r)

def download(url, directory, name):
    with zipfile.ZipFile(pathlib.Path(directory) / name, 'w') as archive:
        archive.writestr(%r, 'VERSION = 2')

core.get_default_custom_nodes_path = lambda: str(custom_nodes)
core.manager_downloader.basic_download_url = download
manager = core.UnifiedManager()
manager.active_nodes['fixture'] = ('1.0.0', str(custom_nodes / 'fixture'))
manager.execute_install_script = Mock(return_value=True)
version = SimpleNamespace(version='2.0.0', download_url='https://example.invalid/fixture.zip', status='NodeVersionStatusActive')
print(json.dumps(manager._cnr_switch_version('fixture', version, instant_execution=True, no_deps=True).result))
''' % (str(custom_nodes), member)
    child = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, cwd=str(REPO_ROOT), env={**os.environ, **dict(encoding)})
    assert child.returncode == 0, child.stderr[-600:]
    return json.loads(child.stdout.strip().splitlines()[-1])


def test_files_that_the_new_version_lacks_are_removed_from_the_pack(switch, tmp_path):
    """They were looked for in `custom_nodes`: a file of that name there was removed, and the one of the pack stayed."""
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
    # with `..`, the file was extracted into the pack; the absolute name is extracted to a path under the pack, where nothing is
    assert sorted(os.listdir(new)) == (['.tracking', '__init__.py', 'removed.py'] if name.startswith('{') else ['.tracking', '__init__.py'])


@pytest.mark.parametrize('name, inside', [
    ('removed.py', True), ('nodes/removed.py', True), ('nodes/', True), ('nodes/../removed.py', True), ('', True),
    ('..', False), ('../removed.py', False), ('nodes/../../removed.py', False), ('{pack}/../removed.py', False),
    ('{pack}/removed.py', True), ('{pack}@2/removed.py', False),
])
def test_name_of_a_file_of_the_pack(tmp_path, name, inside):
    pack = tmp_path / 'custom_nodes/fixture'
    pack.mkdir(parents=True)

    assert load_manager_util().is_inside(str(pack), name.format(pack=pack)) is inside


def test_name_through_a_link_that_leads_out_of_the_pack(tmp_path):
    pack = tmp_path / 'custom_nodes/fixture'
    (pack / 'nodes').mkdir(parents=True)
    try:
        (pack / 'linked').symlink_to(tmp_path, target_is_directory=True)
        (pack / 'inner').symlink_to(pack / 'nodes', target_is_directory=True)
    except OSError:
        pytest.skip('a link cannot be made here')

    assert load_manager_util().is_inside(str(pack), 'linked/removed.py') is False
    assert load_manager_util().is_inside(str(pack), 'inner/removed.py') is True


@pytest.mark.parametrize('name', ['removed.py', '../removed.py', '{custom_nodes}/removed.py'])
def test_switch_at_once_removes_the_files_of_the_pack_alone(tmp_path, name):
    custom_nodes = tmp_path / 'custom_nodes'
    pack = old_version(custom_nodes, 'fixture', name.format(custom_nodes=custom_nodes))

    assert switch_at_once(custom_nodes) is True

    assert (custom_nodes / 'removed.py').exists()
    # with `..`, the file was extracted into the pack; the absolute name is extracted to a path under the pack, where nothing is
    assert sorted(os.listdir(pack)) == (['.tracking', '__init__.py', 'removed.py'] if name.startswith('{') else ['.tracking', '__init__.py'])


def linked_out_of(pack, custom_nodes):
    """A folder of the pack that is a link to `custom_nodes`."""
    try:
        (pack / 'linked').symlink_to(custom_nodes, target_is_directory=True)
    except OSError:
        pytest.skip('a link cannot be made here')


def test_reserved_switch_leaves_a_file_behind_a_link_out_of_the_pack(switch, tmp_path):
    custom_nodes = tmp_path / 'custom_nodes'
    old, new = old_version(custom_nodes, 'fixture@1_0_0', 'linked/removed.py'), custom_nodes / 'fixture@2_0_0'
    linked_out_of(old, custom_nodes)

    assert switch('fixture', 'https://example.invalid/fixture.zip', str(old), str(new), False, str(custom_nodes), 'NodeVersionStatusActive')

    assert (custom_nodes / 'removed.py').exists()


def test_switch_at_once_leaves_a_file_behind_a_link_out_of_the_pack(tmp_path):
    custom_nodes = tmp_path / 'custom_nodes'
    linked_out_of(old_version(custom_nodes, 'fixture', 'linked/removed.py'), custom_nodes)

    assert switch_at_once(custom_nodes) is True

    assert (custom_nodes / 'removed.py').exists()


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
    """`alias/__init__.py` is `__init__.py`, as two names that differ in case alone are one file on Windows."""
    try:
        (pack / 'alias').symlink_to('.', target_is_directory=True)
    except OSError:
        pytest.skip('a link cannot be made here')


def test_reserved_switch_keeps_a_file_that_the_old_list_names_in_a_way_of_its_own(switch, tmp_path):
    """What the new version lacks is removed before its archive is extracted."""
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


def file_that_cannot_be_removed(pack):
    """`olddir/old.py` in a folder that may not be written: as a file that another program has open is on Windows."""
    if os.name != 'posix' or os.geteuid() == 0:
        pytest.skip('the file can be removed here')
    (pack / 'olddir').mkdir()
    (pack / 'olddir/old.py').write_text('VERSION = 1')
    (pack / 'olddir').chmod(0o555)


def archives(custom_nodes):
    return [name for name in os.listdir(custom_nodes) if name.endswith('.zip')]


def test_reserved_switch_goes_on_past_a_file_that_cannot_be_removed(switch, tmp_path):
    """The file stays beside those of the new version; the switch stopped there, with the node pack at neither version."""
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
    """The folder of the old version may not be read, so that it cannot be told to be empty."""
    custom_nodes = tmp_path / 'custom_nodes'
    old, new = old_version(custom_nodes, 'fixture@1_0_0', 'olddir/', 'removed.py'), custom_nodes / 'fixture@2_0_0'
    if os.name != 'posix' or os.geteuid() == 0:
        pytest.skip('the folder can be read here')
    (old / 'olddir').mkdir(mode=0)

    try:
        assert switch('fixture', 'https://example.invalid/fixture.zip', str(old), str(new), False, str(custom_nodes), 'NodeVersionStatusActive')

        assert sorted(os.listdir(new)) == ['.tracking', '__init__.py', 'olddir']
        assert (new / '__init__.py').read_text() == 'VERSION = 2'
    finally:
        # for the removal of the temporary directory
        (next(pack for pack in (new, old) if pack.exists()) / 'olddir').chmod(0o700)


def test_reserved_switch_does_not_move_a_pack_that_keeps_its_directory(switch, monkeypatch, tmp_path):
    """On Windows a folder with a file that is open is not renamed, not even to its own name."""
    def move(source, target):
        raise PermissionError(13, 'Access is denied', source, 5, target)

    monkeypatch.setattr(shutil, 'move', move)
    custom_nodes = tmp_path / 'custom_nodes'
    pack = old_version(custom_nodes, 'fixture', 'removed.py')

    assert switch('fixture', 'https://example.invalid/fixture.zip', str(pack), str(pack), False, str(custom_nodes), 'NodeVersionStatusActive')

    assert sorted(os.listdir(pack)) == ['.tracking', '__init__.py']
    assert (pack / '.tracking').read_text() == '__init__.py'


def test_install_script_of_a_reserved_switch_runs_where_the_pack_was_moved_to(monkeypatch, tmp_path):
    """The start-up script reads the reserved switch, carries it out and runs the install script of the new version."""
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
    """Here the list of the files of the old version is not there."""
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


# where the separator is `/`, a name that Windows cannot hold is extracted as it is
NOT_ON_WINDOWS = pytest.mark.skipif(os.sep != '/', reason='Windows extracts this name to another path')


@pytest.mark.parametrize('name, path', [
    ('__init__.py', '__init__.py'), ('./__init__.py', '__init__.py'), ('nodes//loader.py', 'nodes/loader.py'), ('nodes/', 'nodes'),
    ('../removed.py', 'removed.py'), ('/removed.py', 'removed.py'), ('nodes/../loader.py', 'nodes/loader.py'), ('', ''),
    pytest.param('loader?.py', 'loader?.py', marks=NOT_ON_WINDOWS), pytest.param('nodes./loader.py. ', 'nodes./loader.py. ', marks=NOT_ON_WINDOWS),
])
def test_path_that_a_member_of_an_archive_is_extracted_to(tmp_path, name, path):
    """As `zipfile` extracts it: an archive with that member is extracted, and the file is where the function says."""
    assert load_manager_util().extracted_path(name) == path.replace('/', os.sep)
    if name and not name.endswith('/'):
        with zipfile.ZipFile(tmp_path / 'archive.zip', 'w') as archive:
            archive.writestr(name, '')
        load_manager_util().extract_package_as_zip(str(tmp_path / 'archive.zip'), str(tmp_path / 'extracted'))
        assert (tmp_path / 'extracted' / path).is_file()


@pytest.mark.parametrize('name, path', [
    ('loader?.py', 'loader_.py'), ('nodes/a:b<c>d|e"f*.py', 'nodes\\a_b_c_d_e_f_.py'), ('nodes./loader.py. ', 'nodes\\loader.py'),
    ('C:/nodes/loader.py', 'nodes\\loader.py'), ('nodes\\..\\loader.py', 'nodes\\loader.py'), (' ./loader.py', 'loader.py'),
])
def test_path_that_a_member_of_an_archive_is_extracted_to_on_windows(monkeypatch, name, path):
    """There `zipfile` also replaces the characters that a name cannot hold, and drops the dots and spaces that end a part."""
    manager_util = load_manager_util()
    monkeypatch.setattr(manager_util, 'os', types.SimpleNamespace(path=ntpath))

    assert manager_util.extracted_path(name) == path
    assert zipfile.ZipFile._sanitize_windows_name(path, '\\') == path


def test_reserved_switch_reads_the_list_as_it_is_written(tmp_path):
    """As UTF-8. The file with the Korean name is not there: the file system of the child cannot name it."""
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
