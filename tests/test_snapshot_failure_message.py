"""The Snapshot Manager says why restoring or removing a snapshot failed.

For an answer that is not a success, the message names the snapshot and the reason, both
as text. The reason is the server's text when the answer is plain text, which is how the
server gives one, and otherwise the status line: most refusals carry no text, and a proxy
answers with a page of markup. A restart is asked for only after a restore that the
server accepted.

The cases run the shipped `restore_snapshot` and `remove_snapshot` of snapshot.js in node,
with a stand-in for the API that answers as the case says and stand-ins for the dialog
that record what the handlers do.
"""
import json
import os
from pathlib import Path

import pytest

from js_lift import NODE, JsSource, run_node, slice_braced

JS = JsSource(Path(os.environ.get("MANAGER_JS_DIR") or (Path(__file__).resolve().parent.parent / "js")))

pytestmark = pytest.mark.skipif(NODE is None, reason="node is required to execute the lifted production JS")

NAME = "2026-01-01_00-00-00_<b>snapshot</b>"
ESCAPED_NAME = "2026-01-01_00-00-00_&lt;b&gt;snapshot&lt;/b&gt;"
PROXY_PAGE = "<html><body><h1>502 Bad Gateway</h1><hr><center>nginx</center></body></html>"
FORBIDDEN = "message: This action is not allowed with this security level configuration."


def run(action, status, body="", content_type=None, status_text="", fails=False):
    """Click Restore or Remove on the snapshot NAME; return what the handler did."""
    source = JS.text("snapshot.js")
    helper = slice_braced(source, "async function failureReason(response)") if "function failureReason" in source else ""
    answer = {"status": status, "statusText": status_text,
              "headers": {"Content-Type": content_type} if content_type else {}}
    script = """
        %s
        %s
        const calls = [];
        const api = {fetchApi: async () => {
            if(%s) {
                throw new TypeError('Failed to fetch');
            }
            // a body is not allowed with every status, so the text is given by hand
            const response = new Response(null, %s);
            response.text = async () => %s;
            response.json = async () => JSON.parse(%s);
            return response;
        }};
        const show_message = (text) => calls.push('message: ' + text);
        const handle403Response = async (response, text) => show_message(
            text || 'This action is not allowed with this security level configuration.');
        const app = {ui: {dialog: {close: () => calls.push('dialog closed')}}};
        const SnapshotManager = {instance: {
            invalidateControl: async () => calls.push('list refreshed'),
            updateMessage: () => calls.push('restart asked'),
        }};
        %s
        %s
        const handlers = {Restore: restore_snapshot, Remove: remove_snapshot};
        await handlers[%s](%s);
        console.log(JSON.stringify(calls));
    """ % (
        JS.lift_declaration("common.js", "export function sanitizeHTML("), helper,
        json.dumps(fails), json.dumps(answer), json.dumps(body), json.dumps(body or "{}"),
        slice_braced(source, "async function restore_snapshot(target)"),
        slice_braced(source, "async function remove_snapshot(target)"),
        json.dumps(action), json.dumps(NAME),
    )
    return run_node(script)


REFUSALS = [
    pytest.param(400, "", None, "Bad Request", "HTTP 400 Bad Request", id="400 without text"),
    pytest.param(400, "Invalid <i>target</i>", "text/plain; charset=utf-8", "Bad Request",
                 "Invalid &lt;i&gt;target&lt;/i&gt;", id="400 with a reason"),
    pytest.param(502, PROXY_PAGE, "text/html", "Bad Gateway", "HTTP 502 Bad Gateway", id="502 with the page of a proxy"),
    pytest.param(500, "", None, "", "HTTP 500", id="500 without a status text"),
]


@pytest.mark.parametrize("action", ["Restore", "Remove"])
@pytest.mark.parametrize("status, body, content_type, status_text, reason", REFUSALS)
def test_refused_request_names_the_snapshot_and_the_reason(action, status, body, content_type, status_text, reason):
    calls = run(action, status, body, content_type, status_text)

    assert calls == ["message: %s snapshot failed: %s / %s" % (action, ESCAPED_NAME, reason), "list refreshed"]


@pytest.mark.parametrize("action", ["Restore", "Remove"])
def test_request_without_an_answer_names_the_snapshot(action):
    calls = run(action, 0, fails=True)

    assert calls == ["message: %s snapshot failed: %s / TypeError: Failed to fetch" % (action, ESCAPED_NAME),
                     "list refreshed"]


@pytest.mark.parametrize("action", ["Restore", "Remove"])
def test_request_refused_by_the_security_level_asks_for_no_restart(action):
    assert run(action, 403, status_text="Forbidden") == [FORBIDDEN, "list refreshed"]


def test_accepted_restore_asks_for_a_restart():
    assert run("Restore", 200, status_text="OK") == ["dialog closed", "list refreshed", "restart asked"]


def test_accepted_removal_asks_for_none():
    assert run("Remove", 200, status_text="OK") == ["dialog closed", "list refreshed"]
