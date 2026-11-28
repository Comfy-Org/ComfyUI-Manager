import ast
import asyncio
import logging
import os
import threading
import traceback
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import pytest

from legacy_html_testutil import PACKAGE
from test_invalid_installation import BAR_URL, FOO_URL, NODE_LIST, core, custom_nodes, pack  # noqa: F401 -- fixtures

pytestmark = pytest.mark.parametrize('core', ['legacy'], indirect=True)


def server(names, **namespace):
    path = PACKAGE / 'legacy/manager_server.py'
    nodes = [node for node in ast.parse(path.read_text(encoding='utf-8')).body if getattr(node, 'name', None) in names]
    assert {node.name for node in nodes} == set(names)
    for node in nodes:
        node.decorator_list = []
    exec(compile(ast.Module(nodes, []), str(path), 'exec'), namespace)
    return namespace


def request(query=None, body=None):
    async def json_body():
        return body
    return SimpleNamespace(rel_url=SimpleNamespace(query=query), json=json_body)


class Fetched(list):
    answers: dict
    during_a_fetch: list


@pytest.fixture
def fetched(core, custom_nodes, monkeypatch):  # noqa: F811
    names = Fetched()
    names.answers = answers = {}
    names.during_a_fetch = during_a_fetch = []

    def fetch(path):
        name = Path(path).name
        names.append(name)
        if during_a_fetch:
            during_a_fetch.pop()()
        if isinstance(answers.get(name), Exception):
            raise answers[name]
        return answers.get(name, (False, True))

    monkeypatch.setattr(core, 'git_repo_update_check_with', fetch)
    return names


@pytest.fixture
def listed(core, custom_nodes, monkeypatch):  # noqa: F811
    node_list = [dict(item) for item in NODE_LIST]

    async def get_data_by_mode(mode, filename, channel_url=None):
        shown = add.others.get('the local mode' if mode == 'local' else channel_url, node_list)
        return {'custom-node-list.json': {'custom_nodes': [dict(item) for item in shown]},
                'extras.json': {'favorites': []}}.get(filename, {})

    monkeypatch.setattr(core, 'get_data_by_mode', get_data_by_mode)

    def add(name):
        url = f'https://github.com/example/{name}'
        node_list.append({'author': 'example', 'title': name, 'reference': url, 'files': [url],
                          'install_type': 'git-clone', 'description': ''})
        return url

    add.others = {}
    return add


class Lock:
    def __init__(self, update_check_done):
        self.held = threading.Lock()
        self.update_check_done = update_check_done
        self.after_the_end = []

    def __enter__(self):
        self.held.acquire()

    def __exit__(self, *error):
        self.held.release()
        if self.after_the_end and self.update_check_done.is_set():
            self.after_the_end.pop()()


class Checks:
    def __init__(self, core):  # noqa: F811
        self.events = []
        self.started = []
        self.update_check_done = threading.Event()
        self.update_check_done.set()
        self.update_check_lock = Lock(self.update_check_done)
        self.thread = lambda target: SimpleNamespace(start=lambda: self.started.append(target))
        self.ask = server(
            {'check_update'}, core=core, update_check_done=self.update_check_done, update_check_lock=self.update_check_lock,
            update_check_paths={}, update_check_ui_ids=set(), traceback=traceback,
            threading=SimpleNamespace(Thread=lambda target: self.thread(target)),
            manager_security=SimpleNamespace(reject_non_json_post=lambda request: None),
            web=SimpleNamespace(json_response=lambda data: data),
            PromptServer=SimpleNamespace(instance=SimpleNamespace(send_sync=self.sent)))['check_update']

    def sent(self, name, data):
        self.events.append((name, {key: sorted(value) if isinstance(value, list) else value for key, value in data.items()}))

    def ask_for_a_check(self, mode='cache', ui_id='the page'):
        return asyncio.run(self.ask(request(body={'mode': mode, 'ui_id': ui_id})))

    def ended(self):
        return [event for name, event in self.events if event['status'] == 'done']


def check_for_updates(core, fetched, mode='cache'):  # noqa: F811
    checks = Checks(core)
    answer = checks.ask_for_a_check(mode)
    fetched_by_the_request = list(fetched)
    checks.started.pop()()
    return {'answer': answer, 'fetched by the request': fetched_by_the_request, 'fetched': sorted(fetched),
            'check': [event for name, event in checks.events if name == 'cm-check-update']}


class EndMark(threading.Event):
    def __init__(self):
        super().__init__()
        self.queue_waits = threading.Event()

    def wait(self):
        self.queue_waits.set()
        super().wait()


DISABLE = ('disable', ('a-row', 'ComfyUI-Foo', False))


