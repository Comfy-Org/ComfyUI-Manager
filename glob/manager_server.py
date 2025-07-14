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
from datetime import datetime

from server import PromptServer
import manager_core as core
import manager_util
import cm_global
import logging
import asyncio
import queue

import manager_downloader


logging.info(f"### Loading: ComfyUI-Manager ({core.version_str})")
logging.info("[ComfyUI-Manager] network_mode: " + core.get_config()['network_mode'])

comfy_ui_hash = "-"
comfyui_tag = None

SECURITY_MESSAGE_MIDDLE_OR_BELOW = "ERROR: To use this action, a security_level of `middle or below` is required. Please contact the administrator.\nReference: https://github.com/ltdrdata/ComfyUI-Manager#security-policy"
SECURITY_MESSAGE_NORMAL_MINUS = "ERROR: To use this feature, you must either set '--listen' to a local IP and set the security level to 'normal-' or lower, or set the security level to 'middle' or 'weak'. Please contact the administrator.\nReference: https://github.com/ltdrdata/ComfyUI-Manager#security-policy"
SECURITY_MESSAGE_GENERAL = "ERROR: This installation is not allowed in this security_level. Please contact the administrator.\nReference: https://github.com/ltdrdata/ComfyUI-Manager#security-policy"
SECURITY_MESSAGE_NORMAL_MINUS_MODEL = "ERROR: Downloading models that are not in '.safetensors' format is only allowed for models registered in the 'default' channel at this security level. If you want to download this model, set the security level to 'normal-' or lower."

routes = PromptServer.instance.routes

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

def is_loopback(address):
    import ipaddress
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False

is_local_mode = is_loopback(args.listen)


model_dir_name_map = {
    "checkpoints": "checkpoints",
    "checkpoint": "checkpoints",
    "unclip": "checkpoints",
    "text_encoders": "text_encoders",
    "clip": "text_encoders",
    "vae": "vae",
    "lora": "loras",
    "t2i-adapter": "controlnet",
    "t2i-style": "controlnet",
    "controlnet": "controlnet",
    "clip_vision": "clip_vision",
    "gligen": "gligen",
    "upscale": "upscale_models",
    "embedding": "embeddings",
    "embeddings": "embeddings",
    "unet": "diffusion_models",
    "diffusion_model": "diffusion_models",
}


def is_allowed_security_level(level):
    if level == 'block':
        return False
    elif level == 'high':
        if is_local_mode:
            return core.get_config()['security_level'] in ['weak', 'normal-']
        else:
            return core.get_config()['security_level'] == 'weak'
    elif level == 'middle':
        return core.get_config()['security_level'] in ['weak', 'normal', 'normal-']
    else:
        return True


async def get_risky_level(files, pip_packages):
    json_data1 = await core.get_data_by_mode('local', 'custom-node-list.json')
    json_data2 = await core.get_data_by_mode('cache', 'custom-node-list.json', channel_url='https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main')

    all_urls = set()
    for x in json_data1['custom_nodes'] + json_data2['custom_nodes']:
        all_urls.update(x.get('files', []))

    for x in files:
        if x not in all_urls:
            return "high"

    all_pip_packages = set()
    for x in json_data1['custom_nodes'] + json_data2['custom_nodes']:
        all_pip_packages.update(x.get('pip', []))

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
            logging.error(f"[ComfyUI-Manager] Unexpected behavior: `{cmd}`")
            return 0

        process = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, env=core.get_script_env())

        stdout_thread = threading.Thread(target=handle_stream, args=(process.stdout, ""))
        stderr_thread = threading.Thread(target=handle_stream, args=(process.stderr, "[!]"))

        stdout_thread.start()
        stderr_thread.start()

        stdout_thread.join()
        stderr_thread.join()

        return process.wait()


core.manager_funcs = ManagerFuncsInComfyUI()

sys.path.append('../..')

from manager_downloader import download_url, download_url_with_agent

core.comfy_path = os.path.dirname(folder_paths.__file__)
core.js_path = os.path.join(core.comfy_path, "web", "extensions")

local_db_model = os.path.join(manager_util.comfyui_manager_path, "model-list.json")
local_db_alter = os.path.join(manager_util.comfyui_manager_path, "alter-list.json")
local_db_custom_node_list = os.path.join(manager_util.comfyui_manager_path, "custom-node-list.json")
local_db_extension_node_mappings = os.path.join(manager_util.comfyui_manager_path, "extension-node-map.json")


def set_preview_method(method):
    if method == 'auto':
        args.preview_method = latent_preview.LatentPreviewMethod.Auto
    elif method == 'latent2rgb':
        args.preview_method = latent_preview.LatentPreviewMethod.Latent2RGB
    elif method == 'taesd':
        args.preview_method = latent_preview.LatentPreviewMethod.TAESD
    else:
        args.preview_method = latent_preview.LatentPreviewMethod.NoPreviews

    core.get_config()['preview_method'] = method


if args.preview_method == latent_preview.LatentPreviewMethod.NoPreviews:
    set_preview_method(core.get_config()['preview_method'])
else:
    logging.warning("[ComfyUI-Manager] Since --preview-method is set, ComfyUI-Manager's preview method feature will be ignored.")


def set_component_policy(mode):
    core.get_config()['component_policy'] = mode

def set_update_policy(mode):
    core.get_config()['update_policy'] = mode

def set_db_mode(mode):
    core.get_config()['db_mode'] = mode

