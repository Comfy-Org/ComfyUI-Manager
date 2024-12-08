import traceback

import folder_paths
import locale
import subprocess  # don't remove this
import concurrent
import nodes
import os
import sys
import threading
import re
import shutil
import git
import datetime
import logging

from server import PromptServer
import manager_core as core
import cm_global

print(f"### Loading: ComfyUI-Manager ({core.version_str})")

comfy_ui_hash = "-"

SECURITY_MESSAGE_MIDDLE_OR_BELOW = f"ERROR: To use this action, a security_level of `middle or below` is required. Please contact the administrator.\nReference: https://github.com/ltdrdata/ComfyUI-Manager#security-policy"
SECURITY_MESSAGE_NORMAL_MINUS = f"ERROR: To use this feature, you must either set '--listen' to a local IP and set the security level to 'normal-' or lower, or set the security level to 'middle' or 'weak'. Please contact the administrator.\nReference: https://github.com/ltdrdata/ComfyUI-Manager#security-policy"
SECURITY_MESSAGE_GENERAL = f"ERROR: This installation is not allowed in this security_level. Please contact the administrator.\nReference: https://github.com/ltdrdata/ComfyUI-Manager#security-policy"

def handle_stream(stream, prefix):
    stream.reconfigure(encoding=locale.getpreferredencoding(), errors='replace')
    for msg in stream:
        if prefix == '[!]' and ('it/s]' in msg or 's/it]' in msg) and ('%|' in msg or 'it [' in msg):
            if msg.startswith('100%'):
                print('\r' + msg, end="", file=sys.stderr),
            else:
                print('\r' + msg[:-1], end="", file=sys.stderr),
        else:
            if prefix == '[!]':
                print(prefix, msg, end="", file=sys.stderr)
            else:
                print(prefix, msg, end="")


from comfy.cli_args import args
import latent_preview


is_local_mode = args.listen.startswith('127.') or args.listen.startswith('local.')


def is_allowed_security_level(level):
    if level == 'block':
        return False
    elif level == 'high':
        if is_local_mode:
            return core.get_config()['security_level'].lower() in ['weak', 'normal-']
        else:
            return core.get_config()['security_level'].lower() == 'weak'
    elif level == 'middle':
        return core.get_config()['security_level'].lower() in ['weak', 'normal', 'normal-']
    else:
        return True


async def get_risky_level(files, pip_packages):
    json_data1 = await core.get_data_by_mode('local', 'custom-node-list.json')
    json_data2 = await core.get_data_by_mode('cache', 'custom-node-list.json', channel_url='https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main')

    all_urls = set()
    for x in json_data1['custom_nodes'] + json_data2['custom_nodes']:
        all_urls.update(x['files'])

    for x in files:
        if x not in all_urls:
            return "high"

    all_pip_packages = set()
    for x in json_data1['custom_nodes'] + json_data2['custom_nodes']:
        if "pip" in x:
            all_pip_packages.update(x['pip'])

    for p in pip_packages:
        if p not in all_pip_packages:
            return "block"

    return "middle"


class ManagerFuncsInComfyUI(core.ManagerFuncs):
    def get_current_preview_method(self):
        if args.preview_method == latent_preview.LatentPreviewMethod.Auto:
            return "auto"
        elif args.preview_method == latent_preview.LatentPreviewMethod.Latent2RGB:
            return "latent2rgb"
        elif args.preview_method == latent_preview.LatentPreviewMethod.TAESD:
            return "taesd"
        else:
            return "none"

    def run_script(self, cmd, cwd='.'):
        if len(cmd) > 0 and cmd[0].startswith("#"):
            print(f"[ComfyUI-Manager] Unexpected behavior: `{cmd}`")
            return 0

        process = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)

        stdout_thread = threading.Thread(target=handle_stream, args=(process.stdout, ""))
        stderr_thread = threading.Thread(target=handle_stream, args=(process.stderr, "[!]"))

        stdout_thread.start()
        stderr_thread.start()

        stdout_thread.join()
        stderr_thread.join()

        return process.wait()


core.manager_funcs = ManagerFuncsInComfyUI()

sys.path.append('../..')

from manager_downloader import download_url

core.comfy_path = os.path.dirname(folder_paths.__file__)
core.js_path = os.path.join(core.comfy_path, "web", "extensions")

local_db_model = os.path.join(core.comfyui_manager_path, "model-list.json")
local_db_alter = os.path.join(core.comfyui_manager_path, "alter-list.json")
local_db_custom_node_list = os.path.join(core.comfyui_manager_path, "custom-node-list.json")
local_db_extension_node_mappings = os.path.join(core.comfyui_manager_path, "extension-node-map.json")
components_path = os.path.join(core.comfyui_manager_path, 'components')


def set_preview_method(method):
    if method == 'auto':
        args.preview_method = latent_preview.LatentPreviewMethod.Auto
    elif method == 'latent2rgb':
        args.preview_method = latent_preview.LatentPreviewMethod.Latent2RGB
    elif method == 'taesd':
        args.preview_method = latent_preview.LatentPreviewMethod.TAESD
    else:
        args.preview_method = latent_preview.LatentPreviewMethod.NoPreviews

    core.get_config()['preview_method'] = args.preview_method


set_preview_method(core.get_config()['preview_method'])


def set_badge_mode(mode):
    core.get_config()['badge_mode'] = mode


def set_default_ui_mode(mode):
    core.get_config()['default_ui'] = mode


def set_component_policy(mode):
    core.get_config()['component_policy'] = mode


def set_double_click_policy(mode):
    core.get_config()['double_click_policy'] = mode