def run_the_queue(core, monkeypatch, update_check_done, *tasks):  # noqa: F811
    order = []
    scratch = Path(core.get_default_custom_nodes_path()).parent
    core.get_config()['model_download_by_agent'] = True
    monkeypatch.setattr(core, 'update_path', lambda path: order.append('ComfyUI is updated') or 'skipped')
    monkeypatch.setattr(core.unified_manager, 'unified_disable', lambda node_name, is_unknown: order.append('the task') or core.ManagedResult('disable'))
    monkeypatch.setattr(core.unified_manager, 'unified_enable', lambda cnr_id: order.append('the task') or core.ManagedResult('enable'))
    monkeypatch.setattr(core.unified_manager, 'unified_update', lambda node_name, node_ver: order.append('the task') or SimpleNamespace(
        ver='unknown', result=True, action='skip'))
    namespace = server({'task_worker', 'TaskBatch'}, core=core, logging=logging, traceback=traceback, os=os,
                       folder_paths=SimpleNamespace(__file__=str(scratch / 'folder_paths.py')),
                       get_model_path=lambda data: str(scratch / data['filename']),
                       download_url_with_agent=lambda url, path: order.append('the model is downloaded') or True,
                       manager_util=SimpleNamespace(clear_pip_cache=lambda: None), replaces_cnr_with_nightly=lambda node_id: False,
                       update_check_done=update_check_done, tasks_in_progress=set(), task_worker_lock=threading.Lock(),
                       PromptServer=SimpleNamespace(instance=SimpleNamespace(send_sync=lambda name, data: None)))
    namespace['task_batch_queue'] = deque([namespace['TaskBatch'](None, list(tasks), None)])
    queue_run = threading.Thread(target=lambda: asyncio.run(namespace['task_worker']()), daemon=True)
    queue_run.start()
    return order, queue_run


def run_the_queue_during_a_check(core, monkeypatch, *tasks):  # noqa: F811
    update_check_done = EndMark()
    order, queue_run = run_the_queue(core, monkeypatch, update_check_done, *tasks)
    update_check_done.queue_waits.wait(5)
    order.append('the check ends')
    update_check_done.set()
    queue_run.join()
    return order


def progress(total):
    return [{'status': 'in_progress', 'done_count': done, 'total_count': total} for done in range(1, total + 1)]


def done(updatable, *ui_ids):
    return {'status': 'done', 'updatable': sorted(updatable), 'ui_ids': sorted(ui_ids or ['the page'])}


@pytest.mark.parametrize('query', [{'mode': 'cache'}, {'mode': 'cache', 'skip_update': 'true'}],
                         ids=['without-skip_update', 'with-skip_update'])
def test_the_request_for_the_node_list_fetches_no_repository(core, custom_nodes, listed, fetched, query):  # noqa: F811
    pack(custom_nodes / 'ComfyUI-Foo', git_url=FOO_URL)
    pack(custom_nodes / 'ComfyUI-Bar', git_url=BAR_URL)
    handler = server({'fetch_customnode_list'}, core=core, populate_markdown=lambda row: None,
                     web=SimpleNamespace(json_response=lambda result, content_type: result))['fetch_customnode_list']

    rows = asyncio.run(handler(request(query=query)))['node_packs']

    assert {key: row['active_version'] for key, row in rows.items() if row['state'] == 'enabled'} == {
        'comfyui-foo': 'nightly', 'ComfyUI-Bar': 'unknown'}
    assert fetched == []


def test_a_check_fetches_the_enabled_git_nodepacks_of_the_list_once_its_request_is_answered(
        core, custom_nodes, listed, fetched):  # noqa: F811
    pack(custom_nodes / 'ComfyUI-Foo', git_url=FOO_URL)
    pack(custom_nodes / 'bar-clone', git_url=BAR_URL)
    pack(custom_nodes / '.disabled/ComfyUI-Bar')
    pack(custom_nodes / 'comfyui-baz', 'comfyui-baz', version='2.0.0', tracking=True)
    pack(custom_nodes / '.disabled/ComfyUI-Disabled', git_url=listed('ComfyUI-Disabled'))
    listed('ComfyUI-Invalid')
    pack(custom_nodes / 'ComfyUI-Invalid')
    pack(custom_nodes / 'ComfyUI-NotListed', git_url='https://github.com/example/ComfyUI-NotListed')
    fetched.answers.update({'ComfyUI-Foo': (True, True), 'bar-clone': (True, True)})

    data = check_for_updates(core, fetched)

    assert data['answer'] == {}
    assert data['fetched by the request'] == []
    assert data['fetched'] == ['ComfyUI-Foo', 'bar-clone']
    assert data['check'] == progress(2) + [done(['ComfyUI-Bar', 'comfyui-foo'])]


@pytest.mark.parametrize('shown', ['the local mode', 'https://example.invalid/a-channel'],
                         ids=['the-local-list', 'the-list-of-another-channel'])
