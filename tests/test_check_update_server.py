import pytest

from test_invalid_installation import PRELUDE
from test_install_flags_config import _run_child

CHECK = '''
import queue, threading, traceback

fetched = []
answers = {}

def fetch(path):
    name = pathlib.Path(path).name
    fetched.append(name)
    if isinstance(answers.get(name), Exception):
        raise answers[name]
    return answers.get(name, (False, True))

core.git_repo_update_check_with = fetch
core.get_channel_dict = lambda: {'default': core.DEFAULT_CHANNEL}

other_lists = {}

async def get_data_by_mode(mode, filename, channel_url=None):
    node_list = other_lists.get('the local mode' if mode == 'local' else channel_url, NODE_LIST)
    return {'custom-node-list.json': {'custom_nodes': [dict(item) for item in node_list]},
            'extras.json': {'favorites': []}}.get(filename, {})

core.get_data_by_mode = get_data_by_mode

def listed(name):
    url = f'https://github.com/example/{name}'
    NODE_LIST.append({'author': 'example', 'title': name, 'reference': url, 'files': [url],
                      'install_type': 'git-clone', 'description': ''})
    return url

def request(query=None, body=None):
    async def json_body():
        return body
    return SimpleNamespace(rel_url=SimpleNamespace(query=query), json=json_body)

def node_list(query):
    handler = server_function('fetch_customnode_list', core=core, populate_markdown=lambda row: None,
                              web=SimpleNamespace(json_response=lambda result, content_type: result))
    return asyncio.run(handler(request(query=query)))['node_packs']

events = []
update_check_done = threading.Event()
update_check_done.set()
started = []

def ask_for_a_check(mode='cache'):
    ask = server_function(
        'check_update', core=core, update_check_done=update_check_done,
        threading=SimpleNamespace(Thread=lambda target: SimpleNamespace(start=lambda: started.append(target))),
        _reject_non_json_content_type=lambda request: None, web=SimpleNamespace(json_response=lambda data: data),
        PromptServer=SimpleNamespace(instance=SimpleNamespace(send_sync=lambda name, data: events.append([name, data]))))
    return asyncio.run(ask(request(body={'mode': mode})))

def check_for_updates(mode='cache'):
    answer = ask_for_a_check(mode)
    fetched_by_the_request = list(fetched)
    started.pop()()
    return {'answer': answer, 'fetched by the request': fetched_by_the_request, 'fetched': sorted(fetched),
            'check': [event for name, event in events if name == 'cm-check-update']}
'''


def run(body):
    return _run_child(PRELUDE + CHECK + body)


def progress(total):
    return [{'status': 'in_progress', 'done_count': done, 'total_count': total} for done in range(1, total + 1)]


@pytest.mark.parametrize('query', [{'mode': 'cache'}, {'mode': 'cache', 'skip_update': 'true'}],
                         ids=['without-skip_update', 'with-skip_update'])
def test_the_request_for_the_node_list_fetches_no_repository(query):
    data = run(f'''
pack('ComfyUI-Foo', git_url=FOO_URL)
pack('ComfyUI-Bar', git_url=BAR_URL)
rows = node_list({query!r})
emit({{'installed': {{key: row['active_version'] for key, row in rows.items() if row['state'] == 'enabled'}}, 'fetched': fetched}})
''')
    assert data == {'installed': {'comfyui-foo': 'nightly', 'ComfyUI-Bar': 'unknown'}, 'fetched': []}


def test_a_check_fetches_the_enabled_git_nodepacks_of_the_list_once_its_request_is_answered():
    data = run('''
pack('ComfyUI-Foo', git_url=FOO_URL)
pack('bar-clone', git_url=BAR_URL)
pack('.disabled/ComfyUI-Bar')
pack('comfyui-baz', 'comfyui-baz', version='2.0.0', tracking=True)
pack('.disabled/ComfyUI-Disabled', git_url=listed('ComfyUI-Disabled'))
listed('ComfyUI-Invalid')
pack('ComfyUI-Invalid')
pack('ComfyUI-NotListed', git_url='https://github.com/example/ComfyUI-NotListed')
answers.update({'ComfyUI-Foo': (True, True), 'bar-clone': (True, True)})
emit(check_for_updates())
''')
    assert data['answer'] == {}
    assert data['fetched by the request'] == []
    assert data['fetched'] == ['ComfyUI-Foo', 'bar-clone']
    assert data['check'][:-1] == progress(2)
    assert sorted(data['check'][-1].pop('updatable')) == ['ComfyUI-Bar', 'comfyui-foo']
    assert data['check'][-1] == {'status': 'done'}


