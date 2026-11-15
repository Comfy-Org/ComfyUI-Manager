"""A disabled node pack that another extension asks for is enabled, and then ComfyUI restarts.

An extension asks through `cm.try-install-custom-node` for a node pack it needs. When the pack is
disabled, the user is asked whether to enable it and restart. The pack is enabled as the Enable
button of the Custom Nodes Manager does: it is found in the node list, put in the queue, and the
queue is awaited. ComfyUI restarts only after the queue reports success.

The cases run the shipped cm-api.js and common.js in Chromium against stand-ins for ComfyUI's
scripts; no ComfyUI server is used. The stand-in for the API answers each route as the case
says and records the requests.

Browser cases require Playwright and its Chromium install.
"""
import hashlib
import os
from pathlib import Path

import pytest

from test_grid_highlight_escaping import browser  # noqa: F401 -- fixture

JS = Path(os.environ.get("MANAGER_JS_DIR") or (Path(__file__).resolve().parent.parent / "js"))
EXTENSION = "http://manager.test/extensions/comfyui-manager/"

STATUS = "/manager/queue/status"
GETLIST = "/customnode/getlist"
RESET = "/manager/queue/reset"
INSTALL = "/manager/queue/install"
START = "/manager/queue/start"
REBOOT = "/manager/reboot"
ENABLE = [("GET", GETLIST), ("GET", STATUS), ("POST", RESET), ("POST", INSTALL), ("POST", START)]

URL = "https://github.com/someone/Other-Pack"
# The entry of custom-node-list.json that the server sends with the request
TARGET = {"title": "Other Pack", "installed": "Disabled", "files": [URL], "id": "listed-id"}
# The node list as /customnode/getlist answers it: rows by key
PACKS = {
    "another-pack": {"id": "another-pack", "title": "Another Pack", "version": "1.0.0", "state": "disabled",
                     "files": ["https://github.com/someone/Another-Pack"]},
    "from-the-registry": {"id": "from-the-registry", "title": "No Files", "version": "1.0.0", "state": "disabled"},
    "other-pack": {"id": "other-pack", "title": "Other Pack", "version": "nightly", "state": "disabled",
                   "files": [URL], "repository": URL},
}
UI_ID = hashlib.md5(b"other-pack").hexdigest()

SCRIPTS = {
    # `window.answers[route]` says how a route answers: `status`, `json`, `fails` for a request that
    # gets no answer, and for the install route `result`, which the queue reports for the pack:
    # `during` the install request, as for a pack from the registry, or after the queue is started.
    # As the server does, the queue reports once more when it is started with nothing in it. A
    # report of an earlier run arrives before the pack is queued. With `silent`, no report of the
    # started queue reaches the page.
    "api.js": """
        class Api extends EventTarget {
            report(detail) {
                this.dispatchEvent(new CustomEvent('cm-queue-status', {detail}));
            }

            async fetchApi(path, options) {
                const route = path.split('?')[0];
                const answer = window.answers[route] ?? {};
                const body = options?.body ? JSON.parse(options.body) : null;
                window.requested.push({path, method: options?.method ?? 'GET', body});
                if(answer.fails) {
                    throw new TypeError('Failed to fetch');
                }
                const nothing = () => this.report({status: 'done', nodepack_result: {}, model_result: {}});
                if(route == '/manager/queue/reset') {
                    nothing();
                }
                if(answer.result !== undefined) {
                    const report = () => {
                        this.report({status: 'in_progress', target: body.ui_id, ui_target: 'nodepack_manager'});
                        this.report({status: 'done', nodepack_result: {[body.ui_id]: answer.result}, model_result: {}});
                    };
                    if(answer.during) report(); else this.reportWhenStarted = report;
                }
                if(route == '/manager/queue/start' && !window.answers['/manager/queue/install'].silent) {
                    setTimeout(this.reportWhenStarted ?? nothing, 50);
                }
                return {status: answer.status ?? 200, json: async () => answer.json, text: async () => ''};
            }
        }
        export const api = new Api();
    """,
    # `show_message` in common.js and the handler show their text in this dialog.
    "app.js": """
        const element = document.createElement('div');
        element.id = 'comfy-dialog';
        document.body.append(element);
        export const app = {ui: {dialog: {element, show(html) { element.innerHTML = html; }}}};
    """,
    "ui.js": "export const $el = () => null; export class ComfyDialog {}",
}


