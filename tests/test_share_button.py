import os
from pathlib import Path

import pytest

from test_grid_highlight_escaping import browser  # noqa: F401 -- fixture

JS = Path(os.environ.get("MANAGER_JS_DIR") or (Path(__file__).resolve().parent.parent / "js"))
EXTENSION = "http://manager.test/extensions/comfyui-manager/"

ANSWERS = {
    "/manager/db_mode": "cache",
    "/manager/channel_url_list": {"list": ["default::https://example.invalid/channel"], "selected": "default"},
}

MENUS = {
    "top bar": '<header id="topbar"></header><div class="comfy-menu" style="display: none"></div>',
    "old menu": '<div class="comfy-menu"></div>',
}

STAND_INS = {
    "scripts/api.js": """
        class Api extends EventTarget {
            async fetchApi(path, options) {
                const answer = window.answers[path.split('?')[0]] ?? '';
                if(options?.method == 'POST' && path == '/manager/share_option') {
                    window.saved = JSON.parse(options.body).value;
                }
                return {status: 200, json: async () => answer, text: async () => typeof answer == 'string' ? answer : JSON.stringify(answer)};
            }
        }
        export const api = new Api();
    """,
    "scripts/app.js": """
        import { ComfyDialog } from './ui.js';
        const settingsGroup = {element: document.createElement('div')};
        export const app = {
            ui: {dialog: new ComfyDialog()},
            graph: new (class { clear() {} })(),
            menu: {element: document.createElement('div'), settingsGroup},
            graphToPrompt: async () => ({}),
            registerExtension(extension) { window.extension = extension; },
        };
        app.graph._nodes = [];
        app.menu.element.append(settingsGroup.element);
    """,
    "scripts/ui.js": """
        const style = document.createElement('style');
        style.textContent = '.comfy-modal { display: none; position: fixed; z-index: 100; top: 50%; left: 50%; transform: translate(-50%, -50%); padding: 20px; background: #353535; color: #ddd; }';
        document.head.append(style);

        export function $el(tag, propsOrChildren, children) {
            const [name, ...classes] = tag.split('.');
            const element = document.createElement(name);
            element.classList.add(...classes);
            if(typeof propsOrChildren == 'string') {
                propsOrChildren = {textContent: propsOrChildren};
            }
            else if(Array.isArray(propsOrChildren) || propsOrChildren instanceof Element) {
                children = propsOrChildren;
                propsOrChildren = {};
            }
            const {parent, $: callback, dataset, style, ...props} = propsOrChildren ?? {};
            Object.assign(element.style, style);
            Object.assign(element.dataset, dataset);
            Object.assign(element, props);
            if(children) {
                element.append(...[children].flat());
            }
            parent?.append(element);
            callback?.(element);
            return element;
        }

        export class ComfyDialog {
            constructor() {
                this.element = $el('div.comfy-modal', {parent: document.body}, [
                    $el('div.comfy-modal-content', [
                        $el('p', {$: (p) => (this.textElement = p)}),
                        $el('button', {type: 'button', textContent: 'Close', onclick: () => this.close()}),
                    ]),
                ]);
            }

            close() {
                this.element.style.display = 'none';
            }

            show(html) {
                this.textElement.innerHTML = html;
                this.element.style.display = 'flex';
            }
        }
    """,
    "scripts/ui/components/button.js": """
        const style = document.createElement('style');
        style.textContent = '.comfyui-button { display: flex; }';
        document.head.append(style);

        export class ComfyButton {
            constructor({icon, tooltip, content, action, classList = 'comfyui-button'}) {
                this.element = document.createElement('button');
                this.element.className = classList;
                this.element.title = tooltip;
                this.element.setAttribute('aria-label', tooltip);
                this.element.textContent = content ?? icon;
                this.element.addEventListener('click', (event) => action(event, this));
            }
        }
    """,
    "scripts/ui/components/buttonGroup.js": """
        export class ComfyButtonGroup {
            constructor(...buttons) {
                this.element = document.createElement('div');
                this.element.className = 'comfyui-button-group';
                this.element.append(...buttons);
            }
        }
    """,
    "extensions/core/groupNode.js": """
        export class GroupNodeConfig {}
        export class GroupNodeHandler {}
    """,
}


