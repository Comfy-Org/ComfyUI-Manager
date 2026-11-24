import json
import os
from pathlib import Path

import pytest

from js_lift import NODE, JsSource, run_node, slice_braced

JS = JsSource(Path(os.environ.get("MANAGER_JS_DIR") or (Path(__file__).resolve().parent.parent / "js")))

pytestmark = pytest.mark.skipif(NODE is None, reason="node is required to execute the lifted production JS")


def switch(version, status, versions_status=200):
    script = """
        const shown = [], requested = [];
        const api = {fetchApi: async (path, options) => {
            if(path == '/comfyui_manager/comfyui_versions') {
                return {status: %s, json: async () => ({versions: ['nightly', 'v0.3.60'], current: 'v0.3.59'})};
            }
            requested.push({path, body: JSON.parse(options.body)});
            return {status: path == '/comfyui_manager/comfyui_switch_version' ? %s : 200};
        }};
        const switch_comfyui_button = {style: {}};
        const update_policy_combo = {value: 'unchanged'};
        let update_policy_chosen = false;
        let chosen;
        const showVersionSelectorDialog = (versions, current, onSelect) => { chosen = onSelect(%s); };
        const infoToast = (text) => shown.push('toast: ' + text);
        const customAlert = (text) => shown.push('alert: ' + text);
        const handle403Response = async () => shown.push('security level message');
        %s
        await switchComfyUI();
        await chosen;
        console.log(JSON.stringify({shown, requested, update_policy: update_policy_combo.value, update_policy_chosen,
                                    button_disabled: switch_comfyui_button.disabled}));
    """ % (json.dumps(versions_status), json.dumps(status), json.dumps(version),
           slice_braced(JS.text("comfyui-manager.js"), "async function switchComfyUI()"))
    return run_node(script)


def switch_request(version):
    return {"path": "/comfyui_manager/comfyui_switch_version", "body": {"ver": version}}


@pytest.mark.parametrize("version, update_policy", [("nightly", "nightly-comfyui"), ("v0.3.60", "stable-comfyui")])
def test_a_switch_that_happened_sets_the_update_policy_of_the_version(version, update_policy):
    did = switch(version, 200)

    assert did["requested"] == [switch_request(version), {"path": "/manager/policy/update", "body": {"value": update_policy}}]
    assert did["update_policy"] == update_policy
    assert did["update_policy_chosen"] is True
    assert did["shown"] == ["toast: ComfyUI version is switched to " + version]


@pytest.mark.parametrize("version", ["nightly", "v0.3.60"])
@pytest.mark.parametrize("status, shown", [
    (403, "security level message"),
    (400, "alert: Failed to switch ComfyUI version."),
    (500, "alert: Failed to switch ComfyUI version."),
])
def test_a_switch_that_did_not_happen_leaves_the_update_policy(version, status, shown):
    did = switch(version, status)

    assert did["requested"] == [switch_request(version)]
    assert did["update_policy"] == "unchanged"
    assert did["update_policy_chosen"] is False
    assert did["shown"] == [shown]


def test_without_the_list_of_versions_nothing_is_switched():
    did = switch("v0.3.60", 200, versions_status=400)

    assert did["requested"] == []
    assert did["shown"] == ["alert: Failed to fetch ComfyUI versions."]
    assert did["button_disabled"] is False