def print_comfyui_version():
    global comfy_ui_hash

    is_detached = False
    try:
        repo = git.Repo(os.path.dirname(folder_paths.__file__))
        core.comfy_ui_revision = len(list(repo.iter_commits('HEAD')))

        comfy_ui_hash = repo.head.commit.hexsha
        cm_global.variables['comfyui.revision'] = core.comfy_ui_revision

        core.comfy_ui_commit_datetime = repo.head.commit.committed_datetime
        cm_global.variables['comfyui.commit_datetime'] = core.comfy_ui_commit_datetime

        is_detached = repo.head.is_detached
        current_branch = repo.active_branch.name

        try:
            if core.comfy_ui_commit_datetime.date() < core.comfy_ui_required_commit_datetime.date():
                print(f"\n\n## [WARN] ComfyUI-Manager: Your ComfyUI version ({core.get_comfyui_tag()})[{core.comfy_ui_commit_datetime.date()}] is too old. Please update to the latest version. ##\n\n")
        except:
            pass

        # process on_revision_detected -->
        if 'cm.on_revision_detected_handler' in cm_global.variables:
            for k, f in cm_global.variables['cm.on_revision_detected_handler']:
                try:
                    f(core.comfy_ui_revision)
                except Exception:
                    print(f"[ERROR] '{k}' on_revision_detected_handler")
                    traceback.print_exc()

            del cm_global.variables['cm.on_revision_detected_handler']
        else:
            print(f"[ComfyUI-Manager] Some features are restricted due to your ComfyUI being outdated.")
        # <--

        if current_branch == "master":
            version_tag = core.get_comfyui_tag()
            if version_tag is None:
                print(f"### ComfyUI Revision: {core.comfy_ui_revision} [{comfy_ui_hash[:8]}] | Released on '{core.comfy_ui_commit_datetime.date()}'")
            else:
                print(f"### ComfyUI Version: {core.get_comfyui_tag()} | Released on '{core.comfy_ui_commit_datetime.date()}'")
        else:
            print(f"### ComfyUI Revision: {core.comfy_ui_revision} on '{current_branch}' [{comfy_ui_hash[:8]}] | Released on '{core.comfy_ui_commit_datetime.date()}'")
    except:
        if is_detached:
            print(f"### ComfyUI Revision: {core.comfy_ui_revision} [{comfy_ui_hash[:8]}] *DETACHED | Released on '{core.comfy_ui_commit_datetime.date()}'")
        else:
            print("### ComfyUI Revision: UNKNOWN (The currently installed ComfyUI is not a Git repository)")


print_comfyui_version()


async def populate_github_stats(json_obj, json_obj_github):
    if 'custom_nodes' in json_obj:
        for i, node in enumerate(json_obj['custom_nodes']):
            url = node['reference']
            if url in json_obj_github:
                json_obj['custom_nodes'][i]['stars'] = json_obj_github[url]['stars']
                json_obj['custom_nodes'][i]['last_update'] = json_obj_github[url]['last_update']
                json_obj['custom_nodes'][i]['trust'] = json_obj_github[url]['author_account_age_days'] > 180
            else:
                json_obj['custom_nodes'][i]['stars'] = -1
                json_obj['custom_nodes'][i]['last_update'] = -1
                json_obj['custom_nodes'][i]['trust'] = False
        return json_obj


def setup_environment():
    git_exe = core.get_config()['git_exe']

    if git_exe != '':
        git.Git().update_environment(GIT_PYTHON_GIT_EXECUTABLE=git_exe)


setup_environment()

# Expand Server api

import server
from aiohttp import web
import aiohttp
import json
import zipfile
import urllib.request


def get_model_dir(data):
    if 'download_model_base' in folder_paths.folder_names_and_paths:
        models_base = folder_paths.folder_names_and_paths['download_model_base'][0][0]
    else:
        models_base = folder_paths.models_dir

    def resolve_custom_node(save_path):
        save_path = save_path[13:] # remove 'custom_nodes/'
        repo_name = save_path.replace('\\','/').split('/')[0] # get custom node repo name
        repo_path = core.lookup_installed_custom_nodes(repo_name)
        if repo_path is not None and repo_path[0]:
            # Returns the retargeted path based on the actually installed repository
            return os.path.join(os.path.dirname(repo_path[1]), save_path)
        else:
            return None

    if data['save_path'] != 'default':
        if '..' in data['save_path'] or data['save_path'].startswith('/'):
            print(f"[WARN] '{data['save_path']}' is not allowed path. So it will be saved into 'models/etc'.")
            base_model = os.path.join(models_base, "etc")
        else:
            if data['save_path'].startswith("custom_nodes"):
                base_model = resolve_custom_node(data['save_path'])
                if base_model is None:
                    print(f"[ComfyUI-Manager] The target custom node for model download is not installed: {data['save_path']}")
                    return None
            else:
                base_model = os.path.join(models_base, data['save_path'])
    else:
        model_type = data['type']
        if model_type == "checkpoints" or model_type == "checkpoint":
            base_model = folder_paths.folder_names_and_paths["checkpoints"][0][0]
        elif model_type == "unclip":
            base_model = folder_paths.folder_names_and_paths["checkpoints"][0][0]
        elif model_type == "clip" or model_type == "text_encoders":
            if folder_paths.folder_names_and_paths.get("text_encoders"):
                base_model = folder_paths.folder_names_and_paths["text_encoders"][0][0]
            else:
                print(f"[ComfyUI-Manager] Your ComfyUI is outdated version.")
                base_model = folder_paths.folder_names_and_paths["clip"][0][0]  # outdated version
        elif model_type == "VAE":
            base_model = folder_paths.folder_names_and_paths["vae"][0][0]
        elif model_type == "lora":
            base_model = folder_paths.folder_names_and_paths["loras"][0][0]
        elif model_type == "T2I-Adapter":
            base_model = folder_paths.folder_names_and_paths["controlnet"][0][0]
        elif model_type == "T2I-Style":
            base_model = folder_paths.folder_names_and_paths["controlnet"][0][0]
        elif model_type == "controlnet":
            base_model = folder_paths.folder_names_and_paths["controlnet"][0][0]
        elif model_type == "clip_vision":
            base_model = folder_paths.folder_names_and_paths["clip_vision"][0][0]
        elif model_type == "gligen":
            base_model = folder_paths.folder_names_and_paths["gligen"][0][0]
        elif model_type == "upscale":
            base_model = folder_paths.folder_names_and_paths["upscale_models"][0][0]
        elif model_type == "embeddings":
            base_model = folder_paths.folder_names_and_paths["embeddings"][0][0]
        elif model_type == "unet" or model_type == "diffusion_model":
            if folder_paths.folder_names_and_paths.get("diffusion_models"):
                base_model = folder_paths.folder_names_and_paths["diffusion_models"][0][1]
            else:
                print(f"[ComfyUI-Manager] Your ComfyUI is outdated version.")
                base_model = folder_paths.folder_names_and_paths["unet"][0][0]  # outdated version
        else:
            base_model = os.path.join(models_base, "etc")

    return base_model


