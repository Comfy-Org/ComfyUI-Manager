"""The pygit2 backend updates the submodules of a repository as `git submodule update --init --recursive` does.

Each case runs the update in a process of its own, with pygit2 asked for and no git executable on `PATH`.
"""

import os
import shutil
import socket
import ssl
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

from _install_flags_testutil import GIT_LOCATION
from test_git_commit_and_submodules import git_with_local_submodules, head, repository, repository_with_a_submodule

pytest.importorskip('pygit2')

# For a git server: what `pack-objects` writes to stderr reaches the client as a progress message, here the first
# two bytes of a Korean character. pygit2 decodes each piece of a message, and a piece can end like that.
MESSAGE_CUT_IN_A_CHARACTER = {'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'uploadpack.packObjectsHook',
                              'GIT_CONFIG_VALUE_0': """sh -c 'printf "\\355\\225" >&2; exec "$@"' --"""}


@pytest.fixture(autouse=True)
def git_finds_its_repository_by_the_directory(monkeypatch):
    for name in GIT_LOCATION:
        monkeypatch.delenv(name, raising=False)


def run_with_pygit2(tmp_path, code):
    """In a process of its own, with no git executable to fall back on."""
    (tmp_path / 'no-git').mkdir(exist_ok=True)
    common = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'comfyui_manager', 'common')
    code = f'import sys; sys.path.insert(0, {common!r}); import git_compat\nassert git_compat.USE_PYGIT2\n{code}\n'
    env = {key: value for key, value in os.environ.items() if key not in ('GIT_EXE_PATH', 'GIT_PYTHON_GIT_EXECUTABLE')}
    return subprocess.run([sys.executable, '-c', code], env={**env, 'PATH': str(tmp_path / 'no-git'), 'CM_USE_PYGIT2': '1'},
                          capture_output=True, text=True)


def update_submodules_with_pygit2(tmp_path, clone, init=True, first=''):
    return run_with_pygit2(tmp_path, f'{first}\ngit_compat.open_repo({str(clone)!r}).submodule_update(init={init})')


def test_pygit2_updates_the_fetched_submodules_beside_one_never_fetched(tmp_path):
    """Without a git executable there is no fallback: pygit2 refuses a submodule that was never fetched."""
    library = repository(tmp_path / 'library')
    origin = tmp_path / 'origin'
    origin.mkdir()
    git_with_local_submodules(origin, 'init', '-q')
    for name in ('a-never-fetched', 'b-fetched'):
        git_with_local_submodules(origin, 'submodule', 'add', '-q', str(tmp_path / 'library'), name)
    git_with_local_submodules(origin, 'commit', '-q', '-a', '-m', 'two submodules')
    clone = tmp_path / 'clone'
    git_with_local_submodules(tmp_path, 'clone', '-q', str(origin), str(clone))
    git_with_local_submodules(clone, 'submodule', 'update', '-q', '--init', 'b-fetched')
    git_with_local_submodules(clone / 'b-fetched', 'checkout', '-q', library[0])
    (tmp_path / 'no-git').mkdir()
    common = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'comfyui_manager', 'common')
    code = (f'import sys; sys.path.insert(0, {common!r}); import git_compat\n'
            f'assert git_compat.USE_PYGIT2\ngit_compat.open_repo({str(clone)!r}).submodule_update(init=False)\n')
    env = {key: value for key, value in os.environ.items() if key not in ('GIT_EXE_PATH', 'GIT_PYTHON_GIT_EXECUTABLE')}

    child = subprocess.run([sys.executable, '-c', code], env={**env, 'PATH': str(tmp_path / 'no-git'), 'CM_USE_PYGIT2': '1'},
                           capture_output=True, text=True)

    assert child.returncode == 0, child.stderr
    assert head(clone / 'b-fetched') == library[1]
    assert os.listdir(clone / 'a-never-fetched') == []