def print_comfyui_version():
    global comfy_ui_hash
    global comfyui_tag

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

        comfyui_tag = core.get_comfyui_tag()

        try:
            if not os.environ.get('__COMFYUI_DESKTOP_VERSION__') and core.comfy_ui_commit_datetime.date() < core.comfy_ui_required_commit_datetime.date():
                logging.warning(f"\n\n## [WARN] ComfyUI-Manager: Your ComfyUI version ({core.comfy_ui_revision})[{core.comfy_ui_commit_datetime.date()}] is too old. Please update to the latest version. ##\n\n")
        except:
            pass

        # process on_revision_detected -->
        if 'cm.on_revision_detected_handler' in cm_global.variables:
            for k, f in cm_global.variables['cm.on_revision_detected_handler']:
                try:
                    f(core.comfy_ui_revision)
                except Exception:
                    logging.error(f"[ERROR] '{k}' on_revision_detected_handler")
                    traceback.print_exc()

            del cm_global.variables['cm.on_revision_detected_handler']
        else:
            logging.warning("[ComfyUI-Manager] Some features are restricted due to your ComfyUI being outdated.")
        # <--

        if current_branch == "master":
            if comfyui_tag:
                logging.info(f"### ComfyUI Version: {comfyui_tag} | Released on '{core.comfy_ui_commit_datetime.date()}'")
            else:
                logging.info(f"### ComfyUI Revision: {core.comfy_ui_revision} [{comfy_ui_hash[:8]}] | Released on '{core.comfy_ui_commit_datetime.date()}'")
        else:
            if comfyui_tag:
                logging.info(f"### ComfyUI Version: {comfyui_tag} on '{current_branch}' | Released on '{core.comfy_ui_commit_datetime.date()}'")
            else:
                logging.info(f"### ComfyUI Revision: {core.comfy_ui_revision} on '{current_branch}' [{comfy_ui_hash[:8]}] | Released on '{core.comfy_ui_commit_datetime.date()}'")
    except:
        if is_detached:
            logging.info(f"### ComfyUI Revision: {core.comfy_ui_revision} [{comfy_ui_hash[:8]}] *DETACHED | Released on '{core.comfy_ui_commit_datetime.date()}'")
        else:
            logging.info("### ComfyUI Revision: UNKNOWN (The currently installed ComfyUI is not a Git repository)")


print_comfyui_version()
core.check_invalid_nodes()



def setup_environment():
    git_exe = core.get_config()['git_exe']

    if git_exe != '':
        git.Git().update_environment(GIT_PYTHON_GIT_EXECUTABLE=git_exe)


setup_environment()

# Expand Server api

from aiohttp import web
import aiohttp
import json
import zipfile
import urllib.request


def get_model_dir(data, show_log=False):
    if 'download_model_base' in folder_paths.folder_names_and_paths:
        models_base = folder_paths.folder_names_and_paths['download_model_base'][0][0]
    else:
        models_base = folder_paths.models_dir

    # NOTE: Validate to prevent path traversal.
    if any(char in data['filename'] for char in {'/', '\\', ':'}):
        return None

    def resolve_custom_node(save_path):
        save_path = save_path[13:] # remove 'custom_nodes/'

        # NOTE: Validate to prevent path traversal.
        if save_path.startswith(os.path.sep) or ':' in save_path:
            return None

        repo_name = save_path.replace('\\','/').split('/')[0] # get custom node repo name

        # NOTE: The creation of files within the custom node path should be removed in the future.
        repo_path = core.lookup_installed_custom_nodes_legacy(repo_name)
        if repo_path is not None and repo_path[0]:
            # Returns the retargeted path based on the actually installed repository
            return os.path.join(os.path.dirname(repo_path[1]), save_path)
        else:
            return None

    if data['save_path'] != 'default':
        if '..' in data['save_path'] or data['save_path'].startswith('/'):
            if show_log:
                logging.info(f"[WARN] '{data['save_path']}' is not allowed path. So it will be saved into 'models/etc'.")
            base_model = os.path.join(models_base, "etc")
        else:
            if data['save_path'].startswith("custom_nodes"):
                base_model = resolve_custom_node(data['save_path'])
                if base_model is None:
                    if show_log:
                        logging.info(f"[ComfyUI-Manager] The target custom node for model download is not installed: {data['save_path']}")
                    return None
            else:
                base_model = os.path.join(models_base, data['save_path'])
    else:
        model_dir_name = model_dir_name_map.get(data['type'].lower())
        if model_dir_name is not None:
            base_model = folder_paths.folder_names_and_paths[model_dir_name][0][0]
        else:
            base_model = os.path.join(models_base, "etc")

    return base_model


def get_model_path(data, show_log=False):
    base_model = get_model_dir(data, show_log)
    if base_model is None:
        return None
    else:
        if data['filename'] == '<huggingface>':
            return os.path.join(base_model, os.path.basename(data['url']))
        else:
            return os.path.join(base_model, data['filename'])


def check_state_of_git_node_pack(node_packs, do_fetch=False, do_update_check=True, do_update=False):
    if do_fetch:
        print("Start fetching...", end="")
    elif do_update:
        print("Start updating...", end="")
    elif do_update_check:
        print("Start update check...", end="")

    def process_custom_node(item):
        core.check_state_of_git_node_pack_single(item, do_fetch, do_update_check, do_update)

    with concurrent.futures.ThreadPoolExecutor(4) as executor:
        for k, v in node_packs.items():
            if v.get('active_version') in ['unknown', 'nightly']:
                executor.submit(process_custom_node, v)

    if do_fetch:
        print("\x1b[2K\rFetching done.")
    elif do_update:
        update_exists = any(item.get('updatable', False) for item in node_packs.values())
        if update_exists:
            print("\x1b[2K\rUpdate done.")
        else:
            print("\x1b[2K\rAll extensions are already up-to-date.")
    elif do_update_check:
        print("\x1b[2K\rUpdate check done.")


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


task_queue = queue.Queue()
nodepack_result = {}
model_result = {}
tasks_in_progress = set()
task_worker_lock = threading.Lock()

