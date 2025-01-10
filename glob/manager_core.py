"""
description:
    `manager_core` contains the core implementation of the management functions in ComfyUI-Manager.
"""

import json
import os
import sys
import subprocess
import re
import shutil
import configparser
import platform
from datetime import datetime

import git
from git.remote import RemoteProgress
from urllib.parse import urlparse
from tqdm.auto import tqdm
import time
import yaml
import zipfile
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

orig_print = print

from rich import print
from packaging import version

import uuid

glob_path = os.path.join(os.path.dirname(__file__))  # ComfyUI-Manager/glob
sys.path.append(glob_path)

import cm_global
import cnr_utils
import manager_util
import git_utils
import manager_downloader
from node_package import InstalledNodePackage


version_code = [3, 5, 1]
version_str = f"V{version_code[0]}.{version_code[1]}" + (f'.{version_code[2]}' if len(version_code) > 2 else '')


DEFAULT_CHANNEL = "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main"


default_custom_nodes_path = None


def get_default_custom_nodes_path():
    global default_custom_nodes_path
    if default_custom_nodes_path is None:
        try:
            import folder_paths
            default_custom_nodes_path = folder_paths.get_folder_paths("custom_nodes")[0]
        except:
            default_custom_nodes_path = os.path.abspath(os.path.join(manager_util.comfyui_manager_path, '..'))

    return default_custom_nodes_path


def get_custom_nodes_paths():
        try:
            import folder_paths
            return folder_paths.get_folder_paths("custom_nodes")
        except:
            custom_nodes_path = os.path.abspath(os.path.join(manager_util.comfyui_manager_path, '..'))
            return [custom_nodes_path]


def get_comfyui_tag():
    repo = git.Repo(comfy_path)
    try:
        return repo.git.describe('--tags')
    except:
        return None


def get_script_env():
    copied = os.environ.copy()
    git_exe = get_config().get('git_exe')
    if git_exe is not None:
        copied['GIT_EXE_PATH'] = git_exe
    copied['COMFYUI_PATH'] = comfy_path

    return copied


invalid_nodes = {}


def extract_base_custom_nodes_dir(x:str):
    if os.path.dirname(x).endswith('.disabled'):
        return os.path.dirname(os.path.dirname(x))
    elif x.endswith('.disabled'):
        return os.path.dirname(x)
    else:
        return os.path.dirname(x)


def check_invalid_nodes():
    global invalid_nodes

    try:
        import folder_paths
    except:
        try:
            sys.path.append(comfy_path)
            import folder_paths
        except:
            raise Exception(f"Invalid COMFYUI_PATH: {comfy_path}")

    def check(root):
        global invalid_nodes

        subdirs = [d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]
        for subdir in subdirs:
            if subdir in ['.disabled', '__pycache__']:
                continue


            package = unified_manager.installed_node_packages.get(subdir)
            if not package:
                continue

            if not package.isValid():
                invalid_nodes[subdir] = package.fullpath

    node_paths = folder_paths.get_folder_paths("custom_nodes")
    for x in node_paths:
        check(x)

        disabled_dir = os.path.join(x, '.disabled')
        if os.path.exists(disabled_dir):
            check(disabled_dir)

    if len(invalid_nodes):
        print("\n-------------------- ComfyUI-Manager invalid nodes notice ----------------")
        print("\nNodes requiring reinstallation have been detected:\n(Directly delete the corresponding path and reinstall.)\n")

        for x in invalid_nodes.values():
            print(x)

        print("\n---------------------------------------------------------------------------\n")


comfy_path = os.environ.get('COMFYUI_PATH')
if comfy_path is None:
    try:
        import folder_paths
        comfy_path = os.path.join(os.path.dirname(folder_paths.__file__))
    except:
        comfy_path = os.path.abspath(os.path.join(manager_util.comfyui_manager_path, '..', '..'))


channel_list_template_path = os.path.join(manager_util.comfyui_manager_path, 'channels.list.template')
git_script_path = os.path.join(manager_util.comfyui_manager_path, "git_helper.py")

manager_files_path = None
manager_config_path = None
manager_channel_list_path = None
manager_startup_script_path = None
manager_snapshot_path = None
manager_pip_overrides_path = None
manager_components_path = None

def update_user_directory(user_dir):
    global manager_files_path
    global manager_config_path
    global manager_channel_list_path
    global manager_startup_script_path
    global manager_snapshot_path
    global manager_pip_overrides_path
    global manager_components_path

    manager_files_path = os.path.abspath(os.path.join(user_dir, 'default', 'ComfyUI-Manager'))
    if not os.path.exists(manager_files_path):
        os.makedirs(manager_files_path)

    manager_snapshot_path = os.path.join(manager_files_path, "snapshots")
    if not os.path.exists(manager_snapshot_path):
        os.makedirs(manager_snapshot_path)

    manager_startup_script_path = os.path.join(manager_files_path, "startup-scripts")
    if not os.path.exists(manager_startup_script_path):
        os.makedirs(manager_startup_script_path)

    manager_config_path = os.path.join(manager_files_path, 'config.ini')
    manager_channel_list_path = os.path.join(manager_files_path, 'channels.list')
    manager_pip_overrides_path = os.path.join(manager_files_path, "pip_overrides.json")
    manager_components_path = os.path.join(manager_files_path, "components")
    manager_util.cache_dir = os.path.join(manager_files_path, "cache")

    if not os.path.exists(manager_util.cache_dir):
        os.makedirs(manager_util.cache_dir)

try:
    import folder_paths
    update_user_directory(folder_paths.get_user_directory())

except Exception:
    # fallback:
    # This case is only possible when running with cm-cli, and in practice, this case is not actually used.
    update_user_directory(os.path.abspath(manager_util.comfyui_manager_path))


cached_config = None
js_path = None

comfy_ui_required_revision = 1930
comfy_ui_required_commit_datetime = datetime(2024, 1, 24, 0, 0, 0)

comfy_ui_revision = "Unknown"
comfy_ui_commit_datetime = datetime(1900, 1, 1, 0, 0, 0)

channel_dict = None
channel_list = None


def remap_pip_package(pkg):
    if pkg in cm_global.pip_overrides:
        res = cm_global.pip_overrides[pkg]
        print(f"[ComfyUI-Manager] '{pkg}' is remapped to '{res}'")
        return res
    else:
        return pkg


def is_blacklisted(name):
    name = name.strip()

    pattern = r'([^<>!=]+)([<>!=]=?)([^ ]*)'
    match = re.search(pattern, name)

    if match:
        name = match.group(1)

    if name in cm_global.pip_blacklist:
        return True

    if name in cm_global.pip_downgrade_blacklist:
        pips = manager_util.get_installed_packages()

        if match is None:
            if name in pips:
                return True
        elif match.group(2) in ['<=', '==', '<']:
            if name in pips:
                if manager_util.StrictVersion(pips[name]) >= manager_util.StrictVersion(match.group(3)):
                    return True

    return False


def is_installed(name):
    name = name.strip()

    if name.startswith('#'):
        return True

    pattern = r'([^<>!=]+)([<>!=]=?)([0-9.a-zA-Z]*)'
    match = re.search(pattern, name)

    if match:
        name = match.group(1)

    if name in cm_global.pip_blacklist:
        return True

    if name in cm_global.pip_downgrade_blacklist:
        pips = manager_util.get_installed_packages()

        if match is None:
            if name in pips:
                return True
        elif match.group(2) in ['<=', '==', '<']:
            if name in pips:
                if manager_util.StrictVersion(pips[name]) >= manager_util.StrictVersion(match.group(3)):
                    print(f"[ComfyUI-Manager] skip black listed pip installation: '{name}'")
                    return True

    pkg = manager_util.get_installed_packages().get(name.lower())
    if pkg is None:
        return False  # update if not installed

    if match is None:
        return True   # don't update if version is not specified

    if match.group(2) in ['>', '>=']:
        if manager_util.StrictVersion(pkg) < manager_util.StrictVersion(match.group(3)):
            return False
        elif manager_util.StrictVersion(pkg) > manager_util.StrictVersion(match.group(3)):
            print(f"[SKIP] Downgrading pip package isn't allowed: {name.lower()} (cur={pkg})")

    if match.group(2) == '==':
        if manager_util.StrictVersion(pkg) < manager_util.StrictVersion(match.group(3)):
            return False

    if match.group(2) == '~=':
        if manager_util.StrictVersion(pkg) == manager_util.StrictVersion(match.group(3)):
            return False

    return name.lower() in manager_util.get_installed_packages()


def normalize_channel(channel):
    if channel == 'local':
        return channel
    elif channel is None:
        return None
    elif channel.startswith('https://'):
        return channel

    tmp_dict = get_channel_dict()
    channel_url = tmp_dict.get(channel)
    if channel_url:
        return channel_url

    raise Exception(f"Invalid channel name '{channel}'")


class ManagedResult:
    def __init__(self, action):
        self.action = action
        self.items = []
        self.result = True
        self.to_path = None
        self.msg = None
        self.target = None
        self.postinstall = lambda: True

    def append(self, item):
        self.items.append(item)

    def fail(self, msg):
        self.result = False
        self.msg = msg
        return self

    def with_target(self, target):
        self.target = target
        return self

    def with_msg(self, msg):
        self.msg = msg
        return self

    def with_postinstall(self, postinstall):
        self.postinstall = postinstall
        return self


