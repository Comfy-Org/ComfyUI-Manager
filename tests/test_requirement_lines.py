from types import SimpleNamespace

import pytest

from test_install_flags_config import _run_child
from test_pip_blacklist_matching import CM_GLOBAL, MANAGER_UTIL, load_prestartup, set_lists  # noqa: F401 -- fixture

INDEX = 'https://example.invalid/whl/cu121'
MIRROR = 'https://example.invalid/simple'
REPO = 'git+https://example.invalid/packs/proto'
OVERRIDES = {'opencv-python': 'opencv-contrib-python-headless'}
FORCED = ['--force-reinstall', '--no-deps', '--no-cache-dir']

LINES = {
    'demo-pkg': [['demo-pkg']],
    'demo-pkg==1.2': [['demo-pkg==1.2']],
    'demo-pkg>=1,<2': [['demo-pkg>=1,<2']],
    'demo-pkg; python_version < "3.12"': [['demo-pkg; python_version < "3.12"']],
    'opencv-python': [['opencv-contrib-python-headless']],
    'pygit2>=1.18  # clone_repository(proxy=...) requires 1.18.0+': [['pygit2>=1.18']],
    'demo-pkg; python_version < "3.12"  # older pythons': [['demo-pkg; python_version < "3.12"']],
    'opencv-python  # headless on servers': [['opencv-contrib-python-headless']],
    f'torch --index-url {INDEX}': [['torch', '--index-url', INDEX]],
    f'torch==2.1.1  --index-url {INDEX}  # the CUDA build': [['torch==2.1.1', '--index-url', INDEX]],
    f'torch --extra-index-url {INDEX}  # the CUDA build': [['torch', '--extra-index-url', INDEX]],
    f'torch --index-url {MIRROR} --extra-index-url {INDEX}': [['torch', '--index-url', MIRROR, '--extra-index-url', INDEX]],
    '# a comment': [],
    '   ': [],
}
URL_LINES = {
    f'{REPO}#subdirectory=sub': [f'{REPO}#subdirectory=sub'],
    f'proto-dist @ {REPO}#egg=proto-dist  # pinned': [f'proto-dist @ {REPO}#egg=proto-dist'],
}
BLACKLISTED = ['xformers', 'xformers  # attention', f'xformers --index-url {INDEX}', f'XFormers>=0.0.30 --extra-index-url {INDEX}  # attention']
OPTION_ROWS = {
    f'--extra-index-url {INDEX}': f'--extra-index-url {INDEX}',
    f'--index-url {INDEX}  # the CUDA build': f'--index-url {INDEX}',
    '-r other.txt': '-r other.txt',
    '-c constraints.txt': '-c constraints.txt',
    '-f https://example.invalid/wheels': '-f https://example.invalid/wheels',
    '--trusted-host example.invalid': '--trusted-host example.invalid',
    '--only-binary :all:': '--only-binary :all:',
    '    --hash=sha256:4bc89822243270757f4c272934e2521ad4b41f0cdcdce82672eeacf01ca3d5f1': '--hash=sha256:4bc89822243270757f4c272934e2521ad4b41f0cdcdce82672eeacf01ca3d5f1',
}
EDITABLE_ROWS = {
    '-e ./local': ['-e', './local'],
    '-e .': ['-e', '.'],
    '--editable ./local': ['-e', './local'],
    '--editable=./local': ['-e', './local'],
    '-e./local': ['-e', './local'],
    f'-e {REPO}#egg=proto-dist  # pinned': ['-e', f'{REPO}#egg=proto-dist'],
    '-e requests': ['-e', 'requests'],
    f'-e ./local --extra-index-url {INDEX}': ['-e', './local', '--extra-index-url', INDEX],
}
WITH_A_ROW_AFTER = {row: f'{row}\ndemo-pkg' for row in [*OPTION_ROWS, *EDITABLE_ROWS]}