async def task_worker():
    global task_queue
    global nodepack_result
    global model_result
    global tasks_in_progress

    async def do_install(item) -> str:
        ui_id, node_spec_str, channel, mode, skip_post_install = item

        try:
            node_spec = core.unified_manager.resolve_node_spec(node_spec_str)
            if node_spec is None:
                logging.error(f"Cannot resolve install target: '{node_spec_str}'")
                return f"Cannot resolve install target: '{node_spec_str}'"

            node_name, version_spec, is_specified = node_spec
            res = await core.unified_manager.install_by_id(node_name, version_spec, channel, mode, return_postinstall=skip_post_install)
            # discard post install if skip_post_install mode

            if res.action not in ['skip', 'enable', 'install-git', 'install-cnr', 'switch-cnr']:
                logging.error(f"[ComfyUI-Manager] Installation failed:\n{res.msg}")
                return res.msg

            elif not res.result:
                logging.error(f"[ComfyUI-Manager] Installation failed:\n{res.msg}")
                return res.msg

            return 'success'
        except Exception:
            traceback.print_exc()
            return f"Installation failed:\n{node_spec_str}"

    async def do_update(item):
        ui_id, node_name, node_ver = item

        try:
            res = core.unified_manager.unified_update(node_name, node_ver)

            if res.ver == 'unknown':
                url = core.unified_manager.unknown_active_nodes[node_name][0]
                try:
                    title = os.path.basename(url)
                except Exception:
                    title = node_name
            else:
                url = core.unified_manager.cnr_map[node_name].get('repository')
                title = core.unified_manager.cnr_map[node_name]['name']

            manager_util.clear_pip_cache()

            if url is not None:
                base_res = {'url': url, 'title': title}
            else:
                base_res = {'title': title}

            if res.result:
                if res.action == 'skip':
                    base_res['msg'] = 'skip'
                    return base_res
                else:
                    base_res['msg'] = 'success'
                    return base_res

            base_res['msg'] = f"An error occurred while updating '{node_name}'."
            logging.error(f"\nERROR: An error occurred while updating '{node_name}'. (res.result={res.result}, res.action={res.action})")
            return base_res
        except Exception:
            traceback.print_exc()

        return {'msg':f"An error occurred while updating '{node_name}'."}

    async def do_update_comfyui(is_stable) -> str:
        try:
            repo_path = os.path.dirname(folder_paths.__file__)
            latest_tag = None
            if is_stable:
                res, latest_tag = core.update_to_stable_comfyui(repo_path)
            else:
                res = core.update_path(repo_path)
                
            if res == "fail":
                logging.error("ComfyUI update failed")
                return "fail"
            elif res == "updated":
                if is_stable:
                    logging.info("ComfyUI is updated to latest stable version.")
                    return "success-stable-"+latest_tag
                else:
                    logging.info("ComfyUI is updated to latest nightly version.")
                    return "success-nightly"
            else:  # skipped
                logging.info("ComfyUI is up-to-date.")
                return "skip"

        except Exception:
            traceback.print_exc()

        return "An error occurred while updating 'comfyui'."

    async def do_fix(item) -> str:
        ui_id, node_name, node_ver = item

        try:
            res = core.unified_manager.unified_fix(node_name, node_ver)

            if res.result:
                return 'success'
            else:
                logging.error(res.msg)

            logging.error(f"\nERROR: An error occurred while fixing '{node_name}@{node_ver}'.")
        except Exception:
            traceback.print_exc()

        return f"An error occurred while fixing '{node_name}@{node_ver}'."

    async def do_uninstall(item) -> str:
        ui_id, node_name, is_unknown = item

        try:
            res = core.unified_manager.unified_uninstall(node_name, is_unknown)

            if res.result:
                return 'success'

            logging.error(f"\nERROR: An error occurred while uninstalling '{node_name}'.")
        except Exception:
            traceback.print_exc()

        return f"An error occurred while uninstalling '{node_name}'."

    async def do_disable(item) -> str:
        ui_id, node_name, is_unknown = item

        try:
            res = core.unified_manager.unified_disable(node_name, is_unknown)

            if res:
                return 'success'

        except Exception:
            traceback.print_exc()

        return f"Failed to disable: '{node_name}'"

    async def do_install_model(item) -> str:
        ui_id, json_data = item

        model_path = get_model_path(json_data)
        model_url = json_data['url']

        res = False

        try:
            if model_path is not None:
                logging.info(f"Install model '{json_data['name']}' from '{model_url}' into '{model_path}'")

                if json_data['filename'] == '<huggingface>':
                    if os.path.exists(os.path.join(model_path, os.path.dirname(json_data['url']))):
                        logging.error(f"[ComfyUI-Manager] the model path already exists: {model_path}")
                        return f"The model path already exists: {model_path}"

                    logging.info(f"[ComfyUI-Manager] Downloading '{model_url}' into '{model_path}'")
                    manager_downloader.download_repo_in_bytes(repo_id=model_url, local_dir=model_path)

                    return 'success'

                elif not core.get_config()['model_download_by_agent'] and (
                        model_url.startswith('https://github.com') or model_url.startswith('https://huggingface.co') or model_url.startswith('https://heibox.uni-heidelberg.de')):
                    model_dir = get_model_dir(json_data, True)
                    download_url(model_url, model_dir, filename=json_data['filename'])
                    if model_path.endswith('.zip'):
                        res = core.unzip(model_path)
                    else:
                        res = True

                    if res:
                        return 'success'
                else:
                    res = download_url_with_agent(model_url, model_path)
                    if res and model_path.endswith('.zip'):
                        res = core.unzip(model_path)
            else:
                logging.error(f"[ComfyUI-Manager] Model installation error: invalid model type - {json_data['type']}")

            if res:
                return 'success'

        except Exception as e:
            logging.error(f"[ComfyUI-Manager] ERROR: {e}")

        return f"Model installation error: {model_url}"

    stats = {}

    while True:
        done_count = len(nodepack_result) + len(model_result)
        total_count = done_count + task_queue.qsize()

        if task_queue.empty():
            logging.info(f"\n[ComfyUI-Manager] Queued works are completed.\n{stats}")

            logging.info("\nAfter restarting ComfyUI, please refresh the browser.")
            PromptServer.instance.send_sync("cm-queue-status",
                                            {'status': 'done',
                                             'nodepack_result': nodepack_result, 'model_result': model_result,
                                             'total_count': total_count, 'done_count': done_count})
            nodepack_result = {}
            task_queue = queue.Queue()
            return  # terminate worker thread

        with task_worker_lock:
            kind, item = task_queue.get()
            tasks_in_progress.add((kind, item[0]))

        try:
            if kind == 'install':
                msg = await do_install(item)
            elif kind == 'install-model':
                msg = await do_install_model(item)
            elif kind == 'update':
                msg = await do_update(item)
            elif kind == 'update-main':
                msg = await do_update(item)
            elif kind == 'update-comfyui':
                msg = await do_update_comfyui(item[1])
            elif kind == 'fix':
                msg = await do_fix(item)
            elif kind == 'uninstall':
                msg = await do_uninstall(item)
            elif kind == 'disable':
                msg = await do_disable(item)
            else:
                msg = "Unexpected kind: " + kind
        except Exception:
            traceback.print_exc()
            msg = f"Exception: {(kind, item)}"

        with task_worker_lock:
            tasks_in_progress.remove((kind, item[0]))

            ui_id = item[0]
            if kind == 'install-model':
                model_result[ui_id] = msg
                ui_target = "model_manager"
            elif kind == 'update-main':
                nodepack_result[ui_id] = msg
                ui_target = "main"
            elif kind == 'update-comfyui':
                nodepack_result['comfyui'] = msg
                ui_target = "main"
            elif kind == 'update':
                nodepack_result[ui_id] = msg['msg']
                ui_target = "nodepack_manager"
            else:
                nodepack_result[ui_id] = msg
                ui_target = "nodepack_manager"

        stats[kind] = stats.get(kind, 0) + 1

        PromptServer.instance.send_sync("cm-queue-status",
                                        {'status': 'in_progress', 'target': item[0], 'ui_target': ui_target,
                                         'total_count': total_count, 'done_count': done_count})