class UnifiedManager:
    def __init__(self):
        self.installed_node_packages: dict[str, InstalledNodePackage] = {}

        self.cnr_inactive_nodes = {}       # node_id -> node_version -> fullpath
        self.nightly_inactive_nodes = {}   # node_id -> fullpath
        self.unknown_inactive_nodes = {}   # node_id -> repo url * fullpath
        self.active_nodes = {}             # node_id -> node_version * fullpath
        self.unknown_active_nodes = {}     # node_id -> repo url * fullpath
        self.cnr_map = {}                  # node_id -> cnr info
        self.repo_cnr_map = {}             # repo_url -> cnr info
        self.custom_node_map_cache = {}    # (channel, mode) -> augmented custom node list json
        self.processed_install = set()


    def get_cnr_by_repo(self, url):
        return self.repo_cnr_map.get(git_utils.normalize_url(url))

    def resolve_unspecified_version(self, node_name, guess_mode=None):
        if guess_mode == 'active':
            # priority:
            # 1. CNR/nightly active nodes
            # 2. unknown
            # 3. Fail

            if node_name in self.cnr_map:
                version_spec = self.get_from_cnr_active_nodes(node_name)

                if version_spec is None:
                    if node_name in self.unknown_active_nodes:
                        version_spec = "unknown"
                    else:
                        return None

            elif node_name in self.unknown_active_nodes:
                version_spec = "unknown"
            else:
                return None

        elif guess_mode == 'inactive':
            # priority:
            # 1. CNR latest in inactive
            # 2. nightly
            # 3. unknown
            # 4. Fail

            if node_name in self.cnr_map:
                latest = self.get_from_cnr_inactive_nodes(node_name)

                if latest is not None:
                    version_spec = str(latest[0])
                else:
                    if node_name in self.nightly_inactive_nodes:
                        version_spec = "nightly"
                    else:
                        version_spec = "unknown"

            elif node_name in self.unknown_inactive_nodes:
                version_spec = "unknown"
            else:
                return None

        else:
            # priority:
            # 1. CNR latest in world
            # 2. unknown

            if node_name in self.cnr_map:
                version_spec = self.cnr_map[node_name]['latest_version']['version']
            else:
                version_spec = "unknown"

        return version_spec

    def resolve_node_spec(self, node_name, guess_mode=None):
        """
        resolve to 'node_name, version_spec' from version string

        version string:
            node_name@latest
            node_name@nightly
            node_name@unknown
            node_name@<version>
            node_name

        if guess_mode is 'active' or 'inactive'
            return can be 'None' based on state check
        otherwise
            return 'unknown' version when failed to guess
        """

        spec = node_name.split('@')

        if len(spec) == 2:
            node_name = spec[0]
            version_spec = spec[1]

            if version_spec == 'latest':
                if node_name not in self.cnr_map:
                    print(f"ERROR: '{node_name}' is not a CNR node.")
                    return None
                else:
                    version_spec = self.cnr_map[node_name]['latest_version']['version']

        elif guess_mode in ['active', 'inactive']:
            node_name = spec[0]
            version_spec = self.resolve_unspecified_version(node_name, guess_mode=guess_mode)
            if version_spec is None:
                return None
        else:
            node_name = spec[0]
            version_spec = self.resolve_unspecified_version(node_name)
            if version_spec is None:
                return None

        return node_name, version_spec, len(spec) > 1

    def resolve_from_path(self, fullpath):
        url = git_utils.git_url(fullpath)
        if url:
            cnr = self.get_cnr_by_repo(url)
            commit_hash = git_utils.get_commit_hash(fullpath)
            if cnr:
                cnr_utils.generate_cnr_id(fullpath, cnr['id'])
                return {'id': cnr['id'], 'cnr': cnr, 'ver': 'nightly', 'hash': commit_hash}
            else:
                url = os.path.basename(url)
                if url.endswith('.git'):
                    url = url[:-4]
                return {'id': url, 'ver': 'unknown', 'hash': commit_hash}
        else:
            info = cnr_utils.read_cnr_info(fullpath)

            if info:
                cnr = self.cnr_map.get(info['id'])
                if cnr:
                    return {'id': cnr['id'], 'cnr': cnr, 'ver': info['version']}
                else:
                    return None
            else:
                return None

    def update_cache_at_path(self, fullpath):
        node_package = InstalledNodePackage.from_fullpath(fullpath, self.resolve_from_path)
        self.installed_node_packages[node_package.id] = node_package

        if node_package.is_disabled and node_package.is_unknown:
            # NOTE: unknown package does not have an url.
            self.unknown_inactive_nodes[node_package.id] = ('', node_package.fullpath)

        if node_package.is_disabled and node_package.is_nightly:
            self.nightly_inactive_nodes[node_package.id] = node_package.fullpath

        if node_package.is_enabled:
            self.active_nodes[node_package.id] = node_package.version, node_package.fullpath

        if node_package.is_enabled and node_package.is_unknown:
            # NOTE: unknown package does not have an url.
            self.unknown_active_nodes[node_package.id] = ('', node_package.fullpath)

        if node_package.is_from_cnr and node_package.is_disabled:
            self.add_to_cnr_inactive_nodes(node_package.id, node_package.version, node_package.fullpath)

    def is_updatable(self, node_id):
        cur_ver = self.get_cnr_active_version(node_id)
        latest_ver = self.cnr_map[node_id]['latest_version']['version']

        if cur_ver and latest_ver:
            return self.safe_version(latest_ver) > self.safe_version(cur_ver)

        return False

    def fetch_or_pull_git_repo(self, is_pull=False):
        updated = set()
        failed = set()

        def check_update(node_name, fullpath, ver_spec):
            try:
                if is_pull:
                    is_updated, success = git_repo_update_check_with(fullpath, do_update=True)
                else:
                    is_updated, success = git_repo_update_check_with(fullpath, do_fetch=True)

                return f"{node_name}@{ver_spec}", is_updated, success
            except Exception:
                traceback.print_exc()

            return f"{node_name}@{ver_spec}", False, False

        with ThreadPoolExecutor() as executor:
            futures = []

            for k, v in self.unknown_active_nodes.items():
                futures.append(executor.submit(check_update, k, v[1], 'unknown'))

            for k, v in self.active_nodes.items():
                if v[0] == 'nightly':
                    futures.append(executor.submit(check_update, k, v[1], 'nightly'))

            for future in as_completed(futures):
                item, is_updated, success = future.result()

                if is_updated:
                    updated.add(item)

                if not success:
                    failed.add(item)

        return dict(updated=list(updated), failed=list(failed))

    def is_enabled(self, node_id, version_spec=None):
        """
        1. true if node_id@<specified_version> is enabled
        2. true if node_id@<any> is enabled and version_spec==None
        3. false otherwise

        remark: latest version_spec is not allowed. Must be resolved before call.
        """
        if version_spec == "cnr":
            return self.get_cnr_active_version(node_id) not in [None, 'nightly']
        elif version_spec == 'unknown' and self.is_unknown_active(node_id):
            return True
        elif version_spec is not None and self.get_cnr_active_version(node_id) == version_spec:
            return True
        elif version_spec is None and (node_id in self.active_nodes or node_id in self.unknown_active_nodes):
            return True
        return False

    def is_disabled(self, node_id, version_spec=None):
        """
        1. node_id@unknown is disabled if version_spec is @unknown
        2. node_id@nightly is disabled if version_spec is @nightly
        4. node_id@<specified_version> is disabled if version_spec is not None
        5. not exists (active node_id) if version_spec is None

        remark: latest version_spec is not allowed. Must be resolved before call.
        """
        if version_spec == "unknown":
            return node_id in self.unknown_inactive_nodes
        elif version_spec == "nightly":
            return node_id in self.nightly_inactive_nodes
        elif version_spec == "cnr":
            res = self.cnr_inactive_nodes.get(node_id, None)
            if res is None:
                return False

            res = [x for x in res.keys() if x != 'nightly']
            return len(res) > 0
        elif version_spec is not None:
            return version_spec in self.cnr_inactive_nodes.get(node_id, [])

        if node_id in self.nightly_inactive_nodes:
            return True
        elif node_id in self.unknown_inactive_nodes:
            return True

        target = self.cnr_inactive_nodes.get(node_id, None)
        if target is not None and target == version_spec:
            return True

        return False

    def is_registered_in_cnr(self, node_id):
        return node_id in self.cnr_map

    def get_cnr_active_version(self, node_id):
        res = self.active_nodes.get(node_id)
        if res:
            return res[0]
        else:
            return None

    def is_unknown_active(self, node_id):
        return node_id in self.unknown_active_nodes

    def add_to_cnr_inactive_nodes(self, node_id, ver, fullpath):
        ver_map = self.cnr_inactive_nodes.get(node_id)
        if ver_map is None:
            ver_map = {}
            self.cnr_inactive_nodes[node_id] = ver_map

        ver_map[ver] = fullpath

    def get_from_cnr_active_nodes(self, node_id):
        ver_path = self.active_nodes.get(node_id)
        if ver_path is None:
            return None

        return ver_path[0]

    def get_from_cnr_inactive_nodes(self, node_id, ver=None):
        ver_map = self.cnr_inactive_nodes.get(node_id)
        if ver_map is None:
            return None

        if ver is not None:
            return ver_map.get(ver)

        latest = None
        for k, v in ver_map.items():
            if latest is None:
                latest = self.safe_version(k), v
                continue

            cur_ver = self.safe_version(k)
            if cur_ver > latest[0]:
                latest = cur_ver, v

        return latest

    async def reload(self, cache_mode):
        self.custom_node_map_cache = {}
        self.cnr_inactive_nodes = {}      # node_id -> node_version -> fullpath
        self.nightly_inactive_nodes = {}  # node_id -> fullpath
        self.unknown_inactive_nodes = {}  # node_id -> repo url * fullpath
        self.unknown_active_nodes = {}    # node_id -> repo url * fullpath
        self.active_nodes = {}            # node_id -> node_version * fullpath

        # reload 'cnr_map' and 'repo_cnr_map'
        cnrs = await cnr_utils.get_cnr_data(cache_mode=cache_mode)

        for x in cnrs:
            self.cnr_map[x['id']] = x

            if 'repository' in x:
                normalized_url = git_utils.normalize_url(x['repository'])
                self.repo_cnr_map[normalized_url] = x

        # reload node status info from custom_nodes/*
        for custom_nodes_path in folder_paths.get_folder_paths('custom_nodes'):
            for x in os.listdir(custom_nodes_path):
                fullpath = os.path.join(custom_nodes_path, x)
                if os.path.isdir(fullpath):
                    if x not in ['__pycache__', '.disabled']:
                        self.update_cache_at_path(fullpath)

        # reload node status info from custom_nodes/.disabled/*
        for custom_nodes_path in folder_paths.get_folder_paths('custom_nodes'):
            disabled_dir = os.path.join(custom_nodes_path, '.disabled')
            if os.path.exists(disabled_dir):
                for x in os.listdir(disabled_dir):
                    fullpath = os.path.join(disabled_dir, x)
                    if os.path.isdir(fullpath):
                        self.update_cache_at_path(fullpath)

    @staticmethod
    async def load_nightly(channel, mode):
        res = {}

        channel_url = normalize_channel(channel)
        if channel_url:
            if mode not in ['remote', 'local', 'cache']:
                print(f"[bold red]ERROR: Invalid mode is specified `--mode {mode}`[/bold red]", file=sys.stderr)
                return {}

        json_obj = await get_data_by_mode(mode, 'custom-node-list.json', channel_url=channel_url)
        for x in json_obj['custom_nodes']:
            for y in x['files']:
                if 'github.com' in y and not (y.endswith('.py') or y.endswith('.js')):
                    repo_name = y.split('/')[-1]
                    res[repo_name] = (x, False)

            if 'id' in x:
                if x['id'] not in res:
                    res[x['id']] = (x, True)

        return res

    async def get_custom_nodes(self, channel, mode):
        default_channel = normalize_channel('default')
        cache = self.custom_node_map_cache.get((default_channel, mode)) # CNR/nightly should always be based on the default channel.

        if cache is not None:
            return cache

        channel = normalize_channel(channel)
        print(f"nightly_channel: {channel}/{mode}")
        nodes = await self.load_nightly(channel, mode)

        res = {}
        added_cnr = set()
        for v in nodes.values():
            v = v[0]
            if len(v['files']) == 1:
                cnr = self.get_cnr_by_repo(v['files'][0])
                if cnr:
                    if 'latest_version' not in cnr:
                        v['cnr_latest'] = '0.0.0'
                    else:
                        v['cnr_latest'] = cnr['latest_version']['version']
                    v['id'] = cnr['id']
                    v['author'] = cnr['publisher']['name']
                    v['title'] = cnr['name']
                    v['description'] = cnr['description']
                    v['health'] = '-'
                    added_cnr.add(cnr['id'])
                    node_id = v['id']
                else:
                    node_id = v['files'][0].split('/')[-1]
                res[node_id] = v
            elif len(v['files']) > 1:
                res[v['files'][0]] = v  # A custom node composed of multiple url is treated as a single repository with one representative path

        self.custom_node_map_cache[(channel, mode)] = res
        return res

    @staticmethod
    def safe_version(ver_str):
        try:
            return version.parse(ver_str)
        except:
            return version.parse("0.0.0")

    def execute_install_script(self, url, repo_path, instant_execution=False, lazy_mode=False, no_deps=False):
        install_script_path = os.path.join(repo_path, "install.py")
        requirements_path = os.path.join(repo_path, "requirements.txt")

        if lazy_mode:
            install_cmd = ["#LAZY-INSTALL-SCRIPT", sys.executable]
            return try_install_script(url, repo_path, install_cmd)
        else:
            if os.path.exists(requirements_path) and not no_deps:
                print("Install: pip packages")
                pip_fixer = manager_util.PIPFixer(manager_util.get_installed_packages())
                res = True
                with open(requirements_path, "r") as requirements_file:
                    for line in requirements_file:
                        package_name = remap_pip_package(line.strip())
                        if package_name and not package_name.startswith('#') and package_name not in self.processed_install:
                            self.processed_install.add(package_name)
                            install_cmd = [sys.executable, "-m", "pip", "install", package_name]
                            if package_name.strip() != "" and not package_name.startswith('#'):
                                res = res and try_install_script(url, repo_path, install_cmd, instant_execution=instant_execution)

                pip_fixer.fix_broken()
                return res

            if os.path.exists(install_script_path) and install_script_path not in self.processed_install:
                self.processed_install.add(install_script_path)
                print("Install: install script")
                install_cmd = [sys.executable, "install.py"]
                return try_install_script(url, repo_path, install_cmd, instant_execution=instant_execution)

        return True

    def reserve_cnr_switch(self, target, zip_url, from_path, to_path, no_deps):
        script_path = os.path.join(manager_startup_script_path, "install-scripts.txt")
        with open(script_path, "a") as file:
            obj = [target, "#LAZY-CNR-SWITCH-SCRIPT", zip_url, from_path, to_path, no_deps, get_default_custom_nodes_path(), sys.executable]
            file.write(f"{obj}\n")

        print(f"Installation reserved: {target}")

        return True

    def reserve_migration(self, moves):
        script_path = os.path.join(manager_startup_script_path, "install-scripts.txt")
        with open(script_path, "a") as file:
            obj = ["", "#LAZY-MIGRATION", moves]
            file.write(f"{obj}\n")

        return True

    def unified_fix(self, node_id, version_spec, instant_execution=False, no_deps=False):
        """
        fix dependencies
        """

        result = ManagedResult('fix')

        info = self.active_nodes.get(node_id)
        if info is None or not os.path.exists(info[1]):
            return result.fail(f'not found: {node_id}@{version_spec}')

        self.execute_install_script(node_id, info[1], instant_execution=instant_execution, no_deps=no_deps)

        return result

    def cnr_switch_version(self, node_id, version_spec=None, instant_execution=False, no_deps=False, return_postinstall=False):
        if instant_execution:
            return self.cnr_switch_version_instant(node_id, version_spec, instant_execution, no_deps, return_postinstall)
        else:
            return self.cnr_switch_version_lazy(node_id, version_spec, no_deps, return_postinstall)

    def cnr_switch_version_lazy(self, node_id, version_spec=None, no_deps=False, return_postinstall=False):
        """
        switch between cnr version (lazy mode)
        """

        result = ManagedResult('switch-cnr')

        node_info = cnr_utils.install_node(node_id, version_spec)
        if node_info is None or not node_info.download_url:
            return result.fail(f'not available node: {node_id}@{version_spec}')

        version_spec = node_info.version

        if self.active_nodes[node_id][0] == version_spec:
            return ManagedResult('skip').with_msg("Up to date")

        zip_url = node_info.download_url
        from_path = self.active_nodes[node_id][1]
        target = node_id
        to_path = os.path.join(get_default_custom_nodes_path(), target)

        def postinstall():
            return self.reserve_cnr_switch(target, zip_url, from_path, to_path, no_deps)

        if return_postinstall:
            return result.with_postinstall(postinstall)
        else:
            if not postinstall():
                return result.fail(f"Failed to execute install script: {node_id}@{version_spec}")

        return result

    def cnr_switch_version_instant(self, node_id, version_spec=None, instant_execution=True, no_deps=False, return_postinstall=False):
        """
        switch between cnr version
        """

        # 1. download
        result = ManagedResult('switch-cnr')

        node_info = cnr_utils.install_node(node_id, version_spec)
        if node_info is None or not node_info.download_url:
            return result.fail(f'not available node: {node_id}@{version_spec}')

        version_spec = node_info.version

        if self.active_nodes[node_id][0] == version_spec:
            return ManagedResult('skip').with_msg("Up to date")

        archive_name = f"CNR_temp_{str(uuid.uuid4())}.zip"  # should be unpredictable name - security precaution
        download_path = os.path.join(get_default_custom_nodes_path(), archive_name)
        manager_downloader.download_url(node_info.download_url, get_default_custom_nodes_path(), archive_name)

        # 2. extract files into <node_id>
        install_path = self.active_nodes[node_id][1]
        extracted = manager_util.extract_package_as_zip(download_path, install_path)
        os.remove(download_path)

        if extracted is None:
            if len(os.listdir(install_path)) == 0:
                shutil.rmtree(install_path)

            return result.fail(f'Empty archive file: {node_id}@{version_spec}')

        # 3. calculate garbage files (.tracking - extracted)
        tracking_info_file = os.path.join(install_path, '.tracking')
        prev_files = set()
        with open(tracking_info_file, 'r') as f:
            for line in f:
                prev_files.add(line.strip())
        garbage = prev_files.difference(extracted)
        garbage = [os.path.join(install_path, x) for x in garbage]

        # 4-1. remove garbage files
        for x in garbage:
            if os.path.isfile(x):
                os.remove(x)

        # 4-2. remove garbage dir if empty
        for x in garbage:
            if os.path.isdir(x):
                if not os.listdir(x):
                    os.rmdir(x)

        # 5. create .tracking file
        tracking_info_file = os.path.join(install_path, '.tracking')
        with open(tracking_info_file, "w", encoding='utf-8') as file:
            file.write('\n'.join(list(extracted)))

        # 6. post install
        result.target = version_spec

        def postinstall():
            res = self.execute_install_script(f"{node_id}@{version_spec}", install_path, instant_execution=instant_execution, no_deps=no_deps)
            return res

        if return_postinstall:
            return result.with_postinstall(postinstall)
        else:
            if not postinstall():
                return result.fail(f"Failed to execute install script: {node_id}@{version_spec}")

        return result

    def unified_enable(self, node_id, version_spec=None):
        """
        priority if version_spec == None
        1. CNR latest in disk
        2. nightly
        3. unknown

        remark: latest version_spec is not allowed. Must be resolved before call.
        """

        result = ManagedResult('enable')

        if version_spec is None:
            version_spec = self.resolve_unspecified_version(node_id, guess_mode='inactive')
            if version is None:
                return result.fail(f'Specified inactive node not exists: {node_id}')

        if self.is_enabled(node_id, version_spec):
            return ManagedResult('skip').with_msg('Already enabled')

        if not self.is_disabled(node_id, version_spec):
            return ManagedResult('skip').with_msg('Not installed')

        from_path = None
        to_path = None

        if version_spec == 'unknown':
            repo_and_path = self.unknown_inactive_nodes.get(node_id)
            if repo_and_path is None:
                return result.fail(f'Specified inactive node not exists: {node_id}@unknown')
            from_path = repo_and_path[1]

            base_path = extract_base_custom_nodes_dir(from_path)
            to_path = os.path.join(base_path, node_id)
        elif version_spec == 'nightly':
            self.unified_disable(node_id, False)
            from_path = self.nightly_inactive_nodes.get(node_id)
            if from_path is None:
                return result.fail(f'Specified inactive node not exists: {node_id}@nightly')
            base_path = extract_base_custom_nodes_dir(from_path)
            to_path = os.path.join(base_path, node_id)
        elif version_spec is not None:
            self.unified_disable(node_id, False)
            cnr_info = self.cnr_inactive_nodes.get(node_id)

            if cnr_info is None or len(cnr_info) == 0:
                return result.fail(f'Specified inactive cnr node not exists: {node_id}')

            if version_spec == "cnr":
                version_spec = next(iter(cnr_info))

            if version_spec not in cnr_info:
                return result.fail(f'Specified inactive node not exists: {node_id}@{version_spec}')

            from_path = cnr_info[version_spec]
            base_path = extract_base_custom_nodes_dir(from_path)
            to_path = os.path.join(base_path, node_id)

        if from_path is None or not os.path.exists(from_path):
            return result.fail(f'Specified inactive node path not exists: {from_path}')

        # move from disk
        shutil.move(from_path, to_path)

        # update cache
        if version_spec == 'unknown':
            del self.unknown_inactive_nodes[node_id]
            self.unknown_active_nodes[node_id] = to_path
            return result.with_target(to_path)
        elif version_spec == 'nightly':
            del self.nightly_inactive_nodes[node_id]
        else:
            del self.cnr_inactive_nodes[node_id][version_spec]

        self.active_nodes[node_id] = version_spec, to_path
        return result.with_target(to_path)

    def unified_disable(self, node_id, is_unknown):
        result = ManagedResult('disable')

        if is_unknown:
            version_spec = 'unknown'
        else:
            version_spec = None

        if not self.is_enabled(node_id, version_spec):
            if not self.is_disabled(node_id, version_spec):
                return ManagedResult('skip').with_msg('Not installed')
            else:
                return ManagedResult('skip').with_msg('Already disabled')

        if is_unknown:
            repo_and_path = self.unknown_active_nodes.get(node_id)

            if repo_and_path is None or not os.path.exists(repo_and_path[1]):
                return result.fail(f'Specified active node not exists: {node_id}')

            base_path = extract_base_custom_nodes_dir(repo_and_path[1])
            to_path = os.path.join(base_path, '.disabled', node_id)

            shutil.move(repo_and_path[1], to_path)
            result.append((repo_and_path[1], to_path))

            self.unknown_inactive_nodes[node_id] = repo_and_path[0], to_path
            del self.unknown_active_nodes[node_id]

            return result

        ver_and_path = self.active_nodes.get(node_id)

        if ver_and_path is None or not os.path.exists(ver_and_path[1]):
            return result.fail(f'Specified active node not exists: {node_id}')

        base_path = extract_base_custom_nodes_dir(ver_and_path[1])

        # NOTE: A disabled node may have multiple versions, so preserve it using the `@ suffix`.
        to_path = os.path.join(base_path, '.disabled', f"{node_id}@{ver_and_path[0].replace('.', '_')}")
        shutil.move(ver_and_path[1], to_path)
        result.append((ver_and_path[1], to_path))

        if ver_and_path[0] == 'nightly':
            self.nightly_inactive_nodes[node_id] = to_path
        else:
            self.add_to_cnr_inactive_nodes(node_id, ver_and_path[0], to_path)

        del self.active_nodes[node_id]

        return result

    def unified_uninstall(self, node_id: str, is_unknown: bool):
        """
        Remove whole installed custom nodes including inactive nodes
        """
        result = ManagedResult('uninstall')

        if is_unknown:
            # remove from actives
            repo_and_path = self.unknown_active_nodes.get(node_id)

            is_removed = False

            if repo_and_path is not None and os.path.exists(repo_and_path[1]):
                rmtree(repo_and_path[1])
                result.append(repo_and_path[1])
                del self.unknown_active_nodes[node_id]

                is_removed = True

            # remove from inactives
            repo_and_path = self.unknown_inactive_nodes.get(node_id)

            if repo_and_path is not None and os.path.exists(repo_and_path[1]):
                rmtree(repo_and_path[1])
                result.append(repo_and_path[1])
                del self.unknown_inactive_nodes[node_id]

                is_removed = True

            if is_removed:
                return result
            else:
                return ManagedResult('skip')

        # remove from actives
        ver_and_path = self.active_nodes.get(node_id)

        if ver_and_path is not None and os.path.exists(ver_and_path[1]):
            shutil.rmtree(ver_and_path[1])
            result.items.append(ver_and_path)
            del self.active_nodes[node_id]

        # remove from nightly inactives
        fullpath = self.nightly_inactive_nodes.get(node_id)
        if fullpath is not None and os.path.exists(fullpath):
            shutil.rmtree(fullpath)
            result.items.append(('nightly', fullpath))
            del self.nightly_inactive_nodes[node_id]

        # remove from cnr inactives
        ver_map = self.cnr_inactive_nodes.get(node_id)
        if ver_map is not None:
            for key, fullpath in ver_map.items():
                shutil.rmtree(fullpath)
                result.items.append((key, fullpath))
            del self.cnr_inactive_nodes[node_id]

        if len(result.items) == 0:
            return ManagedResult('skip').with_msg('Not installed')

        return result

    def cnr_install(self, node_id, version_spec=None, instant_execution=False, no_deps=False, return_postinstall=False):
        result = ManagedResult('install-cnr')

        node_info = cnr_utils.install_node(node_id, version_spec)
        if node_info is None or not node_info.download_url:
            return result.fail(f'not available node: {node_id}@{version_spec}')

        archive_name = f"CNR_temp_{str(uuid.uuid4())}.zip"  # should be unpredictable name - security precaution
        download_path = os.path.join(get_default_custom_nodes_path(), archive_name)

        # re-download. I cannot trust existing file.
        if os.path.exists(download_path):
            os.remove(download_path)

        # install_path
        install_path = os.path.join(get_default_custom_nodes_path(), node_id)
        if os.path.exists(install_path):
            return result.fail(f'Install path already exists: {install_path}')

        manager_downloader.download_url(node_info.download_url, get_default_custom_nodes_path(), archive_name)
        os.makedirs(install_path, exist_ok=True)
        extracted = manager_util.extract_package_as_zip(download_path, install_path)
        os.remove(download_path)
        result.to_path = install_path

        if extracted is None:
            shutil.rmtree(install_path)
            return result.fail(f'Empty archive file: {node_id}@{version_spec}')

        # create .tracking file
        tracking_info_file = os.path.join(install_path, '.tracking')
        with open(tracking_info_file, "w", encoding='utf-8') as file:
            file.write('\n'.join(extracted))

        result.target = version_spec

        def postinstall():
            return self.execute_install_script(node_id, install_path, instant_execution=instant_execution, no_deps=no_deps)

        if return_postinstall:
            return result.with_postinstall(postinstall)
        else:
            if not postinstall():
                return result.fail(f"Failed to execute install script: {node_id}@{version_spec}")

        return result

    def repo_install(self, url, repo_path, instant_execution=False, no_deps=False, return_postinstall=False):
        result = ManagedResult('install-git')
        result.append(url)

        if not is_valid_url(url):
            return result.fail(f"Invalid git url: {url}")

        if url.endswith("/"):
            url = url[:-1]
        try:
            print(f"Download: git clone '{url}'")

            # Clone the repository from the remote URL
            if not instant_execution and platform.system() == 'Windows':
                res = manager_funcs.run_script([sys.executable, git_script_path, "--clone", get_default_custom_nodes_path(), url, repo_path], cwd=get_default_custom_nodes_path())
                if res != 0:
                    return result.fail(f"Failed to clone repo: {url}")
            else:
                repo = git.Repo.clone_from(url, repo_path, recursive=True, progress=GitProgress())
                repo.git.clear_cache()
                repo.close()

            def postinstall():
                return self.execute_install_script(url, repo_path, instant_execution=instant_execution, no_deps=no_deps)

            if return_postinstall:
                return result.with_postinstall(postinstall)
            else:
                if not postinstall():
                    return result.fail(f"Failed to execute install script: {url}")

        except Exception as e:
            return result.fail(f"Install(git-clone) error: {url} / {e}")

        print("Installation was successful.")
        return result

    def repo_update(self, repo_path, instant_execution=False, no_deps=False, return_postinstall=False):
        result = ManagedResult('update-git')

        if not os.path.exists(os.path.join(repo_path, '.git')):
            return result.fail(f'Path not found: {repo_path}')

        # version check
        repo = git.Repo(repo_path)

        if repo.head.is_detached:
            switch_to_default_branch(repo)

        current_branch = repo.active_branch
        branch_name = current_branch.name

        if current_branch.tracking_branch() is None:
            print(f"[ComfyUI-Manager] There is no tracking branch ({current_branch})")
            remote_name = 'origin'
        else:
            remote_name = current_branch.tracking_branch().remote_name
        remote = repo.remote(name=remote_name)

        try:
            remote.fetch()
        except Exception as e:
            if 'detected dubious' in str(e):
                print("[ComfyUI-Manager] Try fixing 'dubious repository' error on 'ComfyUI' repository")
                safedir_path = comfy_path.replace('\\', '/')
                subprocess.run(['git', 'config', '--global', '--add', 'safe.directory', safedir_path])
                try:
                    remote.fetch()
                except Exception:
                    print("\n[ComfyUI-Manager] Failed to fixing repository setup. Please execute this command on cmd: \n"
                          "-----------------------------------------------------------------------------------------\n"
                          f'git config --global --add safe.directory "{safedir_path}"\n'
                          "-----------------------------------------------------------------------------------------\n")

        commit_hash = repo.head.commit.hexsha
        remote_commit_hash = repo.refs[f'{remote_name}/{branch_name}'].object.hexsha

        if commit_hash != remote_commit_hash:
            git_pull(repo_path)

            if len(repo.remotes) > 0:
                url = repo.remotes[0].url
            else:
                url = "unknown repo"

            def postinstall():
                return self.execute_install_script(url, repo_path, instant_execution=instant_execution, no_deps=no_deps)

            if return_postinstall:
                return result.with_postinstall(postinstall)
            else:
                if not postinstall():
                    return result.fail(f"Failed to execute install script: {url}")

            return result
        else:
            return ManagedResult('skip').with_msg('Up to date')

    def unified_update(self, node_id, version_spec=None, instant_execution=False, no_deps=False, return_postinstall=False):
        orig_print(f"\x1b[2K\rUpdating: {node_id}", end='')

        if version_spec is None:
            version_spec = self.resolve_unspecified_version(node_id, guess_mode='active')

        if version_spec is None:
            return ManagedResult('update').fail(f'Update not available: {node_id}@{version_spec}')

        if version_spec == 'nightly':
            return self.repo_update(self.active_nodes[node_id][1], instant_execution=instant_execution, no_deps=no_deps, return_postinstall=return_postinstall).with_target('nightly')
        elif version_spec == 'unknown':
            return self.repo_update(self.unknown_active_nodes[node_id][1], instant_execution=instant_execution, no_deps=no_deps, return_postinstall=return_postinstall).with_target('unknown')
        else:
            return self.cnr_switch_version(node_id, instant_execution=instant_execution, no_deps=no_deps, return_postinstall=return_postinstall)

    async def install_by_id(self, node_id, version_spec=None, channel=None, mode=None, instant_execution=False, no_deps=False, return_postinstall=False):
        """
        priority if version_spec == None
        1. CNR latest
        2. unknown

        remark: latest version_spec is not allowed. Must be resolved before call.
        """

        repo_url = None
        if version_spec is None:
            if self.is_enabled(node_id):
                return ManagedResult('skip')
            elif self.is_disabled(node_id):
                return self.unified_enable(node_id)
            else:
                version_spec = self.resolve_unspecified_version(node_id)

        if version_spec == 'unknown' or version_spec == 'nightly':
            custom_nodes = await self.get_custom_nodes(channel, mode)
            the_node = custom_nodes.get(node_id)
            if the_node is not None:
                repo_url = the_node['files'][0]
            else:
                result = ManagedResult('install')
                return result.fail(f"Node '{node_id}@{version_spec}' not found in [{channel}, {mode}]")

        if self.is_enabled(node_id, version_spec):
            return ManagedResult('skip').with_target(f"{node_id}@{version_spec}")

        elif self.is_disabled(node_id, version_spec):
            return self.unified_enable(node_id, version_spec)

        elif version_spec == 'unknown' or version_spec == 'nightly':
            if version_spec == 'nightly':
                # disable cnr nodes
                if self.is_enabled(node_id, 'cnr'):
                    self.unified_disable(node_id, False)

            to_path = os.path.abspath(os.path.join(get_default_custom_nodes_path(), node_id))
            res = self.repo_install(repo_url, to_path, instant_execution=instant_execution, no_deps=no_deps, return_postinstall=return_postinstall)
            if res.result:
                if version_spec == 'unknown':
                    self.unknown_active_nodes[node_id] = to_path
                elif version_spec == 'nightly':
                    cnr_utils.generate_cnr_id(to_path, node_id)
                    self.active_nodes[node_id] = 'nightly', to_path

            return res.with_target(version_spec)

        if self.is_enabled(node_id, 'nightly'):
            # disable nightly nodes
            self.unified_disable(node_id, False)  # NOTE: don't return from here

        if self.is_disabled(node_id, version_spec):
            # enable and return if specified version is disabled
            return self.unified_enable(node_id, version_spec)

        if self.is_disabled(node_id, "cnr"):
            # enable and switch version if cnr is disabled (not specified version)
            self.unified_enable(node_id, "cnr")
            return self.cnr_switch_version(node_id, version_spec, no_deps=no_deps, return_postinstall=return_postinstall)

        if self.is_enabled(node_id, "cnr"):
            return self.cnr_switch_version(node_id, version_spec, no_deps=no_deps, return_postinstall=return_postinstall)

        res = self.cnr_install(node_id, version_spec, instant_execution=instant_execution, no_deps=no_deps, return_postinstall=return_postinstall)
        if res.result:
            self.active_nodes[node_id] = version_spec, res.to_path

        return res

    async def migrate_unmanaged_nodes(self):
        """
        fix path for nightly and unknown nodes of unmanaged nodes
        """
        await self.reload('cache')
        await self.get_custom_nodes('default', 'cache')

        print("Migration: STAGE 1")
        moves = []

        # migrate nightly inactive
        for x, v in self.nightly_inactive_nodes.items():
            if v.endswith('@nightly'):
                continue

            new_path = os.path.join(get_default_custom_nodes_path(), '.disabled', f"{x}@nightly")
            moves.append((v, new_path))

        self.reserve_migration(moves)

        print("DONE (Migration reserved)")


