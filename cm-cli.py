import os
import sys
import traceback
import json
import asyncio
import concurrent
import threading
from typing import Optional

import typer
from rich import print
from typing_extensions import List, Annotated
import re
import git
import importlib


sys.path.append(os.path.dirname(__file__))
sys.path.append(os.path.join(os.path.dirname(__file__), "glob"))

import manager_util

# read env vars
# COMFYUI_FOLDERS_BASE_PATH is not required in cm-cli.py
# `comfy_path` should be resolved before importing manager_core
comfy_path = os.environ.get('COMFYUI_PATH')
if comfy_path is None:
    try:
        import folder_paths
        comfy_path = os.path.join(os.path.dirname(folder_paths.__file__))
    except:
        print("\n[bold yellow]WARN: The `COMFYUI_PATH` environment variable is not set. Assuming `custom_nodes/ComfyUI-Manager/../../` as the ComfyUI path.[/bold yellow]", file=sys.stderr)
        comfy_path = os.path.abspath(os.path.join(manager_util.comfyui_manager_path, '..', '..'))

# This should be placed here
sys.path.append(comfy_path)

import utils.extra_config
import cm_global
import manager_core as core
from manager_core import unified_manager
import cnr_utils

comfyui_manager_path = os.path.abspath(os.path.dirname(__file__))

cm_global.pip_blacklist = {'torch', 'torchaudio', 'torchsde', 'torchvision'}
cm_global.pip_downgrade_blacklist = ['torch', 'torchaudio', 'torchsde', 'torchvision', 'transformers', 'safetensors', 'kornia']

cm_global.pip_overrides = {}

if os.path.exists(os.path.join(manager_util.comfyui_manager_path, "pip_overrides.json")):
    with open(os.path.join(manager_util.comfyui_manager_path, "pip_overrides.json"), 'r', encoding="UTF-8", errors="ignore") as json_file:
        cm_global.pip_overrides = json.load(json_file)


if os.path.exists(os.path.join(manager_util.comfyui_manager_path, "pip_blacklist.list")):
    with open(os.path.join(manager_util.comfyui_manager_path, "pip_blacklist.list"), 'r', encoding="UTF-8", errors="ignore") as f:
        for x in f.readlines():
            y = x.strip()
            if y != '':
                cm_global.pip_blacklist.add(y)


def check_comfyui_hash():
    try:
        repo = git.Repo(comfy_path)
        core.comfy_ui_revision = len(list(repo.iter_commits('HEAD')))
        core.comfy_ui_commit_datetime = repo.head.commit.committed_datetime
    except:
        print('[bold yellow]INFO: Frozen ComfyUI mode.[/bold yellow]')
        core.comfy_ui_revision = 0
        core.comfy_ui_commit_datetime = 0

    cm_global.variables['comfyui.revision'] = core.comfy_ui_revision


check_comfyui_hash()  # This is a preparation step for manager_core
core.check_invalid_nodes()


def read_downgrade_blacklist():
    try:
        import configparser
        config = configparser.ConfigParser(strict=False)
        config.read(core.manager_config.path)
        default_conf = config['default']

        if 'downgrade_blacklist' in default_conf:
            items = default_conf['downgrade_blacklist'].split(',')
            items = [x.strip() for x in items if x != '']
            cm_global.pip_downgrade_blacklist += items
            cm_global.pip_downgrade_blacklist = list(set(cm_global.pip_downgrade_blacklist))
    except:
        pass


read_downgrade_blacklist()  # This is a preparation step for manager_core


class Ctx:
    folder_paths = None
    
    def __init__(self):
        self.channel = 'default'
        self.no_deps = False
        self.mode = 'cache'
        self.user_directory = None
        self.custom_nodes_paths = [os.path.join(core.comfy_base_path, 'custom_nodes')]
        self.manager_files_directory = os.path.dirname(__file__)
        
        if Ctx.folder_paths is None:
            try:
                Ctx.folder_paths = importlib.import_module('folder_paths')
            except ImportError:
                print("Warning: Unable to import folder_paths module")

    def set_channel_mode(self, channel, mode):
        if mode is not None:
            self.mode = mode

        valid_modes = ["remote", "local", "cache"]
        if mode and mode.lower() not in valid_modes:
            typer.echo(
                f"Invalid mode: {mode}. Allowed modes are 'remote', 'local', 'cache'.",
                err=True,
            )
            exit(1)

        if channel is not None:
            self.channel = channel

        asyncio.run(unified_manager.reload(cache_mode=self.mode, dont_wait=False))
        asyncio.run(unified_manager.load_nightly(self.channel, self.mode))

    def set_no_deps(self, no_deps):
        self.no_deps = no_deps

    def set_user_directory(self, user_directory):
        if user_directory is None:
            return

        extra_model_paths_yaml = os.path.join(user_directory, 'extra_model_paths.yaml')
        if os.path.exists(extra_model_paths_yaml):
            utils.extra_config.load_extra_path_config(extra_model_paths_yaml)

        core.update_user_directory(user_directory)

        if os.path.exists(core.manager_pip_overrides_path):
            with open(core.manager_pip_overrides_path, 'r', encoding="UTF-8", errors="ignore") as json_file:
                cm_global.pip_overrides = json.load(json_file)

        if os.path.exists(core.manager_pip_blacklist_path):
            with open(core.manager_pip_blacklist_path, 'r', encoding="UTF-8", errors="ignore") as f:
                for x in f.readlines():
                    y = x.strip()
                    if y != '':
                        cm_global.pip_blacklist.add(y)

    def update_custom_nodes_dir(self, target_dir):
        import folder_paths
        a, b = folder_paths.folder_names_and_paths['custom_nodes']
        folder_paths.folder_names_and_paths['custom_nodes'] = [os.path.abspath(target_dir)], set()

    @staticmethod
    def get_startup_scripts_path():
        return os.path.join(core.manager_startup_script_path, "install-scripts.txt")

    @staticmethod
    def get_restore_snapshot_path():
        return os.path.join(core.manager_startup_script_path, "restore-snapshot.json")

    @staticmethod
    def get_snapshot_path():
        return core.manager_snapshot_path

    @staticmethod
    def get_custom_nodes_paths():
        if Ctx.folder_paths is None:
            print("Error: folder_paths module is not available")
            return []
        return Ctx.folder_paths.get_folder_paths('custom_nodes')