@routes.get("/customnode/getmappings")
async def fetch_customnode_mappings(request):
    """
    provide unified (node -> node pack) mapping list
    """
    mode = request.rel_url.query["mode"]

    nickname_mode = False
    if mode == "nickname":
        mode = "local"
        nickname_mode = True

    json_obj = await core.get_data_by_mode(mode, 'extension-node-map.json')
    json_obj = core.map_to_unified_keys(json_obj)

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


@routes.get("/customnode/fetch_updates")
async def fetch_updates(request):
    try:
        if request.rel_url.query["mode"] == "local":
            channel = 'local'
        else:
            channel = core.get_config()['channel_url']

        await core.unified_manager.reload(request.rel_url.query["mode"])
        await core.unified_manager.get_custom_nodes(channel, request.rel_url.query["mode"])

        res = core.unified_manager.fetch_or_pull_git_repo(is_pull=False)

        for x in res['failed']:
            logging.error(f"FETCH FAILED: {x}")

        logging.info("\nDone.")

        if len(res['updated']) > 0:
            return web.Response(status=201)

        return web.Response(status=200)
    except:
        traceback.print_exc()
        return web.Response(status=400)


@routes.get("/manager/queue/update_all")
async def update_all(request):
    if not is_allowed_security_level('middle'):
        logging.error(SECURITY_MESSAGE_MIDDLE_OR_BELOW)
        return web.Response(status=403)

    with task_worker_lock:
        is_processing = task_worker_thread is not None and task_worker_thread.is_alive()
        if is_processing:
            return web.Response(status=401)
        
    await core.save_snapshot_with_postfix('autosave')

    if request.rel_url.query["mode"] == "local":
        channel = 'local'
    else:
        channel = core.get_config()['channel_url']

    await core.unified_manager.reload(request.rel_url.query["mode"])
    await core.unified_manager.get_custom_nodes(channel, request.rel_url.query["mode"])

    for k, v in core.unified_manager.active_nodes.items():
        if k == 'comfyui-manager':
            # skip updating comfyui-manager if desktop version
            if os.environ.get('__COMFYUI_DESKTOP_VERSION__'):
                continue

        update_item = k, k, v[0]
        task_queue.put(("update-main", update_item))

    for k, v in core.unified_manager.unknown_active_nodes.items():
        if k == 'comfyui-manager':
            # skip updating comfyui-manager if desktop version
            if os.environ.get('__COMFYUI_DESKTOP_VERSION__'):
                continue

        update_item = k, k, 'unknown'
        task_queue.put(("update-main", update_item))

    return web.Response(status=200)


def convert_markdown_to_html(input_text):
    pattern_a = re.compile(r'\[a/([^]]+)]\(([^)]+)\)')
    pattern_w = re.compile(r'\[w/([^]]+)]')
    pattern_i = re.compile(r'\[i/([^]]+)]')
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
        x['description'] = convert_markdown_to_html(manager_util.sanitize_tag(x['description']))

    if 'name' in x:
        x['name'] = manager_util.sanitize_tag(x['name'])

    if 'title' in x:
        x['title'] = manager_util.sanitize_tag(x['title'])


# freeze imported version
startup_time_installed_node_packs = core.get_installed_node_packs()
@routes.get("/customnode/installed")
async def installed_list(request):
    mode = request.query.get('mode', 'default')

    if mode == 'imported':
        res = startup_time_installed_node_packs
    else:
        res = core.get_installed_node_packs()

    return web.json_response(res, content_type='application/json')


@routes.get("/customnode/getlist")
async def fetch_customnode_list(request):
    """
    provide unified custom node list
    """
    if request.rel_url.query.get("skip_update", '').lower() == "true":
        skip_update = True
    else:
        skip_update = False

    if request.rel_url.query["mode"] == "local":
        channel = 'local'
    else:
        channel = core.get_config()['channel_url']

    node_packs = await core.get_unified_total_nodes(channel, request.rel_url.query["mode"], 'cache')
    json_obj_github = core.get_data_by_mode(request.rel_url.query["mode"], 'github-stats.json', 'default')
    json_obj_extras = core.get_data_by_mode(request.rel_url.query["mode"], 'extras.json', 'default')

    core.populate_github_stats(node_packs, await json_obj_github)
    core.populate_favorites(node_packs, await json_obj_extras)

    check_state_of_git_node_pack(node_packs, not skip_update, do_update_check=not skip_update)

    for v in node_packs.values():
        populate_markdown(v)

    if channel != 'local':
        found = 'custom'

        for name, url in core.get_channel_dict().items():
            if url == channel:
                found = name
                break

        channel = found

    result = dict(channel=channel, node_packs=node_packs.to_dict())

    return web.json_response(result, content_type='application/json')


@routes.get("/customnode/alternatives")
async def fetch_customnode_alternatives(request):
    alter_json = await core.get_data_by_mode(request.rel_url.query["mode"], 'alter-list.json')

    res = {}

    for item in alter_json['items']:
        populate_markdown(item)
        res[item['id']] = item

    res = core.map_to_unified_keys(res)

    return web.json_response(res, content_type='application/json')


