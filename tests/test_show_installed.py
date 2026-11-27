from test_snapshot_restore_pins import run

PACKS = '''
import ast, io
from typing_extensions import Annotated
import typer
from rich.console import Console

def show(name, kind):
    found = [node for node in ast.parse(pathlib.Path('cm-cli.py').read_text(encoding='utf-8')).body
             if isinstance(node, ast.FunctionDef) and node.name in (name, 'show_list')]
    for node in found:
        node.decorator_list = []
    out = io.StringIO()
    scope = {'typer': typer, 'Annotated': Annotated, 'asyncio': asyncio, 'os': os,
             'print': Console(file=out, width=1000, color_system=None).print, 'cmd_ctx': Mock(), 'unified_manager': manager}
    exec(compile(ast.Module(body=found, type_ignores=[]), 'cm-cli.py', 'exec'), scope)
    scope[name](kind, None, None, None)
    return [' '.join(line.split()) for line in out.getvalue().splitlines()]

manager.get_custom_nodes = AsyncMock(return_value={
    'listed-pack': {'title': 'Listed Pack', 'author': 'someone', 'files': ['https://github.com/someone/listed-pack']},
})
manager.cnr_map['registry-pack'] = {'id': 'registry-pack', 'name': 'Registry Pack', 'publisher': {'name': 'someone'},
                                    'latest_version': {'version': '1.0.0'}}
manager.active_nodes['registry-pack'] = ('1.0.0', str(nodes / 'registry-pack'))
manager.unknown_active_nodes['listed-pack'] = ('https://github.com/someone/listed-pack', str(nodes / 'listed-pack'))
manager.unknown_active_nodes['git-pack'] = ('https://example.invalid/git-pack', str(nodes / 'git-pack'))
manager.unknown_inactive_nodes['old-git-pack'] = ('https://example.invalid/old-git-pack', str(nodes / '.disabled/old-git-pack'))
'''


def shown(*commands):
    return run(PACKS + f'print(json.dumps([show(name, kind) for name, kind in {list(commands)!r}]))')


def test_simple_show_lists_every_installed_nodepack():
    assert shown(('simple_show', 'enabled'), ('simple_show', 'disabled'), ('simple_show', 'installed')) == [
        ['Registry Pack@1.0.0', 'Listed Pack@unknown', 'git-pack@unknown'],
        ['old-git-pack@unknown'],
        ['Registry Pack@1.0.0', 'Listed Pack@unknown', 'git-pack@unknown', 'old-git-pack@unknown'],
    ]


def test_show_names_a_git_nodepack_that_the_lists_do_not_know_by_its_id():
    assert shown(('show', 'installed'))[0][2:] == [
        '[ ENABLED ] git-pack git-pack (author: N/A ) [UNKNOWN]',
        '[ DISABLED ] old-git-pack old-git-pack (author: N/A ) [UNKNOWN]',
    ]