@pytest.fixture(scope='module')
def core_runs():
    return _run_child(f"""
import contextlib, io, pathlib, subprocess
from types import SimpleNamespace
import cm_global, manager_util

manager_util.get_pip_cmd = lambda force_uv=False: ['python', '-m', 'pip']
manager_util.subprocess = SimpleNamespace(
    check_output=lambda *args, **kwargs: 'Package Version\\n------- -------\\n', CalledProcessError=subprocess.CalledProcessError)
manager_util.pip_map = None
manager_util.PIPFixer = lambda *args: SimpleNamespace(fix_broken=lambda: None)
cm_global.pip_blacklist, cm_global.pip_downgrade_blacklist, cm_global.pip_overrides = {{'xformers'}}, [], {OVERRIDES!r}
executed = []
manager_core.manager_funcs.run_script = lambda cmd, cwd='.': executed.append(cmd[4:]) or int(cmd[4].startswith('-') and cmd[4] != '-e')
manager = manager_core.unified_manager
runs = {{}}
for number, line in enumerate({[*LINES, *URL_LINES, *BLACKLISTED, *WITH_A_ROW_AFTER.values()]!r}):
    pack = pathlib.Path(tmp) / f'pack{{number}}'
    pack.mkdir()
    (pack / 'requirements.txt').write_text(line + '\\n', encoding='utf-8')
    manager.unknown_active_nodes = {{'pack': ('https://example.invalid/pack', str(pack))}}
    runs[line] = {{}}
    for path, action in [('install', lambda: manager.execute_install_script(None, str(pack), instant_execution=True)),
                         ('fix', lambda: manager.unified_fix('pack', 'unknown', instant_execution=True).result),
                         ('install from a git url', lambda: manager_core.execute_install_script(None, str(pack), instant_execution=True))]:
        manager.processed_install = set()
        del executed[:]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ok = action()
        runs[line][path] = {{'commands': list(executed), 'ok': bool(ok), 'said': [said for said in out.getvalue().splitlines() if 'one row at a time' in said]}}
print(json.dumps(runs))
""")


@pytest.fixture(params=['install', 'fix', 'install from a git url', 'start'])
def installs(request, core_runs, set_lists, monkeypatch, tmp_path, capsys):  # noqa: F811
    monkeypatch.setattr(CM_GLOBAL, 'pip_overrides', OVERRIDES)
    set_lists(blacklist={'xformers'})

    def start(line):
        (tmp_path / 'requirements.txt').write_text(line + '\n', encoding='utf-8')
        executed = []
        startup = load_prestartup(processed_install=set(), comfy_path=str(tmp_path),
                                  process_wrap=lambda cmd, cwd=None, **kwargs: executed.append(cmd[4:]) or int(cmd[4].startswith('-') and cmd[4] != '-e'))
        capsys.readouterr()
        startup['execute_lazy_install_script'](str(tmp_path), 'python')
        said = [said for said in capsys.readouterr().out.splitlines() if 'one row at a time' in said]
        return SimpleNamespace(commands=executed, ok=True, said=said)

    installs = start if request.param == 'start' else lambda line: SimpleNamespace(**core_runs[line][request.param])
    installs.path = request.param
    return installs


@pytest.mark.parametrize('line', LINES)
def test_each_path_gives_the_installer_the_line_as_pip_reads_it(installs, line):
    assert installs(line).commands == LINES[line]


@pytest.mark.parametrize('line', URL_LINES)
def test_a_url_keeps_its_fragment_on_each_path(installs, line):
    forced = [[*URL_LINES[line], *FORCED]] if installs.path == 'fix' else []
    assert installs(line).commands == [URL_LINES[line], *forced]


@pytest.mark.parametrize('line', BLACKLISTED)
def test_a_blacklisted_package_is_skipped_however_its_line_is_written(installs, line):
    assert installs(line).commands == []


@pytest.mark.parametrize('row', OPTION_ROWS)
def test_a_row_with_only_an_option_is_left_out_with_one_line_and_the_rows_after_it_are_installed(installs, row):
    run = installs(WITH_A_ROW_AFTER[row])

    assert (run.commands, run.ok) == ([['demo-pkg']], True)
    assert len(run.said) == 1 and f"'{OPTION_ROWS[row]}'" in run.said[0]


@pytest.mark.parametrize('row', EDITABLE_ROWS)
def test_an_editable_row_goes_to_the_installer_as_its_option_and_its_target(installs, row):
    run = installs(WITH_A_ROW_AFTER[row])

    assert (run.commands, run.ok, run.said) == ([EDITABLE_ROWS[row], ['demo-pkg']], True, [])


@pytest.mark.parametrize('line', ['# a comment', '   ', 'demo-pkg'])
def test_a_row_that_is_not_an_option_row_is_left_out_or_installed_without_that_line(installs, line):
    assert installs(line).said == []