def check_model_installed(json_obj):
    def is_exists(model_dir_name, filename, url):
        if filename == '<huggingface>':
            filename = os.path.basename(url)

        dirs = folder_paths.get_folder_paths(model_dir_name)

        for x in dirs:
            if os.path.exists(os.path.join(x, filename)):
                return True

        return False

    model_dir_names = ['checkpoints', 'loras', 'vae', 'text_encoders', 'diffusion_models', 'clip_vision', 'embeddings',
                       'diffusers', 'vae_approx', 'controlnet', 'gligen', 'upscale_models', 'hypernetworks',
                       'photomaker', 'classifiers']

    total_models_files = set()
    for x in model_dir_names:
        for y in folder_paths.get_filename_list(x):
            total_models_files.add(y)

    def process_model_phase(item):
        if 'diffusion' not in item['filename'] and 'pytorch' not in item['filename'] and 'model' not in item['filename']:
            # non-general name case
            if item['filename'] in total_models_files:
                item['installed'] = 'True'
                return

        if item['save_path'] == 'default':
            model_dir_name = model_dir_name_map.get(item['type'].lower())
            if model_dir_name is not None:
                item['installed'] = str(is_exists(model_dir_name, item['filename'], item['url']))
            else:
                item['installed'] = 'False'
        else:
            model_dir_name = item['save_path'].split('/')[0]
            if model_dir_name in folder_paths.folder_names_and_paths:
                if is_exists(model_dir_name, item['filename'], item['url']):
                    item['installed'] = 'True'

            if 'installed' not in item:
                if item['filename'] == '<huggingface>':
                    filename = os.path.basename(item['url'])
                else:
                    filename = item['filename']

                fullpath = os.path.join(folder_paths.models_dir, item['save_path'], filename)

                item['installed'] = 'True' if os.path.exists(fullpath) else 'False'

    with concurrent.futures.ThreadPoolExecutor(8) as executor:
        for item in json_obj['models']:
            executor.submit(process_model_phase, item)


@routes.get("/externalmodel/getlist")
async def fetch_externalmodel_list(request):
    # The model list is only allowed in the default channel, yet.
    json_obj = await core.get_data_by_mode(request.rel_url.query["mode"], 'model-list.json')

    check_model_installed(json_obj)

    for x in json_obj['models']:
        populate_markdown(x)

    return web.json_response(json_obj, content_type='application/json')


@PromptServer.instance.routes.get("/snapshot/getlist")
async def get_snapshot_list(request):
    items = [f[:-5] for f in os.listdir(core.manager_snapshot_path) if f.endswith('.json')]
    items.sort(reverse=True)
    return web.json_response({'items': items}, content_type='application/json')


@routes.get("/snapshot/remove")
async def remove_snapshot(request):
    if not is_allowed_security_level('middle'):
        logging.error(SECURITY_MESSAGE_MIDDLE_OR_BELOW)
        return web.Response(status=403)

    try:
        target = request.rel_url.query["target"]

        path = os.path.join(core.manager_snapshot_path, f"{target}.json")
        if os.path.exists(path):
            os.remove(path)

        return web.Response(status=200)
    except:
        return web.Response(status=400)


@routes.get("/snapshot/restore")
async def restore_snapshot(request):
    if not is_allowed_security_level('middle'):
        logging.error(SECURITY_MESSAGE_MIDDLE_OR_BELOW)
        return web.Response(status=403)

    try:
        target = request.rel_url.query["target"]

        path = os.path.join(core.manager_snapshot_path, f"{target}.json")
        if os.path.exists(path):
            if not os.path.exists(core.manager_startup_script_path):
                os.makedirs(core.manager_startup_script_path)

            target_path = os.path.join(core.manager_startup_script_path, "restore-snapshot.json")
            shutil.copy(path, target_path)

            logging.info(f"Snapshot restore scheduled: `{target}`")
            return web.Response(status=200)

        logging.error(f"Snapshot file not found: `{path}`")
        return web.Response(status=400)
    except:
        return web.Response(status=400)


@routes.get("/snapshot/get_current")
async def get_current_snapshot_api(request):
    try:
        return web.json_response(await core.get_current_snapshot(), content_type='application/json')
    except:
        return web.Response(status=400)


@routes.get("/snapshot/save")
async def save_snapshot(request):
    try:
        await core.save_snapshot_with_postfix('snapshot')
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
                zip_ref.extractall(core.get_default_custom_nodes_path())

            os.remove(temp_filename)
        except Exception as e:
            logging.error(f"Install(unzip) error: {url} / {e}", file=sys.stderr)
            return False

    logging.info("Installation was successful.")
    return True


def copy_install(files, js_path_name=None):
    for url in files:
        if url.endswith("/"):
            url = url[:-1]
        try:
            filename = os.path.basename(url)
            if url.endswith(".py"):
                download_url(url, core.get_default_custom_nodes_path(), filename)
            else:
                path = os.path.join(core.js_path, js_path_name) if js_path_name is not None else core.js_path
                if not os.path.exists(path):
                    os.makedirs(path)
                download_url(url, path, filename)

        except Exception as e:
            logging.error(f"Install(copy) error: {url} / {e}", file=sys.stderr)
            return False

    logging.info("Installation was successful.")
    return True


def copy_uninstall(files, js_path_name='.'):
    for url in files:
        if url.endswith("/"):
            url = url[:-1]
        dir_name = os.path.basename(url)
        base_path = core.get_default_custom_nodes_path() if url.endswith('.py') else os.path.join(core.js_path, js_path_name)
        file_path = os.path.join(base_path, dir_name)

        try:
            if os.path.exists(file_path):
                os.remove(file_path)
            elif os.path.exists(file_path + ".disabled"):
                os.remove(file_path + ".disabled")
        except Exception as e:
            logging.error(f"Uninstall(copy) error: {url} / {e}", file=sys.stderr)
            return False

    logging.info("Uninstallation was successful.")
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
        base_path = core.get_default_custom_nodes_path() if url.endswith('.py') else os.path.join(core.js_path, js_path_name)
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
            logging.error(f"{action_name}(copy) error: {url} / {e}", file=sys.stderr)

            return False

    logging.info(f"{action_name} was successful.")
    return True


@routes.get("/customnode/versions/{node_name}")
async def get_cnr_versions(request):
    node_name = request.match_info.get("node_name", None)
    versions = core.cnr_utils.all_versions_of_node(node_name)

    if versions is not None:
        return web.json_response(versions, content_type='application/json')

    return web.Response(status=400)