unified_manager = UnifiedManager()


def identify_node_pack_from_path(fullpath):
    module_name = os.path.basename(fullpath)
    if module_name.endswith('.git'):
        module_name = module_name[:-4]

    repo_url = git_utils.git_url(fullpath)
    if repo_url is None:
        # cnr
        cnr = cnr_utils.read_cnr_info(fullpath)
        if cnr is not None:
            return module_name, cnr['version'], cnr['id']

        return None
    else:
        # nightly or unknown
        cnr_id = cnr_utils.read_cnr_id(fullpath)
        commit_hash = git_utils.get_commit_hash(fullpath)

        if cnr_id is not None:
            return module_name, commit_hash, cnr_id
        else:
            return module_name, commit_hash, ''


def get_installed_node_packs():
    res = {}

    for x in get_custom_nodes_paths():
        for y in os.listdir(x):
            if y == '__pycache__' or y == '.disabled':
                continue

            fullpath = os.path.join(x, y)
            info = identify_node_pack_from_path(fullpath)
            if info is None:
                continue

            is_disabled = not y.endswith('.disabled')

            res[info[0]] = { 'ver': info[1], 'cnr_id': info[2], 'enabled': is_disabled }

        disabled_dirs = os.path.join(x, '.disabled')
        if os.path.exists(disabled_dirs):
            for y in os.listdir(disabled_dirs):
                if y == '__pycache__':
                    continue

                fullpath = os.path.join(disabled_dirs, y)
                info = identify_node_pack_from_path(fullpath)
                if info is None:
                    continue

                res[info[0]] = { 'ver': info[1], 'cnr_id': info[2], 'enabled': False }

    return res


