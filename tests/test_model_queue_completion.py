"""The Model Manager ends its pending install when its own queue ends.

The server reports the end of every queue with two dicts, `nodepack_result` and
`model_result`, keyed by the id of each task. A queue that ends with model results ends
the install and reports them. A queue that ends without one is another one's while tasks
are left, and leaves the install pending with its Stop button in place. With no task
left, the install is over without a result, as when a node pack queue ends after a model
install request was refused, and the dialog returns to idle without reporting anything.

The cases run the shipped `onQueueStatus` and `onQueueCompleted` of model-manager.js in
node, against a stand-in for the dialog that records what the handlers do to it and a
stand-in for `/manager/queue/status`. The last cases run `installModels` as well, with a
queue that is still running when the request that started it is answered, and with one
that has ended before.
"""
import json
import os
from pathlib import Path

import pytest

from js_lift import NODE, JsSource, run_node, slice_braced

JS = JsSource(Path(os.environ.get("MANAGER_JS_DIR") or (Path(__file__).resolve().parent.parent / "js")))

pytestmark = pytest.mark.skipif(NODE is None, reason="node is required to execute the lifted production JS")

OTHER_QUEUE = {"status": "done", "nodepack_result": {"pack": "success"}, "model_result": {}}
REFRESH = "To apply the installed model, please click the 'Refresh' button."


DOWNLOADING = {"total_count": 2, "done_count": 0, "in_progress_count": 1, "is_processing": True}
NOTHING_LEFT = {"total_count": 0, "done_count": 0, "in_progress_count": 0, "is_processing": False}
# the server keeps the model results of the queue before until the next one is started
EARLIER_RESULTS_ONLY = {"total_count": 1, "done_count": 1, "in_progress_count": 0, "is_processing": False}


def run(events, queue_status=DOWNLOADING, install_started_while_asking=False):
    """Queue two models, deliver `events`, and return what the handlers did after each one.

    `queue_status` is what the server answers when it is asked what is left in the queue.
    With `install_started_while_asking`, another install becomes the pending one before
    that answer arrives."""
    source = JS.text("model-manager.js")
    script = """
        %s
        const calls = [];
        const self = {
            install_context: {
                btn: {classList: {remove: () => calls.push('button idle')}},
                targets: [{hash: 'model-a'}, {hash: 'model-b'}],
            },
            grid: {updateCell: (item) => calls.push('cell ' + item.hash)},
            hideLoading() {},
            hideStop: () => calls.push('stop hidden'),
            showRefresh: () => calls.push('refresh shown'),
            showStatus: (text) => calls.push('status: ' + text),
            showError: (text) => calls.push('error: ' + text),
            showMessage: (text) => calls.push('message: ' + text),
            %s,
            %s,
        };
        const ModelManager = {instance: self};
        const api = {fetchApi: async (path) => {
            calls.push('asked ' + path);
            if(%s) {
                self.install_context = {
                    btn: {classList: {remove: () => calls.push('button of the new install idle')}},
                    targets: [{hash: 'model-c'}],
                };
            }
            return {json: async () => (%s)};
        }};
        const show_message = (text) => calls.push('dialog: ' + text);
        const infoToast = () => calls.push('toast');

        const steps = [];
        for(const detail of %s) {
            calls.length = 0;
            await self.onQueueStatus({detail});
            // onQueueStatus does not wait for the completion, which may ask the server first
            await new Promise((resolve) => setTimeout(resolve));
            steps.push({pending: self.install_context !== undefined, calls: [...calls]});
        }
        console.log(JSON.stringify(steps));
    """ % (
        JS.lift_declaration("common.js", "export function sanitizeHTML("),
        slice_braced(source, "async onQueueStatus(event)"),
        slice_braced(source, "async onQueueCompleted(info)"),
        json.dumps(install_started_while_asking),
        json.dumps(queue_status),
        json.dumps(events),
    )
    return run_node(script)


@pytest.mark.parametrize("event", [
    OTHER_QUEUE,
    {"status": "done", "nodepack_result": {"pack": "success"}},
])
def test_queue_without_a_model_result_leaves_the_install_pending(event):
    assert run([event]) == [{"pending": True, "calls": ["asked /manager/queue/status"]}]