@pytest.fixture
def page(browser):  # noqa: F811
    page = browser.new_page()

    def route(request):
        url = request.request.url
        name = url.rsplit("/", 1)[-1]
        if url == "http://manager.test/":
            request.fulfill(body="<body></body>", content_type="text/html")
        elif url.startswith(EXTENSION) and (JS / name).is_file():
            request.fulfill(path=str(JS / name), content_type="text/javascript")
        elif url == "http://manager.test/scripts/" + name and name in SCRIPTS:
            request.fulfill(body=SCRIPTS[name], content_type="text/javascript")
        else:
            request.abort()

    page.route("**/*", route)
    page.errors = []
    page.on("pageerror", lambda error: page.errors.append(str(error)))
    page.goto("http://manager.test/")
    yield page
    page.close()


def answers(install=None, reboot=None, packs=PACKS, getlist=None, status=None):
    """How the routes answer; by default the pack is listed as disabled, is enabled, and the restart is accepted."""
    return {
        STATUS: {"json": {"is_processing": False}} if status is None else status,
        GETLIST: {"json": {"channel": "default", "node_packs": packs}} if getlist is None else getlist,
        INSTALL: {"result": "success"} if install is None else install,
        REBOOT: {} if reboot is None else reboot,
    }


def ask(page, answers, target=TARGET):
    """Deliver the request an extension makes for `target`."""
    page.evaluate("""async ({answers, target, module}) => {
        window.requested = [];
        window.answers = answers;
        await import(module);
        const { api } = await import('/scripts/api.js');
        api.dispatchEvent(new CustomEvent('cm-api-try-install-customnode', {detail: {
            sender: 'Some Pack', msg: 'needed for the detector nodes', target,
        }}));
    }""", {"answers": answers, "target": target, "module": EXTENSION + "cm-api.js"})


def confirm(page):
    """Confirm the dialog that asks whether to enable the pack and restart."""
    question = page.get_by_text("Would you like to enable it and reboot?")
    question.wait_for()
    assert "'Some Pack' extension requires the installation of the 'Other Pack' extension" in question.inner_text()
    page.get_by_role("button", name="Confirm").click()


def shown(page, text):
    page.locator("#comfy-dialog").get_by_text(text).wait_for(timeout=5000)


def requested(page):
    return [(request["method"], request["path"].split("?")[0]) for request in page.evaluate("window.requested")]


def test_the_pack_is_enabled_through_the_queue_and_then_comfyui_restarts(page):
    ask(page, answers())
    confirm(page)

    shown(page, "Rebooting...")
    assert requested(page) == ENABLE + [("POST", REBOOT)]
    assert page.evaluate("window.requested[0].path") == GETLIST + "?mode=cache&skip_update=true"
    # what the Enable button of the Custom Nodes Manager sends for this row
    assert page.evaluate("window.requested[3].body") == {**PACKS["other-pack"], "channel": "default", "mode": "cache",
                                                          "ui_id": UI_ID, "skip_post_install": True}
    assert page.errors == []


def test_a_report_that_arrives_while_the_install_request_is_handled_is_not_missed(page):
    ask(page, answers(install={"result": "success", "during": True}))
    confirm(page)

    shown(page, "Rebooting...")
    assert requested(page) == ENABLE + [("POST", REBOOT)]


def test_the_restart_is_announced_when_the_server_restarts_without_answering(page):
    ask(page, answers(reboot={"fails": True}))
    confirm(page)

    shown(page, "Rebooting...")
    assert page.errors == []


def test_a_refused_restart_is_reported(page):
    ask(page, answers(reboot={"status": 403}))
    confirm(page)

    shown(page, "This action is not allowed with this security level configuration.")
    assert requested(page)[-1] == ("POST", REBOOT)
    assert page.errors == []


@pytest.mark.parametrize("install, reason, requests", [
    ({"status": 403}, "This action is not allowed with this security level configuration.", ENABLE[:4]),
    ({"status": 404}, "The request was refused (404). Please check the terminal log.", ENABLE[:4]),
    ({"result": "Cannot resolve install target: 'other-pack@None'"},
     "Cannot resolve install target: 'other-pack@None'", ENABLE),
    ({}, "The queue finished without this node pack. Please try again.", ENABLE),
], ids=["not allowed at this security level", "refused", "failed in the queue", "gone from the queue"])
def test_comfyui_does_not_restart_when_the_pack_was_not_enabled(page, install, reason, requests):
    ask(page, answers(install=install))
    confirm(page)

    shown(page, "Failed to enable 'Other Pack'.")
    shown(page, reason)
    page.wait_for_timeout(300)
    assert requested(page) == requests
    assert page.errors == []


