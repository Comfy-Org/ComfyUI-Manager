import os

import pytest

from test_snapshot_restore_pins import run

REPOSITORY = '''
def repository(path):
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


def test_ref_that_head_names_is_read():
    assert lines('''
import git_utils
commits = repository(nodes / 'fixture')
head_file = nodes / 'fixture/.git/HEAD'
branch = head_file.read_text().strip()[5:]
result = [git_utils.get_commit_hash(str(nodes / 'fixture')) == commits[1]]
head_file.write_text('ref:' + branch + '\\n')
result.append(git_utils.get_commit_hash(str(nodes / 'fixture')) == commits[1])
head_file.write_text('ref: \\n')
result.append(git_utils.get_commit_hash(str(nodes / 'fixture')))
''') == [True, True, 'unknown']


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


def test_ref_whose_place_is_a_folder_is_not_read_as_a_file():
    """git takes a folder there for no ref: after `git pack-refs`, and after `git checkout --orphan feature` beside a branch `feature/x`."""
    assert lines('''
import git_utils
commits = repository(nodes / 'fixture')
subprocess.run(['git', 'pack-refs', '--all'], cwd=nodes / 'fixture', check=True)
branch = (nodes / 'fixture/.git/HEAD').read_text().strip()[5:]
(nodes / 'fixture/.git' / branch).mkdir(parents=True)
result = [git_utils.get_commit_hash(str(nodes / 'fixture')) == commits[1]]
subprocess.run(['git', 'branch', 'feature/x'], cwd=nodes / 'fixture', check=True)
subprocess.run(['git', 'checkout', '-q', '--orphan', 'feature'], cwd=nodes / 'fixture', check=True)
result.append(git_utils.get_commit_hash(str(nodes / 'fixture')))
''') == [True, 'unknown']


def test_commit_that_is_not_ascii_is_read_without_an_error():
    assert lines('''
import git_utils
repository(nodes / 'fixture')
git_dir = nodes / 'fixture/.git'
branch = (git_dir / 'HEAD').read_text().strip()[5:]
subprocess.run(['git', 'pack-refs', '--all'], cwd=nodes / 'fixture', check=True)
(git_dir / 'packed-refs').write_bytes(b'0123\\xff ' + branch.encode() + b'\\n')
result = [git_utils.get_commit_hash(str(nodes / 'fixture'))]
(git_dir / branch).write_bytes(b'0123\\xff\\n')
result.append(git_utils.get_commit_hash(str(nodes / 'fixture')))
(git_dir / 'HEAD').write_bytes(b'0123\\xff\\n')
result.append(git_utils.get_commit_hash(str(nodes / 'fixture')))
''') == ['0123\ufffd'] * 3


def test_head_that_cannot_be_opened_has_no_commit():
    assert lines('''
import git_utils
(nodes / 'fixture/.git/HEAD').mkdir(parents=True)
result = [git_utils.get_commit_hash(str(nodes / 'fixture'))]
''') == ['unknown']


def test_files_that_may_not_be_read_have_no_commit(tmp_path):
    (tmp_path / 'probe').touch()
    (tmp_path / 'probe').chmod(0)
    try:
        open(tmp_path / 'probe').close()
    except OSError:
        pass
    else:
        pytest.skip('a file can be read here whatever its mode, as by root or on Windows')

    assert lines('''
import git_utils
commits = repository(nodes / 'fixture')
git_dir = nodes / 'fixture/.git'
subprocess.run(['git', 'pack-refs', '--all'], cwd=nodes / 'fixture', check=True)
branch = (git_dir / 'HEAD').read_text().strip()[5:]
result = []
(git_dir / 'packed-refs').chmod(0)
result.append(git_utils.get_commit_hash(str(nodes / 'fixture')))
(git_dir / branch).write_text(commits[1])
(git_dir / branch).chmod(0)
result.append(git_utils.get_commit_hash(str(nodes / 'fixture')))
(git_dir / 'HEAD').chmod(0)
result.append(git_utils.get_commit_hash(str(nodes / 'fixture')))
''') == ['unknown', 'unknown', 'unknown']


def test_commit_is_read_beside_refs_that_are_not_utf8():
    assert lines('''
import git_utils
commits = repository(nodes / 'fixture')
subprocess.run(['git', 'pack-refs', '--all'], cwd=nodes / 'fixture', check=True)
packed = nodes / 'fixture/.git/packed-refs'
packed.write_bytes(b'0123456789abcdef0123456789abcdef01234567 refs/heads/\\xff\\xfe\\n' + packed.read_bytes())
result = [git_utils.get_commit_hash(str(nodes / 'fixture')) == commits[1]]
''') == [True]


def test_head_that_is_not_utf8_is_read(tmp_path):
    try:
        open(os.fsencode(tmp_path) + b'/\xff\xfe', 'wb').close()
    except (OSError, ValueError):
        pytest.skip('this file system has no file of such a name, as that of Windows')

    assert lines('''
import git_utils
heads = nodes / 'fixture/.git/refs/heads'
heads.mkdir(parents=True)
(nodes / 'fixture/.git/HEAD').write_bytes(b'ref: refs/heads/\\xff\\xfe\\n')
with open(os.fsencode(heads) + b'/\\xff\\xfe', 'wb') as ref:
    ref.write(b'0123456789abcdef0123456789abcdef01234567\\n')
