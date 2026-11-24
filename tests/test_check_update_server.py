import pytest

from test_invalid_installation import PRELUDE
from test_install_flags_config import _run_child

CHECK = '''
import queue, threading, traceback

fetched = []
answers = {}
during_a_fetch = []

def fetch(path):
    name = pathlib.Path(path).name
    fetched.append(name)
    if during_a_fetch:
        during_a_fetch.pop()()
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

class Lock:
    def __init__(self):
        self.held = threading.Lock()
        self.after_the_end = []

    def __enter__(self):
        self.held.acquire()

    def __exit__(self, *error):
        self.held.release()
        if self.after_the_end and update_check_done.is_set():
            self.after_the_end.pop()()

class EndMark(threading.Event):
    def __init__(self):
        super().__init__()
        self.queue_waits = threading.Event()

    def wait(self):
        self.queue_waits.set()
        super().wait()

events = []
update_check_done = EndMark()
update_check_done.set()
update_check_lock = Lock()
update_check_paths = {}
update_check_ui_ids = set()
started = []

def sent(name, data):
    events.append([name, {key: sorted(value) if isinstance(value, list) else value for key, value in data.items()}])

def started_later(target):
    return SimpleNamespace(start=lambda: started.append(target))

def ask_for_a_check(mode='cache', ui_id='the page', thread=started_later):
    ask = server_function(
        'check_update', core=core, update_check_done=update_check_done, update_check_lock=update_check_lock,
        update_check_paths=update_check_paths, update_check_ui_ids=update_check_ui_ids, traceback=traceback,
        threading=SimpleNamespace(Thread=lambda target: thread(target)),
        _reject_non_json_content_type=lambda request: None, web=SimpleNamespace(json_response=lambda data: data),
        PromptServer=SimpleNamespace(instance=SimpleNamespace(send_sync=sent)))
    return asyncio.run(ask(request(body={'mode': mode, 'ui_id': ui_id})))

def check_for_updates(mode='cache', ui_id='the page'):
    answer = ask_for_a_check(mode, ui_id)
    fetched_by_the_request = list(fetched)
    started.pop()()
    return {'answer': answer, 'fetched by the request': fetched_by_the_request, 'fetched': sorted(fetched),
            'check': [event for name, event in events if name == 'cm-check-update']}

DISABLE = ('disable', ('a-row', 'ComfyUI-Foo', False))

def run_the_queue(*tasks):
    order = []
    config['model_download_by_agent'] = True
    core.update_path = lambda path: order.append('ComfyUI is updated') or 'skipped'
    manager.unified_disable = lambda node_name, is_unknown: order.append('the task') or True
    manager.unified_update = lambda node_name, node_ver: order.append('the task') or SimpleNamespace(ver='unknown', result=True, action='skip')
    task_queue = queue.Queue()
    for task in tasks:
        task_queue.put(task)
    worker = server_function(
        'task_worker', core=core, logging=logging, traceback=traceback, queue=queue, task_queue=task_queue,
        update_check_done=update_check_done, nodepack_result={}, model_result={}, tasks_in_progress=set(),
        task_worker_lock=threading.Lock(), os=os, folder_paths=SimpleNamespace(__file__=str(nodes.parent / 'folder_paths.py')),
        get_model_path=lambda data: str(nodes.parent / data['filename']),
        download_url_with_agent=lambda url, path: order.append('the model is downloaded') or True,
        manager_util=SimpleNamespace(clear_pip_cache=lambda: None),
        PromptServer=SimpleNamespace(instance=SimpleNamespace(send_sync=lambda name, data: None)))
    queue_run = threading.Thread(target=lambda: asyncio.run(worker()), daemon=True)
    queue_run.start()
    return order, queue_run

def run_the_queue_during_a_check(*tasks):
    update_check_done.clear()
    order, queue_run = run_the_queue(*tasks)
    update_check_done.queue_waits.wait(5)
    order.append('the check ends')
    update_check_done.set()
    queue_run.join()
    return order
'''