cmd_ctx = Ctx()


def install_node(node_spec_str, is_all=False, cnt_msg='', **kwargs):
    exit_on_fail = kwargs.get('exit_on_fail', False)
    print(f"install_node exit on fail:{exit_on_fail}...")
    
    if core.is_valid_url(node_spec_str):
        # install via urls
        res = asyncio.run(core.gitclone_install(node_spec_str, no_deps=cmd_ctx.no_deps))
        if not res.result:
            print(res.msg)
            print(f"[bold red]ERROR: An error occurred while installing '{node_spec_str}'.[/bold red]")
            if exit_on_fail:
                sys.exit(1)
        else:
            print(f"{cnt_msg} [INSTALLED] {node_spec_str:50}")
    else:
        node_spec = unified_manager.resolve_node_spec(node_spec_str)

        if node_spec is None:
            return

        node_name, version_spec, is_specified = node_spec

        # NOTE: install node doesn't allow update if version is not specified
        if not is_specified:
            version_spec = None

        res = asyncio.run(unified_manager.install_by_id(node_name, version_spec, cmd_ctx.channel, cmd_ctx.mode, instant_execution=True, no_deps=cmd_ctx.no_deps))

        if res.action == 'skip':
            print(f"{cnt_msg} [   SKIP  ] {node_name:50} => Already installed")
        elif res.action == 'enable':
            print(f"{cnt_msg} [ ENABLED ] {node_name:50}")
        elif res.action == 'install-git' and res.target == 'nightly':
            print(f"{cnt_msg} [INSTALLED] {node_name:50}[NIGHTLY]")
        elif res.action == 'install-git' and res.target == 'unknown':
            print(f"{cnt_msg} [INSTALLED] {node_name:50}[UNKNOWN]")
        elif res.action == 'install-cnr' and res.result:
            print(f"{cnt_msg} [INSTALLED] {node_name:50}[{res.target}]")
        elif res.action == 'switch-cnr' and res.result:
            print(f"{cnt_msg} [INSTALLED] {node_name:50}[{res.target}]")
        elif (res.action == 'switch-cnr' or res.action == 'install-cnr') and not res.result and node_name in unified_manager.cnr_map:
            print(f"\nAvailable version of '{node_name}'")
            show_versions(node_name)
            print("")
        else:
            print(f"[bold red]ERROR: An error occurred while installing '{node_name}'.\n{res.msg}[/bold red]")
            if exit_on_fail:
                sys.exit(1)


def reinstall_node(node_spec_str, is_all=False, cnt_msg=''):
    node_spec = unified_manager.resolve_node_spec(node_spec_str)

    node_name, version_spec, _ = node_spec

    unified_manager.unified_uninstall(node_name, version_spec == 'unknown')
    install_node(node_name, is_all=is_all, cnt_msg=cnt_msg)


def fix_node(node_spec_str, is_all=False, cnt_msg=''):
    node_spec = unified_manager.resolve_node_spec(node_spec_str, guess_mode='active')

    if node_spec is None:
        if not is_all:
            if unified_manager.resolve_node_spec(node_spec_str, guess_mode='inactive') is not None:
                print(f"{cnt_msg} [  SKIPPED  ]: {node_spec_str:50} => Disabled")
            else:
                print(f"{cnt_msg} [  SKIPPED  ]: {node_spec_str:50} => Not installed")

        return

    node_name, version_spec, _ = node_spec

    print(f"{cnt_msg} [   FIXING  ]: {node_name:50}[{version_spec}]")
    res = unified_manager.unified_fix(node_name, version_spec, no_deps=cmd_ctx.no_deps)

    if not res.result:
        print(f"[bold red]ERROR: f{res.msg}[/bold red]")