@pytest.mark.parametrize('installer, row, installed, said', [
    (['python', '-m', 'pip'], f'-e {REPO}#egg=proto-dist  # pinned', ['-e', f'{REPO}#egg=proto-dist'], False),
    (['python', '-m', 'uv', 'pip'], f'-e {REPO}#egg=proto-dist  # pinned', [f'{REPO}#egg=proto-dist'], True),
    (['uv', 'pip'], f'--editable={REPO}#egg=proto-dist --extra-index-url {INDEX}', [f'{REPO}#egg=proto-dist', '--extra-index-url', INDEX], True),
    (['uv', 'pip'], f'-e {REPO}#egg=proto-dist --no-build-isolation', [f'-e {REPO}#egg=proto-dist --no-build-isolation'], False),
    (['python', '-m', 'pip'], '-e ./local', ['-e', './local'], False),
    (['uv', 'pip'], '-e ./local', ['-e', './local'], False),
    (['uv', 'pip'], f'{REPO}#egg=proto-dist', [f'{REPO}#egg=proto-dist'], False),
])
def test_uv_installs_an_editable_git_requirement_without_e_and_pip_installs_it_as_it_is_written(installer, row, installed, said, monkeypatch, capsys):
    monkeypatch.setattr(MANAGER_UTIL, 'get_pip_cmd', lambda force_uv=False: installer)

    assert MANAGER_UTIL.pip_install_args(row, {}) == installed
    assert ('without -e' in capsys.readouterr().out) == said


SAME_ROW_OF_TWO_NODEPACKS = {
    '-e .': ['pack-a', 'pack-b'],
    '-e ./local': ['pack-a', 'pack-b'],
    './wheels/demo_pkg-1.0-py3-none-any.whl': ['pack-a', 'pack-b'],
    '-e .[extra]': ['pack-a', 'pack-b'],
    './wheels/demo_pkg-1.0-py3-none-any.whl; python_version >= "3"': ['pack-a', 'pack-b'],
    'demo-pkg': ['pack-a'],
    'demo-pkg[extra]>=1; python_version >= "3"': ['pack-a'],
    f'-e {REPO}#egg=proto-dist': ['pack-a'],
}


@pytest.fixture(scope='module')
def session_runs():
    return _run_child(f"""
import pathlib, subprocess
from types import SimpleNamespace
import cm_global, manager_util

manager_util.get_pip_cmd = lambda force_uv=False: ['python', '-m', 'pip']
manager_util.subprocess = SimpleNamespace(
    check_output=lambda *args, **kwargs: 'Package Version\\n------- -------\\n', CalledProcessError=subprocess.CalledProcessError)
manager_util.pip_map = None
manager_util.PIPFixer = lambda *args: SimpleNamespace(fix_broken=lambda: None)
cm_global.pip_blacklist, cm_global.pip_downgrade_blacklist, cm_global.pip_overrides = set(), [], {{}}
installed_in = []
manager_core.manager_funcs.run_script = lambda cmd, cwd='.': installed_in.append(pathlib.Path(cwd).name) or 0
manager = manager_core.unified_manager
runs = {{}}
for number, row in enumerate({[*SAME_ROW_OF_TWO_NODEPACKS]!r}):
    packs = [pathlib.Path(tmp) / f'row{{number}}' / name for name in ('pack-a', 'pack-b')]
    for pack in packs:
        (pack / 'local').mkdir(parents=True)
        (pack / 'wheels').mkdir()
        (pack / 'wheels' / 'demo_pkg-1.0-py3-none-any.whl').write_bytes(b'')
        (pack / 'requirements.txt').write_text(row + '\\n', encoding='utf-8')
    manager.unknown_active_nodes = {{pack.name: ('https://example.invalid/' + pack.name, str(pack)) for pack in packs}}
    runs[row] = {{}}
    fixed = set()
    for path, action in [('install', lambda pack: manager.execute_install_script(None, str(pack), instant_execution=True)),
                         ('fix', lambda pack: manager.unified_fix(pack.name, 'unknown', instant_execution=True, fixed=fixed))]:
        manager.processed_install = set()
        del installed_in[:]
        for pack in packs:
            action(pack)
        runs[row][path] = list(installed_in)
print(json.dumps(runs))
""")


@pytest.mark.parametrize('path', ['install', 'fix'])
@pytest.mark.parametrize('row', SAME_ROW_OF_TWO_NODEPACKS)
def test_a_row_that_names_a_path_of_the_nodepack_is_installed_for_each_nodepack_of_a_session(session_runs, row, path):
    assert session_runs[row][path] == SAME_ROW_OF_TWO_NODEPACKS[row]