def run(body):
    return _run_child(PRELUDE + CHECK + body)


def progress(total):
    return [{'status': 'in_progress', 'done_count': done, 'total_count': total} for done in range(1, total + 1)]


def done(updatable, *ui_ids):
    return {'status': 'done', 'updatable': sorted(updatable), 'ui_ids': sorted(ui_ids or ['the page'])}


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
    assert data['check'] == progress(2) + [done(['ComfyUI-Bar', 'comfyui-foo'])]


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
    assert data['check'] == progress(3) + [done(['comfyui-foo'])]


def test_a_check_of_no_nodepack_ends_with_an_empty_result():
    data = run('''
pack('comfyui-baz', 'comfyui-baz', version='2.0.0', tracking=True)
emit(check_for_updates())
''')
    assert data['answer'] == {}
    assert data['check'] == [done([])]


def test_a_check_that_is_asked_for_while_one_runs_starts_no_second_one():
    data = run('''
pack('ComfyUI-Foo', git_url=FOO_URL)
answers['ComfyUI-Foo'] = (True, True)
answered = [ask_for_a_check(ui_id='a page'), ask_for_a_check(ui_id='another page')]
running = len(started)
started.pop()()
ended = [event for name, event in events if event['status'] == 'done']
ask_for_a_check()
emit({'answered': answered, 'running': running, 'ended': ended, 'started after the end': len(started)})
''')
    assert data == {'answered': [{}, {}], 'running': 1, 'ended': [done(['comfyui-foo'], 'a page', 'another page')],
                    'started after the end': 1}


def test_a_check_that_is_asked_for_while_one_runs_adds_the_nodepacks_that_one_does_not_have():
    data = run('''
pack('ComfyUI-Foo', git_url=FOO_URL)
pack('ComfyUI-Bar', git_url=BAR_URL)
other_lists['the local mode'] = [item for item in NODE_LIST if item['title'] == 'ComfyUI-Foo']
answers.update({'ComfyUI-Foo': (True, True), 'ComfyUI-Bar': (True, True)})
ask_for_a_check('local', ui_id='a page')
during_a_fetch.append(lambda: ask_for_a_check(ui_id='another page'))
started.pop()()
emit({'fetched': fetched, 'started': len(started), 'check': [event for name, event in events]})
''')
    assert data == {'fetched': ['ComfyUI-Foo', 'ComfyUI-Bar'], 'started': 0, 'check': [
        {'status': 'in_progress', 'done_count': 1, 'total_count': 2},
        {'status': 'in_progress', 'done_count': 2, 'total_count': 2},
        done(['comfyui-foo', 'ComfyUI-Bar'], 'a page', 'another page')]}


def test_a_request_that_comes_when_the_check_has_had_its_last_look_is_answered_by_the_next_check():
    data = run('''
pack('ComfyUI-Foo', git_url=FOO_URL)
pack('ComfyUI-Bar', git_url=BAR_URL)
other_lists['the local mode'] = [item for item in NODE_LIST if item['title'] == 'ComfyUI-Foo']
answers.update({'ComfyUI-Foo': (True, True), 'ComfyUI-Bar': (True, True)})
ask_for_a_check('local', ui_id='a page')
update_check_lock.after_the_end.append(lambda: ask_for_a_check(ui_id='another page'))
started.pop()()
first = [event for name, event in events]
checks_started, a_check_runs = len(started), not update_check_done.is_set()
del fetched[:]
if started:
    started.pop()()
emit({'first': first, 'checks started': checks_started, 'a check runs': a_check_runs, 'next': [event for name, event in events[len(first):]],
      'fetched by the next': sorted(fetched)})
''')
    assert data == {'first': progress(1) + [done(['comfyui-foo'], 'a page')], 'checks started': 1, 'a check runs': True,
                    'next': progress(2) + [done(['comfyui-foo', 'ComfyUI-Bar'], 'another page')],
                    'fetched by the next': ['ComfyUI-Bar', 'ComfyUI-Foo']}