@routes.get("/customnode/disabled_versions/{node_name}")
async def get_disabled_versions(request):
    node_name = request.match_info.get("node_name", None)
    versions = []
    if node_name in core.unified_manager.nightly_inactive_nodes:
        versions.append(dict(version='nightly'))

    for v in core.unified_manager.cnr_inactive_nodes.get(node_name, {}).keys():
        versions.append(dict(version=v))

    if versions:
        return web.json_response(versions, content_type='application/json')

    return web.Response(status=400)


@routes.post("/customnode/import_fail_info")
async def import_fail_info(request):
    json_data = await request.json()

    if 'cnr_id' in json_data:
        module_name = core.unified_manager.get_module_name(json_data['cnr_id'])
    else:
        module_name = core.unified_manager.get_module_name(json_data['url'])

    if module_name is not None:
        info = cm_global.error_dict.get(module_name)
        if info is not None:
            return web.json_response(info)

    return web.Response(status=400)


@routes.post("/manager/queue/reinstall")
async def reinstall_custom_node(request):
    await uninstall_custom_node(request)
    await install_custom_node(request)


@routes.get("/manager/queue/reset")
async def reset_queue(request):
    global task_queue
    task_queue = queue.Queue()
    return web.Response(status=200)


@routes.get("/manager/queue/status")
async def queue_count(request):
    global task_queue

    with task_worker_lock:
        done_count = len(nodepack_result) + len(model_result)
        in_progress_count = len(tasks_in_progress)
        total_count = done_count + in_progress_count + task_queue.qsize()
        is_processing = task_worker_thread is not None and task_worker_thread.is_alive()

    return web.json_response({
        'total_count': total_count, 'done_count': done_count, 'in_progress_count': in_progress_count,
        'is_processing': is_processing})


@routes.post("/manager/queue/install")
async def install_custom_node(request):
    if not is_allowed_security_level('middle'):
        logging.error(SECURITY_MESSAGE_MIDDLE_OR_BELOW)
        return web.Response(status=403, text="A security error has occurred. Please check the terminal logs")

    json_data = await request.json()

    # non-nightly cnr is safe
    risky_level = None
    cnr_id = json_data.get('id')
    skip_post_install = json_data.get('skip_post_install')

    git_url = None

    selected_version = json_data.get('selected_version')
    if json_data['version'] != 'unknown' and selected_version != 'unknown':
        if skip_post_install:
            if cnr_id in core.unified_manager.nightly_inactive_nodes or cnr_id in core.unified_manager.cnr_inactive_nodes:
                core.unified_manager.unified_enable(cnr_id)
                return web.Response(status=200)
        elif selected_version is None:
            selected_version = 'latest'

        if selected_version != 'nightly':
            risky_level = 'low'
            node_spec_str = f"{cnr_id}@{selected_version}"
        else:
            node_spec_str = f"{cnr_id}@nightly"
            git_url = [json_data.get('repository')]
            if git_url is None:
                logging.error(f"[ComfyUI-Manager] Following node pack doesn't provide `nightly` version: ${git_url}")
                return web.Response(status=404, text=f"Following node pack doesn't provide `nightly` version: ${git_url}")
    elif json_data['version'] != 'unknown' and selected_version == 'unknown':
        logging.error(f"[ComfyUI-Manager] Invalid installation request: {json_data}")
        return web.Response(status=400, text="Invalid installation request")
    else:
        # unknown
        unknown_name = os.path.basename(json_data['files'][0])
        node_spec_str = f"{unknown_name}@unknown"
        git_url = json_data.get('files')

    # apply security policy if not cnr node (nightly isn't regarded as cnr node)
    if risky_level is None:
        if git_url is not None:
            risky_level = await get_risky_level(git_url, json_data.get('pip', []))
        else:
            return web.Response(status=404, text=f"Following node pack doesn't provide `nightly` version: ${git_url}")

    if not is_allowed_security_level(risky_level):
        logging.error(SECURITY_MESSAGE_GENERAL)
        return web.Response(status=404, text="A security error has occurred. Please check the terminal logs")

    install_item = json_data.get('ui_id'), node_spec_str, json_data['channel'], json_data['mode'], skip_post_install
    task_queue.put(("install", install_item))

    return web.Response(status=200)


task_worker_thread:threading.Thread = None

@routes.get("/manager/queue/start")
async def queue_start(request):
    global nodepack_result
    global model_result
    global task_worker_thread

    if task_worker_thread is not None and task_worker_thread.is_alive():
        return web.Response(status=201) # already in-progress

    nodepack_result = {}
    model_result = {}

    task_worker_thread = threading.Thread(target=lambda: asyncio.run(task_worker()))
    task_worker_thread.start()

    return web.Response(status=200)


@routes.post("/manager/queue/fix")
async def fix_custom_node(request):
    if not is_allowed_security_level('middle'):
        logging.error(SECURITY_MESSAGE_GENERAL)
        return web.Response(status=403, text="A security error has occurred. Please check the terminal logs")

    json_data = await request.json()

    node_id = json_data.get('id')
    node_ver = json_data['version']
    if node_ver != 'unknown':
        node_name = node_id
    else:
        # unknown
        node_name = os.path.basename(json_data['files'][0])

    update_item = json_data.get('ui_id'), node_name, json_data['version']
    task_queue.put(("fix", update_item))

    return web.Response(status=200)


@routes.post("/customnode/install/git_url")
async def install_custom_node_git_url(request):
    if not is_allowed_security_level('high'):
        logging.error(SECURITY_MESSAGE_NORMAL_MINUS)
        return web.Response(status=403)

    url = await request.text()
    res = await core.gitclone_install(url)

    if res.action == 'skip':
        logging.info(f"\nAlready installed: '{res.target}'")
        return web.Response(status=200)
    elif res.result:
        logging.info("\nAfter restarting ComfyUI, please refresh the browser.")
        return web.Response(status=200)

    logging.error(res.msg)
    return web.Response(status=400)


@routes.post("/customnode/install/pip")
async def install_custom_node_pip(request):
    if not is_allowed_security_level('high'):
        logging.error(SECURITY_MESSAGE_NORMAL_MINUS)
        return web.Response(status=403)

    packages = await request.text()
    core.pip_install(packages.split(' '))

    return web.Response(status=200)