@pytest.fixture
def page(browser):  # noqa: F811
    page = browser.new_page()

    def route(request):
        url = request.request.url
        name = url.rsplit("/", 1)[-1]
        stand_in = url.removeprefix("http://manager.test/")
        if url == "http://manager.test/":
            request.fulfill(body="<body></body>", content_type="text/html")
        elif url.startswith(EXTENSION) and (JS / name).is_file():
            request.fulfill(path=str(JS / name), content_type="text/css" if name.endswith(".css") else "text/javascript")
        elif stand_in in STAND_INS:
            request.fulfill(body=STAND_INS[stand_in], content_type="text/javascript")
        else:
            request.abort()

    page.route("**/*", route)
    page.add_init_script("""
        window.errors = [];
        addEventListener('error', (event) => errors.push(String(event.error ?? event.message)));
        addEventListener('unhandledrejection', (event) => errors.push(String(event.reason)));
    """)
    page.goto("http://manager.test/")
    yield page
    page.close()


def load(page, menu, share_option):
    page.evaluate("""async ({module, body, answers, share_option}) => {
        document.body.innerHTML = body;
        window.answers = {...answers, '/manager/share_option': share_option};
        await import(module);
        window.extension.init();
        await window.extension.setup();
        const { app } = await import('/scripts/app.js');
        document.getElementById('topbar')?.append(app.menu.element);
    }""", {"module": EXTENSION + "comfyui-manager.js", "body": MENUS[menu], "answers": ANSWERS, "share_option": share_option})


def share_buttons(page):
    return page.get_by_role("button", name="Share", exact=True)


def choose_share(page, value):
    page.evaluate("window.extension.commands.find((command) => command.id == 'Comfy.Manager.Menu.ToggleVisibility').function()")
    page.locator(".setting-item", has=page.get_by_text("Share", exact=True)).locator("select").select_option(value)
    page.wait_for_function("window.saved == '%s'" % value)
    page.get_by_role("button", name="Close", exact=True).first.click()


@pytest.mark.parametrize("menu", MENUS)
@pytest.mark.parametrize("share_option", ["all", "youml", "matrix", "none"])
def test_the_share_button_of_the_menu_follows_the_saved_share_setting(page, menu, share_option):
    load(page, menu, share_option)

    assert share_buttons(page).count() == (0 if share_option == "none" else 1)
    assert page.evaluate("errors") == []


@pytest.mark.parametrize("menu", MENUS)
def test_choosing_none_in_the_manager_menu_hides_the_share_button_and_all_shows_it(page, menu):
    load(page, menu, "all")

    choose_share(page, "none")
    assert share_buttons(page).count() == 0

    choose_share(page, "all")
    assert share_buttons(page).count() == 1
    assert page.evaluate("errors") == []


@pytest.mark.parametrize("menu", MENUS)
@pytest.mark.parametrize("share_option, opened", [
    ("all", "Choose a platform to share your workflow"),
    ("youml", "Share your workflow to YouML.com"),
    ("matrix", "No supported output node found"),
], ids=["all", "youml", "matrix"])
def test_a_click_on_the_share_button_opens_what_the_share_setting_says(page, menu, share_option, opened):
    page.evaluate("window.alert = (message) => { window.alerted = message; }")
    load(page, menu, share_option)

    share_buttons(page).click()

    page.wait_for_function("""(opened) => window.alerted?.includes(opened)
        || [...document.querySelectorAll('.comfy-modal')].some((box) => box.checkVisibility() && box.innerText.includes(opened))""", arg=opened)
    assert page.evaluate("errors") == []
