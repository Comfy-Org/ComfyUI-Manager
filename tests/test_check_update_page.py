import json
import os
import re
from pathlib import Path

import pytest

from js_lift import NODE, JsSource, run_node, slice_braced

JS = JsSource(Path(os.environ.get("MANAGER_JS_DIR") or (Path(__file__).resolve().parent.parent / "js")))

pytestmark = pytest.mark.skipif(NODE is None, reason="node is required to execute the lifted production JS")

REGISTERED = re.compile(r'api\.addEventListener\("(cm-check-update|reconnected)", this\.(\w+)\);')

ROWS = {
    "git-a": {"state": "enabled", "version": "nightly"},
    "git-b": {"state": "enabled", "version": "unknown"},
    "versioned-with-update": {"state": "enabled", "version": "1.0.0", "update-state": "true"},
}
TAKEN = {"data": {}}
CHECK = 'POST /customnode/check_update {"mode":"cache","ui_id":"check-1"}'
LIST = "GET /customnode/getlist?mode=cache&skip_update=true"
LOADING, LOADED = "loading", "loading ended"
WAIT = "status: Checking updates ..."


def run(steps, check_answers=(TAKEN,), ends_before_the_answer=None):
    source = JS.text("custom-nodes-manager.js")
    registered = list(REGISTERED.finditer(source))
    script = """
        console.log = () => {};
        globalThis.window = {};
        %(sanitize_html)s
        %(show_mode)s;
        const calls = [];
        const updateFilter = {value: ShowMode.UPDATE, hasData: false};
        const self = {
            filterList: [updateFilter],
            restartMap: {},
            element: {querySelector: () => ({})},
            getFilterItem: (value) => value === ShowMode.UPDATE ? updateFilter : undefined,
            loadNodes: async () => {},
            showLoading: () => calls.push('loading'),
            hideLoading: () => calls.push('loading ended'),
            showStatus: (text) => calls.push('status: ' + text),
            showError: (text) => calls.push('error: ' + text),
            renderGrid() {
                const updatable = Object.values(this.custom_nodes).filter((row) => row.action === 'updatable');
                calls.push('shown as updatable: ' + updatable.map((row) => row.key).join(' '));
            },
            %(load_data)s,
            %(check_update)s,
            %(ask_for_check)s,
            %(listeners)s,
        };
        const CustomNodesManager = {instance: self};
        const manager_instance = {datasrc_combo: {value: 'cache'}};
        const md5 = (text) => 'hash of ' + text;
        let asked = 0;
        const generateUUID = () => 'check-' + (++asked);
        const infoToast = () => calls.push('toast');
        const heard = {};
        const api = {addEventListener: (name, listener) => { heard[name] = listener; }};
        (function() { %(registrations)s }).call(self);
        const checkAnswers = %(check_answers)s;
        const answeredLater = [];
        const fetchData = async (route, options = {}) => {
            calls.push((options.method ?? 'GET') + ' ' + route + (options.body ? ' ' + options.body : ''));
            if(!route.endsWith('/check_update')) {
                return {data: {channel: 'default', node_packs: structuredClone(%(rows)s)}};
            }
            if(%(ends_before_the_answer)s) {
                heard['cm-check-update']({detail: %(ends_before_the_answer)s});
            }
            const answer = checkAnswers.length > 1 ? checkAnswers.shift() : checkAnswers[0];
            return answer == 'later' ? new Promise((resolve) => answeredLater.push(resolve)) : answer;
        };

        const settle = async () => {
            for(let i = 0; i < 20; i++) {
                await new Promise((resolve) => setTimeout(resolve));
            }
        };
        const done = [];
        for(const [kind, value] of %(steps)s) {
            calls.length = 0;
            if(kind == 'load') {
                self.loadData(value);
            }
            else if(kind == 'answer') {
                answeredLater.shift()(value);
            }
            else {
                await heard[kind]?.({detail: value});
            }
            await settle();
            done.push([...calls]);
        }
        process.stdout.write(JSON.stringify({steps: done, update_filter: Object.keys(updateFilter.hashMap ?? {})}));
    """ % {
        "sanitize_html": JS.lift_declaration("common.js", "export function sanitizeHTML("),
        "show_mode": slice_braced(source, "const ShowMode = "),
        "load_data": slice_braced(source, "async loadData(show_mode = ShowMode.NORMAL)"),
        "check_update": slice_braced(source, "async checkUpdate(mode)"),
        "ask_for_check": slice_braced(source, "async askForCheck(mode)"),
        "listeners": ",".join(slice_braced(source, re.search(r"\n\t(async )?%s\(" % found.group(2), source).group(0))
                              for found in registered),
        "registrations": "\n".join(found.group(0) for found in registered),
        "check_answers": json.dumps(check_answers),
        "ends_before_the_answer": json.dumps(ends_before_the_answer),
        "rows": json.dumps(ROWS),
        "steps": json.dumps(steps),
    }
    return run_node(script)


def progress(done_count):
    return ["cm-check-update", {"status": "in_progress", "done_count": done_count, "total_count": 2}]


def result(*updatable, of="check-1"):
    return ["cm-check-update", {"status": "done", "updatable": list(updatable), "ui_ids": ["of another page", of]}]


RECONNECTED = ["reconnected", None]