def test_a_check_is_of_the_list_that_the_page_shows(core, custom_nodes, listed, fetched, monkeypatch, shown):  # noqa: F811
    mode = 'cache'
    if shown == 'the local mode':
        mode = 'local'
    else:
        core.get_config()['channel_url'] = shown
        monkeypatch.setattr(core, 'valid_channels', core.valid_channels | {shown})
    listed.others[shown] = [item for item in NODE_LIST if item['title'] == 'ComfyUI-Foo']
    pack(custom_nodes / 'ComfyUI-Foo', git_url=FOO_URL)
    pack(custom_nodes / 'ComfyUI-Bar', git_url=BAR_URL)

    assert check_for_updates(core, fetched, mode=mode)['fetched'] == ['ComfyUI-Foo']


def test_a_nodepack_that_cannot_be_fetched_does_not_end_the_check(core, custom_nodes, listed, fetched):  # noqa: F811
    pack(custom_nodes / 'ComfyUI-Foo', git_url=FOO_URL)
    pack(custom_nodes / 'ComfyUI-Bar', git_url=BAR_URL)
    pack(custom_nodes / 'ComfyUI-Qux', git_url=listed('ComfyUI-Qux'))
    fetched.answers.update({'ComfyUI-Foo': (True, True), 'ComfyUI-Bar': OSError('no route to the remote')})

    data = check_for_updates(core, fetched)

    assert data['fetched'] == ['ComfyUI-Bar', 'ComfyUI-Foo', 'ComfyUI-Qux']
    assert data['check'] == progress(3) + [done(['comfyui-foo'])]


def test_a_check_of_no_nodepack_ends_with_an_empty_result(core, custom_nodes, listed, fetched):  # noqa: F811
    pack(custom_nodes / 'comfyui-baz', 'comfyui-baz', version='2.0.0', tracking=True)

    data = check_for_updates(core, fetched)

    assert data['answer'] == {}
    assert data['check'] == [done([])]


def test_a_check_that_is_asked_for_while_one_runs_starts_no_second_one(core, custom_nodes, listed, fetched):  # noqa: F811
    pack(custom_nodes / 'ComfyUI-Foo', git_url=FOO_URL)
    fetched.answers['ComfyUI-Foo'] = (True, True)
    checks = Checks(core)

    assert [checks.ask_for_a_check(ui_id='a page'), checks.ask_for_a_check(ui_id='another page')] == [{}, {}]
    assert len(checks.started) == 1
    checks.started.pop()()
    assert checks.ended() == [done(['comfyui-foo'], 'a page', 'another page')]
    checks.ask_for_a_check()
    assert len(checks.started) == 1


def test_a_check_that_is_asked_for_while_one_runs_adds_the_nodepacks_that_one_does_not_have(
        core, custom_nodes, listed, fetched):  # noqa: F811
    pack(custom_nodes / 'ComfyUI-Foo', git_url=FOO_URL)
    pack(custom_nodes / 'ComfyUI-Bar', git_url=BAR_URL)
    listed.others['the local mode'] = [item for item in NODE_LIST if item['title'] == 'ComfyUI-Foo']
    fetched.answers.update({'ComfyUI-Foo': (True, True), 'ComfyUI-Bar': (True, True)})
    checks = Checks(core)

    checks.ask_for_a_check('local', ui_id='a page')
    fetched.during_a_fetch.append(lambda: checks.ask_for_a_check(ui_id='another page'))
    checks.started.pop()()

    assert fetched == ['ComfyUI-Foo', 'ComfyUI-Bar']
    assert checks.started == []
    assert [event for name, event in checks.events] == [
        {'status': 'in_progress', 'done_count': 1, 'total_count': 2},
        {'status': 'in_progress', 'done_count': 2, 'total_count': 2},
        done(['comfyui-foo', 'ComfyUI-Bar'], 'a page', 'another page')]


def test_a_request_that_comes_when_the_check_has_had_its_last_look_is_answered_by_the_next_check(
        core, custom_nodes, listed, fetched):  # noqa: F811
    pack(custom_nodes / 'ComfyUI-Foo', git_url=FOO_URL)
    pack(custom_nodes / 'ComfyUI-Bar', git_url=BAR_URL)
    listed.others['the local mode'] = [item for item in NODE_LIST if item['title'] == 'ComfyUI-Foo']
    fetched.answers.update({'ComfyUI-Foo': (True, True), 'ComfyUI-Bar': (True, True)})
    checks = Checks(core)

    checks.ask_for_a_check('local', ui_id='a page')
    checks.update_check_lock.after_the_end.append(lambda: checks.ask_for_a_check(ui_id='another page'))
    checks.started.pop()()

    first = [event for name, event in checks.events]
    assert first == progress(1) + [done(['comfyui-foo'], 'a page')]
    assert len(checks.started) == 1
    assert not checks.update_check_done.is_set()

    del fetched[:]
    checks.started.pop()()

    assert [event for name, event in checks.events[len(first):]] == progress(2) + [
        done(['comfyui-foo', 'ComfyUI-Bar'], 'another page')]
    assert sorted(fetched) == ['ComfyUI-Bar', 'ComfyUI-Foo']