def uninstall_node(node_spec_str: str, is_all: bool = False, cnt_msg: str = ''):
    spec = node_spec_str.split('@')
    if len(spec) == 2 and spec[1] == 'unknown':
        node_name = spec[0]
        is_unknown = True
    else:
        node_name = spec[0]
        is_unknown = False

    res = unified_manager.unified_uninstall(node_name, is_unknown)
    if len(spec) == 1 and res.action == 'skip' and not is_unknown:
        res = unified_manager.unified_uninstall(node_name, True)

    if res.action == 'skip':
        print(f"{cnt_msg} [  SKIPPED  ]: {node_name:50} => Not installed")

    elif res.result:
        print(f"{cnt_msg} [UNINSTALLED] {node_name:50}")
    else:
        print(f"ERROR: An error occurred while uninstalling '{node_name}'.")


def update_node(node_spec_str, is_all=False, cnt_msg=''):
    node_spec = unified_manager.resolve_node_spec(node_spec_str, 'active')

    if node_spec is None:
        if unified_manager.resolve_node_spec(node_spec_str, 'inactive'):
            print(f"{cnt_msg} [  SKIPPED  ]: {node_spec_str:50} => Disabled")
        else:
            print(f"{cnt_msg} [  SKIPPED  ]: {node_spec_str:50} => Not installed")
        return None

    node_name, version_spec, _ = node_spec

    res = unified_manager.unified_update(node_name, version_spec, no_deps=cmd_ctx.no_deps, return_postinstall=True)

    if not res.result:
        print(f"ERROR: An error occurred while updating '{node_name}'.")
    elif res.action == 'skip':
        print(f"{cnt_msg} [  SKIPPED  ]: {node_name:50} => {res.msg}")
    else:
        print(f"{cnt_msg} [  UPDATED  ]: {node_name:50} => ({version_spec} -> {res.target})")

    return res.with_target(f'{node_name}@{res.target}')


def update_parallel(nodes):
    is_all = False
    if 'all' in nodes:
        is_all = True
        nodes = []
        for x in unified_manager.active_nodes.keys():
            nodes.append(x)
        for x in unified_manager.unknown_active_nodes.keys():
            nodes.append(x+"@unknown")
    else:
        nodes = [x for x in nodes if x.lower() not in ['comfy', 'comfyui']]

    total = len(nodes)

    lock = threading.Lock()
    processed = []

    i = 0

    def process_custom_node(x):
        nonlocal i
        nonlocal processed

        with lock:
            i += 1

        try:
            res = update_node(x, is_all=is_all, cnt_msg=f'{i}/{total}')
            with lock:
                processed.append(res)
        except Exception as e:
            print(f"ERROR: {e}")
            traceback.print_exc()

    with concurrent.futures.ThreadPoolExecutor(4) as executor:
        for item in nodes:
            executor.submit(process_custom_node, item)

    i = 1
    for res in processed:
        if res is not None:
            print(f"[{i}/{total}] Post update: {res.target}")
            if res.postinstall is not None:
                res.postinstall()
        i += 1


def update_comfyui():
    res = core.update_path(comfy_path, instant_execution=True)
    if res == 'fail':
        print("Updating ComfyUI has failed.")
    elif res == 'updated':
        print("ComfyUI is updated.")
    else:
        print("ComfyUI is already up to date.")


def enable_node(node_spec_str, is_all=False, cnt_msg=''):
    if unified_manager.resolve_node_spec(node_spec_str, guess_mode='active') is not None:
        print(f"{cnt_msg} [  SKIP ] {node_spec_str:50} => Already enabled")
        return

    node_spec = unified_manager.resolve_node_spec(node_spec_str, guess_mode='inactive')

    if node_spec is None:
        print(f"{cnt_msg} [  SKIP ] {node_spec_str:50} => Not found")
        return

    node_name, version_spec, _ = node_spec

    res = unified_manager.unified_enable(node_name, version_spec)

    if res.action == 'skip':
        print(f"{cnt_msg} [  SKIP ] {node_name:50} => {res.msg}")
    elif res.result:
        print(f"{cnt_msg} [ENABLED] {node_name:50}")
    else:
        print(f"{cnt_msg} [  FAIL ] {node_name:50} => {res.msg}")


def disable_node(node_spec_str: str, is_all=False, cnt_msg=''):
    if 'comfyui-manager' in node_spec_str.lower():
        return

    node_spec = unified_manager.resolve_node_spec(node_spec_str, guess_mode='active')

    if node_spec is None:
        if unified_manager.resolve_node_spec(node_spec_str, guess_mode='inactive') is not None:
            print(f"{cnt_msg} [  SKIP  ] {node_spec_str:50} => Already disabled")
        else:
            print(f"{cnt_msg} [  SKIP  ] {node_spec_str:50} => Not found")
        return

    node_name, version_spec, _ = node_spec

    res = unified_manager.unified_disable(node_name, version_spec == 'unknown')

    if res.action == 'skip':
        print(f"{cnt_msg} [  SKIP  ] {node_name:50} => {res.msg}")
    elif res.result:
        print(f"{cnt_msg} [DISABLED] {node_name:50}")
    else:
        print(f"{cnt_msg} [  FAIL  ] {node_name:50} => {res.msg}")


