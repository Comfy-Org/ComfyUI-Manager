import pytest

from test_workflow_nodepack_lookup import EXTENSION, browser, page  # noqa: F401 -- fixture


def model(name, model_type, base, save_path, filename, installed):
    return {"name": name, "type": model_type, "base": base, "save_path": save_path, "description": name,
            "reference": "https://example.invalid/" + filename, "filename": filename,
            "url": "https://example.invalid/" + filename, "size": "4.71MB", "installed": installed}


MODELS = [
    model("FLUX.1 VAE model", "VAE", "FLUX.1", "vae/FLUX1", "ae.safetensors", "False"),
    model("TAEF1 Decoder", "TAESD", "FLUX.1", "vae_approx", "taef1_decoder.pth", "True"),
    model("TAESD Decoder", "TAESD", "SD1.x", "vae_approx", "taesd_decoder.pth", "False"),
    model("RealESRGAN x2", "upscale", "upscale", "default", "RealESRGAN_x2.pth", "False"),
    model("FLUX.1 dev Q4_0", "unet", "FLUX.1", "diffusion_models/FLUX1", "flux1-dev-Q4_0.gguf", "False"),
    model("v1-5-pruned-emaonly", "checkpoint", "SD1.5", "checkpoints/SD1.5", "v1-5-pruned-emaonly.safetensors", "True"),
]


def node(node_type, *values):
    return {"type": node_type, "widgets_values": list(values)}


def workflow(*loaders):
    return [*loaders,
            node("UNETLoader", "z_image_turbo_bf16.safetensors", "default"),
            node("KSampler", 42, "fixed", 8, 1, "res_multistep", "simple", 1),
            node("CLIPTextEncode", "a cute anime girl with gigantic fennec ears and a big fluffy fox tail"),
            {"type": "VHS_VideoCombine", "widgets_values": {"frame_rate": 8, "filename_prefix": "AnimateDiff"}},
            {"type": "Reroute"}]


def choose(page, change):  # noqa: F811
    page.evaluate("() => { window.updated = false; manager.grid.onNextUpdated(() => { window.updated = true; }); }")
    change()
    page.wait_for_function("window.updated")


def open_models(page, nodes, keywords="", **choices):  # noqa: F811
    page.evaluate("""async ({module, server, nodes}) => {
        window.server = server;
        const {app} = await import('/scripts/app.js');
        app.graph._nodes = nodes;
        const {setManagerInstance} = await import(new URL('common.js', module).href);
        setManagerInstance({datasrc_combo: {value: 'cache'}});
        const {ModelManager} = await import(module);
        window.manager = new ModelManager(app, null);
        manager.show();
    }""", {"module": EXTENSION + "model-manager.js", "server": {"/externalmodel/getlist": {"models": MODELS}},
           "nodes": nodes})
    page.wait_for_function("/^[\\d,]+ external models$/.test(document.querySelector('.cmm-manager-status').textContent)")
    if keywords:
        choose(page, lambda: page.fill(".cmm-manager-keywords", keywords))
    for name, value in choices.items():
        choose(page, lambda: page.select_option(".cmm-manager-" + name, value))
    return page.evaluate("""() => ({
        rows: [...document.querySelectorAll('.cmm-manager-grid .tg-body .cmm-node-name')].map(cell => cell.innerText.trim()),
        status: document.querySelector('.cmm-manager-status').textContent,
    })""")


@pytest.mark.parametrize("value, rows", [
    ("ae.safetensors", ["FLUX.1 VAE model"]),
    ("FLUX1/ae.safetensors", ["FLUX.1 VAE model"]),
    ("FLUX1\\ae.safetensors", ["FLUX.1 VAE model"]),
    ("flux1-dev-Q4_0.gguf", ["FLUX.1 dev Q4_0"]),
    ("qwen_3_4b.safetensors", []),
], ids=["file", "file in a folder", "file in a Windows folder", "gguf file", "file not in the list"])
def test_in_workflow_lists_the_models_whose_file_the_workflow_loads(page, value, rows):  # noqa: F811
    shown = open_models(page, workflow(node("VAELoader", value)), filter="in_workflow")

    assert shown == {"rows": rows, "status": f"{len(rows)} external models"}
    assert page.errors == []


def test_in_workflow_keeps_the_marks_of_a_search(page):  # noqa: F811
    shown = open_models(page, workflow(node("VAELoader", "ae.safetensors")), keywords="flux", filter="in_workflow")

    assert shown == {"rows": ["FLUX.1 VAE model"], "status": "1 external models"}
    page.wait_for_function("document.querySelector('.cmm-manager-grid .tg-body .cmm-node-name mark')")
    assert page.locator(".cmm-manager-grid .tg-body .cmm-node-name mark").all_text_contents() == ["FLUX"]
    assert page.errors == []


@pytest.mark.parametrize("keywords, choices, rows", [
    ("", {"type": "TAESD", "base": "FLUX.1"}, ["TAEF1 Decoder"]),
    ("", {"filter": "installed", "base": "FLUX.1"}, ["TAEF1 Decoder"]),
    ("", {"filter": "not_installed", "type": "TAESD"}, ["TAESD Decoder"]),
    ("", {"filter": "in_workflow", "type": "checkpoint"}, ["v1-5-pruned-emaonly"]),
    ("flux", {"filter": "not_installed", "type": "unet"}, ["FLUX.1 dev Q4_0"]),
], ids=["All", "Installed", "Not Installed", "In Workflow", "Not Installed and a search"])
def test_a_filter_choice_narrows_the_list_together_with_type_base_and_search(page, keywords, choices, rows):  # noqa: F811
    nodes = workflow(node("VAELoader", "ae.safetensors"), node("CheckpointLoaderSimple", "SD1.5/v1-5-pruned-emaonly.safetensors"))

    shown = open_models(page, nodes, keywords, **choices)

    assert shown == {"rows": rows, "status": f"{len(rows)} external models"}
    assert page.errors == []