def test_a_check_is_not_of_the_requests_of_the_check_before(core, custom_nodes, listed, fetched):  # noqa: F811
    pack(custom_nodes / 'ComfyUI-Foo', git_url=FOO_URL)
    pack(custom_nodes / 'ComfyUI-Bar', git_url=BAR_URL)
    listed.others['the local mode'] = [item for item in NODE_LIST if item['title'] == 'ComfyUI-Foo']
    checks = Checks(core)

    checks.ask_for_a_check(ui_id='a page')
    checks.started.pop()()
    del fetched[:]
    checks.ask_for_a_check('local', ui_id='another page')
    checks.started.pop()()

    assert fetched == ['ComfyUI-Foo']
    assert checks.ended()[-1] == done([], 'another page')


def test_a_check_whose_thread_cannot_start_does_not_stand_in_the_way_of_the_next(core, custom_nodes, listed):  # noqa: F811
    pack(custom_nodes / 'ComfyUI-Foo', git_url=FOO_URL)
    checks = Checks(core)
    started_later = checks.thread

    def no_thread(target):
        raise RuntimeError("can't start new thread")

    checks.thread = no_thread
    with pytest.raises(RuntimeError):
        checks.ask_for_a_check()
    checks.thread = started_later
    checks.ask_for_a_check()

    assert len(checks.started) == 1


def test_a_check_that_fails_tells_the_pages_that_wait_for_it_and_does_not_hold_the_tasks_of_the_queue(
        core, custom_nodes, listed, monkeypatch):  # noqa: F811
    pack(custom_nodes / 'ComfyUI-Foo', git_url=FOO_URL)

    checks = Checks(core)
    during_the_check = [lambda: checks.ask_for_a_check(ui_id='a page that asks during the check')]

    def fails(paths, on_fetched):
        if during_the_check:
            during_the_check.pop()()
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(core, 'fetch_git_node_packs', fails)

    checks.ask_for_a_check()
    checks.update_check_lock.after_the_end.append(lambda: checks.ask_for_a_check(ui_id='a page that asks after it'))
    checks.started.pop()()

    failed = [event for name, event in checks.events]
    assert failed == [{'status': 'done', 'updatable': None, 'ui_ids': ['a page that asks during the check', 'the page']}]
    assert len(checks.started) == 1

    checks.started.pop()()
    order, queue_run = run_the_queue(core, monkeypatch, checks.update_check_done, DISABLE)
    queue_run.join(5)

    assert [event for name, event in checks.events[len(failed):]] == [
        {'status': 'done', 'updatable': None, 'ui_ids': ['a page that asks after it']}]
    assert order == ['the task']


@pytest.mark.parametrize('task', [DISABLE, ('enable', ('a-row', 'comfyui-foo')), ('update-main', ('ComfyUI-Foo', 'ComfyUI-Foo', 'unknown'))],
                         ids=['disable', 'enable', 'Update-All'])
def test_a_task_of_the_queue_waits_for_the_check_that_runs(core, custom_nodes, monkeypatch, task):  # noqa: F811
    assert run_the_queue_during_a_check(core, monkeypatch, task) == ['the check ends', 'the task']


@pytest.mark.parametrize('task, work', [
    (('install-model', ('a-model', {'name': 'a', 'url': 'https://example.invalid/a.safetensors', 'filename': 'a.safetensors'})),
     'the model is downloaded'),
    (('update-comfyui', ('comfyui', False)), 'ComfyUI is updated'),
], ids=['a-model-download', 'an-update-of-ComfyUI'])
def test_a_model_download_and_an_update_of_ComfyUI_do_not_wait_for_the_check(core, custom_nodes, monkeypatch, task, work):  # noqa: F811
    assert run_the_queue_during_a_check(core, monkeypatch, task, DISABLE) == [work, 'the check ends', 'the task']


def test_the_request_that_fetched_inside_itself_is_gone(core, custom_nodes, fetched):  # noqa: F811
    pack(custom_nodes / 'ComfyUI-Foo', git_url=FOO_URL)
    handler = server({'fetch_updates'}, web=SimpleNamespace(
        json_response=lambda data, status: (status, data['deprecated'])))['fetch_updates']

    assert asyncio.run(handler(request(query={'mode': 'cache'}))) == (410, True)
    assert fetched == []