def show_list(kind, simple=False):
    custom_nodes = asyncio.run(unified_manager.get_custom_nodes(channel=cmd_ctx.channel, mode=cmd_ctx.mode))

    # collect not-installed unknown nodes
    not_installed_unknown_nodes = []
    repo_unknown = {}

    for k, v in custom_nodes.items():
        if 'cnr_latest' not in v:
            if len(v['files']) == 1:
                repo_url = v['files'][0]
                node_name = repo_url.split('/')[-1]
                if node_name not in unified_manager.unknown_inactive_nodes and node_name not in unified_manager.unknown_active_nodes:
                    not_installed_unknown_nodes.append(v)
                else:
                    repo_unknown[node_name] = v

    processed = {}
    unknown_processed = []

    flag = kind in ['all', 'cnr', 'installed', 'enabled']
    for k, v in unified_manager.active_nodes.items():
        if flag:
            cnr = unified_manager.cnr_map[k]
            processed[k] = "[    ENABLED    ] ", cnr['name'], k, cnr['publisher']['name'], v[0]
        else:
            processed[k] = None

    if flag and kind != 'cnr':
        for k, v in unified_manager.unknown_active_nodes.items():
            item = repo_unknown.get(k)

            if item is None:
                continue

            log_item = "[    ENABLED    ] ", item['title'], k, item['author']
            unknown_processed.append(log_item)

    flag = kind in ['all', 'cnr', 'installed', 'disabled']
    for k, v in unified_manager.cnr_inactive_nodes.items():
        if k in processed:
            continue

        if flag:
            cnr = unified_manager.cnr_map[k]
            processed[k] = "[    DISABLED   ] ", cnr['name'], k, cnr['publisher']['name'], ", ".join(list(v.keys()))
        else:
            processed[k] = None

    for k, v in unified_manager.nightly_inactive_nodes.items():
        if k in processed:
            continue

        if flag:
            cnr = unified_manager.cnr_map[k]
            processed[k] = "[    DISABLED   ] ", cnr['name'], k, cnr['publisher']['name'], 'nightly'
        else:
            processed[k] = None

    if flag and kind != 'cnr':
        for k, v in unified_manager.unknown_inactive_nodes.items():
            item = repo_unknown.get(k)

            if item is None:
                continue

            log_item = "[    DISABLED   ] ", item['title'], k, item['author']
            unknown_processed.append(log_item)

    flag = kind in ['all', 'cnr', 'not-installed']
    for k, v in unified_manager.cnr_map.items():
        if k in processed:
            continue

        if flag:
            cnr = unified_manager.cnr_map[k]
            ver_spec = v['latest_version']['version'] if 'latest_version' in v else '0.0.0'
            processed[k] = "[ NOT INSTALLED ] ", cnr['name'], k, cnr['publisher']['name'], ver_spec
        else:
            processed[k] = None

    if flag and kind != 'cnr':
        for x in not_installed_unknown_nodes:
            if len(x['files']) == 1:
                node_id = os.path.basename(x['files'][0])
                log_item = "[ NOT INSTALLED ] ", x['title'], node_id, x['author']
                unknown_processed.append(log_item)

    for x in processed.values():
        if x is None:
            continue

        prefix, title, short_id, author, ver_spec = x
        if simple:
            print(title+'@'+ver_spec)
        else:
            print(f"{prefix} {title:50} {short_id:30} (author: {author:20}) \\[{ver_spec}]")

    for x in unknown_processed:
        prefix, title, short_id, author = x
        if simple:
            print(title+'@unknown')
        else:
            print(f"{prefix} {title:50} {short_id:30} (author: {author:20}) [UNKNOWN]")


async def show_snapshot(simple_mode=False):
    json_obj = await core.get_current_snapshot()

    if simple_mode:
        print(f"[{json_obj['comfyui']}] comfyui")
        for k, v in json_obj['git_custom_nodes'].items():
            print(f"[{v['hash']}] {k}")
        for v in json_obj['file_custom_nodes']:
            print(f"[                   N/A                  ] {v['filename']}")

    else:
        formatted_json = json.dumps(json_obj, ensure_ascii=False, indent=4)
        print(formatted_json)


def show_snapshot_list(simple_mode=False):
    snapshot_path = cmd_ctx.get_snapshot_path()

    files = os.listdir(snapshot_path)
    json_files = [x for x in files if x.endswith('.json')]
    for x in sorted(json_files):
        print(x)


def cancel():
    if os.path.exists(cmd_ctx.get_startup_scripts_path()):
        os.remove(cmd_ctx.get_startup_scripts_path())

    if os.path.exists(cmd_ctx.get_restore_snapshot_path()):
        os.remove(cmd_ctx.get_restore_snapshot_path())


async def auto_save_snapshot():
    path = await core.save_snapshot_with_postfix('cli-autosave')
    print(f"Current snapshot is saved as `{path}`")