def get_model_path(data):
    base_model = get_model_dir(data)
    if base_model is None:
        return None
    else:
        return os.path.join(base_model, data['filename'])


def check_custom_nodes_installed(json_obj, do_fetch=False, do_update_check=True, do_update=False):
    if do_fetch:
        print("Start fetching...", end="")
    elif do_update:
        print("Start updating...", end="")
    elif do_update_check:
        print("Start update check...", end="")

    def process_custom_node(item):
        core.check_a_custom_node_installed(item, do_fetch, do_update_check, do_update)

    with concurrent.futures.ThreadPoolExecutor(4) as executor:
        for item in json_obj['custom_nodes']:
            executor.submit(process_custom_node, item)

    if do_fetch:
        print(f"\x1b[2K\rFetching done.")
    elif do_update:
        update_exists = any(item['installed'] == 'Update' for item in json_obj['custom_nodes'])
        if update_exists:
            print(f"\x1b[2K\rUpdate done.")
        else:
            print(f"\x1b[2K\rAll extensions are already up-to-date.")
    elif do_update_check:
        print(f"\x1b[2K\rUpdate check done.")


def nickname_filter(json_obj):
    preemptions_map = {}

    for k, x in json_obj.items():
        if 'preemptions' in x[1]:
            for y in x[1]['preemptions']:
                preemptions_map[y] = k
        elif k.endswith("/ComfyUI"):
            for y in x[0]:
                preemptions_map[y] = k

    updates = {}
    for k, x in json_obj.items():
        removes = set()
        for y in x[0]:
            k2 = preemptions_map.get(y)
            if k2 is not None and k != k2:
                removes.add(y)

        if len(removes) > 0:
            updates[k] = [y for y in x[0] if y not in removes]

    for k, v in updates.items():
        json_obj[k][0] = v

    return json_obj


@PromptServer.instance.routes.get("/customnode/getmappings")
async def fetch_customnode_mappings(request):
    mode = request.rel_url.query["mode"]

    nickname_mode = False
    if mode == "nickname":
        mode = "local"
        nickname_mode = True

    json_obj = await core.get_data_by_mode(mode, 'extension-node-map.json')

    if nickname_mode:
        json_obj = nickname_filter(json_obj)

    all_nodes = set()
    patterns = []
    for k, x in json_obj.items():
        all_nodes.update(set(x[0]))

        if 'nodename_pattern' in x[1]:
            patterns.append((x[1]['nodename_pattern'], x[0]))

    missing_nodes = set(nodes.NODE_CLASS_MAPPINGS.keys()) - all_nodes

    for x in missing_nodes:
        for pat, item in patterns:
            if re.match(pat, x):
                item.append(x)

    return web.json_response(json_obj, content_type='application/json')


@PromptServer.instance.routes.get("/customnode/fetch_updates")
async def fetch_updates(request):
    try:
        json_obj = await core.get_data_by_mode(request.rel_url.query["mode"], 'custom-node-list.json')

        check_custom_nodes_installed(json_obj, True)

        update_exists = any('custom_nodes' in json_obj and 'installed' in node and node['installed'] == 'Update' for node in
                            json_obj['custom_nodes'])

        if update_exists:
            return web.Response(status=201)

        return web.Response(status=200)
    except:
        return web.Response(status=400)


@PromptServer.instance.routes.get("/customnode/update_all")
async def update_all(request):
    if not is_allowed_security_level('middle'):
        print(SECURITY_MESSAGE_MIDDLE_OR_BELOW)
        return web.Response(status=403)

    try:
        core.save_snapshot_with_postfix('autosave')

        json_obj = await core.get_data_by_mode(request.rel_url.query["mode"], 'custom-node-list.json')

        check_custom_nodes_installed(json_obj, do_update=True)

        updated = [item['title'] for item in json_obj['custom_nodes'] if item['installed'] == 'Update']
        failed = [item['title'] for item in json_obj['custom_nodes'] if item['installed'] == 'Fail']

        res = {'updated': updated, 'failed': failed}

        if len(updated) == 0 and len(failed) == 0:
            status = 200
        else:
            status = 201

        return web.json_response(res, status=status, content_type='application/json')
    except:
        return web.Response(status=400)
    finally:
        core.clear_pip_cache()