def test_check_update_asks_for_the_check_and_loads_the_list_when_it_has_ended():
    data = run([["load", "Update"], progress(1), progress(2), result("git-b")])

    asked, first, second, ended = data["steps"]
    assert asked == [LOADING, "toast", WAIT, CHECK]
    assert first == ["status: Checking updates (1/2) ..."]
    assert second == ["status: Checking updates (2/2) ..."]
    assert ended == ["status: Loading custom nodes (cache) ...", LIST, "shown as updatable: git-b versioned-with-update", LOADED]
    assert data["update_filter"] == ["hash of git-b", "hash of versioned-with-update"]


def test_a_check_that_ends_before_the_request_for_it_is_answered_is_not_missed():
    data = run([["load", "Update"]], ends_before_the_answer=result("git-b")[1])

    assert data["steps"] == [[LOADING, "toast", WAIT, CHECK, "status: Loading custom nodes (cache) ...", LIST,
                              "shown as updatable: git-b versioned-with-update", LOADED]]


def test_a_check_that_finds_no_update_shows_the_list():
    data = run([["load", "Update"], result()])

    assert data["steps"][1] == ["status: Loading custom nodes (cache) ...", LIST,
                                "shown as updatable: versioned-with-update", LOADED]


def test_a_nodepack_that_left_the_list_during_the_check_is_passed_over():
    data = run([["load", "Update"], result("git-b", "uninstalled-meanwhile")])

    assert data["steps"][1][-2:] == ["shown as updatable: git-b versioned-with-update", LOADED]


def test_the_end_of_a_check_that_does_not_answer_this_page_is_passed_over():
    data = run([["load", "Update"], result("git-a", of="of a third page"), result("git-b")])

    assert data["steps"][1:] == [[], ["status: Loading custom nodes (cache) ...", LIST,
                                      "shown as updatable: git-b versioned-with-update", LOADED]]


def test_a_check_that_is_asked_for_again_waits_for_its_own_end():
    data = run([["load", "Update"], ["load", "Update"], result("git-a"), result("git-b", of="check-2")])

    assert data["steps"][1] == [LOADING, "toast", WAIT, CHECK.replace("check-1", "check-2")]
    assert data["steps"][2:] == [[], ["status: Loading custom nodes (cache) ...", LIST,
                                      "shown as updatable: git-b versioned-with-update", LOADED]]


def test_a_check_that_failed_ends_the_loading_with_an_error():
    data = run([["load", "Update"], ["cm-check-update", {"status": "done", "updatable": None, "ui_ids": ["check-1"]}]])

    assert data["steps"][1] == ["error: Failed to check updates.", LOADED]


def test_the_list_alone_asks_for_no_check():
    data = run([["load", "Normal"]])

    assert data["steps"] == [[LOADING, "status: Loading custom nodes (cache) ...", LIST,
                              "shown as updatable: versioned-with-update", LOADED]]


@pytest.mark.parametrize("answer", [{"status": 400, "error": "Bad Request"}, {"status": 404, "error": "Not Found"}],
                         ids=["refused", "a-server-without-the-check"])
def test_a_check_that_the_server_does_not_take_ends_the_loading_with_an_error(answer):
    data = run([["load", "Update"], progress(1), result("git-b")], check_answers=[answer])

    assert data["steps"] == [[LOADING, "toast", WAIT, CHECK, "error: Failed to check updates.", LOADED], [], []]


def test_a_connection_that_came_back_during_the_check_asks_for_the_check_again():
    data = run([["load", "Update"], progress(1), RECONNECTED, result("git-b")])

    assert data["steps"][2:] == [[CHECK], ["status: Loading custom nodes (cache) ...", LIST,
                                           "shown as updatable: git-b versioned-with-update", LOADED]]


def test_a_check_that_the_server_does_not_take_after_the_connection_came_back_ends_the_loading_with_an_error():
    data = run([["load", "Update"], RECONNECTED, result("git-b")], check_answers=[TAKEN, {"status": 404, "error": "Not Found"}])

    assert data["steps"][1:] == [[CHECK, "error: Failed to check updates.", LOADED], []]


def test_the_late_failure_of_an_earlier_request_does_not_end_the_check_that_was_asked_for_after_it():
    data = run([["load", "Update"], ["load", "Update"], ["answer", {"status": 400, "error": "Bad Request"}],
                result("git-b", of="check-2")], check_answers=["later", TAKEN])

    assert data["steps"][2:] == [[], ["status: Loading custom nodes (cache) ...", LIST,
                                      "shown as updatable: git-b versioned-with-update", LOADED]]


def test_a_check_that_ends_after_another_list_was_opened_leaves_that_list():
    data = run([["load", "Update"], ["load", "Normal"], result("git-b")])

    assert data["steps"][1][-2:] == ["shown as updatable: versioned-with-update", LOADED]
    assert data["steps"][2] == []


@pytest.mark.parametrize("before", [[["load", "Normal"]], [["load", "Update"], result("git-a")]],
                         ids=["it-asked-for-none", "its-own-has-ended"])
def test_the_events_of_a_check_this_page_did_not_wait_for_change_nothing(before):
    data = run([*before, progress(1), result("git-b"), RECONNECTED])

    assert data["steps"][-3:] == [[], [], []]