def get_all_installed_node_specs():
    res = []
    processed = set()
    for k, v in unified_manager.active_nodes.items():
        node_spec_str = f"{k}@{v[0]}"
        res.append(node_spec_str)
        processed.add(k)

    for k in unified_manager.cnr_inactive_nodes.keys():
        if k in processed:
            continue

        latest = unified_manager.get_from_cnr_inactive_nodes(k)
        if latest is not None:
            node_spec_str = f"{k}@{str(latest[0])}"
            res.append(node_spec_str)

    for k in unified_manager.nightly_inactive_nodes.keys():
        if k in processed:
            continue

        node_spec_str = f"{k}@nightly"
        res.append(node_spec_str)

    for k in unified_manager.unknown_active_nodes.keys():
        node_spec_str = f"{k}@unknown"
        res.append(node_spec_str)

    for k in unified_manager.unknown_inactive_nodes.keys():
        node_spec_str = f"{k}@unknown"
        res.append(node_spec_str)

    return res


def for_each_nodes(nodes, act, allow_all=True, **kwargs):
    is_all = False
    if allow_all and 'all' in nodes:
        is_all = True
        nodes = get_all_installed_node_specs()
    else:
        nodes = [x for x in nodes if x.lower() not in ['comfy', 'comfyui', 'all']]

    total = len(nodes)
    i = 1
    for x in nodes:
        try:
            act(x, is_all=is_all, cnt_msg=f'{i}/{total}', **kwargs)
        except Exception as e:
            print(f"ERROR: {e}")
            traceback.print_exc()
        i += 1


app = typer.Typer()


@app.command(help="Display help for commands")
def help(ctx: typer.Context):
    print(ctx.find_root().get_help())
    ctx.exit(0)


@app.command(help="Install custom nodes")
def install(
        nodes: List[str] = typer.Argument(
            ..., help="List of custom nodes to install"
        ),
        channel: Annotated[
            str,
            typer.Option(
                show_default=False,
                help="Specify the operation mode"
            ),
        ] = None,
        mode: str = typer.Option(
            None,
            help="[remote|local|cache]"
        ),
        no_deps: Annotated[
            Optional[bool],
            typer.Option(
                "--no-deps",
                show_default=False,
                help="Skip installing any Python dependencies",
            ),
        ] = False,
        user_directory: str = typer.Option(
            None,
            help="user directory"
        ),
        exit_on_fail: bool = typer.Option(
            False,
            help="Exit on failure"
        )
):
    cmd_ctx.set_user_directory(user_directory)
    cmd_ctx.set_channel_mode(channel, mode)
    cmd_ctx.set_no_deps(no_deps)

    pip_fixer = manager_util.PIPFixer(manager_util.get_installed_packages(), comfy_path, core.manager_files_path)
    for_each_nodes(nodes, act=install_node, exit_on_fail=exit_on_fail)
    pip_fixer.fix_broken()


@app.command(help="Reinstall custom nodes")
def reinstall(
        nodes: List[str] = typer.Argument(
            ..., help="List of custom nodes to reinstall"
        ),
        channel: Annotated[
            str,
            typer.Option(
                show_default=False,
                help="Specify the operation mode"
            ),
        ] = None,
        mode: str = typer.Option(
            None,
            help="[remote|local|cache]"
        ),
        no_deps: Annotated[
            Optional[bool],
            typer.Option(
                "--no-deps",
                show_default=False,
                help="Skip installing any Python dependencies",
            ),
        ] = False,
        user_directory: str = typer.Option(
            None,
            help="user directory"
        ),
):
    cmd_ctx.set_user_directory(user_directory)
    cmd_ctx.set_channel_mode(channel, mode)
    cmd_ctx.set_no_deps(no_deps)

    pip_fixer = manager_util.PIPFixer(manager_util.get_installed_packages(), comfy_path, core.manager_files_path)
    for_each_nodes(nodes, act=reinstall_node)
    pip_fixer.fix_broken()


@app.command(help="Uninstall custom nodes")
def uninstall(
        nodes: List[str] = typer.Argument(
            ..., help="List of custom nodes to uninstall"
        ),
        channel: Annotated[
            str,
            typer.Option(
                show_default=False,
                help="Specify the operation mode"
            ),
        ] = None,
        mode: str = typer.Option(
            None,
            help="[remote|local|cache]"
        ),
):
    cmd_ctx.set_channel_mode(channel, mode)
    for_each_nodes(nodes, act=uninstall_node)


@app.command(help="Update custom nodes")
def update(
        nodes: List[str] = typer.Argument(
            ...,
            help="[all|List of custom nodes to update]"
        ),
        channel: Annotated[
            str,
            typer.Option(
                show_default=False,
                help="Specify the operation mode"
            ),
        ] = None,
        mode: str = typer.Option(
            None,
            help="[remote|local|cache]"
        ),
        user_directory: str = typer.Option(
            None,
            help="user directory"
        ),
):
    cmd_ctx.set_user_directory(user_directory)
    cmd_ctx.set_channel_mode(channel, mode)

    if 'all' in nodes:
        asyncio.run(auto_save_snapshot())

    pip_fixer = manager_util.PIPFixer(manager_util.get_installed_packages(), comfy_path, core.manager_files_path)

    for x in nodes:
        if x.lower() in ['comfyui', 'comfy', 'all']:
            update_comfyui()
            break

    update_parallel(nodes)
    pip_fixer.fix_broken()