def convert_markdown_to_html(input_text):
    pattern_a = re.compile(r'\[a/([^]]+)\]\(([^)]+)\)')
    pattern_w = re.compile(r'\[w/([^]]+)\]')
    pattern_i = re.compile(r'\[i/([^]]+)\]')
    pattern_bold = re.compile(r'\*\*([^*]+)\*\*')
    pattern_white = re.compile(r'%%([^*]+)%%')

    def replace_a(match):
        return f"<a href='{match.group(2)}' target='blank'>{match.group(1)}</a>"

    def replace_w(match):
        return f"<p class='cm-warn-note'>{match.group(1)}</p>"

    def replace_i(match):
        return f"<p class='cm-info-note'>{match.group(1)}</p>"

    def replace_bold(match):
        return f"<B>{match.group(1)}</B>"

    def replace_white(match):
        return f"<font color='white'>{match.group(1)}</font>"

    input_text = input_text.replace('\\[', '&#91;').replace('\\]', '&#93;').replace('<', '&lt;').replace('>', '&gt;')

    result_text = re.sub(pattern_a, replace_a, input_text)
    result_text = re.sub(pattern_w, replace_w, result_text)
    result_text = re.sub(pattern_i, replace_i, result_text)
    result_text = re.sub(pattern_bold, replace_bold, result_text)
    result_text = re.sub(pattern_white, replace_white, result_text)

    return result_text.replace("\n", "<BR>")


def populate_markdown(x):
    if 'description' in x:
        x['description'] = convert_markdown_to_html(x['description'])

    if 'name' in x:
        x['name'] = x['name'].replace('<', '&lt;').replace('>', '&gt;')

    if 'title' in x:
        x['title'] = x['title'].replace('<', '&lt;').replace('>', '&gt;')


@PromptServer.instance.routes.get("/customnode/getlist")
async def fetch_customnode_list(request):
    if "skip_update" in request.rel_url.query and request.rel_url.query["skip_update"] == "true":
        skip_update = True
    else:
        skip_update = False

    if request.rel_url.query["mode"] == "local":
        channel = 'local'
    else:
        channel = core.get_config()['channel_url']

    json_obj = await core.get_data_by_mode(request.rel_url.query["mode"], 'custom-node-list.json')
    json_obj_github = await core.get_data_by_mode(request.rel_url.query["mode"], 'github-stats.json', 'default')
    json_obj = await populate_github_stats(json_obj, json_obj_github)

    def is_ignored_notice(code):
        if code is not None and code.startswith('#NOTICE_'):
            try:
                notice_version = [int(x) for x in code[8:].split('.')]
                return notice_version[0] < core.version[0] or (notice_version[0] == core.version[0] and notice_version[1] <= core.version[1])
            except Exception:
                return False
        else:
            return False

    json_obj['custom_nodes'] = [record for record in json_obj['custom_nodes'] if not is_ignored_notice(record.get('author'))]

    check_custom_nodes_installed(json_obj, False, not skip_update)

    for x in json_obj['custom_nodes']:
        populate_markdown(x)

    if channel != 'local':
        found = 'custom'

        for name, url in core.get_channel_dict().items():
            if url == channel:
                found = name
                break

        channel = found

    json_obj['channel'] = channel

    return web.json_response(json_obj, content_type='application/json')


@PromptServer.instance.routes.get("/customnode/alternatives")
async def fetch_customnode_alternatives(request):
    alter_json = await core.get_data_by_mode(request.rel_url.query["mode"], 'alter-list.json')

    for item in alter_json['items']:
        populate_markdown(item)
        
    return web.json_response(alter_json, content_type='application/json')


@PromptServer.instance.routes.get("/alternatives/getlist")
async def fetch_alternatives_list(request):
    if "skip_update" in request.rel_url.query and request.rel_url.query["skip_update"] == "true":
        skip_update = True
    else:
        skip_update = False

    alter_json = await core.get_data_by_mode(request.rel_url.query["mode"], 'alter-list.json')
    custom_node_json = await core.get_data_by_mode(request.rel_url.query["mode"], 'custom-node-list.json')

    fileurl_to_custom_node = {}

    for item in custom_node_json['custom_nodes']:
        for fileurl in item['files']:
            fileurl_to_custom_node[fileurl] = item

    for item in alter_json['items']:
        fileurl = item['id']
        if fileurl in fileurl_to_custom_node:
            custom_node = fileurl_to_custom_node[fileurl]
            core.check_a_custom_node_installed(custom_node, not skip_update)

            populate_markdown(item)
            populate_markdown(custom_node)
            item['custom_node'] = custom_node

    return web.json_response(alter_json, content_type='application/json')


def check_model_installed(json_obj):
    def process_model(item):
        model_path = get_model_path(item)
        item['installed'] = 'None'

        if model_path is not None:
            if model_path.endswith('.zip'):
                if os.path.exists(model_path[:-4]):
                    item['installed'] = 'True'
                else:
                    item['installed'] = 'False'
            elif os.path.exists(model_path):
                item['installed'] = 'True'
            else:
                item['installed'] = 'False'

    with concurrent.futures.ThreadPoolExecutor(8) as executor:
        for item in json_obj['models']:
            executor.submit(process_model, item)


@PromptServer.instance.routes.get("/externalmodel/getlist")
async def fetch_externalmodel_list(request):
    json_obj = await core.get_data_by_mode(request.rel_url.query["mode"], 'model-list.json')

    check_model_installed(json_obj)

    for x in json_obj['models']:
        populate_markdown(x)

    return web.json_response(json_obj, content_type='application/json')


@PromptServer.instance.routes.get("/snapshot/getlist")
async def get_snapshot_list(request):
    snapshots_directory = os.path.join(core.comfyui_manager_path, 'snapshots')
    items = [f[:-5] for f in os.listdir(snapshots_directory) if f.endswith('.json')]
    items.sort(reverse=True)
    return web.json_response({'items': items}, content_type='application/json')