def get_channel_dict():
    global channel_dict

    if channel_dict is None:
        channel_dict = {}

        if not os.path.exists(manager_channel_list_path):
            shutil.copy(channel_list_template_path, manager_channel_list_path)

        with open(manager_channel_list_path, 'r') as file:
            channels = file.read()
            for x in channels.split('\n'):
                channel_info = x.split("::")
                if len(channel_info) == 2:
                    channel_dict[channel_info[0]] = channel_info[1]

    return channel_dict


def get_channel_list():
    global channel_list

    if channel_list is None:
        channel_list = []
        for k, v in get_channel_dict().items():
            channel_list.append(f"{k}::{v}")

    return channel_list


class ManagerFuncs:
    def __init__(self):
        pass

    def get_current_preview_method(self):
        return "none"

    def run_script(self, cmd, cwd='.'):
        if len(cmd) > 0 and cmd[0].startswith("#"):
            print(f"[ComfyUI-Manager] Unexpected behavior: `{cmd}`")
            return 0

        subprocess.check_call(cmd, cwd=cwd, env=get_script_env())

        return 0


manager_funcs = ManagerFuncs()


def write_config():
    config = configparser.ConfigParser()
    config['default'] = {
        'preview_method': manager_funcs.get_current_preview_method(),
        'git_exe':  get_config()['git_exe'],
        'channel_url': get_config()['channel_url'],
        'share_option': get_config()['share_option'],
        'bypass_ssl': get_config()['bypass_ssl'],
        "file_logging": get_config()['file_logging'],
        'default_ui': get_config()['default_ui'],
        'component_policy': get_config()['component_policy'],
        'double_click_policy': get_config()['double_click_policy'],
        'windows_selector_event_loop_policy': get_config()['windows_selector_event_loop_policy'],
        'model_download_by_agent': get_config()['model_download_by_agent'],
        'downgrade_blacklist': get_config()['downgrade_blacklist'],
        'security_level': get_config()['security_level'],
        'skip_migration_check': get_config()['skip_migration_check'],
    }

    directory = os.path.dirname(manager_config_path)
    if not os.path.exists(directory):
        os.makedirs(directory)

    with open(manager_config_path, 'w') as configfile:
        config.write(configfile)