@app.command(help="Disable custom nodes")
def disable(
        nodes: List[str] = typer.Argument(
            ...,
            help="[all|List of custom nodes to disable]"
        ),
        channel: Annotated[
            str,
            typer.Option(
                show_default=False,
                help="Specify the operation mode"
            ),
        ] = None,
        mode: str = typer.Option(
            None,
            help="[remote|local|cache]"
        ),
        user_directory: str = typer.Option(
            None,
            help="user directory"
        ),
):
    cmd_ctx.set_user_directory(user_directory)
    cmd_ctx.set_channel_mode(channel, mode)

    if 'all' in nodes:
        asyncio.run(auto_save_snapshot())

    for_each_nodes(nodes, disable_node, allow_all=True)


@app.command(help="Enable custom nodes")
def enable(
        nodes: List[str] = typer.Argument(
            ...,
            help="[all|List of custom nodes to enable]"
        ),
        channel: Annotated[
            str,
            typer.Option(
                show_default=False,
                help="Specify the operation mode"
            ),
        ] = None,
        mode: str = typer.Option(
            None,
            help="[remote|local|cache]"
        ),
        user_directory: str = typer.Option(
            None,
            help="user directory"
        ),
):
    cmd_ctx.set_user_directory(user_directory)
    cmd_ctx.set_channel_mode(channel, mode)

    if 'all' in nodes:
        asyncio.run(auto_save_snapshot())

    for_each_nodes(nodes, enable_node, allow_all=True)


@app.command(help="Fix dependencies of custom nodes")
def fix(
        nodes: List[str] = typer.Argument(
            ...,
            help="[all|List of custom nodes to fix]"
        ),
        channel: Annotated[
            str,
            typer.Option(
                show_default=False,
                help="Specify the operation mode"
            ),
        ] = None,
        mode: str = typer.Option(
            None,
            help="[remote|local|cache]"
        ),
        user_directory: str = typer.Option(
            None,
            help="user directory"
        ),
):
    cmd_ctx.set_user_directory(user_directory)
    cmd_ctx.set_channel_mode(channel, mode)

    if 'all' in nodes:
        asyncio.run(auto_save_snapshot())

    pip_fixer = manager_util.PIPFixer(manager_util.get_installed_packages(), comfy_path, core.manager_files_path)
    for_each_nodes(nodes, fix_node, allow_all=True)
    pip_fixer.fix_broken()


@app.command("show-versions", help="Show all available versions of the node")
def show_versions(node_name: str):
    versions = cnr_utils.all_versions_of_node(node_name)
    if versions is None:
        print(f"Node not found in Comfy Registry: {node_name}")

    for x in versions:
        print(f"[{x['createdAt'][:10]}] {x['version']} -- {x['changelog']}")


@app.command("show", help="Show node list")
def show(
        arg: str = typer.Argument(
            help="[installed|enabled|not-installed|disabled|all|cnr|snapshot|snapshot-list]"
        ),
        channel: Annotated[
            str,
            typer.Option(
                show_default=False,
                help="Specify the operation mode"
            ),
        ] = None,
        mode: str = typer.Option(
            None,
            help="[remote|local|cache]"
        ),
        user_directory: str = typer.Option(
            None,
            help="user directory"
        ),
):
    valid_commands = [
        "installed",
        "enabled",
        "not-installed",
        "disabled",
        "all",
        "cnr",
        "snapshot",
        "snapshot-list",
    ]
    if arg not in valid_commands:
        typer.echo(f"Invalid command: `show {arg}`", err=True)
        exit(1)

    cmd_ctx.set_user_directory(user_directory)
    cmd_ctx.set_channel_mode(channel, mode)
    if arg == 'snapshot':
        show_snapshot()
    elif arg == 'snapshot-list':
        show_snapshot_list()
    else:
        show_list(arg)


@app.command("simple-show", help="Show node list (simple mode)")
def simple_show(
        arg: str = typer.Argument(
            help="[installed|enabled|not-installed|disabled|all|snapshot|snapshot-list]"
        ),
        channel: Annotated[
            str,
            typer.Option(
                show_default=False,
                help="Specify the operation mode"
            ),
        ] = None,
        mode: str = typer.Option(
            None,
            help="[remote|local|cache]"
        ),
        user_directory: str = typer.Option(
            None,
            help="user directory"
        ),
):
    valid_commands = [
        "installed",
        "enabled",
        "not-installed",
        "disabled",
        "all",
        "snapshot",
        "snapshot-list",
    ]
    if arg not in valid_commands:
        typer.echo(f"[bold red]Invalid command: `show {arg}`[/bold red]", err=True)
        exit(1)

    cmd_ctx.set_user_directory(user_directory)
    cmd_ctx.set_channel_mode(channel, mode)

    if arg == 'snapshot':
        show_snapshot(True)
    elif arg == 'snapshot-list':
        show_snapshot_list(True)
    else:
        show_list(arg, True)