@PromptServer.instance.routes.get("/snapshot/remove")
async def remove_snapshot(request):
    if not is_allowed_security_level('middle'):
        print(SECURITY_MESSAGE_MIDDLE_OR_BELOW)
        return web.Response(status=403)
    
    try:
        target = request.rel_url.query["target"]

        path = os.path.join(core.comfyui_manager_path, 'snapshots', f"{target}.json")
        if os.path.exists(path):
            os.remove(path)

        return web.Response(status=200)
    except:
        return web.Response(status=400)


@PromptServer.instance.routes.get("/snapshot/restore")
async def remove_snapshot(request):
    if not is_allowed_security_level('middle'):
        print(SECURITY_MESSAGE_MIDDLE_OR_BELOW)
        return web.Response(status=403)
    
    try:
        target = request.rel_url.query["target"]

        path = os.path.join(core.comfyui_manager_path, 'snapshots', f"{target}.json")
        if os.path.exists(path):
            if not os.path.exists(core.startup_script_path):
                os.makedirs(core.startup_script_path)

            target_path = os.path.join(core.startup_script_path, "restore-snapshot.json")
            shutil.copy(path, target_path)

            print(f"Snapshot restore scheduled: `{target}`")
            return web.Response(status=200)

        print(f"Snapshot file not found: `{path}`")
        return web.Response(status=400)
    except:
        return web.Response(status=400)


@PromptServer.instance.routes.get("/snapshot/get_current")
async def get_current_snapshot_api(request):
    try:
        return web.json_response(core.get_current_snapshot(), content_type='application/json')
    except:
        return web.Response(status=400)


@PromptServer.instance.routes.get("/snapshot/save")
async def save_snapshot(request):
    try:
        core.save_snapshot_with_postfix('snapshot')
        return web.Response(status=200)
    except:
        return web.Response(status=400)


def unzip_install(files):
    temp_filename = 'manager-temp.zip'
    for url in files:
        if url.endswith("/"):
            url = url[:-1]
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}

            req = urllib.request.Request(url, headers=headers)
            response = urllib.request.urlopen(req)
            data = response.read()

            with open(temp_filename, 'wb') as f:
                f.write(data)

            with zipfile.ZipFile(temp_filename, 'r') as zip_ref:
                zip_ref.extractall(core.custom_nodes_path)

            os.remove(temp_filename)
        except Exception as e:
            print(f"Install(unzip) error: {url} / {e}", file=sys.stderr)
            return False

    print("Installation was successful.")
    return True


def download_url_with_agent(url, save_path):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}

        req = urllib.request.Request(url, headers=headers)
        response = urllib.request.urlopen(req)
        data = response.read()

        if not os.path.exists(os.path.dirname(save_path)):
            os.makedirs(os.path.dirname(save_path))

        with open(save_path, 'wb') as f:
            f.write(data)

    except Exception as e:
        print(f"Download error: {url} / {e}", file=sys.stderr)
        return False

    print("Installation was successful.")
    return True


def copy_install(files, js_path_name=None):
    for url in files:
        if url.endswith("/"):
            url = url[:-1]
        try:
            filename = os.path.basename(url)
            if url.endswith(".py"):
                download_url(url, core.custom_nodes_path, filename)
            else:
                path = os.path.join(core.js_path, js_path_name) if js_path_name is not None else core.js_path
                if not os.path.exists(path):
                    os.makedirs(path)
                download_url(url, path, filename)

        except Exception as e:
            print(f"Install(copy) error: {url} / {e}", file=sys.stderr)
            return False

    print("Installation was successful.")
    return True


def copy_uninstall(files, js_path_name='.'):
    for url in files:
        if url.endswith("/"):
            url = url[:-1]
        dir_name = os.path.basename(url)
        base_path = core.custom_nodes_path if url.endswith('.py') else os.path.join(core.js_path, js_path_name)
        file_path = os.path.join(base_path, dir_name)

        try:
            if os.path.exists(file_path):
                os.remove(file_path)
            elif os.path.exists(file_path + ".disabled"):
                os.remove(file_path + ".disabled")
        except Exception as e:
            print(f"Uninstall(copy) error: {url} / {e}", file=sys.stderr)
            return False

    print("Uninstallation was successful.")
    return True


def copy_set_active(files, is_disable, js_path_name='.'):
    if is_disable:
        action_name = "Disable"
    else:
        action_name = "Enable"

    for url in files:
        if url.endswith("/"):
            url = url[:-1]
        dir_name = os.path.basename(url)
        base_path = core.custom_nodes_path if url.endswith('.py') else os.path.join(core.js_path, js_path_name)
        file_path = os.path.join(base_path, dir_name)

        try:
            if is_disable:
                current_name = file_path
                new_name = file_path + ".disabled"
            else:
                current_name = file_path + ".disabled"
                new_name = file_path

            os.rename(current_name, new_name)

        except Exception as e:
            print(f"{action_name}(copy) error: {url} / {e}", file=sys.stderr)

            return False

    print(f"{action_name} was successful.")
    return True


@PromptServer.instance.routes.post("/customnode/install")
async def install_custom_node(request):
    if not is_allowed_security_level('middle'):
        print(SECURITY_MESSAGE_MIDDLE_OR_BELOW)
        return web.Response(status=403)

    json_data = await request.json()

    risky_level = await get_risky_level(json_data['files'], json_data.get('pip', []))
    if not is_allowed_security_level(risky_level):
        print(SECURITY_MESSAGE_GENERAL)
        return web.Response(status=404)

    install_type = json_data['install_type']

    print(f"Install custom node '{json_data['title']}'")

    res = False

    if len(json_data['files']) == 0:
        return web.Response(status=400)

    if install_type == "unzip":
        res = unzip_install(json_data['files'])

    if install_type == "copy":
        if 'js_path' in json_data:
            if '.' in json_data['js_path'] or ':' in json_data['js_path'] or json_data['js_path'].startswith('/'):
                print(f"[ComfyUI Manager] An abnormal JS path has been transmitted. This could be the result of a security attack.\n{json_data['js_path']}")
                return web.Response(status=400)
            else:
                js_path_name = json_data['js_path']
        else:
            js_path_name = '.'
        res = copy_install(json_data['files'], js_path_name)

    elif install_type == "git-clone":
        res = core.gitclone_install(json_data['files'])

    if 'pip' in json_data:
        for pname in json_data['pip']:
            pkg = core.remap_pip_package(pname)
            install_cmd = [sys.executable, "-m", "pip", "install", pkg]
            core.try_install_script(json_data['files'][0], ".", install_cmd)

    core.clear_pip_cache()

    if res:
        print(f"After restarting ComfyUI, please refresh the browser.")
        return web.json_response({}, content_type='application/json')

    return web.Response(status=400)


