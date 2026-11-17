"""The commit of a git node pack is read from its `.git`, and a checkout brings its submodules along.

The cases run in the isolated child of tests/test_install_flags_config.py, against the real
glob/manager_core and git repositories of a temporary directory.
"""

from test_snapshot_restore_pins import run

REPOSITORY = '''
def repository(path):
    """A git repository with two commits at `path`; their hashes."""
    path.mkdir(parents=True)
    commits = []
    for version in (1, 2):
        (path / '__init__.py').write_text('VERSION = %d' % version)
        for args in (['init', '-q'], ['add', '.'],
                     ['-c', 'user.name=test', '-c', 'user.email=test@example.invalid', 'commit', '-q', '-m', 'version %d' % version]):
            subprocess.run(['git', *args], cwd=path, check=True, capture_output=True)
        commits.append(head(path))
    return commits

def head(path):
    return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=path, check=True, capture_output=True, text=True).stdout.strip()
'''


def lines(body):
    return run(REPOSITORY + body + '\nprint(json.dumps(result))\n')


def test_commit_of_a_pack_whose_refs_are_packed_is_read():
    assert lines('''
import git_utils
commits = repository(nodes / 'fixture')
subprocess.run(['git', 'pack-refs', '--all'], cwd=nodes / 'fixture', check=True)
with open(nodes / 'fixture/.git/packed-refs', 'a') as packed:
    packed.write('\\n')
branch = (nodes / 'fixture/.git/HEAD').read_text().strip()[5:]
result = [(nodes / 'fixture/.git' / branch).exists(), git_utils.get_commit_hash(str(nodes / 'fixture')) == commits[1]]
''') == [False, True]


def test_commit_is_read_beside_refs_that_are_not_utf8():
    assert lines('''
import git_utils
commits = repository(nodes / 'fixture')
subprocess.run(['git', 'pack-refs', '--all'], cwd=nodes / 'fixture', check=True)
packed = nodes / 'fixture/.git/packed-refs'
packed.write_bytes(b'0123456789abcdef0123456789abcdef01234567 refs/heads/\\xff\\xfe\\n' + packed.read_bytes())
result = [git_utils.get_commit_hash(str(nodes / 'fixture')) == commits[1]]
''') == [True]


def test_head_that_is_not_utf8_gives_no_commit():
    assert lines('''
import git_utils
(nodes / 'fixture/.git').mkdir(parents=True)
(nodes / 'fixture/.git/HEAD').write_bytes(b'ref: refs/heads/\\xff\\xfe\\n')
result = [git_utils.get_commit_hash(str(nodes / 'fixture'))]
''') == ['unknown']


def test_packed_ref_is_matched_by_its_bytes():
    assert lines('''
import git_utils
commits = repository(nodes / 'fixture')
subprocess.run(['git', 'pack-refs', '--all'], cwd=nodes / 'fixture', check=True)
git_dir = nodes / 'fixture/.git'
other = b'0123456789abcdef0123456789abcdef01234567 refs/heads/release-\\xff\\n'
(git_dir / 'packed-refs').write_bytes(other + (git_dir / 'packed-refs').read_bytes())
(git_dir / 'HEAD').write_bytes(b'ref: refs/heads/release-\\xfe\\n')
result = [git_utils.get_commit_hash(str(nodes / 'fixture'))]
(git_dir / 'packed-refs').write_bytes(other + commits[1].encode() + b' refs/heads/release-\\xfe\\n')
result.append(git_utils.get_commit_hash(str(nodes / 'fixture')) == commits[1])
''') == ['unknown', True]


SUBMODULE = '''
def git(path, *args):
    subprocess.run(['git', '-c', 'protocol.file.allow=always', '-c', 'user.name=test', '-c', 'user.email=test@example.invalid', *args],
                   cwd=path, check=True, capture_output=True)
library = repository(pathlib.Path(tmp) / 'library')
origin = pathlib.Path(tmp) / 'origin'
origin.mkdir()
git(origin, 'init', '-q')
git(origin, 'submodule', 'add', '-q', str(pathlib.Path(tmp) / 'library'), 'library')
pinned_commits = []
for commit in library:
    git(origin / 'library', 'checkout', '-q', commit)
    git(origin, 'commit', '-q', '-a', '-m', 'library at ' + commit)
    pinned_commits.append(head(origin))
'''


def test_checkout_brings_the_submodules_to_the_commit():
    assert lines(SUBMODULE + '''
git(nodes, 'clone', '-q', '--recursive', str(origin), 'fixture')
result = [core.repo_switch_commit(str(nodes / 'fixture'), pinned_commits[0]), head(nodes / 'fixture') == pinned_commits[0],
          head(nodes / 'fixture/library') == library[0]]
''') == [True, True, True]


def test_submodules_are_brought_to_the_commit_of_a_pack_that_is_at_it_already():
    """As after a restore whose checkout succeeded and whose update of the submodules failed."""
    assert lines(SUBMODULE + '''
git(nodes, 'clone', '-q', '--recursive', str(origin), 'fixture')
git(nodes / 'fixture/library', 'checkout', '-q', library[0])
result = [core.repo_switch_commit(str(nodes / 'fixture'), pinned_commits[1]), head(nodes / 'fixture/library') == library[1]]
''') == [False, True]


def test_submodule_that_was_never_fetched_is_left_alone_in_a_pack_that_is_at_the_commit():
    """A snapshot does not hold the state of the submodules; one that cannot be reached is not a failure of the pack."""
    assert lines(SUBMODULE + '''
import shutil
git(nodes, 'clone', '-q', str(origin), 'fixture')
shutil.rmtree(pathlib.Path(tmp) / 'library')
result = [core.repo_switch_commit(str(nodes / 'fixture'), pinned_commits[1]), list((nodes / 'fixture/library').iterdir())]
''') == [False, []]


def test_git_is_not_run_for_the_submodules_of_a_pack_that_has_none():
    """A restore goes through every git node pack; on Windows each git command takes about half a second."""
    assert lines('''
import git
commits = repository(nodes / 'fixture')
ran = []
execute = git.Git.execute
def recorded(self, command, *args, **kwargs):
    ran.append(list(command))
    return execute(self, command, *args, **kwargs)
git.Git.execute = recorded
result = [core.repo_switch_commit(str(nodes / 'fixture'), commits[1]), [command for command in ran if 'submodule' in command]]
''') == [False, []]