@app.command('cli-only-mode', help="Set whether to use ComfyUI-Manager in CLI-only mode.")
def cli_only_mode(
        mode: str = typer.Argument(
            ..., help="[enable|disable]"
        ),
        user_directory: str = typer.Option(
            None,
            help="user directory"
        )
):
    cmd_ctx.set_user_directory(user_directory)
    cli_mode_flag = os.path.join(cmd_ctx.manager_files_directory, '.enable-cli-only-mode')

    if mode.lower() == 'enable':
        with open(cli_mode_flag, 'w'):
            pass
        print("\nINFO: `cli-only-mode` is enabled\n")
    elif mode.lower() == 'disable':
        if os.path.exists(cli_mode_flag):
            os.remove(cli_mode_flag)
        print("\nINFO: `cli-only-mode` is disabled\n")
    else:
        print(f"\n[bold red]Invalid value for cli-only-mode: {mode}[/bold red]\n")
        exit(1)


@app.command(
    "deps-in-workflow", help="Generate dependencies file from workflow (.json/.png)"
)
def deps_in_workflow(
        workflow: Annotated[
            str, typer.Option(show_default=False, help="Workflow file (.json/.png)")
        ],
        output: Annotated[
            str, typer.Option(show_default=False, help="Output file (.json)")
        ],
        channel: Annotated[
            str,
            typer.Option(
                show_default=False,
                help="Specify the operation mode"
            ),
        ] = None,
        mode: str = typer.Option(
            None,
            help="[remote|local|cache]"
        ),
        user_directory: str = typer.Option(
            None,
            help="user directory"
        )
):
    cmd_ctx.set_user_directory(user_directory)
    cmd_ctx.set_channel_mode(channel, mode)

    input_path = workflow
    output_path = output

    if not os.path.exists(input_path):
        print(f"[bold red]File not found: {input_path}[/bold red]")
        exit(1)

    used_exts, unknown_nodes = asyncio.run(core.extract_nodes_from_workflow(input_path, mode=cmd_ctx.mode, channel_url=cmd_ctx.channel))

    custom_nodes = {}
    for x in used_exts:
        custom_nodes[x] = {'state': core.simple_check_custom_node(x),
                           'hash': '-'
                           }

    res = {
        'custom_nodes': custom_nodes,
        'unknown_nodes': list(unknown_nodes)
    }

    with open(output_path, "w", encoding='utf-8') as output_file:
        json.dump(res, output_file, indent=4)

    print(f"Workflow dependencies are being saved into {output_path}.")


@app.command("save-snapshot", help="Save a snapshot of the current ComfyUI environment. If output path isn't provided. Save to ComfyUI-Manager/snapshots path.")
def save_snapshot(
        output: Annotated[
            str,
            typer.Option(
                show_default=False, help="Specify the output file path. (.json/.yaml)"
            ),
        ] = None,
        user_directory: str = typer.Option(
            None,
            help="user directory"
        ),
        full_snapshot: Annotated[
            bool,
            typer.Option(
                show_default=False, help="If the snapshot should include custom node, ComfyUI version and pip versions (default), or only custom node details"
            ),
        ] = True,
):
    cmd_ctx.set_user_directory(user_directory)

    if output is not None:
        if(not output.endswith('.json') and not output.endswith('.yaml')):
            print("[bold red]ERROR: output path should be either '.json' or '.yaml' file.[/bold red]")
            raise typer.Exit(code=1)
    
        dir_path = os.path.dirname(output)
        
        if(dir_path != '' and not os.path.exists(dir_path)):
            print(f"[bold red]ERROR: {output} path not exists.[/bold red]")
            raise typer.Exit(code=1)
        
    path = asyncio.run(core.save_snapshot_with_postfix('snapshot', output, not full_snapshot))
    print(f"Current snapshot is saved as `{path}`")


@app.command("restore-snapshot", help="Restore snapshot from snapshot file")
def restore_snapshot(
        snapshot_name: str, 
        pip_non_url: Optional[bool] = typer.Option(
            default=None,
            show_default=False,
            is_flag=True,
            help="Restore for pip packages registered on PyPI.",
        ),
        pip_non_local_url: Optional[bool] = typer.Option(
            default=None,
            show_default=False,
            is_flag=True,
            help="Restore for pip packages registered at web URLs.",
        ),
        pip_local_url: Optional[bool] = typer.Option(
            default=None,
            show_default=False,
            is_flag=True,
            help="Restore for pip packages specified by local paths.",
        ),
        user_directory: str = typer.Option(
            None,
            help="user directory"
        ),
        restore_to: Optional[str] = typer.Option(
            None,
            help="Manually specify the installation path for the custom node. Ignore user directory."
        )
):
    cmd_ctx.set_user_directory(user_directory)

    if restore_to:
        cmd_ctx.update_custom_nodes_dir(restore_to)

    extras = []
    if pip_non_url:
        extras.append('--pip-non-url')

    if pip_non_local_url:
        extras.append('--pip-non-local-url')

    if pip_local_url:
        extras.append('--pip-local-url')

    print(f"PIPs restore mode: {extras}")

    if os.path.exists(snapshot_name):
        snapshot_path = os.path.abspath(snapshot_name)
    else:
        snapshot_path = os.path.join(cmd_ctx.get_snapshot_path(), snapshot_name)
        if not os.path.exists(snapshot_path):
            print(f"[bold red]ERROR: `{snapshot_path}` is not exists.[/bold red]")
            exit(1)

    pip_fixer = manager_util.PIPFixer(manager_util.get_installed_packages(), comfy_path, core.manager_files_path)
    try:
        asyncio.run(core.restore_snapshot(snapshot_path, extras))
    except Exception:
        print("[bold red]ERROR: Failed to restore snapshot.[/bold red]")
        traceback.print_exc()
        raise typer.Exit(code=1)
    pip_fixer.fix_broken()