@PromptServer.instance.routes.post("/customnode/fix")
async def fix_custom_node(request):
    if not is_allowed_security_level('middle'):
        print(SECURITY_MESSAGE_GENERAL)
        return web.Response(status=403)

    json_data = await request.json()

    install_type = json_data['install_type']

    print(f"Install custom node '{json_data['title']}'")

    res = False

    if len(json_data['files']) == 0:
        return web.Response(status=400)

    if install_type == "git-clone":
        res = core.gitclone_fix(json_data['files'])
    else:
        return web.Response(status=400)

    if 'pip' in json_data:
        if not is_allowed_security_level('high'):
            print(SECURITY_MESSAGE_GENERAL)
            return web.Response(status=403)

        for pname in json_data['pip']:
            install_cmd = [sys.executable, "-m", "pip", "install", '-U', pname]
            core.try_install_script(json_data['files'][0], ".", install_cmd)

    # HOTFIX: force downgrade to numpy<2
    install_cmd = [sys.executable, "-m", "pip", "install", "numpy<2"]
    core.try_install_script(json_data['files'][0], ".", install_cmd)

    if res:
        print(f"After restarting ComfyUI, please refresh the browser.")
        return web.json_response({}, content_type='application/json')

    return web.Response(status=400)


@PromptServer.instance.routes.post("/customnode/install/git_url")
async def install_custom_node_git_url(request):
    if not is_allowed_security_level('high'):
        print(SECURITY_MESSAGE_NORMAL_MINUS)
        return web.Response(status=403)

    url = await request.text()
    res = core.gitclone_install([url])

    if res:
        print(f"After restarting ComfyUI, please refresh the browser.")
        return web.Response(status=200)

    return web.Response(status=400)


@PromptServer.instance.routes.post("/customnode/install/pip")
async def install_custom_node_git_url(request):
    if not is_allowed_security_level('high'):
        print(SECURITY_MESSAGE_NORMAL_MINUS)
        return web.Response(status=403)

    packages = await request.text()
    core.pip_install(packages.split(' '))

    return web.Response(status=200)


@PromptServer.instance.routes.post("/customnode/uninstall")
async def uninstall_custom_node(request):
    if not is_allowed_security_level('middle'):
        print(SECURITY_MESSAGE_MIDDLE_OR_BELOW)
        return web.Response(status=403)

    json_data = await request.json()

    install_type = json_data['install_type']

    print(f"Uninstall custom node '{json_data['title']}'")

    res = False

    if install_type == "copy":
        js_path_name = json_data['js_path'] if 'js_path' in json_data else '.'
        res = copy_uninstall(json_data['files'], js_path_name)

    elif install_type == "git-clone":
        res = core.gitclone_uninstall(json_data['files'])

    if res:
        print(f"After restarting ComfyUI, please refresh the browser.")
        return web.json_response({}, content_type='application/json')

    return web.Response(status=400)


@PromptServer.instance.routes.post("/customnode/update")
async def update_custom_node(request):
    if not is_allowed_security_level('middle'):
        print(SECURITY_MESSAGE_MIDDLE_OR_BELOW)
        return web.Response(status=403)

    json_data = await request.json()

    install_type = json_data['install_type']

    print(f"Update custom node '{json_data['title']}'")

    res = False

    if install_type == "git-clone":
        res = core.gitclone_update(json_data['files'])

    core.clear_pip_cache()

    if res:
        print(f"After restarting ComfyUI, please refresh the browser.")
        return web.json_response({}, content_type='application/json')

    return web.Response(status=400)


@PromptServer.instance.routes.get("/comfyui_manager/update_comfyui")
async def update_comfyui(request):
    print(f"Update ComfyUI")

    try:
        repo_path = os.path.dirname(folder_paths.__file__)
        res = core.update_path(repo_path)
        if res == "fail":
            print(f"ComfyUI update fail: The installed ComfyUI does not have a Git repository.")
            return web.Response(status=400)
        elif res == "updated":
            return web.Response(status=201)
        else:  # skipped
            return web.Response(status=200)
    except Exception as e:
        print(f"ComfyUI update fail: {e}", file=sys.stderr)

    return web.Response(status=400)


@PromptServer.instance.routes.post("/customnode/toggle_active")
async def toggle_active(request):
    json_data = await request.json()

    install_type = json_data['install_type']
    is_disabled = json_data['installed'] == "Disabled"

    print(f"Update custom node '{json_data['title']}'")

    res = False

    if install_type == "git-clone":
        res = core.gitclone_set_active(json_data['files'], not is_disabled)
    elif install_type == "copy":
        res = copy_set_active(json_data['files'], not is_disabled, json_data.get('js_path', None))

    if res:
        return web.json_response({}, content_type='application/json')

    return web.Response(status=400)