@routes.post("/manager/queue/uninstall")
async def uninstall_custom_node(request):
    if not is_allowed_security_level('middle'):
        logging.error(SECURITY_MESSAGE_MIDDLE_OR_BELOW)
        return web.Response(status=403, text="A security error has occurred. Please check the terminal logs")

    json_data = await request.json()

    node_id = json_data.get('id')
    if json_data['version'] != 'unknown':
        is_unknown = False
        node_name = node_id
    else:
        # unknown
        is_unknown = True
        node_name = os.path.basename(json_data['files'][0])

    uninstall_item = json_data.get('ui_id'), node_name, is_unknown
    task_queue.put(("uninstall", uninstall_item))

    return web.Response(status=200)


@routes.post("/manager/queue/update")
async def update_custom_node(request):
    if not is_allowed_security_level('middle'):
        logging.error(SECURITY_MESSAGE_MIDDLE_OR_BELOW)
        return web.Response(status=403, text="A security error has occurred. Please check the terminal logs")

    json_data = await request.json()

    node_id = json_data.get('id')
    if json_data['version'] != 'unknown':
        node_name = node_id
    else:
        # unknown
        node_name = os.path.basename(json_data['files'][0])

    update_item = json_data.get('ui_id'), node_name, json_data['version']
    task_queue.put(("update", update_item))

    return web.Response(status=200)


@routes.get("/manager/queue/update_comfyui")
async def update_comfyui(request):
    is_stable = core.get_config()['update_policy'] != 'nightly-comfyui'
    task_queue.put(("update-comfyui", ('comfyui', is_stable)))
    return web.Response(status=200)


@routes.get("/comfyui_manager/comfyui_versions")
async def comfyui_versions(request):
    try:
        res, current, latest = core.get_comfyui_versions()
        return web.json_response({'versions': res, 'current': current}, status=200, content_type='application/json')
    except Exception as e:
        logging.error(f"ComfyUI update fail: {e}", file=sys.stderr)

    return web.Response(status=400)


@routes.get("/comfyui_manager/comfyui_switch_version")
async def comfyui_switch_version(request):
    try:
        if "ver" in request.rel_url.query:
            core.switch_comfyui(request.rel_url.query['ver'])

        return web.Response(status=200)
    except Exception as e:
        logging.error(f"ComfyUI update fail: {e}", file=sys.stderr)

    return web.Response(status=400)


@routes.post("/manager/queue/disable")
async def disable_node(request):
    json_data = await request.json()

    node_id = json_data.get('id')
    if json_data['version'] != 'unknown':
        is_unknown = False
        node_name = node_id
    else:
        # unknown
        is_unknown = True
        node_name = os.path.basename(json_data['files'][0])

    update_item = json_data.get('ui_id'), node_name, is_unknown
    task_queue.put(("disable", update_item))

    return web.Response(status=200)


async def check_whitelist_for_model(item):
    json_obj = await core.get_data_by_mode('cache', 'model-list.json')

    for x in json_obj.get('models', []):
        if x['save_path'] == item['save_path'] and x['base'] == item['base'] and x['filename'] == item['filename']:
            return True

    json_obj = await core.get_data_by_mode('local', 'model-list.json')

    for x in json_obj.get('models', []):
        if x['save_path'] == item['save_path'] and x['base'] == item['base'] and x['filename'] == item['filename']:
            return True
        
    return False


@routes.post("/manager/queue/install_model")
async def install_model(request):
    json_data = await request.json()

    if not is_allowed_security_level('middle'):
        logging.error(SECURITY_MESSAGE_MIDDLE_OR_BELOW)
        return web.Response(status=403, text="A security error has occurred. Please check the terminal logs")

    # validate request
    if not await check_whitelist_for_model(json_data):
        logging.error(f"[ComfyUI-Manager] Invalid model install request is detected: {json_data}")
        return web.Response(status=400, text="Invalid model install request is detected")

    if not json_data['filename'].endswith('.safetensors') and not is_allowed_security_level('high'):
        models_json = await core.get_data_by_mode('cache', 'model-list.json', 'default')

        is_belongs_to_whitelist = False
        for x in models_json['models']:
            if x.get('url') == json_data['url']:
                is_belongs_to_whitelist = True
                break

        if not is_belongs_to_whitelist:
            logging.error(SECURITY_MESSAGE_NORMAL_MINUS_MODEL)
            return web.Response(status=403, text="A security error has occurred. Please check the terminal logs")

    install_item = json_data.get('ui_id'), json_data
    task_queue.put(("install-model", install_item))

    return web.Response(status=200)


@routes.get("/manager/preview_method")
async def preview_method(request):
    if "value" in request.rel_url.query:
        set_preview_method(request.rel_url.query['value'])
        core.write_config()
    else:
        return web.Response(text=core.manager_funcs.get_current_preview_method(), status=200)

    return web.Response(status=200)


@routes.get("/manager/db_mode")
async def db_mode(request):
    if "value" in request.rel_url.query:
        set_db_mode(request.rel_url.query['value'])
        core.write_config()
    else:
        return web.Response(text=core.get_config()['db_mode'], status=200)

    return web.Response(status=200)



@routes.get("/manager/policy/component")
async def component_policy(request):
    if "value" in request.rel_url.query:
        set_component_policy(request.rel_url.query['value'])
        core.write_config()
    else:
        return web.Response(text=core.get_config()['component_policy'], status=200)

    return web.Response(status=200)


@routes.get("/manager/policy/update")
async def update_policy(request):
    if "value" in request.rel_url.query:
        set_update_policy(request.rel_url.query['value'])
        core.write_config()
    else:
        return web.Response(text=core.get_config()['update_policy'], status=200)

    return web.Response(status=200)


@routes.get("/manager/channel_url_list")
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


@routes.get("/manager/notice")
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
                    version_tag = os.environ.get('__COMFYUI_DESKTOP_VERSION__')
                    if version_tag is not None:
                        markdown_content += f"<HR>ComfyUI: {version_tag} [Desktop]"
                    else:
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
                        if '__COMFYUI_DESKTOP_VERSION__' not in os.environ:
                            if core.comfy_ui_commit_datetime == datetime(1900, 1, 1, 0, 0, 0):
                                markdown_content = '<P style="text-align: center; color:red; background-color:white; font-weight:bold">Your ComfyUI isn\'t git repo.</P>' + markdown_content
                            elif core.comfy_ui_required_commit_datetime.date() > core.comfy_ui_commit_datetime.date():
                                markdown_content = '<P style="text-align: center; color:red; background-color:white; font-weight:bold">Your ComfyUI is too OUTDATED!!!</P>' + markdown_content
                    except:
                        pass

                    return web.Response(text=markdown_content, status=200)
                else:
                    return web.Response(text="Unable to retrieve Notice", status=200)
            else:
                return web.Response(text="Unable to retrieve Notice", status=200)