result = [git_utils.get_commit_hash(str(nodes / 'fixture'))]
''') == ['0123456789abcdef0123456789abcdef01234567']


# what MinGit 2.56 named the file of a branch that was cloned on Windows
NAMES_OF_GIT_FOR_WINDOWS = [
    (b'rel-\xfe', 'rel-\u00fe'),
    (b'caf\xe9', 'caf\u00e9'),
    (b'rel-\x81', 'rel-81'),
    ('\ud55c\uae00'.encode(), '\ud55c\uae00'),
    ('\ud55c'.encode() + b'\xfe\xe9\xc3', '\ud55c\u00fe\u00e9\u00c3'),
    ('a\U0001f600'.encode(), 'a\U0001f600'),
    (b'\xe0\x80\x80', '\u00e08080'),
    # a surrogate in UTF-8, which `xutftowcsn` of compat/mingw.c of git takes as one
    (b'\xed\xa0\x80', '\ud800'),
]


def test_file_of_a_ref_is_named_as_git_for_windows_names_it():
    assert lines('''
import git_utils
result = [git_utils.file_name_of_git_for_windows(name) for name in %r]
''' % [name for name, _ in NAMES_OF_GIT_FOR_WINDOWS]) == [file_name for _, file_name in NAMES_OF_GIT_FOR_WINDOWS]


@pytest.mark.skipif(os.name != 'nt', reason='the names that Git for Windows gives its files')
def test_ref_that_git_for_windows_made_is_read():
    """A name that is not UTF-8 is no name of a file there, and Git for Windows writes the file under another."""
    assert lines('''
import git_utils
heads = nodes / 'fixture/.git/refs/heads'
heads.mkdir(parents=True)
(nodes / 'fixture/.git/HEAD').write_bytes(b'ref: refs/heads/rel-\\xfe\\n')
(heads / 'rel-\\u00fe').write_text('0123456789abcdef0123456789abcdef01234567\\n')
result = [git_utils.get_commit_hash(str(nodes / 'fixture'))]
''') == ['0123456789abcdef0123456789abcdef01234567']


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
os.environ.update(GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='protocol.file.allow', GIT_CONFIG_VALUE_0='always')
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


@pytest.mark.parametrize('clone', [['--recursive'], []], ids=['with its submodules', 'without its submodules'])
def test_checkout_brings_the_submodules_to_the_commit(clone):
    assert lines(SUBMODULE + '''
git(nodes, 'clone', '-q', *%r, str(origin), 'fixture')
result = [core.repo_switch_commit(str(nodes / 'fixture'), pinned_commits[0]), head(nodes / 'fixture') == pinned_commits[0],
          head(nodes / 'fixture/library') == library[0]]
''' % clone) == [True, True, True]


def test_submodules_are_brought_to_the_commit_of_a_pack_that_is_at_it_already():
    assert lines(SUBMODULE + '''
git(nodes, 'clone', '-q', '--recursive', str(origin), 'fixture')
git(nodes / 'fixture/library', 'checkout', '-q', library[0])
result = [core.repo_switch_commit(str(nodes / 'fixture'), pinned_commits[1]), head(nodes / 'fixture/library') == library[1]]
''') == [False, True]


def test_submodule_that_was_never_fetched_is_left_alone_in_a_pack_cloned_without_its_submodules():
    """As git does without `--init`: no submodule of such a clone is active."""
    assert lines(SUBMODULE + '''
git(nodes, 'clone', '-q', str(origin), 'fixture')
# moved, as git makes files read-only that Windows does not remove
(pathlib.Path(tmp) / 'library').rename(pathlib.Path(tmp) / 'library.away')
result = [core.repo_switch_commit(str(nodes / 'fixture'), pinned_commits[1]), list((nodes / 'fixture/library').iterdir())]
''') == [False, []]


@pytest.mark.parametrize('reachable', [True, False], ids=['reachable', 'away'])
def test_submodule_that_was_never_fetched_is_fetched_in_a_pack_cloned_as_the_manager_clones(reachable):
    """`clone --recursive` makes every submodule active, also one of a later commit: git updates it without `--init`."""
    result = lines(SUBMODULE + '''
import io, logging
log = io.StringIO()
logging.getLogger().addHandler(logging.StreamHandler(log))
plain = pathlib.Path(tmp) / 'plain'
plain.mkdir()
git(plain, 'init', '-q')
git(plain, 'commit', '-q', '--allow-empty', '-m', 'no submodule')
git(nodes, 'clone', '-q', '--recursive', str(plain), 'fixture')
git(plain, 'submodule', 'add', '-q', str(pathlib.Path(tmp) / 'library'), 'library')
git(plain, 'commit', '-q', '-m', 'a submodule')
git(nodes / 'fixture', 'pull', '-q')
if not %r:
    # moved, as git makes files read-only that Windows does not remove
    (pathlib.Path(tmp) / 'library').rename(pathlib.Path(tmp) / 'library.away')
result = [core.repo_switch_commit(str(nodes / 'fixture'), head(plain)), (nodes / 'fixture/library/__init__.py').exists(),
          "'" + str(nodes / 'fixture') + "'" in log.getvalue(), 'library' in log.getvalue()]
''' % reachable)

    assert result == ([False, True, False, False] if reachable else [None, False, True, True])


def test_git_is_not_run_for_the_submodules_of_a_pack_that_has_none():
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