def test_pygit2_updates_a_submodule_of_a_submodule(tmp_path):
    """As `git submodule update --init --recursive` does, which the other backend runs."""
    library, _ = repository_with_a_submodule(tmp_path)
    outer = tmp_path / 'outer'
    outer.mkdir()
    git_with_local_submodules(outer, 'init', '-q')
    git_with_local_submodules(outer, 'submodule', 'add', '-q', str(tmp_path / 'origin'), 'origin')
    git_with_local_submodules(outer, 'commit', '-q', '-a', '-m', 'a submodule with a submodule')
    clone = tmp_path / 'clone'
    git_with_local_submodules(tmp_path, 'clone', '-q', str(outer), str(clone))

    child = update_submodules_with_pygit2(tmp_path, clone)

    assert child.returncode == 0, child.stderr
    assert (clone / 'origin/library/__init__.py').exists()
    assert head(clone / 'origin/library') == library[1]

    git_with_local_submodules(clone / 'origin/library', 'checkout', '-q', library[0])
    child = update_submodules_with_pygit2(tmp_path, clone)

    assert child.returncode == 0, child.stderr
    assert head(clone / 'origin/library') == library[1]

    # without `init` as well, which a restore asks for when the nodepack is at its commit already
    git_with_local_submodules(clone / 'origin/library', 'checkout', '-q', library[0])
    child = update_submodules_with_pygit2(tmp_path, clone, init=False)

    assert child.returncode == 0, child.stderr
    assert head(clone / 'origin/library') == library[1]


def test_pygit2_passes_over_a_submodule_that_gitmodules_alone_names(tmp_path):
    """As git does: an entry left in `.gitmodules` for a submodule that was removed is not a failure."""
    library, _ = repository_with_a_submodule(tmp_path)
    with open(tmp_path / 'origin/.gitmodules', 'a', encoding='utf-8') as gitmodules:
        gitmodules.write(f'[submodule "a-removed"]\n\tpath = a-removed\n\turl = {tmp_path / "nowhere"}\n')
    git_with_local_submodules(tmp_path / 'origin', 'commit', '-q', '-a', '-m', 'an entry without a submodule')
    clone = tmp_path / 'clone'
    git_with_local_submodules(tmp_path, 'clone', '-q', str(tmp_path / 'origin'), str(clone))

    child = update_submodules_with_pygit2(tmp_path, clone)

    assert child.returncode == 0, child.stderr
    assert head(clone / 'library') == library[1]


def add_repository_without_gitmodules(tmp_path, origin):
    """A repository committed inside `origin` by `git add`: a commit in the tree that `.gitmodules` does not name."""
    repository(origin / 'stray')
    git_with_local_submodules(origin, 'add', 'stray')
    git_with_local_submodules(origin, 'commit', '-q', '-m', 'a repository added without `git submodule`')
    clone = tmp_path / 'clone'
    git_with_local_submodules(tmp_path, 'clone', '-q', str(origin), str(clone))
    return clone


def test_pygit2_passes_over_a_commit_in_the_tree_without_gitmodules(tmp_path):
    """As `git clone --recursive` does: there is no url to fetch it from, and the nodepack is installed."""
    repository(tmp_path / 'origin')
    clone = add_repository_without_gitmodules(tmp_path, tmp_path / 'origin')

    child = update_submodules_with_pygit2(tmp_path, clone)

    assert child.returncode == 0, child.stderr
    assert os.listdir(clone / 'stray') == []


def test_pygit2_updates_the_submodules_beside_a_commit_that_gitmodules_does_not_name(tmp_path):
    library, _ = repository_with_a_submodule(tmp_path)
    clone = add_repository_without_gitmodules(tmp_path, tmp_path / 'origin')

    child = update_submodules_with_pygit2(tmp_path, clone)

    assert child.returncode == 0, child.stderr
    assert head(clone / 'library') == library[1]


def test_pygit2_does_not_pass_over_a_submodule_it_could_not_fetch(tmp_path):
    """Without a git executable nothing else does the update: the caller must not take it as done."""
    repository_with_a_submodule(tmp_path)
    clone = tmp_path / 'clone'
    git_with_local_submodules(tmp_path, 'clone', '-q', str(tmp_path / 'origin'), str(clone))
    shutil.rmtree(tmp_path / 'library')

    child = update_submodules_with_pygit2(tmp_path, clone)

    assert child.returncode != 0, child.stderr
    assert 'GitCommandError' in child.stderr


