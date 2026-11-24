import os
from pathlib import Path

import pytest

from test_grid_highlight_escaping import browser  # noqa: F401 -- fixture

JS = Path(os.environ.get("MANAGER_JS_DIR") or (Path(__file__).resolve().parent.parent / "js"))
EXTENSION = "http://manager.test/extensions/comfyui-manager/"

SAVED = {"homeserver": "matrix.org", "username": "user"}
ASK_FOR_ACCOUNT = "Please set your Matrix account details."

SCRIPTS = {
    "api.js": """
        export const api = {
            addEventListener() {},
            async fetchApi(path, options) {
                window.requested.push({path, method: options?.method ?? 'GET', body: options?.body ? JSON.parse(options.body) : null});
                if(path == '/manager/get_matrix_auth') {
                    if(window.offline) throw new TypeError('Failed to fetch');
                    if(window.saved) return {status: 200, json: async () => window.saved};
                    return {status: 404, json: async () => { throw new SyntaxError('Unexpected end of JSON input'); }};
                }
                return {status: 200, json: async () => ({matrix: {success: true}})};
            }
        };
    """,
    "app.js": """
        const image = {filename: 'a.png', subfolder: '', type: 'output'};
        export const app = {
            graph: {_nodes: [{type: 'SaveImage', id: 1, title: 'Save Image', images: [image]}]},
            graphToPrompt: async () => ({workflow: {}, output: {}}),
            ui: {dialog: {element: document.body, show() {}}},
        };
    """,
    "ui.js": """
        export function $el(tag, props, children) {
            const names = tag.split('.');
            const element = document.createElement(names.shift());
            element.classList.add(...names);
            const {parent, style, ...rest} = props ?? {};
            Object.assign(element.style, style);
            Object.assign(element, rest);
            element.append(...(children ?? []));
            parent?.append(element);
            return element;
        }
        export class ComfyDialog {
            close() { this.element.style.display = 'none'; }
        }
    """,
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
    page.alerts = []
    page.on("pageerror", lambda error: page.errors.append(str(error)))
    page.on("dialog", lambda dialog: (page.alerts.append(dialog.message), dialog.dismiss()))
    page.goto("http://manager.test/")
    yield page
    page.close()


def open_dialog(page, saved, offline=False):
    page.evaluate("""async ({saved, offline, module}) => {
        window.requested = [];
        window.saved = saved;
        window.offline = offline;
        const { ShareDialog, getPotentialOutputsAndOutputNodes } = await import(module);
        const { app } = await import('/scripts/app.js');
        window.dialog = new ShareDialog();
        window.dialog.show(getPotentialOutputsAndOutputNodes(app.graph._nodes));
    }""", {"saved": saved, "offline": offline, "module": EXTENSION + "comfyui-share-common.js"})
    page.wait_for_timeout(200)


def fields(page):
    return page.evaluate("""() => ({
        homeserver: dialog.matrix_homeserver_input.value,
        username: dialog.matrix_username_input.value,
        password: dialog.matrix_password_input.value,
    })""")


def share_to_matrix(page, matrix=True, **typed):
    page.evaluate("""async ({typed, matrix}) => {
        for(const [name, value] of Object.entries(typed)) {
            dialog[`matrix_${name}_input`].value = value;
        }
        dialog.matrix_destination_checkbox.checked = matrix;
        await dialog.share_button.onclick();
    }""", {"typed": typed, "matrix": matrix})
    page.wait_for_timeout(200)


def shared(page):
    return [request["body"]["matrix_auth"] for request in page.evaluate("window.requested")
            if request["path"] == "/manager/share"]


def test_the_saved_account_is_shown_without_its_password(page):
    open_dialog(page, SAVED)

    assert fields(page) == {**SAVED, "password": ""}
    assert "Saved password" in page.evaluate("dialog.matrix_password_input.placeholder")
    assert page.errors == []


def test_the_saved_account_is_shared_with_an_empty_password(page):
    open_dialog(page, SAVED)

    share_to_matrix(page)

    assert shared(page) == [{**SAVED, "password": ""}]
    assert page.alerts == []
    assert page.errors == []


def test_another_account_needs_a_password(page):
    open_dialog(page, SAVED)

    share_to_matrix(page, username="someone-else")

    assert page.alerts == [ASK_FOR_ACCOUNT]
    assert shared(page) == []


def test_the_homeserver_cannot_be_typed(page):
    open_dialog(page, SAVED)

    assert page.evaluate("dialog.matrix_homeserver_input.readOnly") is True
    assert fields(page)["homeserver"] == "matrix.org"


@pytest.mark.parametrize("homeserver", ["other.example", "https://matrix.org", "", None],
                         ids=["another homeserver", "matrix.org with a scheme", "empty", "null"])
def test_a_saved_homeserver_does_not_reach_the_field_or_the_request(page, homeserver):
    open_dialog(page, {"homeserver": homeserver, "username": "user"})
    assert fields(page) == {"homeserver": "matrix.org", "username": "user", "password": ""}

    share_to_matrix(page)

    assert shared(page) == [{"homeserver": "matrix.org", "username": "user", "password": ""}]
    assert page.errors == []


def test_a_typed_password_is_sent(page):
    open_dialog(page, SAVED)

    share_to_matrix(page, username="someone-else", password="a new password")

    assert shared(page) == [{"homeserver": "matrix.org", "username": "someone-else", "password": "a new password"}]
    assert page.alerts == []


def test_without_a_saved_account_a_password_is_needed(page):
    open_dialog(page, None)
    assert fields(page) == {"homeserver": "matrix.org", "username": "", "password": ""}
    assert page.evaluate("dialog.matrix_password_input.placeholder") == "Password"

    share_to_matrix(page, username="user")

    assert page.alerts == [ASK_FOR_ACCOUNT]
    assert shared(page) == []
    assert page.errors == []


def test_the_account_that_was_shared_is_the_saved_one_afterwards(page):
    open_dialog(page, SAVED)
    share_to_matrix(page, username="someone-else", password="a new password")

    share_to_matrix(page, username="user", password="")
    assert page.alerts == [ASK_FOR_ACCOUNT]

    share_to_matrix(page, username="someone-else", password="")
    assert shared(page)[1:] == [{"homeserver": "matrix.org", "username": "someone-else", "password": ""}]


def test_a_field_changed_and_changed_back_is_the_saved_account(page):
    open_dialog(page, SAVED)

    share_to_matrix(page, username="someone-else")
    share_to_matrix(page, username="user")

    assert page.alerts == [ASK_FOR_ACCOUNT]
    assert shared(page) == [{**SAVED, "password": ""}]


def test_the_saved_account_that_cannot_be_read_is_no_saved_account(page):
    open_dialog(page, SAVED, offline=True)
    assert fields(page) == {"homeserver": "matrix.org", "username": "", "password": ""}

    share_to_matrix(page, username="user")

    assert page.alerts == [ASK_FOR_ACCOUNT]
    assert shared(page) == []
    assert page.errors == []


def test_sharing_without_matrix_needs_no_account(page):
    open_dialog(page, None)

    share_to_matrix(page, matrix=False)

    assert page.alerts == []
    assert page.evaluate("window.requested.at(-1).body.share_destinations") == []