@routes.get("/manager/reboot")
def restart(self):
    if not is_allowed_security_level('middle'):
        logging.error(SECURITY_MESSAGE_MIDDLE_OR_BELOW)
        return web.Response(status=403)

    try:
        sys.stdout.close_log()
    except Exception:
        pass

    if '__COMFY_CLI_SESSION__' in os.environ:
        with open(os.path.join(os.environ['__COMFY_CLI_SESSION__'] + '.reboot'), 'w'):
            pass

        print("\nRestarting...\n\n")  # This printing should not be logging - that will be ugly
        exit(0)

    print("\nRestarting... [Legacy Mode]\n\n")  # This printing should not be logging - that will be ugly

    sys_argv = sys.argv.copy()
    if '--windows-standalone-build' in sys_argv:
        sys_argv.remove('--windows-standalone-build')

    if sys_argv[0].endswith("__main__.py"):  # this is a python module
        module_name = os.path.basename(os.path.dirname(sys_argv[0]))
        cmds = [sys.executable, '-m', module_name] + sys_argv[1:]
    elif sys.platform.startswith('win32'):
        cmds = ['"' + sys.executable + '"', '"' + sys_argv[0] + '"'] + sys_argv[1:]
    else:
        cmds = [sys.executable] + sys_argv

    print(f"Command: {cmds}", flush=True)

    return os.execv(sys.executable, cmds)


@routes.post("/manager/component/save")
async def save_component(request):
    try:
        data = await request.json()
        name = data['name']
        workflow = data['workflow']

        if not os.path.exists(core.manager_components_path):
            os.mkdir(core.manager_components_path)

        if 'packname' in workflow and workflow['packname'] != '':
            sanitized_name = manager_util.sanitize_filename(workflow['packname']) + '.pack'
        else:
            sanitized_name = manager_util.sanitize_filename(name) + '.json'

        filepath = os.path.join(core.manager_components_path, sanitized_name)
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


@routes.post("/manager/component/loads")
async def load_components(request):
    if os.path.exists(core.manager_components_path):
        try:
            json_files = [f for f in os.listdir(core.manager_components_path) if f.endswith('.json')]
            pack_files = [f for f in os.listdir(core.manager_components_path) if f.endswith('.pack')]

            components = {}
            for json_file in json_files + pack_files:
                file_path = os.path.join(core.manager_components_path, json_file)
                with open(file_path, 'r') as file:
                    try:
                        # When there is a conflict between the .pack and the .json, the pack takes precedence and overrides.
                        components.update(json.load(file))
                    except json.JSONDecodeError as e:
                        logging.error(f"[ComfyUI-Manager] Error decoding component file in file {json_file}: {e}")

            return web.json_response(components)
        except Exception as e:
            logging.error(f"[ComfyUI-Manager] failed to load components\n{e}")
            return web.Response(status=400)
    else:
        return web.json_response({})


@routes.get("/manager/version")
async def get_version(request):
    return web.Response(text=core.version_str, status=200)


async def _confirm_try_install(sender, custom_node_url, msg):
    json_obj = await core.get_data_by_mode('default', 'custom-node-list.json')

    sender = manager_util.sanitize_tag(sender)
    msg = manager_util.sanitize_tag(msg)
    target = core.lookup_customnode_by_url(json_obj, custom_node_url)

    if target is not None:
        PromptServer.instance.send_sync("cm-api-try-install-customnode",
                                        {"sender": sender, "target": target, "msg": msg})
    else:
        logging.error(f"[ComfyUI Manager API] Failed to try install - Unknown custom node url '{custom_node_url}'")


def confirm_try_install(sender, custom_node_url, msg):
    asyncio.run(_confirm_try_install(sender, custom_node_url, msg))


cm_global.register_api('cm.try-install-custom-node', confirm_try_install)


async def default_cache_update():
    core.refresh_channel_dict()
    channel_url = core.get_config()['channel_url']
    async def get_cache(filename):
        try:
            if core.get_config()['default_cache_as_channel_url']:
                uri = f"{channel_url}/{filename}"
            else:
                uri = f"{core.DEFAULT_CHANNEL}/{filename}"

            cache_uri = str(manager_util.simple_hash(uri)) + '_' + filename
            cache_uri = os.path.join(manager_util.cache_dir, cache_uri)

            json_obj = await manager_util.get_data(uri, True)

            with manager_util.cache_lock:
                with open(cache_uri, "w", encoding='utf-8') as file:
                    json.dump(json_obj, file, indent=4, sort_keys=True)
                    logging.info(f"[ComfyUI-Manager] default cache updated: {uri}")
        except Exception as e:
            logging.error(f"[ComfyUI-Manager] Failed to perform initial fetching '{filename}': {e}")
            traceback.print_exc()

    if core.get_config()['network_mode'] != 'offline':
        a = get_cache("custom-node-list.json")
        b = get_cache("extension-node-map.json")
        c = get_cache("model-list.json")
        d = get_cache("alter-list.json")
        e = get_cache("github-stats.json")

        await asyncio.gather(a, b, c, d, e)

        if core.get_config()['network_mode'] == 'private':
            logging.info("[ComfyUI-Manager] The private comfyregistry is not yet supported in `network_mode=private`.")
        else:
            # load at least once
            await core.unified_manager.reload('remote', dont_wait=False)
            await core.unified_manager.get_custom_nodes(channel_url, 'remote')

    logging.info("[ComfyUI-Manager] All startup tasks have been completed.")


threading.Thread(target=lambda: asyncio.run(default_cache_update())).start()

if not os.path.exists(core.manager_config_path):
    core.get_config()
    core.write_config()


cm_global.register_extension('ComfyUI-Manager',
                             {'version': core.version,
                                 'name': 'ComfyUI Manager',
                                 'nodes': {},
                                 'description': 'This extension provides the ability to manage custom nodes in ComfyUI.', })


