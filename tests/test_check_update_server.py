import ast
import asyncio
import logging
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


@pytest.fixture
def fetched(core, custom_nodes, monkeypatch):  # noqa: F811
    names = Fetched()
    names.answers = answers = {}

    def fetch(path):
        name = Path(path).name
        names.append(name)
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


class Checks:
    def __init__(self, core):  # noqa: F811
        self.events = []
        self.started = []
        self.update_check_done = threading.Event()
        self.update_check_done.set()
        self.ask = server(
            {'check_update'}, core=core, update_check_done=self.update_check_done,
            threading=SimpleNamespace(Thread=lambda target: SimpleNamespace(start=lambda: self.started.append(target))),
            manager_security=SimpleNamespace(reject_non_json_post=lambda request: None),
            web=SimpleNamespace(json_response=lambda data: data),
            PromptServer=SimpleNamespace(instance=SimpleNamespace(
                send_sync=lambda name, data: self.events.append((name, data)))))['check_update']

    def ask_for_a_check(self, mode='cache'):
        return asyncio.run(self.ask(request(body={'mode': mode})))

    def ended(self):
        return [event for name, event in self.events if event['status'] == 'done']


def check_for_updates(core, fetched, mode='cache'):  # noqa: F811
    checks = Checks(core)
    answer = checks.ask_for_a_check(mode)
    fetched_by_the_request = list(fetched)
    checks.started.pop()()
    return {'answer': answer, 'fetched by the request': fetched_by_the_request, 'fetched': sorted(fetched),
            'check': [event for name, event in checks.events if name == 'cm-check-update']}


def progress(total):
    return [{'status': 'in_progress', 'done_count': done, 'total_count': total} for done in range(1, total + 1)]


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
    assert data['check'][:-1] == progress(2)
    assert sorted(data['check'][-1].pop('updatable')) == ['ComfyUI-Bar', 'comfyui-foo']
    assert data['check'][-1] == {'status': 'done'}


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
    assert data['check'] == progress(3) + [{'status': 'done', 'updatable': ['comfyui-foo']}]


def test_a_check_of_no_nodepack_ends_with_an_empty_result(core, custom_nodes, listed, fetched):  # noqa: F811
    pack(custom_nodes / 'comfyui-baz', 'comfyui-baz', version='2.0.0', tracking=True)

    data = check_for_updates(core, fetched)

    assert data['answer'] == {}
    assert data['check'] == [{'status': 'done', 'updatable': []}]


def test_a_check_that_is_asked_for_while_one_runs_starts_no_second_one(core, custom_nodes, listed, fetched):  # noqa: F811
    pack(custom_nodes / 'ComfyUI-Foo', git_url=FOO_URL)
    fetched.answers['ComfyUI-Foo'] = (True, True)
    checks = Checks(core)

    assert [checks.ask_for_a_check(), checks.ask_for_a_check()] == [{}, {}]
    assert len(checks.started) == 1
    checks.started.pop()()
    assert checks.ended() == [{'status': 'done', 'updatable': ['comfyui-foo']}]
    checks.ask_for_a_check()
    assert len(checks.started) == 1


def test_a_task_of_the_queue_waits_for_the_check_that_runs(core, custom_nodes, monkeypatch):  # noqa: F811
    order = []
    monkeypatch.setattr(core.unified_manager, 'unified_disable', lambda node_name, is_unknown: order.append('the task') or True)
    update_check_done = threading.Event()
    namespace = server({'task_worker', 'TaskBatch'}, core=core, logging=logging, traceback=traceback,
                       update_check_done=update_check_done, tasks_in_progress=set(), task_worker_lock=threading.Lock(),
                       PromptServer=SimpleNamespace(instance=SimpleNamespace(send_sync=lambda name, data: None)))
    namespace['task_batch_queue'] = deque([namespace['TaskBatch'](None, [('disable', ('a-row', 'ComfyUI-Foo', False))], None)])
    queue_run = threading.Thread(target=lambda: asyncio.run(namespace['task_worker']()))

    queue_run.start()
    queue_run.join(0.5)
    order.append('the check ends')
    update_check_done.set()
    queue_run.join()

    assert order == ['the check ends', 'the task']


def test_the_request_that_fetched_inside_itself_is_gone(core, custom_nodes, fetched):  # noqa: F811
    pack(custom_nodes / 'ComfyUI-Foo', git_url=FOO_URL)
    handler = server({'fetch_updates'}, web=SimpleNamespace(
        json_response=lambda data, status: (status, data['deprecated'])))['fetch_updates']

    assert asyncio.run(handler(request(query={'mode': 'cache'}))) == (410, True)
    assert fetched == []