def read_config():
    try:
        config = configparser.ConfigParser()
        config.read(manager_config_path)
        default_conf = config['default']

        # policy migration: disable_unsecure_features -> security_level
        if 'disable_unsecure_features' in default_conf:
            if default_conf['disable_unsecure_features'].lower() == 'true':
                security_level = 'strong'
            else:
                security_level = 'normal'
        else:
            security_level = default_conf['security_level'] if 'security_level' in default_conf else 'normal'

        return {
                    'preview_method': default_conf['preview_method'] if 'preview_method' in default_conf else manager_funcs.get_current_preview_method(),
                    'git_exe': default_conf['git_exe'] if 'git_exe' in default_conf else '',
                    'channel_url': default_conf['channel_url'] if 'channel_url' in default_conf else DEFAULT_CHANNEL,
                    'share_option': default_conf['share_option'] if 'share_option' in default_conf else 'all',
                    'bypass_ssl': default_conf['bypass_ssl'].lower() == 'true' if 'bypass_ssl' in default_conf else False,
                    'file_logging': default_conf['file_logging'].lower() == 'true' if 'file_logging' in default_conf else True,
                    'default_ui': default_conf['default_ui'] if 'default_ui' in default_conf else 'none',
                    'component_policy': default_conf['component_policy'] if 'component_policy' in default_conf else 'workflow',
                    'double_click_policy': default_conf['double_click_policy'] if 'double_click_policy' in default_conf else 'copy-all',
                    'windows_selector_event_loop_policy': default_conf['windows_selector_event_loop_policy'].lower() == 'true' if 'windows_selector_event_loop_policy' in default_conf else False,
                    'model_download_by_agent': default_conf['model_download_by_agent'].lower() == 'true' if 'model_download_by_agent' in default_conf else False,
                    'downgrade_blacklist': default_conf['downgrade_blacklist'] if 'downgrade_blacklist' in default_conf else '',
                    'skip_migration_check': default_conf['skip_migration_check'].lower() == 'true' if 'skip_migration_check' in default_conf else False,
                    'security_level': security_level
               }

    except Exception:
        return {
            'preview_method': manager_funcs.get_current_preview_method(),
            'git_exe': '',
            'channel_url': DEFAULT_CHANNEL,
            'share_option': 'all',
            'bypass_ssl': False,
            'file_logging': True,
            'default_ui': 'none',
            'component_policy': 'workflow',
            'double_click_policy': 'copy-all',
            'windows_selector_event_loop_policy': False,
            'model_download_by_agent': False,
            'downgrade_blacklist': '',
            'skip_migration_check': False,
            'security_level': 'normal',
        }


def get_config():
    global cached_config

    if cached_config is None:
        cached_config = read_config()

    return cached_config


def switch_to_default_branch(repo):
    try:
        default_branch = repo.git.symbolic_ref('refs/remotes/origin/HEAD').replace('refs/remotes/origin/', '')
        repo.git.checkout(default_branch)
    except:
        try:
            repo.git.checkout(repo.heads.master)
        except:
            try:
                repo.git.checkout('-b', 'master', 'origin/master')
            except:
                print("[ComfyUI Manager] Failed to switch to the default branch")


def try_install_script(url, repo_path, install_cmd, instant_execution=False):
    if not instant_execution and ((len(install_cmd) > 0 and install_cmd[0].startswith('#')) or (platform.system() == "Windows" and comfy_ui_commit_datetime.date() >= comfy_ui_required_commit_datetime.date())):
        if not os.path.exists(manager_startup_script_path):
            os.makedirs(manager_startup_script_path)

        script_path = os.path.join(manager_startup_script_path, "install-scripts.txt")
        with open(script_path, "a") as file:
            obj = [repo_path] + install_cmd
            file.write(f"{obj}\n")

        return True
    else:
        if len(install_cmd) == 5 and install_cmd[2:4] == ['pip', 'install']:
            if is_blacklisted(install_cmd[4]):
                print(f"[ComfyUI-Manager] skip black listed pip installation: '{install_cmd[4]}'")
                return True

        print(f"\n## ComfyUI-Manager: EXECUTE => {install_cmd}")
        code = manager_funcs.run_script(install_cmd, cwd=repo_path)

        if platform.system() != "Windows":
            try:
                if comfy_ui_commit_datetime.date() < comfy_ui_required_commit_datetime.date():
                    print("\n\n###################################################################")
                    print(f"[WARN] ComfyUI-Manager: Your ComfyUI version ({comfy_ui_revision})[{comfy_ui_commit_datetime.date()}] is too old. Please update to the latest version.")
                    print("[WARN] The extension installation feature may not work properly in the current installed ComfyUI version on Windows environment.")
                    print("###################################################################\n\n")
            except:
                pass

        if code != 0:
            if url is None:
                url = os.path.dirname(repo_path)
            print(f"install script failed: {url}")
            return False

        return True