def test_pygit2_does_not_pass_over_a_git_that_did_not_come_back(tmp_path):
    repository_with_a_submodule(tmp_path)
    clone = tmp_path / 'clone'
    git_with_local_submodules(tmp_path, 'clone', '-q', str(tmp_path / 'origin'), str(clone))
    shutil.rmtree(tmp_path / 'library')
    late = ('import subprocess\n'
            'def late(command, timeout, **_):\n'
            '    raise subprocess.TimeoutExpired(command, timeout)\n'
            'subprocess.run = late')

    child = update_submodules_with_pygit2(tmp_path, clone, first=late)

    assert child.returncode != 0, child.stderr
    assert 'TimeoutExpired' in child.stderr


def test_pygit2_fetches_a_submodule_whose_fetch_failed_at_the_update_before(tmp_path):
    """An update whose submodules cannot be fetched is undone; what the clone of the submodule left is not in the way of the next."""
    repository(tmp_path / 'library')
    origin, pack = tmp_path / 'origin', tmp_path / 'pack'
    repository(origin)
    git_with_local_submodules(tmp_path, 'clone', '-q', str(origin), str(pack))
    git_with_local_submodules(origin, 'submodule', 'add', '-q', str(tmp_path / 'library'), 'library')
    git_with_local_submodules(origin, 'commit', '-q', '-m', 'a submodule')
    (tmp_path / 'library').rename(tmp_path / 'library.away')
    # as an update of Manager does it
    update = (f'repo = git_compat.open_repo({str(pack)!r})\n'
              'commit = repo.head_commit_hexsha\n'
              'repo.pull_ff_only()\n'
              'try:\n'
              '    repo.submodule_update()\n'
              'except Exception:\n'
              '    repo.reset_hard(commit)\n'
              '    raise')

    child = run_with_pygit2(tmp_path, update)

    assert child.returncode != 0, child.stderr
    assert head(pack) != head(origin)

    (tmp_path / 'library.away').rename(tmp_path / 'library')
    child = run_with_pygit2(tmp_path, update)

    assert child.returncode == 0, child.stderr
    assert head(pack) == head(origin)
    assert (pack / 'library/__init__.py').read_text() == 'VERSION = 2'


class GitHostBehindAProxy(BaseHTTPRequestHandler):
    """A proxy, and behind it the https host of the repositories of `server.root`: the tunnel it is asked for ends in itself."""
    protocol_version = 'HTTP/1.1'

    def handle(self):
        # one that did not ask the proxy begins with a TLS hello, and is not answered
        if self.connection.recv(1, socket.MSG_PEEK) == b'C':
            super().handle()

    def do_CONNECT(self):
        self.send_response(200)
        self.end_headers()
        self.connection = self.server.tls.wrap_socket(self.connection, server_side=True)
        self.rfile = self.connection.makefile('rb')
        self.wfile = self.connection.makefile('wb', 0)

    def finish(self):
        super().finish()
        self.connection.close()

    def do_GET(self):
        url = urlsplit(self.path)
        self.server.asked.add(url.path.split('/')[1])
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        cgi = {'GIT_PROJECT_ROOT': self.server.root, 'GIT_HTTP_EXPORT_ALL': '1', 'REQUEST_METHOD': self.command,
               'PATH_INFO': url.path, 'QUERY_STRING': url.query, 'CONTENT_TYPE': self.headers.get('Content-Type', '')}
        answer = subprocess.run([self.server.backend], input=body, env={**os.environ, **cgi, **MESSAGE_CUT_IN_A_CHARACTER}, check=True, capture_output=True).stdout
        headers, _, content = answer.partition(b'\r\n\r\n')
        status = headers.partition(b'Status: ')[2].split(b'\r\n')[0] or b'200 OK'
        self.wfile.write(b'HTTP/1.1 %s\r\nContent-Length: %d\r\n%s\r\n\r\n%s' % (status, len(content), headers, content))

    do_POST = do_GET

    def log_message(self, *args):
        pass