def test_a_check_is_not_of_the_requests_of_the_check_before():
    data = run('''
pack('ComfyUI-Foo', git_url=FOO_URL)
pack('ComfyUI-Bar', git_url=BAR_URL)
other_lists['the local mode'] = [item for item in NODE_LIST if item['title'] == 'ComfyUI-Foo']
check_for_updates(ui_id='a page')
del fetched[:]
emit(check_for_updates('local', ui_id='another page'))
''')
    assert data['fetched'] == ['ComfyUI-Foo']
    assert data['check'][-1] == done([], 'another page')


def test_a_check_whose_thread_cannot_start_does_not_stand_in_the_way_of_the_next():
    data = run('''
pack('ComfyUI-Foo', git_url=FOO_URL)

def no_thread(target):
    raise RuntimeError("can't start new thread")

try:
    ask_for_a_check(thread=no_thread)
except RuntimeError:
    pass
ask_for_a_check()
emit(len(started))
''')
    assert data == 1


def test_a_check_that_fails_tells_the_pages_that_wait_for_it_and_does_not_hold_the_tasks_of_the_queue():
    data = run('''
pack('ComfyUI-Foo', git_url=FOO_URL)
during_the_check = [lambda: ask_for_a_check(ui_id='a page that asks during the check')]

def fails(paths, on_fetched):
    if during_the_check:
        during_the_check.pop()()
    raise RuntimeError("can't start new thread")

core.fetch_git_node_packs = fails
ask_for_a_check()
update_check_lock.after_the_end.append(lambda: ask_for_a_check(ui_id='a page that asks after it'))
started.pop()()
failed = [event for name, event in events]
checks_started = len(started)
if started:
    started.pop()()
order, queue_run = run_the_queue(DISABLE)
queue_run.join(5)
emit({'failed': failed, 'checks started': checks_started, 'next': [event for name, event in events[len(failed):]], 'order': order})
''')
    assert data == {'failed': [{'status': 'done', 'updatable': None, 'ui_ids': ['a page that asks during the check', 'the page']}],
                    'checks started': 1,
                    'next': [{'status': 'done', 'updatable': None, 'ui_ids': ['a page that asks after it']}],
                    'order': ['the task']}


@pytest.mark.parametrize('task', [('disable', ('a-row', 'ComfyUI-Foo', False)), ('update-main', ('ComfyUI-Foo', 'ComfyUI-Foo', 'unknown'))],
                         ids=['disable', 'Update-All'])
def test_a_task_of_the_queue_waits_for_the_check_that_runs(task):
    assert run(f'emit(run_the_queue_during_a_check({task!r}))') == ['the check ends', 'the task']


@pytest.mark.parametrize('task, work', [
    (('install-model', ('a-model', {'name': 'a', 'url': 'https://example.invalid/a.safetensors', 'filename': 'a.safetensors'})),
     'the model is downloaded'),
    (('update-comfyui', ('comfyui', False)), 'ComfyUI is updated'),
], ids=['a-model-download', 'an-update-of-ComfyUI'])
def test_a_model_download_and_an_update_of_ComfyUI_do_not_wait_for_the_check(task, work):
    assert run(f'emit(run_the_queue_during_a_check({task!r}, DISABLE))') == [work, 'the check ends', 'the task']


def test_the_request_that_fetched_inside_itself_is_gone():
    data = run('''
pack('ComfyUI-Foo', git_url=FOO_URL)
handler = server_function('fetch_updates', _reject_non_json_content_type=lambda request: None,
                          web=SimpleNamespace(json_response=lambda data, status: [status, data['deprecated']]))
emit({'answer': asyncio.run(handler(request(body={'mode': 'cache'}))), 'fetched': fetched})
''')
    assert data == {'answer': [410, True], 'fetched': []}