@pytest.mark.parametrize("queue_status", [NOTHING_LEFT, EARLIER_RESULTS_ONLY])
def test_install_that_ends_without_a_result_returns_to_idle(queue_status):
    assert run([OTHER_QUEUE], queue_status=queue_status) == [{"pending": False, "calls": [
        "asked /manager/queue/status", "stop hidden", "button idle", "cell model-a", "cell model-b",
    ]}]


def test_install_started_while_the_server_is_asked_stays_pending():
    assert run([OTHER_QUEUE], queue_status=NOTHING_LEFT, install_started_while_asking=True) == [
        {"pending": True, "calls": ["asked /manager/queue/status"]},
    ]


def test_queue_with_the_model_results_ends_the_install():
    own_queue = {"status": "done", "nodepack_result": {},
                 "model_result": {"model-a": "success", "model-b": "success"}}

    other, own = run([OTHER_QUEUE, own_queue])

    assert other == {"pending": True, "calls": ["asked /manager/queue/status"]}
    assert own == {"pending": False, "calls": [
        "stop hidden", "button idle", "cell model-a", "cell model-b",
        "status: Install 2 models successfully", "refresh shown", "message: " + REFRESH, "toast",
    ]}


def test_failed_download_is_reported_as_text():
    failure = "Model installation error: <b>https://example.invalid/a.safetensors</b>"
    escaped = "Model installation error: &lt;b&gt;https://example.invalid/a.safetensors&lt;/b&gt;\n"

    (step,) = run([{"status": "done", "nodepack_result": {},
                    "model_result": {"model-a": failure, "model-b": "success"}}])

    assert step["pending"] is False
    assert "error: " + escaped in step["calls"]
    assert "dialog: Installation Error:\n" + escaped in step["calls"]
    assert not [call for call in step["calls"] if call.startswith("status: ")]


def install(queue_ends_before_the_start_is_answered):
    """Install one model, and return whether the install is pending and the Stop button shown."""
    source = JS.text("model-manager.js")
    script = """
        %s
        let stop_shown = false;
        const self = {
            grid: {scrollRowIntoView() {}, updateCell() {}},
            focusInstall: () => true,
            hideLoading() {},
            showStop: () => { stop_shown = true; },
            hideStop: () => { stop_shown = false; },
            showRefresh() {}, showStatus() {}, showError() {}, showMessage() {},
            %s,
            %s,
            %s,
        };
        const ModelManager = {instance: self};
        const api = {fetchApi: async (path) => {
            if(path == '/manager/queue/status') {
                return {json: async () => ({is_processing: false, total_count: 0, done_count: 0})};
            }
            if(path == '/manager/queue/start' && %s) {
                // a download that fails at once: the queue ends while the request is on its way
                await self.onQueueStatus({detail: {
                    status: 'done', nodepack_result: {}, model_result: {'model-a': 'download failed'},
                }});
            }
            return {status: 200};
        }};
        const show_message = () => {};
        const showTerminal = () => {};
        const infoToast = () => {};

        const button = {classList: {add() {}, remove() {}}};
        await self.installModels([{hash: 'model-a', name: 'a', originalData: {}}], button);
        console.log(JSON.stringify({pending: self.install_context !== undefined, stop_shown}));
    """ % (
        JS.lift_declaration("common.js", "export function sanitizeHTML("),
        slice_braced(source, "async installModels(list, btn)"),
        slice_braced(source, "async onQueueStatus(event)"),
        slice_braced(source, "async onQueueCompleted(info)"),
        json.dumps(queue_ends_before_the_start_is_answered),
    )
    return run_node(script)


def test_started_install_is_pending_with_its_stop_button():
    assert install(queue_ends_before_the_start_is_answered=False) == {"pending": True, "stop_shown": True}


def test_queue_that_ends_before_its_start_is_answered_leaves_no_stop_button():
    assert install(queue_ends_before_the_start_is_answered=True) == {"pending": False, "stop_shown": False}