@app.command(
    "restore-dependencies", help="Restore dependencies from whole installed custom nodes."
)
def restore_dependencies(
        user_directory: str = typer.Option(
            None,
            help="user directory"
        )
):
    cmd_ctx.set_user_directory(user_directory)

    node_paths = []

    for base_path in cmd_ctx.get_custom_nodes_paths():
        for name in os.listdir(base_path):
            target = os.path.join(base_path, name)
            if os.path.isdir(target) and not name.endswith('.disabled'):
                node_paths.append(target)

    total = len(node_paths)
    i = 1

    pip_fixer = manager_util.PIPFixer(manager_util.get_installed_packages(), comfy_path, core.manager_files_path)
    for x in node_paths:
        print("----------------------------------------------------------------------------------------------------")
        print(f"Restoring [{i}/{total}]: {x}")
        unified_manager.execute_install_script('', x, instant_execution=True)
        i += 1
    pip_fixer.fix_broken()


@app.command(
    "post-install", help="Install dependencies and execute installation script"
)
def post_install(
        path: str = typer.Argument(
            help="path to custom node",
        )
):
    path = os.path.expanduser(path)

    pip_fixer = manager_util.PIPFixer(manager_util.get_installed_packages(), comfy_path, core.manager_files_path)
    unified_manager.execute_install_script('', path, instant_execution=True)
    pip_fixer.fix_broken()


@app.command(
    "install-deps",
    help="Install dependencies from dependencies file(.json) or workflow(.png/.json)",
)
def install_deps(
        deps: str = typer.Argument(
            help="Dependency spec file (.json)",
        ),
        channel: Annotated[
            str,
            typer.Option(
                show_default=False,
                help="Specify the operation mode"
            ),
        ] = None,
        mode: str = typer.Option(
            None,
            help="[remote|local|cache]"
        ),
        user_directory: str = typer.Option(
            None,
            help="user directory"
        ),
):
    cmd_ctx.set_user_directory(user_directory)
    cmd_ctx.set_channel_mode(channel, mode)
    asyncio.run(auto_save_snapshot())

    if not os.path.exists(deps):
        print(f"[bold red]File not found: {deps}[/bold red]")
        exit(1)
    else:
        with open(deps, 'r', encoding="UTF-8", errors="ignore") as json_file:
            try:
                json_obj = json.load(json_file)
            except:
                print(f"[bold red]Invalid json file: {deps}[/bold red]")
                exit(1)

            pip_fixer = manager_util.PIPFixer(manager_util.get_installed_packages(), comfy_path, core.manager_files_path)
            for k in json_obj['custom_nodes'].keys():
                state = core.simple_check_custom_node(k)
                if state == 'installed':
                    continue
                elif state == 'not-installed':
                    asyncio.run(core.gitclone_install(k, instant_execution=True))
                else:  # disabled
                    core.gitclone_set_active([k], False)
            pip_fixer.fix_broken()

        print("Dependency installation and activation complete.")


@app.command(help="Clear reserved startup action in ComfyUI-Manager")
def clear():
    cancel()


@app.command("export-custom-node-ids", help="Export custom node ids")
def export_custom_node_ids(
        path: str,
        channel: Annotated[
            str,
            typer.Option(
                show_default=False,
                help="Specify the operation mode"
            ),
        ] = None,
        mode: str = typer.Option(
            None,
            help="[remote|local|cache]"
        ),
        user_directory: str = typer.Option(
            None,
            help="user directory"
        ),
):
    cmd_ctx.set_user_directory(user_directory)
    cmd_ctx.set_channel_mode(channel, mode)

    with open(path, "w", encoding='utf-8') as output_file:
        for x in unified_manager.cnr_map.keys():
            print(x, file=output_file)

        custom_nodes = asyncio.run(unified_manager.get_custom_nodes(channel=cmd_ctx.channel, mode=cmd_ctx.mode))
        for x in custom_nodes.values():
            if 'cnr_latest' not in x:
                if len(x['files']) == 1:
                    repo_url = x['files'][0]
                    node_id = repo_url.split('/')[-1]
                    print(f"{node_id}@unknown", file=output_file)

                if 'id' in x:
                    print(f"{x['id']}@unknown", file=output_file)


if __name__ == '__main__':
    sys.argv[0] = re.sub(r'(-script\.pyw|\.exe)?$', '', sys.argv[0])
    sys.exit(app())


print("")