@pytest.fixture
def git_host_behind_a_proxy(tmp_path, monkeypatch):
    """The repositories of `tmp_path` at an https `url` that only the proxy of the global git configuration leads to."""
    backend = os.path.join(subprocess.run(['git', '--exec-path'], check=True, capture_output=True, text=True).stdout.strip(), 'git-http-backend')
    if not os.path.exists(backend) or shutil.which('openssl') is None:
        pytest.skip('git-http-backend and openssl are needed')

    # https, and a name: libgit2 leaves the proxy aside for http, and does not match a certificate with an address
    certificate, key = str(tmp_path / 'certificate.pem'), str(tmp_path / 'key.pem')
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '2', '-keyout', key, '-out', certificate,
                    '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost'], check=True, capture_output=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), GitHostBehindAProxy)
    server.tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.tls.load_cert_chain(certificate, key)
    server.backend, server.root, server.asked = backend, str(tmp_path), set()
    server.url = 'https://localhost:%d/' % server.server_port

    # what the update reads in its own process: the proxy as git_compat finds it, and the certificate to trust
    (tmp_path / 'home').mkdir()
    (tmp_path / 'home/.gitconfig').write_text('[http]\n\tproxy = http://127.0.0.1:%d\n' % server.server_port)
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('SSL_CERT_FILE', certificate)

    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()
    server.server_close()


def pin(path, submodule, commit):
    """Commits `submodule` at `commit` in the repository at `path`, which need not have that commit; the hash."""
    git_with_local_submodules(path, 'update-index', '--cacheinfo', f'160000,{commit},{submodule}')
    git_with_local_submodules(path, 'commit', '-q', '-m', f'{submodule} at {commit}')
    return head(path)


def test_pygit2_fetches_the_submodules_through_the_proxy(tmp_path, git_host_behind_a_proxy):
    """The nodepack is cloned through `http.proxy` of the global git configuration: so are its submodules, and theirs."""
    library, _ = repository_with_a_submodule(tmp_path)
    origin, outer, clone = tmp_path / 'origin', tmp_path / 'outer', tmp_path / 'clone'
    # relative: beside the url that its repository is cloned from
    git_with_local_submodules(origin, 'config', '-f', '.gitmodules', 'submodule.library.url', '../library')
    git_with_local_submodules(origin, 'commit', '-q', '-a', '-m', 'the library beside it')
    outer.mkdir()
    git_with_local_submodules(outer, 'init', '-q')
    git_with_local_submodules(outer, 'submodule', 'add', '-q', '../origin', 'origin')
    git_with_local_submodules(outer, 'commit', '-q', '-a', '-m', 'a submodule with a submodule')

    cloned = f'git_compat.clone_repo({git_host_behind_a_proxy.url + "outer"!r}, {str(clone)!r})'
    child = update_submodules_with_pygit2(tmp_path, clone, first=cloned)

    assert child.returncode == 0, child.stderr
    assert head(clone / 'origin/library') == library[1]
    assert git_host_behind_a_proxy.asked == {'outer', 'origin', 'library'}

    # commits that the clones of the submodules do not have yet
    (tmp_path / 'library/__init__.py').write_text('VERSION = 3')
    git_with_local_submodules(tmp_path / 'library', 'commit', '-q', '-a', '-m', 'version 3')
    later = head(tmp_path / 'library')
    pin(clone, 'origin', pin(origin, 'library', later))
    child = update_submodules_with_pygit2(tmp_path, clone)

    assert child.returncode == 0, child.stderr
    assert head(clone / 'origin/library') == later

    # and without `init`, which a restore asks for when the nodepack is at its commit already
    (tmp_path / 'library/__init__.py').write_text('VERSION = 4')
    git_with_local_submodules(tmp_path / 'library', 'commit', '-q', '-a', '-m', 'version 4')
    latest = head(tmp_path / 'library')
    pin(clone, 'origin', pin(origin, 'library', latest))
    child = update_submodules_with_pygit2(tmp_path, clone, init=False)

    assert child.returncode == 0, child.stderr
    assert head(clone / 'origin/library') == latest


def test_pygit2_fetches_a_submodule_with_an_ssh_url_over_https(tmp_path, git_host_behind_a_proxy):
    """As the nodepack itself, whose ssh url is cloned over https: a public repository needs no credentials."""
    library, _ = repository_with_a_submodule(tmp_path)
    origin, clone = tmp_path / 'origin', tmp_path / 'clone'
    git_with_local_submodules(origin, 'config', '-f', '.gitmodules', 'submodule.library.url', 'git@localhost:library')
    git_with_local_submodules(origin, 'commit', '-q', '-a', '-m', 'an ssh url')

    cloned = f'git_compat.clone_repo({git_host_behind_a_proxy.url + "origin"!r}, {str(clone)!r})'
    child = update_submodules_with_pygit2(tmp_path, clone, first=cloned)

    assert child.returncode == 0, child.stderr
    assert head(clone / 'library') == library[1]