@pytest.mark.parametrize('shown', [
    "mode = 'local'; listed_under = 'the local mode'",
    "config['channel_url'] = listed_under = 'https://example.invalid/a-channel'; core.valid_channels.add(listed_under)",
], ids=['the-local-list', 'the-list-of-another-channel'])
def test_a_check_is_of_the_list_that_the_page_shows(shown):
    data = run(f'''
mode = 'cache'
{shown}
other_lists[listed_under] = [item for item in NODE_LIST if item['title'] == 'ComfyUI-Foo']
pack('ComfyUI-Foo', git_url=FOO_URL)
pack('ComfyUI-Bar', git_url=BAR_URL)
emit(check_for_updates(mode=mode))
''')
    assert data['fetched'] == ['ComfyUI-Foo']


def test_a_nodepack_that_cannot_be_fetched_does_not_end_the_check():
    data = run('''
pack('ComfyUI-Foo', git_url=FOO_URL)
pack('ComfyUI-Bar', git_url=BAR_URL)
pack('ComfyUI-Qux', git_url=listed('ComfyUI-Qux'))
answers.update({'ComfyUI-Foo': (True, True), 'ComfyUI-Bar': OSError('no route to the remote')})
emit(check_for_updates())
''')
    assert data['fetched'] == ['ComfyUI-Bar', 'ComfyUI-Foo', 'ComfyUI-Qux']
    assert data['check'] == progress(3) + [{'status': 'done', 'updatable': ['comfyui-foo']}]


def test_a_check_of_no_nodepack_ends_with_an_empty_result():
    data = run('''
pack('comfyui-baz', 'comfyui-baz', version='2.0.0', tracking=True)
emit(check_for_updates())
''')
    assert data['answer'] == {}
    assert data['check'] == [{'status': 'done', 'updatable': []}]


def test_a_check_that_is_asked_for_while_one_runs_starts_no_second_one():
    data = run('''
pack('ComfyUI-Foo', git_url=FOO_URL)
answers['ComfyUI-Foo'] = (True, True)
answered = [ask_for_a_check(), ask_for_a_check()]
running = len(started)
started.pop()()
ended = [event for name, event in events if event['status'] == 'done']
ask_for_a_check()
emit({'answered': answered, 'running': running, 'ended': ended, 'started after the end': len(started)})
''')
    assert data == {'answered': [{}, {}], 'running': 1, 'ended': [{'status': 'done', 'updatable': ['comfyui-foo']}],
                    'started after the end': 1}


def test_a_task_of_the_queue_waits_for_the_check_that_runs():
    data = run('''
order = []
manager.unified_disable = lambda node_name, is_unknown: order.append('the task') or True
task_queue = queue.Queue()
task_queue.put(('disable', ('a-row', 'ComfyUI-Foo', False)))
worker = server_function(
    'task_worker', core=core, logging=logging, traceback=traceback, queue=queue, task_queue=task_queue,
    update_check_done=update_check_done, nodepack_result={}, model_result={}, tasks_in_progress=set(),
    task_worker_lock=threading.Lock(),
    PromptServer=SimpleNamespace(instance=SimpleNamespace(send_sync=lambda name, data: None)))
update_check_done.clear()
queue_run = threading.Thread(target=lambda: asyncio.run(worker()))
queue_run.start()
queue_run.join(0.5)
order.append('the check ends')
update_check_done.set()
queue_run.join()
emit(order)
''')
    assert data == ['the check ends', 'the task']


def test_the_request_that_fetched_inside_itself_is_gone():
    data = run('''
pack('ComfyUI-Foo', git_url=FOO_URL)
handler = server_function('fetch_updates', _reject_non_json_content_type=lambda request: None,
                          web=SimpleNamespace(json_response=lambda data, status: [status, data['deprecated']]))
emit({'answer': asyncio.run(handler(request(body={'mode': 'cache'}))), 'fetched': fetched})
''')
    assert data == {'answer': [410, True], 'fetched': []}