def test_the_wait_ends_when_no_report_reaches_the_page(page):
    page.clock.install()
    ask(page, answers(install={"silent": True}))
    confirm(page)
    shown(page, "Enabling... 'Other Pack'")

    page.clock.fast_forward(59000)
    assert "Failed to enable" not in page.locator("#comfy-dialog").inner_text()
    page.clock.fast_forward(2000)
    shown(page, "Failed to enable 'Other Pack'.")
    shown(page, "The queue did not report the result.")

    # a later report for the same row, as its Disable in the Custom Nodes Manager sends
    page.evaluate("""async (ui_id) => {
        const { api } = await import('/scripts/api.js');
        api.report({status: 'done', nodepack_result: {[ui_id]: 'success'}, model_result: {}});
    }""", UI_ID)
    page.clock.fast_forward(1000)
    assert requested(page) == ENABLE
    assert page.errors == []


def test_a_queue_that_is_running_is_left_alone(page):
    ask(page, answers(status={"json": {"is_processing": True}}))
    confirm(page)

    shown(page, "Failed to enable 'Other Pack'.")
    shown(page, "There are already tasks in progress.")
    page.wait_for_timeout(300)
    assert requested(page) == ENABLE[:2]
    assert page.errors == []


@pytest.mark.parametrize("packs", [
    {**PACKS, "other-pack": {**PACKS["other-pack"], "state": "enabled"}},
    {key: pack for key, pack in PACKS.items() if key != "other-pack"},
], ids=["listed as enabled", "not listed"])
def test_a_pack_that_the_node_list_does_not_have_as_disabled_is_not_queued(page, packs):
    ask(page, answers(packs=packs))
    confirm(page)

    shown(page, "Failed to enable 'Other Pack'.")
    shown(page, "Please enable it in the Custom Nodes Manager.")
    page.wait_for_timeout(300)
    assert requested(page) == ENABLE[:1]
    assert page.errors == []


def test_a_node_list_that_cannot_be_read_is_reported(page):
    ask(page, answers(getlist={"status": 500}))
    confirm(page)

    shown(page, "Failed to get the custom node list (500).")
    page.wait_for_timeout(300)
    assert requested(page) == ENABLE[:1]


@pytest.mark.parametrize("failing, requests", [
    ({"getlist": {"fails": True}}, ENABLE[:1]),
    ({"install": {"fails": True}}, ENABLE[:4]),
], ids=["the node list", "the install request"])
def test_a_request_that_gets_no_answer_is_reported(page, failing, requests):
    ask(page, answers(**failing))
    confirm(page)

    shown(page, "Failed to enable 'Other Pack'.")
    shown(page, "Failed to fetch")
    page.wait_for_timeout(300)
    assert requested(page) == requests
    assert page.errors == []


def test_text_from_the_node_list_and_the_queue_is_shown_as_text(page):
    markup = '<img src="/bad.png" onerror="window.__probe=1">'
    target = {**TARGET, "title": "Other " + markup}
    ask(page, answers(install={"result": "failed " + markup}), target)
    page.get_by_text("Would you like to enable it and reboot?").wait_for()
    page.get_by_role("button", name="Confirm").click()

    shown(page, "failed " + markup)
    assert "Failed to enable 'Other " + markup + "'." in page.locator("#comfy-dialog").inner_text()
    assert page.locator("#comfy-dialog img").count() == 0
    assert page.evaluate("window.__probe === undefined")


def test_nothing_is_requested_when_the_user_declines(page):
    ask(page, answers())
    page.get_by_text("Would you like to enable it and reboot?").wait_for()
    page.get_by_role("button", name="Cancel").click()

    page.wait_for_timeout(500)
    assert requested(page) == []
    assert page.locator("#comfy-dialog").inner_text() == ""


def test_a_pack_that_is_installed_but_did_not_load_is_only_reported(page):
    alerts = []
    page.on("dialog", lambda dialog: (alerts.append(dialog.message), dialog.dismiss()))

    ask(page, answers(), {**TARGET, "installed": "True"})

    page.wait_for_timeout(500)
    assert len(alerts) == 1
    assert "it seems that the extension is in an import-fail state" in alerts[0]
    assert requested(page) == []
