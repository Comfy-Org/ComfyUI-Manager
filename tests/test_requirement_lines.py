import os
from types import SimpleNamespace

import pytest

from _install_flags_testutil import import_reader
from test_pip_blacklist_matching import load_prestartup, set_lists  # noqa: F401 -- fixture

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
CORE_PATHS = [f'{tree} {path}' for tree in ('glob', 'legacy') for path in ('install', 'fix', 'install from a git url')]


@pytest.fixture(params=[*CORE_PATHS, 'start'])
def installs(request, set_lists, monkeypatch, tmp_path, capsys):  # noqa: F811
    from comfyui_manager.common import cm_global

    set_lists(blacklist={'xformers'})
    monkeypatch.setattr(cm_global, 'pip_overrides', OVERRIDES)
    executed = []

    def ran(action, line):
        (tmp_path / 'requirements.txt').write_text(line + '\n', encoding='utf-8')
        capsys.readouterr()
        ok = action()
        said = [said for said in capsys.readouterr().out.splitlines() if 'one row at a time' in said]
        return SimpleNamespace(commands=executed, ok=bool(ok), said=said)

    def start(line):
        startup = load_prestartup(processed_install=set(), comfy_path=str(tmp_path), _unified_resolver_succeeded=False,
                                  process_wrap=lambda cmd, cwd=None, **kwargs: executed.append(cmd[4:]) or int(cmd[4].startswith('-') and cmd[4] != '-e'))
        return ran(lambda: startup['execute_lazy_install_script'](str(tmp_path), 'python') or True, line)

    if request.param == 'start':
        start.path = 'start'
        return start

    tree, path = request.param.split(' ', 1)
    core = import_reader(tree)
    monkeypatch.setattr(core.manager_util, 'PIPFixer', lambda *args: SimpleNamespace(fix_broken=lambda: None))
    monkeypatch.setattr(core.manager_util, 'use_unified_resolver', False)
    monkeypatch.setattr(core.manager_funcs, 'run_script', lambda cmd, cwd='.': executed.append(cmd[4:]) or int(cmd[4].startswith('-') and cmd[4] != '-e'))
    monkeypatch.setattr(core.unified_manager, 'processed_install', set())
    monkeypatch.setattr(core.unified_manager, 'unknown_active_nodes', {'pack': ('https://example.invalid/pack', str(tmp_path))})
    action = {'install': lambda: core.unified_manager.execute_install_script(None, str(tmp_path), instant_execution=True),
              'fix': lambda: core.unified_manager.unified_fix('pack', 'unknown', instant_execution=True).result,
              'install from a git url': lambda: core.execute_install_script(None, str(tmp_path), instant_execution=True)}[path]

    def installs(line):
        return ran(action, line)

    installs.path = path
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
    run = installs(f'{row}\ndemo-pkg')

    assert (run.commands, run.ok) == ([['demo-pkg']], True)
    assert len(run.said) == 1 and f"'{OPTION_ROWS[row]}'" in run.said[0]


@pytest.mark.parametrize('row', EDITABLE_ROWS)
def test_an_editable_row_goes_to_the_installer_as_its_option_and_its_target(installs, row):
    run = installs(f'{row}\ndemo-pkg')

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
    manager_util = import_reader('glob').manager_util
    monkeypatch.setattr(manager_util, 'get_pip_cmd', lambda force_uv=False: installer)

    assert manager_util.pip_install_args(row, {}) == installed
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


@pytest.mark.parametrize('path', ['install', 'fix'])
@pytest.mark.parametrize('tree', ['glob', 'legacy'])
@pytest.mark.parametrize('row', SAME_ROW_OF_TWO_NODEPACKS)
def test_a_row_that_names_a_path_of_the_nodepack_is_installed_for_each_nodepack_of_a_session(row, tree, path, set_lists, monkeypatch, tmp_path):  # noqa: F811
    core = import_reader(tree)
    packs = [tmp_path / name for name in ('pack-a', 'pack-b')]
    for pack in packs:
        (pack / 'local').mkdir(parents=True)
        (pack / 'wheels').mkdir()
        (pack / 'wheels' / 'demo_pkg-1.0-py3-none-any.whl').write_bytes(b'')
        (pack / 'requirements.txt').write_text(row + '\n', encoding='utf-8')
    installed_in = []
    monkeypatch.setattr(core.manager_util, 'PIPFixer', lambda *args: SimpleNamespace(fix_broken=lambda: None))
    monkeypatch.setattr(core.manager_util, 'use_unified_resolver', False)
    monkeypatch.setattr(core.manager_funcs, 'run_script', lambda cmd, cwd='.': installed_in.append(os.path.basename(cwd)) or 0)
    monkeypatch.setattr(core.unified_manager, 'processed_install', set())
    monkeypatch.setattr(core.unified_manager, 'unknown_active_nodes', {pack.name: (f'https://example.invalid/{pack.name}', str(pack)) for pack in packs})
    fixed = set()
    action = {'install': lambda pack: core.unified_manager.execute_install_script(None, str(pack), instant_execution=True),
              'fix': lambda pack: core.unified_manager.unified_fix(pack.name, 'unknown', instant_execution=True, fixed=fixed)}[path]

    for pack in packs:
        action(pack)

    assert installed_in == SAME_ROW_OF_TWO_NODEPACKS[row]


@pytest.mark.parametrize('tree', ['glob', 'legacy'])
def test_the_manager_requirements_of_comfyui_are_read_by_the_same_rule(tree, set_lists, monkeypatch, tmp_path):  # noqa: F811
    core = import_reader(tree)
    executed = []
    monkeypatch.setattr(core.subprocess, 'run', lambda cmd, **kwargs: executed.append(cmd[4:]))
    monkeypatch.delenv('COMFYUI_MANAGER_SKIP_MANAGER_REQUIREMENTS', raising=False)
    (tmp_path / 'manager_requirements.txt').write_text(
        f'# the Manager\n--extra-index-url {INDEX}\ncomfyui_manager==4.0.3  # pinned by ComfyUI\n\n{REPO}#subdirectory=manager\n', encoding='utf-8')

    core.install_manager_requirements(str(tmp_path))

    assert executed == [['comfyui_manager==4.0.3'], [f'{REPO}#subdirectory=manager']]