@PromptServer.instance.routes.post("/model/install")
async def install_model(request):
    json_data = await request.json()

    model_path = get_model_path(json_data)

    if not is_allowed_security_level('middle'):
        print(SECURITY_MESSAGE_MIDDLE_OR_BELOW)
        return web.Response(status=403)

    if not json_data['filename'].endswith('.safetensors') and not is_allowed_security_level('high'):
        models_json = await core.get_data_by_mode('cache', 'model-list.json')

        is_belongs_to_whitelist = False
        for x in models_json['models']:
            if x.get('url') == json_data['url']:
                is_belongs_to_whitelist = True
                break

        if not is_belongs_to_whitelist:
            print(SECURITY_MESSAGE_NORMAL_MINUS)
            return web.Response(status=403)

    res = False

    try:
        if model_path is not None:
            print(f"Install model '{json_data['name']}' into '{model_path}'")

            model_url = json_data['url']
            if not core.get_config()['model_download_by_agent'] and (
                    model_url.startswith('https://github.com') or model_url.startswith('https://huggingface.co') or model_url.startswith('https://heibox.uni-heidelberg.de')):
                model_dir = get_model_dir(json_data)
                download_url(model_url, model_dir, filename=json_data['filename'])
                if model_path.endswith('.zip'):
                    res = core.unzip(model_path)
                else:
                    res = True

                if res:
                    return web.json_response({}, content_type='application/json')
            else:
                res = download_url_with_agent(model_url, model_path)
                if res and model_path.endswith('.zip'):
                    res = core.unzip(model_path)
        else:
            print(f"Model installation error: invalid model type - {json_data['type']}")

        if res:
            return web.json_response({}, content_type='application/json')
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)

    return web.Response(status=400)


@PromptServer.instance.routes.get("/manager/preview_method")
async def preview_method(request):
    if "value" in request.rel_url.query:
        set_preview_method(request.rel_url.query['value'])
        core.write_config()
    else:
        return web.Response(text=core.manager_funcs.get_current_preview_method(), status=200)

    return web.Response(status=200)


@PromptServer.instance.routes.get("/manager/badge_mode")
async def badge_mode(request):
    if "value" in request.rel_url.query:
        set_badge_mode(request.rel_url.query['value'])
        core.write_config()
    else:
        return web.Response(text=core.get_config()['badge_mode'], status=200)

    return web.Response(status=200)


@PromptServer.instance.routes.get("/manager/default_ui")
async def default_ui_mode(request):
    if "value" in request.rel_url.query:
        set_default_ui_mode(request.rel_url.query['value'])
        core.write_config()
    else:
        return web.Response(text=core.get_config()['default_ui'], status=200)

    return web.Response(status=200)


@PromptServer.instance.routes.get("/manager/component/policy")
async def component_policy(request):
    if "value" in request.rel_url.query:
        set_component_policy(request.rel_url.query['value'])
        core.write_config()
    else:
        return web.Response(text=core.get_config()['component_policy'], status=200)

    return web.Response(status=200)


@PromptServer.instance.routes.get("/manager/dbl_click/policy")
async def dbl_click_policy(request):
    if "value" in request.rel_url.query:
        set_double_click_policy(request.rel_url.query['value'])
        core.write_config()
    else:
        return web.Response(text=core.get_config()['double_click_policy'], status=200)

    return web.Response(status=200)


@PromptServer.instance.routes.get("/manager/channel_url_list")
async def channel_url_list(request):
    channels = core.get_channel_dict()
    if "value" in request.rel_url.query:
        channel_url = channels.get(request.rel_url.query['value'])
        if channel_url is not None:
            core.get_config()['channel_url'] = channel_url
            core.write_config()
    else:
        selected = 'custom'
        selected_url = core.get_config()['channel_url']

        for name, url in channels.items():
            if url == selected_url:
                selected = name
                break

        res = {'selected': selected,
               'list': core.get_channel_list()}
        return web.json_response(res, status=200)

    return web.Response(status=200)


def add_target_blank(html_text):
    pattern = r'(<a\s+href="[^"]*"\s*[^>]*)(>)'

    def add_target(match):
        if 'target=' not in match.group(1):
            return match.group(1) + ' target="_blank"' + match.group(2)
        return match.group(0)

    modified_html = re.sub(pattern, add_target, html_text)

    return modified_html


@PromptServer.instance.routes.get("/manager/notice")
async def get_notice(request):
    url = "github.com"
    path = "/ltdrdata/ltdrdata.github.io/wiki/News"

    async with aiohttp.ClientSession(trust_env=True, connector=aiohttp.TCPConnector(verify_ssl=False)) as session:
        async with session.get(f"https://{url}{path}") as response:
            if response.status == 200:
                # html_content = response.read().decode('utf-8')
                html_content = await response.text()

                pattern = re.compile(r'<div class="markdown-body">([\s\S]*?)</div>')
                match = pattern.search(html_content)

                if match:
                    markdown_content = match.group(1)
                    version_tag = core.get_comfyui_tag()
                    if version_tag is None:
                        markdown_content += f"<HR>ComfyUI: {core.comfy_ui_revision}[{comfy_ui_hash[:6]}]({core.comfy_ui_commit_datetime.date()})"
                    else:
                        markdown_content += (f"<HR>ComfyUI: {version_tag}<BR>"
                                             f"&nbsp; &nbsp; &nbsp; &nbsp; &nbsp;({core.comfy_ui_commit_datetime.date()})")
                    # markdown_content += f"<BR>&nbsp; &nbsp; &nbsp; &nbsp; &nbsp;()"
                    markdown_content += f"<BR>Manager: {core.version_str}"

                    markdown_content = add_target_blank(markdown_content)

                    try:
                        if core.is_electron:
                            pass
                        elif core.comfy_ui_commit_datetime == datetime.datetime(1900, 1, 1, 0, 0, 0):
                            markdown_content = f'<P style="text-align: center; color:red; background-color:white; font-weight:bold">Your ComfyUI isn\'t git repo.</P>' + markdown_content
                        elif core.comfy_ui_required_commit_datetime.date() > core.comfy_ui_commit_datetime.date():
                            markdown_content = f'<P style="text-align: center; color:red; background-color:white; font-weight:bold">Your ComfyUI is too OUTDATED!!!</P>' + markdown_content
                    except Exception as error:
                        logging.warning("Unexpected error when checking ComfyUI version via git.")

                    return web.Response(text=markdown_content, status=200)
                else:
                    return web.Response(text="Unable to retrieve Notice", status=200)
            else:
                return web.Response(text="Unable to retrieve Notice", status=200)