# use subprocess to avoid file system lock by git (Windows)
def __win_check_git_update(path, do_fetch=False, do_update=False):
    if do_fetch:
        command = [sys.executable, git_script_path, "--fetch", path]
    elif do_update:
        command = [sys.executable, git_script_path, "--pull", path]
    else:
        command = [sys.executable, git_script_path, "--check", path]

    new_env = get_script_env()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=get_default_custom_nodes_path(), env=new_env)
    output, _ = process.communicate()
    output = output.decode('utf-8').strip()

    if 'detected dubious' in output:
        # fix and try again
        safedir_path = path.replace('\\', '/')
        try:
            print(f"[ComfyUI-Manager] Try fixing 'dubious repository' error on '{safedir_path}' repo")
            process = subprocess.Popen(['git', 'config', '--global', '--add', 'safe.directory', safedir_path], env=new_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            output, _ = process.communicate()

            process = subprocess.Popen(command, env=new_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            output, _ = process.communicate()
            output = output.decode('utf-8').strip()
        except Exception:
            print('[ComfyUI-Manager] failed to fixing')

        if 'detected dubious' in output:
            print(f'\n[ComfyUI-Manager] Failed to fixing repository setup. Please execute this command on cmd: \n'
                  f'-----------------------------------------------------------------------------------------\n'
                  f'git config --global --add safe.directory "{safedir_path}"\n'
                  f'-----------------------------------------------------------------------------------------\n')

    if do_update:
        if "CUSTOM NODE PULL: Success" in output:
            process.wait()
            print(f"\x1b[2K\rUpdated: {path}")
            return True, True    # updated
        elif "CUSTOM NODE PULL: None" in output:
            process.wait()
            return False, True   # there is no update
        else:
            print(f"\x1b[2K\rUpdate error: {path}")
            process.wait()
            return False, False  # update failed
    else:
        if "CUSTOM NODE CHECK: True" in output:
            process.wait()
            return True, True
        elif "CUSTOM NODE CHECK: False" in output:
            process.wait()
            return False, True
        else:
            print(f"\x1b[2K\rFetch error: {path}")
            print(f"\n{output}\n")
            process.wait()
            return False, True


def __win_check_git_pull(path):
    command = [sys.executable, git_script_path, "--pull", path]
    process = subprocess.Popen(command, env=get_script_env(), cwd=get_default_custom_nodes_path())
    process.wait()


def execute_install_script(url, repo_path, lazy_mode=False, instant_execution=False, no_deps=False):
    # import ipdb; ipdb.set_trace()
    install_script_path = os.path.join(repo_path, "install.py")
    requirements_path = os.path.join(repo_path, "requirements.txt")

    if lazy_mode:
        install_cmd = ["#LAZY-INSTALL-SCRIPT",  sys.executable]
        try_install_script(url, repo_path, install_cmd)
    else:
        if os.path.exists(requirements_path) and not no_deps:
            print("Install: pip packages")
            pip_fixer = manager_util.PIPFixer(manager_util.get_installed_packages())
            with open(requirements_path, "r") as requirements_file:
                for line in requirements_file:
                    #handle comments
                    if '#' in line:
                        if line.strip()[0] == '#':
                            print("Line is comment...skipping")
                            continue
                        else:
                            line = line.split('#')[0].strip()

                    package_name = remap_pip_package(line.strip())

                    if package_name and not package_name.startswith('#'):
                        if '--index-url' in package_name:
                            s = package_name.split('--index-url')
                            install_cmd = [sys.executable, "-m", "pip", "install", s[0].strip(), '--index-url', s[1].strip()]
                        else:
                            install_cmd = [sys.executable, "-m", "pip", "install", package_name]

                        if package_name.strip() != "" and not package_name.startswith('#'):
                            try_install_script(url, repo_path, install_cmd, instant_execution=instant_execution)
            pip_fixer.fix_broken()

        if os.path.exists(install_script_path):
            print("Install: install script")
            install_cmd = [sys.executable, "install.py"]
            try_install_script(url, repo_path, install_cmd, instant_execution=instant_execution)

    return True


def git_repo_update_check_with(path, do_fetch=False, do_update=False, no_deps=False):
    """

    perform update check for git custom node
    and fetch or update if flag is on

    :param path: path to git custom node
    :param do_fetch: do fetch during check
    :param do_update: do update during check
    :param no_deps: don't install dependencies
    :return: update state * success
    """
    if do_fetch:
        orig_print(f"\x1b[2K\rFetching: {path}", end='')
    elif do_update:
        orig_print(f"\x1b[2K\rUpdating: {path}", end='')

    # Check if the path is a git repository
    if not os.path.exists(os.path.join(path, '.git')):
        raise ValueError(f'[ComfyUI-Manager] Not a valid git repository: {path}')

    if platform.system() == "Windows":
        updated, success = __win_check_git_update(path, do_fetch, do_update)
        if updated and success:
            execute_install_script(None, path, lazy_mode=True, no_deps=no_deps)
        return updated, success
    else:
        # Fetch the latest commits from the remote repository
        repo = git.Repo(path)

        remote_name = 'origin'
        remote = repo.remote(name=remote_name)

        if not do_update and repo.head.is_detached:
            if do_fetch:
                remote.fetch()

            return True, True  # detached branch is treated as updatable

        if repo.head.is_detached:
            switch_to_default_branch(repo)

        current_branch = repo.active_branch
        branch_name = current_branch.name

        # Get the current commit hash
        commit_hash = repo.head.commit.hexsha

        if do_fetch or do_update:
            remote.fetch()

        if do_update:
            if repo.is_dirty():
                print(f"\nSTASH: '{path}' is dirty.")
                repo.git.stash()

            if f'{remote_name}/{branch_name}' not in repo.refs:
                switch_to_default_branch(repo)
                current_branch = repo.active_branch
                branch_name = current_branch.name

            remote_commit_hash = repo.refs[f'{remote_name}/{branch_name}'].object.hexsha

            if commit_hash == remote_commit_hash:
                repo.close()
                return False, True

            try:
                remote.pull()
                repo.git.submodule('update', '--init', '--recursive')
                new_commit_hash = repo.head.commit.hexsha

                if commit_hash != new_commit_hash:
                    execute_install_script(None, path, no_deps=no_deps)
                    print(f"\x1b[2K\rUpdated: {path}")
                    return True, True
                else:
                    return False, False

            except Exception as e:
                print(f"\nUpdating failed: {path}\n{e}", file=sys.stderr)
                return False, False

        if repo.head.is_detached:
            repo.close()
            return True, True

        # Get commit hash of the remote branch
        current_branch = repo.active_branch
        branch_name = current_branch.name

        if f'{remote_name}/{branch_name}' in repo.refs:
            remote_commit_hash = repo.refs[f'{remote_name}/{branch_name}'].object.hexsha
        else:
            return True, True  # Assuming there's an update if it's not the default branch.

        # Compare the commit hashes to determine if the local repository is behind the remote repository
        if commit_hash != remote_commit_hash:
            # Get the commit dates
            commit_date = repo.head.commit.committed_datetime
            remote_commit_date = repo.refs[f'{remote_name}/{branch_name}'].object.committed_datetime

            # Compare the commit dates to determine if the local repository is behind the remote repository
            if commit_date < remote_commit_date:
                repo.close()
                return True, True

        repo.close()

    return False, True


class GitProgress(RemoteProgress):
    def __init__(self):
        super().__init__()
        self.pbar = tqdm()

    def update(self, op_code, cur_count, max_count=None, message=''):
        self.pbar.total = max_count
        self.pbar.n = cur_count
        self.pbar.pos = 0
        self.pbar.refresh()


def is_valid_url(url):
    try:
        # Check for HTTP/HTTPS URL format
        result = urlparse(url)
        if all([result.scheme, result.netloc]):
            return True
    finally:
        # Check for SSH git URL format
        pattern = re.compile(r"^(.+@|ssh://).+:.+$")
        if pattern.match(url):
            return True
    return False


async def gitclone_install(url, instant_execution=False, msg_prefix='', no_deps=False):
    await unified_manager.reload('cache')
    await unified_manager.get_custom_nodes('default', 'cache')

    print(f"{msg_prefix}Install: {url}")

    result = ManagedResult('install-git')

    if not is_valid_url(url):
        return result.fail(f"Invalid git url: '{url}'")

    if url.endswith("/"):
        url = url[:-1]
    try:
        cnr = unified_manager.get_cnr_by_repo(url)
        if cnr:
            cnr_id = cnr['id']
            return await unified_manager.install_by_id(cnr_id, version_spec='nightly')
        else:
            repo_name = os.path.splitext(os.path.basename(url))[0]

            # NOTE: Keep original name as possible if unknown node
            # node_dir = f"{repo_name}@unknown"
            node_dir = repo_name

            repo_path = os.path.join(get_default_custom_nodes_path(), node_dir)

            if os.path.exists(repo_path):
                return result.fail(f"Already exists: '{repo_path}'")

            for custom_nodes_dir in get_custom_nodes_paths():
                disabled_repo_path1 = os.path.join(custom_nodes_dir, '.disabled', node_dir)
                disabled_repo_path2 = os.path.join(custom_nodes_dir, repo_name+'.disabled')  # old style

                if os.path.exists(disabled_repo_path1):
                    return result.fail(f"Already exists (disabled): '{disabled_repo_path1}'")

                if os.path.exists(disabled_repo_path2):
                    return result.fail(f"Already exists (disabled): '{disabled_repo_path2}'")

            print(f"CLONE into '{repo_path}'")

            # Clone the repository from the remote URL
            if not instant_execution and platform.system() == 'Windows':
                res = manager_funcs.run_script([sys.executable, git_script_path, "--clone", get_default_custom_nodes_path(), url, repo_path], cwd=get_default_custom_nodes_path())
                if res != 0:
                    return result.fail(f"Failed to clone '{url}' into  '{repo_path}'")
            else:
                repo = git.Repo.clone_from(url, repo_path, recursive=True, progress=GitProgress())
                repo.git.clear_cache()
                repo.close()

            execute_install_script(url, repo_path, instant_execution=instant_execution, no_deps=no_deps)
            print("Installation was successful.")
            return result.with_target(repo_path)

    except Exception as e:
        traceback.print_exc()
        print(f"Install(git-clone) error: {url} / {e}", file=sys.stderr)
        return result.fail(f"Install(git-clone) error: {url} / {e}")


def git_pull(path):
    # Check if the path is a git repository
    if not os.path.exists(os.path.join(path, '.git')):
        raise ValueError('Not a git repository')

    # Pull the latest changes from the remote repository
    if platform.system() == "Windows":
        return __win_check_git_pull(path)
    else:
        repo = git.Repo(path)

        if repo.is_dirty():
            print(f"STASH: '{path}' is dirty.")
            repo.git.stash()

        if repo.head.is_detached:
            switch_to_default_branch(repo)

        current_branch = repo.active_branch
        remote_name = current_branch.tracking_branch().remote_name
        remote = repo.remote(name=remote_name)

        remote.pull()
        repo.git.submodule('update', '--init', '--recursive')

        repo.close()

    return True


async def get_data_by_mode(mode, filename, channel_url=None):
    if channel_url in get_channel_dict():
        channel_url = get_channel_dict()[channel_url]

    try:
        if mode == "local":
            uri = os.path.join(manager_util.comfyui_manager_path, filename)
            json_obj = await manager_util.get_data(uri)
        else:
            if channel_url is None:
                uri = get_config()['channel_url'] + '/' + filename
            else:
                uri = channel_url + '/' + filename

            cache_uri = str(manager_util.simple_hash(uri))+'_'+filename
            cache_uri = os.path.join(manager_util.cache_dir, cache_uri)

            if mode == "cache":
                if manager_util.is_file_created_within_one_day(cache_uri):
                    json_obj = await manager_util.get_data(cache_uri)
                else:
                    json_obj = await manager_util.get_data(uri)
                    with manager_util.cache_lock:
                        with open(cache_uri, "w", encoding='utf-8') as file:
                            json.dump(json_obj, file, indent=4, sort_keys=True)
            else:
                json_obj = await manager_util.get_data(uri)
                with manager_util.cache_lock:
                    with open(cache_uri, "w", encoding='utf-8') as file:
                        json.dump(json_obj, file, indent=4, sort_keys=True)
    except Exception as e:
        print(f"[ComfyUI-Manager] Due to a network error, switching to local mode.\n=> {filename}\n=> {e}")
        uri = os.path.join(manager_util.comfyui_manager_path, filename)
        json_obj = await manager_util.get_data(uri)

    return json_obj


def gitclone_fix(files, instant_execution=False, no_deps=False):
    print(f"Try fixing: {files}")
    for url in files:
        if not is_valid_url(url):
            print(f"Invalid git url: '{url}'")
            return False

        if url.endswith("/"):
            url = url[:-1]
        try:
            repo_name = os.path.splitext(os.path.basename(url))[0]
            repo_path = os.path.join(get_default_custom_nodes_path(), repo_name)

            if os.path.exists(repo_path+'.disabled'):
                repo_path = repo_path+'.disabled'

            if not execute_install_script(url, repo_path, instant_execution=instant_execution, no_deps=no_deps):
                return False

        except Exception as e:
            print(f"Install(git-clone) error: {url} / {e}", file=sys.stderr)
            return False

    print(f"Attempt to fixing '{files}' is done.")
    return True


def pip_install(packages):
    install_cmd = ['#FORCE', sys.executable, "-m", "pip", "install", '-U'] + packages
    try_install_script('pip install via manager', '..', install_cmd)


def rmtree(path):
    retry_count = 3

    while True:
        try:
            retry_count -= 1

            if platform.system() == "Windows":
                manager_funcs.run_script(['attrib', '-R', path + '\\*', '/S'])
            shutil.rmtree(path)

            return True

        except Exception as ex:
            print(f"ex: {ex}")
            time.sleep(3)

            if retry_count < 0:
                raise ex

            print(f"Uninstall retry({retry_count})")


def gitclone_uninstall(files):
    import os

    print(f"Uninstall: {files}")
    for url in files:
        if url.endswith("/"):
            url = url[:-1]
        try:
            for custom_nodes_dir in get_custom_nodes_paths():
                dir_name = os.path.splitext(os.path.basename(url))[0].replace(".git", "")
                dir_path = os.path.join(custom_nodes_dir, dir_name)

                # safety check
                if dir_path == '/' or dir_path[1:] == ":/" or dir_path == '':
                    print(f"Uninstall(git-clone) error: invalid path '{dir_path}' for '{url}'")
                    return False

                install_script_path = os.path.join(dir_path, "uninstall.py")
                disable_script_path = os.path.join(dir_path, "disable.py")
                if os.path.exists(install_script_path):
                    uninstall_cmd = [sys.executable, "uninstall.py"]
                    code = manager_funcs.run_script(uninstall_cmd, cwd=dir_path)

                    if code != 0:
                        print(f"An error occurred during the execution of the uninstall.py script. Only the '{dir_path}' will be deleted.")
                elif os.path.exists(disable_script_path):
                    disable_script = [sys.executable, "disable.py"]
                    code = manager_funcs.run_script(disable_script, cwd=dir_path)
                    if code != 0:
                        print(f"An error occurred during the execution of the disable.py script. Only the '{dir_path}' will be deleted.")

                if os.path.exists(dir_path):
                    rmtree(dir_path)
                elif os.path.exists(dir_path + ".disabled"):
                    rmtree(dir_path + ".disabled")
        except Exception as e:
            print(f"Uninstall(git-clone) error: {url} / {e}", file=sys.stderr)
            return False

    print("Uninstallation was successful.")
    return True


def gitclone_set_active(files, is_disable):
    import os

    if is_disable:
        action_name = "Disable"
    else:
        action_name = "Enable"

    print(f"{action_name}: {files}")
    for url in files:
        if url.endswith("/"):
            url = url[:-1]
        try:
            for custom_nodes_dir in get_custom_nodes_paths():
                dir_name = os.path.splitext(os.path.basename(url))[0].replace(".git", "")
                dir_path = os.path.join(custom_nodes_dir, dir_name)

                # safety check
                if dir_path == '/' or dir_path[1:] == ":/" or dir_path == '':
                    print(f"{action_name}(git-clone) error: invalid path '{dir_path}' for '{url}'")
                    return False

                if is_disable:
                    current_path = dir_path
                    base_path = extract_base_custom_nodes_dir(current_path)
                    new_path = os.path.join(base_path, ".disabled", dir_name)

                    if not os.path.exists(current_path):
                        continue
                else:
                    current_path1 = os.path.join(get_default_custom_nodes_path(), ".disabled", dir_name)
                    current_path2 = dir_path + ".disabled"

                    if os.path.exists(current_path1):
                        current_path = current_path1
                    elif os.path.exists(current_path2):
                        current_path = current_path2
                    else:
                        continue

                    base_path = extract_base_custom_nodes_dir(current_path)
                    new_path = os.path.join(base_path, dir_name)

                shutil.move(current_path, new_path)

                if is_disable:
                    if os.path.exists(os.path.join(new_path, "disable.py")):
                        disable_script = [sys.executable, "disable.py"]
                        try_install_script(url, new_path, disable_script)
                else:
                    if os.path.exists(os.path.join(new_path, "enable.py")):
                        enable_script = [sys.executable, "enable.py"]
                        try_install_script(url, new_path, enable_script)

                break  # for safety

        except Exception as e:
            print(f"{action_name}(git-clone) error: {url} / {e}", file=sys.stderr)
            return False

    print(f"{action_name} was successful.")
    return True


def gitclone_update(files, instant_execution=False, skip_script=False, msg_prefix="", no_deps=False):
    import os

    print(f"{msg_prefix}Update: {files}")
    for url in files:
        if url.endswith("/"):
            url = url[:-1]
        try:
            for custom_nodes_dir in get_default_custom_nodes_path():
                repo_name = os.path.splitext(os.path.basename(url))[0].replace(".git", "")
                repo_path = os.path.join(custom_nodes_dir, repo_name)

                if os.path.exists(repo_path+'.disabled'):
                    repo_path = repo_path+'.disabled'

                elif os.path.exists(os.path.join(get_default_custom_nodes_path(), "disabled", repo_name)):
                    repo_path = os.path.join(get_default_custom_nodes_path(), "disabled", repo_name)

                if not os.path.exists(repo_path):
                    continue

                git_pull(repo_path)

                if not skip_script:
                    if instant_execution:
                        if not execute_install_script(url, repo_path, lazy_mode=False, instant_execution=True, no_deps=no_deps):
                            return False
                    else:
                        if not execute_install_script(url, repo_path, lazy_mode=True, no_deps=no_deps):
                            return False

                break  # for safety

        except Exception as e:
            print(f"Update(git-clone) error: {url} / {e}", file=sys.stderr)
            return False

    if not skip_script:
        print("Update was successful.")
    return True


def update_path(repo_path, instant_execution=False, no_deps=False):
    if not os.path.exists(os.path.join(repo_path, '.git')):
        return "fail"

    # version check
    repo = git.Repo(repo_path)

    if repo.head.is_detached:
        switch_to_default_branch(repo)

    current_branch = repo.active_branch
    branch_name = current_branch.name

    if current_branch.tracking_branch() is None:
        print(f"[ComfyUI-Manager] There is no tracking branch ({current_branch})")
        remote_name = 'origin'
    else:
        remote_name = current_branch.tracking_branch().remote_name
    remote = repo.remote(name=remote_name)

    try:
        remote.fetch()
    except Exception as e:
        if 'detected dubious' in str(e):
            print("[ComfyUI-Manager] Try fixing 'dubious repository' error on 'ComfyUI' repository")
            safedir_path = comfy_path.replace('\\', '/')
            subprocess.run(['git', 'config', '--global', '--add', 'safe.directory', safedir_path])
            try:
                remote.fetch()
            except Exception:
                print(f"\n[ComfyUI-Manager] Failed to fixing repository setup. Please execute this command on cmd: \n"
                      f"-----------------------------------------------------------------------------------------\n"
                      f'git config --global --add safe.directory "{safedir_path}"\n'
                      f"-----------------------------------------------------------------------------------------\n")

    commit_hash = repo.head.commit.hexsha
    remote_commit_hash = repo.refs[f'{remote_name}/{branch_name}'].object.hexsha

    if commit_hash != remote_commit_hash:
        git_pull(repo_path)
        execute_install_script("ComfyUI", repo_path, instant_execution=instant_execution, no_deps=no_deps)
        return "updated"
    else:
        return "skipped"


def lookup_customnode_by_url(data, target):
    for x in data['custom_nodes']:
        if target in x['files']:
            for custom_nodes_dir in get_custom_nodes_paths():
                dir_name = os.path.splitext(os.path.basename(target))[0].replace(".git", "")
                dir_path = os.path.join(custom_nodes_dir, dir_name)
                if os.path.exists(dir_path):
                    x['installed'] = 'True'
                else:
                    disabled_path1 = os.path.join(custom_nodes_dir, '.disabled', dir_name)
                    disabled_path2 = dir_path + ".disabled"

                    if os.path.exists(disabled_path1) or os.path.exists(disabled_path2):
                        x['installed'] = 'Disabled'
                    else:
                        continue

                return x

    return None


def lookup_installed_custom_nodes_legacy(repo_name):
    base_paths = get_custom_nodes_paths()

    for base_path in base_paths:
        repo_path = os.path.join(base_path, repo_name)
        if os.path.exists(repo_path):
            return True, repo_path
        elif os.path.exists(repo_path + '.disabled'):
            return False, repo_path

    return None


def simple_check_custom_node(url):
    dir_name = os.path.splitext(os.path.basename(url))[0].replace(".git", "")
    dir_path = os.path.join(get_default_custom_nodes_path(), dir_name)
    if os.path.exists(dir_path):
        return 'installed'
    elif os.path.exists(dir_path+'.disabled'):
        return 'disabled'

    return 'not-installed'


def check_state_of_git_node_pack_single(item, do_fetch=False, do_update_check=True, do_update=False):
    if item['version'] == 'unknown':
        dir_path = unified_manager.unknown_active_nodes.get(item['id'])[1]
    elif item['version'] == 'nightly':
        dir_path = unified_manager.active_nodes.get(item['id'])[1]
    else:
        # skip CNR nodes
        dir_path = None

    if dir_path and os.path.exists(dir_path):
        if do_update_check:
            update_state, success = git_repo_update_check_with(dir_path, do_fetch, do_update)
            if (do_update_check or do_update) and update_state:
                item['update-state'] = 'true'
            elif do_update and not success:
                item['update-state'] = 'fail'


def get_installed_pip_packages():
    # extract pip package infos
    pips = subprocess.check_output([sys.executable, '-m', 'pip', 'freeze'], text=True).split('\n')

    res = {}
    for x in pips:
        if x.strip() == "":
            continue

        if ' @ ' in x:
            spec_url = x.split(' @ ')
            res[spec_url[0]] = spec_url[1]
        else:
            res[x] = ""

    return res


async def get_current_snapshot():
    await unified_manager.reload('cache')
    await unified_manager.get_custom_nodes('default', 'cache')

    # Get ComfyUI hash
    repo_path = comfy_path

    if not os.path.exists(os.path.join(repo_path, '.git')):
        print("ComfyUI update fail: The installed ComfyUI does not have a Git repository.")
        return {}

    repo = git.Repo(repo_path)
    comfyui_commit_hash = repo.head.commit.hexsha

    git_custom_nodes = {}
    cnr_custom_nodes = {}
    file_custom_nodes = []

    # Get custom nodes hash
    for custom_nodes_dir in get_custom_nodes_paths():
        paths = os.listdir(custom_nodes_dir)

        disabled_path = os.path.join(custom_nodes_dir, '.disabled')
        if os.path.exists(disabled_path):
            for x in os.listdir(disabled_path):
                paths.append(os.path.join(disabled_path, x))

        for path in paths:
            if path in ['.disabled', '__pycache__']:
                continue

            fullpath = os.path.join(custom_nodes_dir, path)

            if os.path.isdir(fullpath):
                is_disabled = path.endswith(".disabled") or os.path.basename(os.path.dirname(fullpath)) == ".disabled"

                try:
                    info = unified_manager.resolve_from_path(fullpath)

                    if info is None:
                        continue

                    if info['ver'] not in ['nightly', 'latest', 'unknown']:
                        if is_disabled:
                            continue  # don't restore disabled state of CNR node.

                        cnr_custom_nodes[info['id']] = info['ver']
                    else:
                        repo = git.Repo(fullpath)
                        commit_hash = repo.head.commit.hexsha
                        url = repo.remotes.origin.url
                        git_custom_nodes[url] = dict(hash=commit_hash, disabled=is_disabled)
                except:
                    print(f"Failed to extract snapshots for the custom node '{path}'.")

            elif path.endswith('.py'):
                is_disabled = path.endswith(".py.disabled")
                filename = os.path.basename(path)
                item = {
                    'filename': filename,
                    'disabled': is_disabled
                }

                file_custom_nodes.append(item)

    pip_packages = get_installed_pip_packages()

    return {
        'comfyui': comfyui_commit_hash,
        'git_custom_nodes': git_custom_nodes,
        'cnr_custom_nodes': cnr_custom_nodes,
        'file_custom_nodes': file_custom_nodes,
        'pips': pip_packages,
    }


async def save_snapshot_with_postfix(postfix, path=None):
    if path is None:
        now = datetime.now()

        date_time_format = now.strftime("%Y-%m-%d_%H-%M-%S")
        file_name = f"{date_time_format}_{postfix}"

        path = os.path.join(manager_snapshot_path, f"{file_name}.json")
    else:
        file_name = path.replace('\\', '/').split('/')[-1]
        file_name = file_name.split('.')[-2]

    snapshot = await get_current_snapshot()
    if path.endswith('.json'):
        with open(path, "w") as json_file:
            json.dump(snapshot, json_file, indent=4)

        return file_name + '.json'

    elif path.endswith('.yaml'):
        with open(path, "w") as yaml_file:
            snapshot = {'custom_nodes': snapshot}
            yaml.dump(snapshot, yaml_file, allow_unicode=True)

        return path


async def extract_nodes_from_workflow(filepath, mode='local', channel_url='default'):
    # prepare json data
    workflow = None
    if filepath.endswith('.json'):
        with open(filepath, "r", encoding="UTF-8", errors="ignore") as json_file:
            try:
                workflow = json.load(json_file)
            except:
                print(f"Invalid workflow file: {filepath}")
                exit(-1)

    elif filepath.endswith('.png'):
        from PIL import Image
        with Image.open(filepath) as img:
            if 'workflow' not in img.info:
                print(f"The specified .png file doesn't have a workflow: {filepath}")
                exit(-1)
            else:
                try:
                    workflow = json.loads(img.info['workflow'])
                except:
                    print(f"This is not a valid .png file containing a ComfyUI workflow: {filepath}")
                    exit(-1)

    if workflow is None:
        print(f"Invalid workflow file: {filepath}")
        exit(-1)

    # extract nodes
    used_nodes = set()

    def extract_nodes(sub_workflow):
        for x in sub_workflow['nodes']:
            node_name = x.get('type')

            # skip virtual nodes
            if node_name in ['Reroute', 'Note']:
                continue

            if node_name is not None and not (node_name.startswith('workflow/') or node_name.startswith('workflow>')):
                used_nodes.add(node_name)

    if 'nodes' in workflow:
        extract_nodes(workflow)

        if 'extra' in workflow:
            if 'groupNodes' in workflow['extra']:
                for x in workflow['extra']['groupNodes'].values():
                    extract_nodes(x)

    # lookup dependent custom nodes
    ext_map = await get_data_by_mode(mode, 'extension-node-map.json', channel_url)

    rext_map = {}
    preemption_map = {}
    patterns = []
    for k, v in ext_map.items():
        if k == 'https://github.com/comfyanonymous/ComfyUI':
            for x in v[0]:
                if x not in preemption_map:
                    preemption_map[x] = []

                preemption_map[x] = k
            continue

        for x in v[0]:
            if x not in rext_map:
                rext_map[x] = []

            rext_map[x].append(k)

        if 'preemptions' in v[1]:
            for x in v[1]['preemptions']:
                if x not in preemption_map:
                    preemption_map[x] = []

                preemption_map[x] = k

        if 'nodename_pattern' in v[1]:
            patterns.append((v[1]['nodename_pattern'], k))

    # identify used extensions
    used_exts = set()
    unknown_nodes = set()

    for node_name in used_nodes:
        ext = preemption_map.get(node_name)

        if ext is None:
            ext = rext_map.get(node_name)
            if ext is not None:
                ext = ext[0]

        if ext is None:
            for pat_ext in patterns:
                if re.search(pat_ext[0], node_name):
                    ext = pat_ext[1]
                    break

        if ext == 'https://github.com/comfyanonymous/ComfyUI':
            pass
        elif ext is not None:
            if 'Fooocus' in ext:
                print(f">> {node_name}")

            used_exts.add(ext)
        else:
            unknown_nodes.add(node_name)

    return used_exts, unknown_nodes


def unzip(model_path):
    if not os.path.exists(model_path):
        print(f"[ComfyUI-Manager] unzip: File not found: {model_path}")
        return False

    base_dir = os.path.dirname(model_path)
    filename = os.path.basename(model_path)
    target_dir = os.path.join(base_dir, filename[:-4])

    os.makedirs(target_dir, exist_ok=True)

    with zipfile.ZipFile(model_path, 'r') as zip_ref:
        zip_ref.extractall(target_dir)

    # Check if there's only one directory inside the target directory
    contents = os.listdir(target_dir)
    if len(contents) == 1 and os.path.isdir(os.path.join(target_dir, contents[0])):
        nested_dir = os.path.join(target_dir, contents[0])
        # Move each file and sub-directory in the nested directory up to the target directory
        for item in os.listdir(nested_dir):
            shutil.move(os.path.join(nested_dir, item), os.path.join(target_dir, item))
        # Remove the now empty nested directory
        os.rmdir(nested_dir)

    os.remove(model_path)
    return True


def map_to_unified_keys(json_obj):
    res = {}
    for k, v in json_obj.items():
        cnr = unified_manager.get_cnr_by_repo(k)
        if cnr:
            res[cnr['id']] = v
        else:
            res[k] = v

    return res


async def get_unified_total_nodes(channel, mode):
    await unified_manager.reload(mode)

    res = await unified_manager.get_custom_nodes(channel, mode)

    # collect pure cnr ids (i.e. not exists in custom-node-list.json)
    # populate state/updatable field to non-pure cnr nodes
    cnr_ids = set(unified_manager.cnr_map.keys())
    for k, v in res.items():
        # resolve cnr_id from repo url
        files_in_json = v.get('files', [])
        cnr_id = None
        if len(files_in_json) == 1:
            cnr = unified_manager.get_cnr_by_repo(files_in_json[0])
            if cnr:
                cnr_id = cnr['id']

        if cnr_id is not None:
            # cnr or nightly version
            cnr_ids.remove(cnr_id)
            updatable = False
            cnr = unified_manager.cnr_map[cnr_id]

            if cnr_id in invalid_nodes:
                v['invalid-installation'] = True

            if cnr_id in unified_manager.active_nodes:
                # installed
                v['state'] = 'enabled'
                if unified_manager.active_nodes[cnr_id][0] != 'nightly':
                    updatable = unified_manager.is_updatable(cnr_id)
                else:
                    updatable = False
                v['active_version'] = unified_manager.active_nodes[cnr_id][0]
                v['version'] = v['active_version']

                if cm_global.try_call(api="cm.is_import_failed_extension", name=unified_manager.active_nodes[cnr_id][1]):
                    v['import-fail'] = True

            elif cnr_id in unified_manager.cnr_inactive_nodes:
                # disabled
                v['state'] = 'disabled'
                cnr_ver = unified_manager.get_from_cnr_inactive_nodes(cnr_id)
                if cnr_ver is not None:
                    v['version'] = str(cnr_ver[0])
                else:
                    v['version'] = '0'

            elif cnr_id in unified_manager.nightly_inactive_nodes:
                # disabled
                v['state'] = 'disabled'
                v['version'] = 'nightly'
            else:
                # not installed
                v['state'] = 'not-installed'

            if 'version' not in v:
                v['version'] = cnr['latest_version']['version']

            v['update-state'] = 'true' if updatable else 'false'
        else:
            # unknown version
            v['version'] = 'unknown'

            if unified_manager.is_enabled(k, 'unknown'):
                v['state'] = 'enabled'
                v['active_version'] = 'unknown'

                if cm_global.try_call(api="cm.is_import_failed_extension", name=unified_manager.unknown_active_nodes[k][1]):
                    v['import-fail'] = True

            elif unified_manager.is_disabled(k, 'unknown'):
                v['state'] = 'disabled'
            else:
                v['state'] = 'not-installed'

    # add items for pure cnr nodes
    if normalize_channel(channel) == DEFAULT_CHANNEL:
        # Don't show CNR nodes unless default channel
        for cnr_id in cnr_ids:
            cnr = unified_manager.cnr_map[cnr_id]
            author = cnr['publisher']['name']
            title = cnr['name']
            reference = f"https://registry.comfy.org/nodes/{cnr['id']}"
            install_type = "cnr"
            description = cnr.get('description', '')

            ver = None
            active_version = None
            updatable = False
            import_fail = None
            if cnr_id in unified_manager.active_nodes:
                # installed
                state = 'enabled'
                updatable = unified_manager.is_updatable(cnr_id)
                active_version = unified_manager.active_nodes[cnr['id']][0]
                ver = active_version

                if cm_global.try_call(api="cm.is_import_failed_extension", name=unified_manager.active_nodes[cnr_id][1]):
                    import_fail = True

            elif cnr['id'] in unified_manager.cnr_inactive_nodes:
                # disabled
                state = 'disabled'
            elif cnr['id'] in unified_manager.nightly_inactive_nodes:
                # disabled
                state = 'disabled'
                ver = 'nightly'
            else:
                # not installed
                state = 'not-installed'

            if ver is None:
                ver = cnr['latest_version']['version']

            item = dict(author=author, title=title, reference=reference, install_type=install_type,
                        description=description, state=state, updatable=updatable, version=ver)

            if active_version:
                item['active_version'] = active_version

            if import_fail:
                item['import-fail'] = True

            res[cnr_id] = item

    return res


def populate_github_stats(node_packs, json_obj_github):
    for k, v in node_packs.items():
        url = v['reference']
        if url in json_obj_github:
            v['stars'] = json_obj_github[url]['stars']
            v['last_update'] = json_obj_github[url]['last_update']
            v['trust'] = json_obj_github[url]['author_account_age_days'] > 600
        else:
            v['stars'] = -1
            v['last_update'] = -1
            v['trust'] = False


def populate_favorites(node_packs, json_obj_extras):
    favorites = set(json_obj_extras['favorites'])

    for k, v in node_packs.items():
        if v.get('version') != 'unknown':
            if k in favorites:
                v['is_favorite'] = True


async def restore_snapshot(snapshot_path, git_helper_extras=None):
    cloned_repos = []
    checkout_repos = []
    enabled_repos = []
    disabled_repos = []
    skip_node_packs = []

    await unified_manager.reload('cache')
    await unified_manager.get_custom_nodes('default', 'cache')

    cnr_repo_map = {}
    for k, v in unified_manager.repo_cnr_map.items():
        cnr_repo_map[v['id']] = k

    print("Restore snapshot.")

    postinstalls = []

    with open(snapshot_path, 'r', encoding="UTF-8") as snapshot_file:
        if snapshot_path.endswith('.json'):
            info = json.load(snapshot_file)
        elif snapshot_path.endswith('.yaml'):
            info = yaml.load(snapshot_file, Loader=yaml.SafeLoader)
            info = info['custom_nodes']

        # for cnr restore
        cnr_info = info.get('cnr_custom_nodes')
        if cnr_info is not None:
            # disable not listed cnr nodes
            todo_disable = []
            todo_checkout = []

            for k, v in unified_manager.active_nodes.items():
                if 'comfyui-manager' in k:
                    continue

                if v[0] != 'nightly':
                    if k not in cnr_info:
                        todo_disable.append(k)
                    else:
                        cnr_ver = cnr_info[k]
                        if v[1] != cnr_ver:
                            todo_checkout.append((k, cnr_ver))
                        else:
                            skip_node_packs.append(k)

            for x in todo_disable:
                unified_manager.unified_disable(x, False)
                disabled_repos.append(x)

            for x in todo_checkout:
                unified_manager.cnr_switch_version(x[0], x[1], instant_execution=True, no_deps=True, return_postinstall=False)
                checkout_repos.append(x[1])

            # install listed cnr nodes
            for k, v in cnr_info.items():
                if 'comfyui-manager' in k:
                    continue

                ps = await unified_manager.install_by_id(k, version_spec=v, instant_execution=True, return_postinstall=True)
                cloned_repos.append(k)
                if ps is not None and ps.result:
                    if hasattr(ps, 'postinstall'):
                        postinstalls.append(ps.postinstall)
                    else:
                        print("cm-cli: unexpected [0001]")

        # for nightly restore
        git_info = info.get('git_custom_nodes')
        if git_info is not None:
            todo_disable = []
            todo_enable = []
            todo_checkout = []
            processed_urls = []

            for k, v in unified_manager.active_nodes.items():
                if 'comfyui-manager' in k:
                    continue

                if v[0] == 'nightly' and cnr_repo_map.get(k):
                    repo_url = cnr_repo_map.get(k)

                    normalized_url1 = git_utils.normalize_url(repo_url)
                    normalized_url2 = git_utils.normalize_url_http(repo_url)

                    if normalized_url1 not in git_info and normalized_url2 not in git_info:
                        todo_disable.append(k)
                    else:
                        if normalized_url1 in git_info:
                            commit_hash = git_info[normalized_url1]['hash']
                            todo_checkout.append((v[1], commit_hash))

                        if normalized_url2 in git_info:
                            commit_hash = git_info[normalized_url2]['hash']
                            todo_checkout.append((v[1], commit_hash))

            for k, v in unified_manager.nightly_inactive_nodes.items():
                if 'comfyui-manager' in k:
                    continue

                if cnr_repo_map.get(k):
                    repo_url = cnr_repo_map.get(k)
                    normalized_url1 = git_utils.normalize_url(repo_url)
                    normalized_url2 = git_utils.normalize_url_http(repo_url)

                    if normalized_url1 in git_info:
                        commit_hash = git_info[normalized_url1]['hash']
                        todo_enable.append((k, commit_hash))
                        processed_urls.append(normalized_url1)

                    if normalized_url2 in git_info:
                        commit_hash = git_info[normalized_url2]['hash']
                        todo_enable.append((k, commit_hash))
                        processed_urls.append(normalized_url2)

            for x in todo_disable:
                unified_manager.unified_disable(x, False)
                disabled_repos.append(x)

            for x in todo_enable:
                res = unified_manager.unified_enable(x, 'nightly')

                is_switched = False
                if res and res.target:
                    is_switched = repo_switch_commit(res.target, x[1])

                if is_switched:
                    checkout_repos.append(x)
                else:
                    enabled_repos.append(x)

            for x in todo_checkout:
                is_switched = repo_switch_commit(x[0], x[1])

                if is_switched:
                    checkout_repos.append(x)
                else:
                    skip_node_packs.append(x[0])

            for x in git_info.keys():
                normalized_url = git_utils.normalize_url(x)
                cnr = unified_manager.repo_cnr_map.get(normalized_url)
                if cnr is not None:
                    pack_id = cnr['id']
                    await unified_manager.install_by_id(pack_id, 'nightly', instant_execution=True, no_deps=False, return_postinstall=False)
                    cloned_repos.append(pack_id)
                    processed_urls.append(x)

            for x in processed_urls:
                if x in git_info:
                    del git_info[x]

            # remained nightly will be installed and migrated

    # for unknown restore
    todo_disable = []
    todo_enable = []
    todo_checkout = []
    processed_urls = []

    for k2, v2 in unified_manager.unknown_active_nodes.items():
        repo_url = resolve_giturl_from_path(v2[1])

        if repo_url is None:
            continue

        normalized_url1 = git_utils.normalize_url(repo_url)
        normalized_url2 = git_utils.normalize_url_http(repo_url)

        if normalized_url1 not in git_info and normalized_url2 not in git_info:
            todo_disable.append(k2)
        else:
            if normalized_url1 in git_info:
                commit_hash = git_info[normalized_url1]['hash']
                todo_checkout.append((k2, commit_hash))
                processed_urls.append(normalized_url1)

            if normalized_url2 in git_info:
                commit_hash = git_info[normalized_url2]['hash']
                todo_checkout.append((k2, commit_hash))
                processed_urls.append(normalized_url2)

    for k2, v2 in unified_manager.unknown_inactive_nodes.items():
        repo_url = resolve_giturl_from_path(v2[1])

        if repo_url is None:
            continue

        normalized_url1 = git_utils.normalize_url(repo_url)
        normalized_url2 = git_utils.normalize_url_http(repo_url)

        if normalized_url1 in git_info:
            commit_hash = git_info[normalized_url1]['hash']
            todo_enable.append((k2, commit_hash))
            processed_urls.append(normalized_url1)

        if normalized_url2 in git_info:
            commit_hash = git_info[normalized_url2]['hash']
            todo_enable.append((k2, commit_hash))
            processed_urls.append(normalized_url2)

    for x in todo_disable:
        unified_manager.unified_disable(x, True)
        disabled_repos.append(x)

    for x in todo_enable:
        res = unified_manager.unified_enable(x[0], 'unknown')

        is_switched = False
        if res and res.target:
            is_switched = repo_switch_commit(res.target, x[1])

        if is_switched:
            checkout_repos.append(x)
        else:
            enabled_repos.append(x)

    for x in todo_checkout:
        is_switched = repo_switch_commit(x[0], x[1])

        if is_switched:
            checkout_repos.append(x)
        else:
            skip_node_packs.append(x[0])

    for x in processed_urls:
        if x in git_info:
            del git_info[x]

    for repo_url in git_info.keys():
        repo_name = os.path.basename(repo_url)
        if repo_name.endswith('.git'):
            repo_name = repo_name[:-4]

        to_path = os.path.join(get_default_custom_nodes_path(), repo_name)
        unified_manager.repo_install(repo_url, to_path, instant_execution=True, no_deps=False, return_postinstall=False)
        cloned_repos.append(repo_name)

    # reload
    await unified_manager.migrate_unmanaged_nodes()

    # print summary
    for x in cloned_repos:
        print(f"[ INSTALLED ] {x}")
    for x in checkout_repos:
        print(f"[  CHECKOUT ] {x}")
    for x in enabled_repos:
        print(f"[  ENABLED  ] {x}")
    for x in disabled_repos:
        print(f"[  DISABLED ] {x}")
    for x in skip_node_packs:
        print(f"[  SKIPPED ] {x}")

    # if is_failed:
    #     print("[bold red]ERROR: Failed to restore snapshot.[/bold red]")


# check need to migrate
need_to_migrate = False


async def check_need_to_migrate():
    global need_to_migrate

    await unified_manager.reload('cache')
    await unified_manager.load_nightly(channel='default', mode='cache')

    legacy_custom_nodes = []

    for x in unified_manager.active_nodes.values():
        if x[0] == 'nightly' and not x[1].endswith('@nightly'):
            legacy_custom_nodes.append(x[1])

    for x in unified_manager.nightly_inactive_nodes.values():
        if not x.endswith('@nightly'):
            legacy_custom_nodes.append(x)

    if len(legacy_custom_nodes) > 0:
        print("\n--------------------- ComfyUI-Manager migration notice --------------------")
        print("The following custom nodes were installed using the old management method and require migration:\n")
        print("\n".join(legacy_custom_nodes))
        print("---------------------------------------------------------------------------\n")
        need_to_migrate = True


def get_comfyui_versions():
    repo = git.Repo(comfy_path)
    versions = [x.name for x in repo.tags if x.name.startswith('v')]
    versions.reverse()  # nearest tag

    versions = versions[:4]

    current_tag = repo.git.describe('--tags')

    if current_tag not in versions:
        versions = sorted(versions + [current_tag], reverse=True)
        versions = versions[:4]

    main_branch = repo.heads.master
    latest_commit = main_branch.commit
    latest_tag = repo.git.describe('--tags', latest_commit.hexsha)

    if latest_tag != versions[0]:
        versions.insert(0, 'nightly')
    else:
        versions[0] = 'nightly'
        current_tag = 'nightly'

    return versions, current_tag


def switch_comfyui(tag):
    repo = git.Repo(comfy_path)

    if tag == 'nightly':
        repo.git.checkout('main')
        repo.remotes.origin.pull()
        print("[ComfyUI-Manager] ComfyUI version is switched to the latest 'main' version")
    else:
        repo.git.checkout(tag)
        print(f"[ComfyUI-Manager] ComfyUI version is switched to '{tag}'")


def resolve_giturl_from_path(fullpath):
    """
    resolve giturl path of unclassified custom node based on remote url in .git/config
    """
    git_config_path = os.path.join(fullpath, '.git', 'config')

    if not os.path.exists(git_config_path):
        return "unknown"

    config = configparser.ConfigParser()
    config.read(git_config_path)

    for k, v in config.items():
        if k.startswith('remote ') and 'url' in v:
            return v['url'].replace("git@github.com:", "https://github.com/")

    return None


def repo_switch_commit(repo_path, commit_hash):
    try:
        repo = git.Repo(repo_path)
        if repo.head.commit.hexsha == commit_hash:
            return False

        repo.git.checkout(commit_hash)
        return True
    except:
        return None
