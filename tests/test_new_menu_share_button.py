"""The Share button of the new-style menu follows the Share setting, at start and when it is changed.

The button group is built by the shipped lines of setup() and the setting is changed through the
shipped change handler of the Share combo, both lifted from comfyui-manager.js. The ComfyUI frontend
components they import and the DOM are stubs.
"""
import json
import os
from pathlib import Path

import pytest

from js_lift import NODE, JsSource, run_node, slice_braced

JS = JsSource(Path(os.environ.get("MANAGER_JS_DIR") or (Path(__file__).resolve().parent.parent / "js")))
MENU = "comfyui-manager.js"
CHOICES = ["all", "none", "youml", "matrix"]

pytestmark = pytest.mark.skipif(NODE is None, reason="node is required to execute the lifted production JS")


def share_button_shown(initial, *changes):
    """Whether the new menu shows a Share button after setup(), then after each change of the setting."""
    menu_group = JS.lift_span(MENU, "// new style Manager buttons", "app.menu?.settingsGroup.element.before(cmGroup.element);")
    for module in ("button.js", "buttonGroup.js"):
        menu_group = menu_group.replace('await import("../../scripts/ui/components/%s")' % module, "components")
    change_handler = slice_braced(JS.text(MENU), "share_combo.addEventListener('change', function (event) ") + ");"
    script = """
        const element = (tagName) => ({tagName, id: '', title: '', style: {}, children: []});
        const components = {
            ComfyButton: class { constructor(options) { this.element = element('BUTTON'); this.element.title = options.tooltip; } },
            ComfyButtonGroup: class { constructor(...buttons) { this.element = element('DIV'); this.element.children = buttons; } },
        };
        const find = (nodes, test) => {
            for (const node of nodes) {
                const found = test(node) ? node : find(node.children, test);
                if (found) return found;
            }
            return null;
        };
        const legacyShareButton = element('BUTTON');
        legacyShareButton.id = 'shareButton';
        const menuGroups = [];
        const document = {getElementById: (id) => find([legacyShareButton, ...menuGroups], (node) => node.id === id)};
        const app = {menu: {settingsGroup: {element: {before: (node) => menuGroups.push(node)}}}};
        const api = {fetchApi: async () => ({})};
        const listeners = {};
        const share_combo = {addEventListener: (type, listener) => { listeners[type] = listener; }};
        let share_option = %s;
        let share_option_chosen = false;

        %s
        %s

        const shown = () => {
            const button = find(menuGroups, (node) => node.title === 'Share');
            return button !== null && button.style.display !== 'none';
        };
        const seen = [shown()];
        for (const value of %s) {
            listeners.change({target: {value}});
            seen.push(shown());
        }
        console.log(JSON.stringify({seen}));
    """ % (json.dumps(initial), menu_group, change_handler, json.dumps(changes))
    return run_node(script)["seen"]


@pytest.mark.parametrize("option", CHOICES)
def test_the_share_button_is_shown_unless_the_option_is_none(option):
    assert share_button_shown(option) == [option != "none"]


@pytest.mark.parametrize("initial, changed", [(initial, changed) for initial in CHOICES for changed in CHOICES
                                              if changed != initial])
def test_changing_the_option_shows_or_hides_it_without_a_reload(initial, changed):
    assert share_button_shown(initial, changed) == [initial != "none", changed != "none"]