@PromptServer.instance.routes.get("/manager/reboot")
def restart(self):
    if not is_allowed_security_level('middle'):
        print(SECURITY_MESSAGE_MIDDLE_OR_BELOW)
        return web.Response(status=403)

    try:
        sys.stdout.close_log()
    except Exception as e:
        pass

    if '__COMFY_CLI_SESSION__' in os.environ:
        with open(os.path.join(os.environ['__COMFY_CLI_SESSION__'] + '.reboot'), 'w') as file:
            pass

        print(f"\nRestarting...\n\n")
        exit(0)

    print(f"\nRestarting... [Legacy Mode]\n\n")

    sys_argv = sys.argv.copy()
    if '--windows-standalone-build' in sys_argv:
        sys_argv.remove('--windows-standalone-build')

    if sys.platform.startswith('win32'):
        return os.execv(sys.executable, ['"' + sys.executable + '"', '"' + sys.argv[0] + '"'] + sys.argv[1:])
    else:
        return os.execv(sys.executable, [sys.executable] + sys.argv)


def sanitize_filename(input_string):
    # 알파벳, 숫자, 및 밑줄 이외의 문자를 밑줄로 대체
    result_string = re.sub(r'[^a-zA-Z0-9_]', '_', input_string)
    return result_string


@PromptServer.instance.routes.post("/manager/component/save")
async def save_component(request):
    try:
        data = await request.json()
        name = data['name']
        workflow = data['workflow']

        if not os.path.exists(components_path):
            os.mkdir(components_path)

        if 'packname' in workflow and workflow['packname'] != '':
            sanitized_name = sanitize_filename(workflow['packname']) + '.pack'
        else:
            sanitized_name = sanitize_filename(name) + '.json'

        filepath = os.path.join(components_path, sanitized_name)
        components = {}
        if os.path.exists(filepath):
            with open(filepath) as f:
                components = json.load(f)

        components[name] = workflow

        with open(filepath, 'w') as f:
            json.dump(components, f, indent=4, sort_keys=True)
        return web.Response(text=filepath, status=200)
    except:
        return web.Response(status=400)


@PromptServer.instance.routes.post("/manager/component/loads")
async def load_components(request):
    try:
        json_files = [f for f in os.listdir(components_path) if f.endswith('.json')]
        pack_files = [f for f in os.listdir(components_path) if f.endswith('.pack')]

        components = {}
        for json_file in json_files + pack_files:
            file_path = os.path.join(components_path, json_file)
            with open(file_path, 'r') as file:
                try:
                    # When there is a conflict between the .pack and the .json, the pack takes precedence and overrides.
                    components.update(json.load(file))
                except json.JSONDecodeError as e:
                    print(f"[ComfyUI-Manager] Error decoding component file in file {json_file}: {e}")

        return web.json_response(components)
    except Exception as e:
        print(f"[ComfyUI-Manager] failed to load components\n{e}")
        return web.Response(status=400)


args.enable_cors_header = "*"
if hasattr(PromptServer.instance, "app"):
    app = PromptServer.instance.app
    cors_middleware = server.create_cors_middleware(args.enable_cors_header)
    app.middlewares.append(cors_middleware)


def sanitize(data):
    return data.replace("<", "&lt;").replace(">", "&gt;")


async def _confirm_try_install(sender, custom_node_url, msg):
    json_obj = await core.get_data_by_mode('default', 'custom-node-list.json')

    sender = sanitize(sender)
    msg = sanitize(msg)
    target = core.lookup_customnode_by_url(json_obj, custom_node_url)

    if target is not None:
        PromptServer.instance.send_sync("cm-api-try-install-customnode",
                                        {"sender": sender, "target": target, "msg": msg})
    else:
        print(f"[ComfyUI Manager API] Failed to try install - Unknown custom node url '{custom_node_url}'")


def confirm_try_install(sender, custom_node_url, msg):
    asyncio.run(_confirm_try_install(sender, custom_node_url, msg))


cm_global.register_api('cm.try-install-custom-node', confirm_try_install)

import asyncio


async def default_cache_update():
    async def get_cache(filename):
        uri = 'https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main/' + filename
        cache_uri = str(core.simple_hash(uri)) + '_' + filename
        cache_uri = os.path.join(core.cache_dir, cache_uri)

        json_obj = await core.get_data(uri, True)

        with core.cache_lock:
            with open(cache_uri, "w", encoding='utf-8') as file:
                json.dump(json_obj, file, indent=4, sort_keys=True)
                print(f"[ComfyUI-Manager] default cache updated: {uri}")

    a = get_cache("custom-node-list.json")
    b = get_cache("extension-node-map.json")
    c = get_cache("model-list.json")
    d = get_cache("alter-list.json")
    e = get_cache("github-stats.json")

    await asyncio.gather(a, b, c, d, e)


threading.Thread(target=lambda: asyncio.run(default_cache_update())).start()

if not os.path.exists(core.config_path):
    core.get_config()
    core.write_config()


cm_global.register_extension('ComfyUI-Manager',
                             {'version': core.version,
                                 'name': 'ComfyUI Manager',
                                 'nodes': {},
                                 'description': 'It provides the ability to manage custom nodes in ComfyUI.', })

