"""
description:
    `manager_core` contains the core implementation of the management functions in ComfyUI-Manager.

TODO:
    Consider removal from CLI:
        get_custom_nodes
        load_nightly
        get_from_cnr_inactive_nodes
        Remove is_unknown from unified_disable, unified_uninstall
        Remove version_spec from unified_update
        Remove extract_nodes_from_workflow
        Remove nightly_inactive_nodes
        Remove unknown_inactive_nodes
        Remove active_nodes
        Remove unknown_active_nodes
        Remove cnr_map
"""

import json
import logging
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

# orig_print preserves reference to built-in print before rich overrides it
# TODO: Replace remaining orig_print calls with logging.debug()
orig_print = print

from rich import print
from packaging import version

import uuid

from ..common import cm_global
from ..common import cnr_utils
from ..common import manager_util
from ..common import git_utils
from ..common import manager_downloader
from ..common.node_package import InstalledNodePackage
from comfyui_manager.data_models import SecurityLevel, NetworkMode
from ..common import context
from collections import defaultdict


version_code = [5, 0]
version_str = f"V{version_code[0]}.{version_code[1]}" + (f'.{version_code[2]}' if len(version_code) > 2 else '')


DEFAULT_CHANNEL = "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main"


default_custom_nodes_path = None


class InvalidChannel(Exception):
    def __init__(self, channel):
        self.channel = channel
        super().__init__(channel)


def get_default_custom_nodes_path():
    global default_custom_nodes_path
    if default_custom_nodes_path is None:
        try:
            import folder_paths
            default_custom_nodes_path = folder_paths.get_folder_paths("custom_nodes")[0]
        except Exception:
            default_custom_nodes_path = os.path.abspath(os.path.join(manager_util.comfyui_manager_path, '..'))

    return default_custom_nodes_path


def get_custom_nodes_paths():
        try:
            import folder_paths
            return folder_paths.get_folder_paths("custom_nodes")
        except Exception:
            custom_nodes_path = os.path.abspath(os.path.join(manager_util.comfyui_manager_path, '..'))
            return [custom_nodes_path]


def get_script_env():
    new_env = os.environ.copy()
    git_exe = get_config().get('git_exe')
    if git_exe is not None:
        new_env['GIT_EXE_PATH'] = git_exe

    if 'COMFYUI_PATH' not in new_env:
        new_env['COMFYUI_PATH'] = context.comfy_path

    if 'COMFYUI_FOLDERS_BASE_PATH' not in new_env:
        new_env['COMFYUI_FOLDERS_BASE_PATH'] = context.comfy_path

    return new_env


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
    except Exception:
        try:
            sys.path.append(context.comfy_path)
            import folder_paths
        except Exception:
            raise Exception(f"Invalid COMFYUI_FOLDERS_BASE_PATH: {context.comfy_path}")

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


cached_config = None
js_path = None

comfy_ui_required_revision = 1930
comfy_ui_required_commit_datetime = datetime(2024, 1, 24, 0, 0, 0)

comfy_ui_revision = "Unknown"
comfy_ui_commit_datetime = datetime(1900, 1, 1, 0, 0, 0)

channel_dict = None
valid_channels = {'default', 'local'}
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

    pattern = r'([^<>!~=]+)([<>!~=]=?)([^ ]*)'
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
        elif match.group(2) in ['<=', '==', '<', '~=']:
            if name in pips:
                if manager_util.StrictVersion(pips[name]) >= manager_util.StrictVersion(match.group(3)):
                    return True

    return False


def is_installed(name):
    name = name.strip()

    if name.startswith('#'):
        return True

    pattern = r'([^<>!~=]+)([<>!~=]=?)([0-9.a-zA-Z]*)'
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
        elif match.group(2) in ['<=', '==', '<', '~=']:
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
    elif channel.startswith('http://') and get_config()['http_channel_enabled'] == True:
        return channel

    tmp_dict = get_channel_dict()
    channel_url = tmp_dict.get(channel)
    if channel_url:
        return channel_url

    raise InvalidChannel(channel)


class ManagedResult:
    def __init__(self, action):
        self.action = action
        self.items = []
        self.result = True
        self.to_path = None
        self.msg = None
        self.target = None  # Deprecated: use target_path or target_version instead
        self.target_path = None  # Installation/operation path
        self.target_version = None  # Version specification
        self.postinstall = lambda: True
        self.ver = None

    def append(self, item):
        self.items.append(item)

    def fail(self, msg):
        self.result = False
        self.msg = msg
        return self

    def with_target(self, target):
        """Deprecated: use with_target_path or with_target_version instead"""
        self.target = target
        return self

    def with_target_path(self, path):
        """Set the target installation/operation path"""
        self.target_path = path
        self.target = path  # Maintain backward compatibility
        return self

    def with_target_version(self, version):
        """Set the target version specification"""
        self.target_version = version
        self.target = version  # Maintain backward compatibility
        return self

    def with_msg(self, msg):
        self.msg = msg
        return self

    def with_postinstall(self, postinstall):
        self.postinstall = postinstall
        return self

    def with_ver(self, ver):
        self.ver = ver
        return self


def identify_node_pack_from_path(fullpath):
    module_name = os.path.basename(fullpath)
    if module_name.endswith('.git'):
        module_name = module_name[:-4]

    repo_url = git_utils.git_url(fullpath)
    if repo_url is None:
        # cnr
        cnr = cnr_utils.read_cnr_info(fullpath)
        if cnr is not None:
            return module_name, cnr['version'], cnr['id'], None, None

        return None
    else:
        # nightly or unknown
        cnr_id = cnr_utils.read_cnr_id(fullpath)
        commit_hash = git_utils.get_commit_hash(fullpath)

        github_id = git_utils.normalize_to_github_id(repo_url)
        if github_id is None:
            try:
                github_id = os.path.basename(repo_url)
            except Exception:
                logging.warning(f"[ComfyUI-Manager] unexpected repo url: {repo_url}")
                github_id = module_name

        if cnr_id is not None:
            return module_name, commit_hash, cnr_id, None, github_id
        else:
            return module_name, commit_hash, '', None, github_id


class NormalizedKeyDict:
    def __init__(self):
        self._store = {}
        self._key_map = {}

    def _normalize_key(self, key):
        if isinstance(key, str):
            return key.strip().lower()
        return key

    def __setitem__(self, key, value):
        norm_key = self._normalize_key(key)
        self._key_map[norm_key] = key
        self._store[key] = value

    def __getitem__(self, key):
        norm_key = self._normalize_key(key)
        original_key = self._key_map[norm_key]
        return self._store[original_key]

    def __delitem__(self, key):
        norm_key = self._normalize_key(key)
        original_key = self._key_map.pop(norm_key)
        del self._store[original_key]

    def __contains__(self, key):
        return self._normalize_key(key) in self._key_map

    def get(self, key, default=None):
        return self[key] if key in self else default

    def setdefault(self, key, default=None):
        if key in self:
            return self[key]
        self[key] = default
        return default

    def pop(self, key, default=None):
        if key in self:
            val = self[key]
            del self[key]
            return val
        if default is not None:
            return default
        raise KeyError(key)

    def keys(self):
        return self._store.keys()

    def values(self):
        return self._store.values()

    def items(self):
        return self._store.items()

    def __iter__(self):
        return iter(self._store)

    def __len__(self):
        return len(self._store)

    def __repr__(self):
        return repr(self._store)

    def to_dict(self):
        return dict(self._store)


class UnifiedManager:
    def __init__(self):
        self.installed_node_packages: dict[str, list[InstalledNodePackage]] = defaultdict(list)
        self.repo_nodepack_map = {}  # compact_url -> InstalledNodePackage mapping 
        self.reload()
        self.processed_install = set()

    def reload(self):
        import folder_paths

        self.installed_node_packages: dict[str, list[InstalledNodePackage]] = defaultdict(list)
        self.repo_nodepack_map = {}

        # reload node status info from custom_nodes/*
        for custom_nodes_path in folder_paths.get_folder_paths('custom_nodes'):
            logging.debug(f"reload() scanning enabled packages in: {custom_nodes_path}")
            dir_list = os.listdir(custom_nodes_path)
            logging.debug(f"reload() os.listdir found {len(dir_list)} items")
            for x in dir_list:
                fullpath = os.path.join(custom_nodes_path, x)
                is_dir = os.path.isdir(fullpath)
                if is_dir:
                    if x not in ['__pycache__', '.disabled']:
                        try:
                            node_package = InstalledNodePackage.from_fullpath(fullpath, self.resolve_from_path)
                            logging.debug(f"reload() enabled package: dirname='{x}', id='{node_package.id}', version='{node_package.version}'")
                            self.installed_node_packages[node_package.id].append(node_package)

                            # For CNR packages, also index under normalized name for case-insensitive lookup
                            if node_package.is_from_cnr:
                                normalized_id = cnr_utils.normalize_package_name(node_package.id)
                                if normalized_id != node_package.id:
                                    logging.debug(f"reload() also indexing CNR package under normalized name: '{normalized_id}'")
                                    self.installed_node_packages[normalized_id].append(node_package)

                            # Build repo_packname_map for git repositories
                            if node_package.repo_url:
                                compact_url = git_utils.compact_url(node_package.repo_url)
                                self.repo_nodepack_map[compact_url] = node_package
                        except Exception as e:
                            logging.debug(f"reload() FAILED to load enabled package '{x}': {e}")
                        
        # reload node status info from custom_nodes/.disabled/*
        for custom_nodes_path in folder_paths.get_folder_paths('custom_nodes'):
            disabled_dir = os.path.join(custom_nodes_path, '.disabled')
            if os.path.exists(disabled_dir):
                for x in os.listdir(disabled_dir):
                    fullpath = os.path.join(disabled_dir, x)
                    if os.path.isdir(fullpath):
                        node_package = InstalledNodePackage.from_fullpath(fullpath, self.resolve_from_path)
                        logging.debug(f"reload() disabled package: dirname='{x}', id='{node_package.id}', version='{node_package.version}'")
                        self.installed_node_packages[node_package.id].append(node_package)

                        # For CNR packages, also index under normalized name for case-insensitive lookup
                        if node_package.is_from_cnr:
                            normalized_id = cnr_utils.normalize_package_name(node_package.id)
                            if normalized_id != node_package.id:
                                logging.debug(f"reload() also indexing disabled CNR package under normalized name: '{normalized_id}'")
                                self.installed_node_packages[normalized_id].append(node_package)

                        # Build repo_packname_map for git repositories
                        if node_package.repo_url:
                            compact_url = git_utils.compact_url(node_package.repo_url)
                            self.repo_nodepack_map[compact_url] = node_package

                        
    def _get_packages_by_name_or_url(self, packname):
        """
        Helper method to get packages by CNR ID or normalized URL.
        Returns a list of InstalledNodePackage objects.
        """
        logging.debug(f"_get_packages_by_name_or_url('{packname}')")
        packages = list(self.installed_node_packages.get(packname, []))
        logging.debug(f"  direct lookup found {len(packages)} package(s)")

        # If packname is a CNR ID (not URL-like), also check for nightly packages via repository URL
        # This ensures we find BOTH CNR and nightly versions of the same package
        is_url = self.is_url_like(packname)
        if not is_url:
            # First try to get repo_url from the packages we already found (disabled CNR packages have repo_url)
            repo_url = None
            for pkg in packages:
                if pkg.repo_url:
                    repo_url = pkg.repo_url
                    logging.debug(f"  found repo_url from package: {repo_url}")
                    break

            # If we didn't find a repo_url in the direct lookup, try CNR API
            if not repo_url:
                # Try to get the original package name from nightly packages (which preserve casing in their compact_url)
                original_packname = None
                for pkg_id in self.installed_node_packages.keys():
                    if '/' in pkg_id:  # This is a nightly package with format "owner/PackageName"
                        parts = pkg_id.split('/')
                        if len(parts) == 2:
                            pkg_name = parts[1]
                            if cnr_utils.normalize_package_name(pkg_name) == packname:
                                original_packname = pkg_name
                                logging.debug(f"  found original packname '{original_packname}' from nightly package")
                                break

                try:
                    # Try CNR API with the original casing if available, otherwise use normalized packname
                    cnr_packname = original_packname if original_packname else packname
                    pack_info = cnr_utils.get_nodepack(cnr_packname)
                    if pack_info and 'repository' in pack_info:
                        repo_url = pack_info['repository']
                        logging.debug(f"  CNR API returned repo_url: {repo_url}")
                except Exception:
                    pass  # CNR API lookup failed, continue without nightly packages

            # If we have a repo_url (from package or CNR), look up nightly packages
            if repo_url:
                compact_url = git_utils.compact_url(repo_url)
                url_packages = self.installed_node_packages.get(compact_url, [])
                logging.debug(f"  compact_url lookup found {len(url_packages)} package(s)")
                packages.extend(url_packages)

        logging.debug(f"  returning {len(packages)} package(s)")
        return packages

    def get_module_name(self, x):
        packs = self.installed_node_packages.get(x)

        if packs is None:
            compact_url_x = git_utils.compact_url(x)
            packs = self.installed_node_packages.get(compact_url_x)

        if packs is not None:
            for x in packs:
                return os.path.basename(x.fullpath)

        return None

    def get_active_pack(self, packname):
        # Get packages by CNR ID or normalized URL
        logging.debug(f"get_active_pack('{packname}')")
        packages = self._get_packages_by_name_or_url(packname)
        logging.debug(f"  found {len(packages)} packages total")
        for i, x in enumerate(packages):
            logging.debug(f"  package[{i}]: id='{x.id}', version='{x.version}', is_enabled={x.is_enabled}")
            if x.is_enabled:
                logging.debug(f"  → returning enabled package: {x.id}")
                return x

        logging.debug("  → returning None (no enabled package found)")
        return None

    def get_inactive_pack(self, packname, version_spec=None):
        """
        Find a disabled node package by name and version.

        Checks all installed packages with the given name, filtering for disabled ones.
        Matches based on version_spec:
          - 'unknown' → unknown version
          - 'nightly' → nightly version
          - 'latest'  → newest CNR version
          - exact version match
        If no exact match, falls back in order: latest → nightly → unknown.

        Returns the matching InstalledNodePackage or None.
        """
        latest_pack = None
        nightly_pack = None
        unknown_pack = None
        # Get packages by CNR ID or normalized URL
        packages = self._get_packages_by_name_or_url(packname)
        for x in packages:
            if x.is_disabled:
                if x.is_unknown:
                    if version_spec == 'unknown':
                        return x
                    unknown_pack = x

                elif x.is_nightly:
                    if version_spec == 'nightly':
                        return x
                    nightly_pack = x

                elif x.is_from_cnr:
                    if x.version == version_spec:
                        return x

                    if latest_pack is None:
                        latest_pack = x
                    elif manager_util.StrictVersion(latest_pack.version) < manager_util.StrictVersion(x.version):
                        latest_pack = x

        if version_spec == 'latest':
            return latest_pack

        # version_spec is not given
        if latest_pack is not None:
            return latest_pack
        elif nightly_pack is not None:
            return nightly_pack
        return unknown_pack

    def is_url_like(self, packname):
        """Check if packname looks like a URL (git repository)"""
        url_patterns = [
            'http://', 'https://', 'git@', 'ssh://',
            '.git', 'github.com', 'gitlab.com', 'bitbucket.org'
        ]
        return any(pattern in packname.lower() for pattern in url_patterns)


    def resolve_unspecified_version(self, packname, guess_mode=None):
        # Handle URL-like identifiers
        if self.is_url_like(packname):
            # For URLs, default to nightly version
            return 'nightly'

        if guess_mode == 'active':
            # priority:
            # 1. CNR/nightly active nodes
            # 2. Fail
            x = self.get_active_pack(packname)
            return x.version if x is not None else None

        elif guess_mode == 'inactive':
            # priority:
            # 1. CNR latest in inactive
            # 2. nightly
            # 3. fail

            # Get packages by CNR ID or normalized URL
            packs = self._get_packages_by_name_or_url(packname)

            latest_cnr = None
            nightly = None

            for x in packs:
                # Return None if any nodepack is enabled
                if x.is_enabled:
                    return None

                if x.is_from_cnr:
                    # find latest cnr
                    if latest_cnr is None:
                        latest_cnr = x
                    elif manager_util.StrictVersion(latest_cnr.version) < manager_util.StrictVersion(x.version):
                        latest_cnr = x
                else:
                    nightly = x

            if latest_cnr is not None:
                return latest_cnr.version

            return 'nightly' if nightly is not None else None
        else:
            # priority:
            # 1. CNR latest in world
            # 2. nightly in world
            # 3. fail

            # Get packages by CNR ID or normalized URL
            packs = self._get_packages_by_name_or_url(packname)

            latest_cnr = None
            nightly = None

            for x in packs:
                if x.is_from_cnr:
                    # find latest cnr
                    if latest_cnr is None:
                        latest_cnr = x
                    elif manager_util.StrictVersion(latest_cnr.version) < manager_util.StrictVersion(x.version):
                        latest_cnr = x
                else:
                    nightly = x

            if latest_cnr is not None:
                return latest_cnr.version

            return 'nightly' if nightly is not None else None

    def resolve_node_spec(self, packname, guess_mode=None):
        """
        resolve to 'packname, version_spec' from version string

        version string:
            packname@latest
            packname@nightly
            packname@<version>
            packname

        if guess_mode is not specified:
            return value can be 'None' based on state check
        """

        spec = packname.split('@')

        if len(spec) == 2:
            packname = spec[0]
            version_spec = spec[1]

            if version_spec == 'latest':
                info = cnr_utils.get_nodepack(packname)
                if info is None or 'latest_version' not in info:
                    return None
                
                version_spec = info['latest_version']
        else:
            if guess_mode not in ['active', 'inactive']:
                guess_mode = None
                
            packname = spec[0]
            version_spec = self.resolve_unspecified_version(packname, guess_mode=guess_mode)

        return packname, version_spec, len(spec) > 1

    @staticmethod
    def resolve_from_path(fullpath):
        url = git_utils.git_url(fullpath)
        if url:
            url = git_utils.compact_url(url)
            commit_hash = git_utils.get_commit_hash(fullpath)
            return {'id': url, 'ver': 'nightly', 'hash': commit_hash}
        else:
            info = cnr_utils.read_cnr_info(fullpath)

            if info:
                return {'id': info['id'], 'ver': info['version']}
            else:
                return None

    def is_enabled(self, packname, version_spec=None) -> bool:
        """
        1. `packname@<any>` is enabled         if `version_spec=None`
        3. `packname@nightly` is enabled       if `version_spec=nightly`
        4. `packname@<version_spec>` is enabled
        5. False otherwise

        NOTE: version_spec cannot be 'latest' or 'unknown'
        """

        # Get packages by CNR ID or normalized URL
        packs = self._get_packages_by_name_or_url(packname)

        for x in packs:
            if x.is_enabled:
                if version_spec is None:
                    return True
                elif version_spec == 'nightly':
                    return x.is_nightly
                elif x.is_from_cnr:
                    return manager_util.StrictVersion(x.version) == manager_util.StrictVersion(version_spec)
                return False

        return False

    def is_disabled(self, packname, version_spec=None):
        """
        1. not exists (active packname) if version_spec is None
        3. `packname@nightly` is disabled if `version_spec=nightly`
        4. `packname@<version_spec> is disabled

        NOTE: version_spec cannot be 'latest' or 'unknown'
        """

        # Get packages by CNR ID or normalized URL
        packs = self._get_packages_by_name_or_url(packname)
        logging.debug(f"is_disabled(packname='{packname}', version_spec='{version_spec}'): found {len(packs)} package(s)")

        if version_spec is None:
            for x in packs:
                if x.is_enabled:
                    return False

            return True

        for x in packs:
            logging.debug(f"  checking package: id='{x.id}', version='{x.version}', disabled={x.is_disabled}, is_from_cnr={x.is_from_cnr}")
            if x.is_disabled:
                if version_spec == 'nightly':
                    result = x.is_nightly
                    logging.debug(f"  nightly check: {result}")
                    if result:
                        return True
                    # Continue checking other packages
                elif x.is_from_cnr:
                    result = manager_util.StrictVersion(x.version) == manager_util.StrictVersion(version_spec)
                    logging.debug(f"  CNR version check: {x.version} == {version_spec} -> {result}")
                    if result:
                        return True
                    # Continue checking other packages

        logging.debug("  no matching disabled package found -> False")
        return False
        
    def execute_install_script(self, url, repo_path, instant_execution=False, lazy_mode=False, no_deps=False):
        install_script_path = os.path.join(repo_path, "install.py")
        requirements_path = os.path.join(repo_path, "requirements.txt")

        res = True
        if lazy_mode:
            install_cmd = ["#LAZY-INSTALL-SCRIPT", sys.executable]
            return try_install_script(url, repo_path, install_cmd)
        else:
            if os.path.exists(requirements_path) and not no_deps:
                print("Install: pip packages")
                pip_fixer = manager_util.PIPFixer(manager_util.get_installed_packages(), context.comfy_path, context.manager_files_path)
                lines = manager_util.robust_readlines(requirements_path)
                for line in lines:
                    package_name = remap_pip_package(line.strip())
                    if package_name and not package_name.startswith('#') and package_name not in self.processed_install:
                        self.processed_install.add(package_name)
                        clean_package_name = package_name.split('#')[0].strip()
                        install_cmd = manager_util.make_pip_cmd(["install", clean_package_name])
                        if clean_package_name != "" and not clean_package_name.startswith('#'):
                            res = res and try_install_script(url, repo_path, install_cmd, instant_execution=instant_execution)

                pip_fixer.fix_broken()

            if os.path.exists(install_script_path) and install_script_path not in self.processed_install:
                self.processed_install.add(install_script_path)
                print("Install: install script")
                install_cmd = [sys.executable, "install.py"]
                return res and try_install_script(url, repo_path, install_cmd, instant_execution=instant_execution)

        return res

    @staticmethod
    def reserve_cnr_switch(target, zip_url, from_path, to_path, no_deps):
        script_path = os.path.join(context.manager_startup_script_path, "install-scripts.txt")
        with open(script_path, "a") as file:
            obj = [target, "#LAZY-CNR-SWITCH-SCRIPT", zip_url, from_path, to_path, no_deps, get_default_custom_nodes_path(), sys.executable]
            file.write(f"{obj}\n")

        print(f"Installation reserved: {target}")

        return True

    def unified_fix(self, packname, version_spec, instant_execution=False, no_deps=False):
        """
        fix dependencies
        """

        result = ManagedResult('fix')

        x = self.get_active_pack(packname)

        if x is None:
            return result.fail(f'not found: {packname}@{version_spec}')
        
        self.execute_install_script(packname, x.fullpath, instant_execution=instant_execution, no_deps=no_deps)

        return result

    def cnr_switch_version(self, packname, version_spec=None, instant_execution=False, no_deps=False, return_postinstall=False):
        if instant_execution:
            return self.cnr_switch_version_instant(packname, version_spec, instant_execution, no_deps, return_postinstall)
        else:
            return self.cnr_switch_version_lazy(packname, version_spec, no_deps, return_postinstall)

    def cnr_switch_version_lazy(self, packname, version_spec=None, no_deps=False, return_postinstall=False):
        """
        switch between cnr version (lazy mode)
        """

        result = ManagedResult('switch-cnr')

        # fetch info for installation
        node_info = cnr_utils.install_node(packname, version_spec)
        if node_info is None or not node_info.download_url:
            return result.fail(f'not available node: {packname}@{version_spec}')

        version_spec = node_info.version

        # cancel if the specified nodepack is not installed
        active_node = self.get_active_pack(packname)

        if active_node is None:
            return result.fail(f"Failed to switch version: '{packname}' was not previously installed.")

        # skip if the specified version is installed already
        if active_node.version == version_spec:
            return ManagedResult('skip').with_msg("Up to date")

        # install
        zip_url = node_info.download_url
        from_path = active_node.fullpath
        target = packname
        to_path = os.path.join(get_default_custom_nodes_path(), target)

        def postinstall():
            return self.reserve_cnr_switch(target, zip_url, from_path, to_path, no_deps)

        if return_postinstall:
            return result.with_postinstall(postinstall)
        else:
            if not postinstall():
                return result.fail(f"Failed to execute install script: {packname}@{version_spec}")

        return result

    def cnr_switch_version_instant(self, packname, version_spec=None, instant_execution=True, no_deps=False, return_postinstall=False):
        """
        switch between cnr version

        If `version_spec` is None, it is considered the latest version.
        """

        # 1. Resolve packname to original case (CNR API requires original case)
        # For version switching, the package must already be installed (either active or inactive)
        result = ManagedResult('switch-cnr')

        # Try to find the package in active or inactive state to get original name
        active_node = self.get_active_pack(packname)
        inactive_node_any = self.get_inactive_pack(packname)  # Get any inactive version

        # Use the original package ID if found
        if active_node is not None:
            original_packname = active_node.id
        elif inactive_node_any is not None:
            original_packname = inactive_node_any.id
        else:
            original_packname = packname  # Fallback to input name

        # Remove URL prefix if present (e.g., "owner/repo" → "repo")
        # CNR API expects package name, not URL
        if '/' in original_packname:
            original_packname = original_packname.split('/')[-1]

        logging.debug(f"[DEBUG] cnr_switch_version_instant: Resolved packname '{packname}' → '{original_packname}'")

        # 2. Fetch CNR package info
        node_info = cnr_utils.install_node(original_packname, version_spec)
        if node_info is None or not node_info.download_url:
            return result.fail(f'not available node: {original_packname}@{version_spec}')

        version_spec = node_info.version

        # 2. Check if requested CNR version already exists in .disabled/
        inactive_node = self.get_inactive_pack(packname, version_spec=version_spec)

        logging.debug(f"[DEBUG] cnr_switch_version_instant: packname={packname}, version_spec={version_spec}")
        logging.debug(f"[DEBUG] cnr_switch_version_instant: inactive_node={inactive_node.id if inactive_node else None}, is_from_cnr={inactive_node.is_from_cnr if inactive_node else None}")

        if inactive_node is not None and inactive_node.is_from_cnr and inactive_node.version == version_spec:
            # Case A: Requested CNR version exists in .disabled/
            # This ensures proper version switching for both Archive ↔ Nightly transitions
            # Solution: Disable current active version, enable the disabled CNR version

            logging.debug(f"[DEBUG] cnr_switch_version_instant: Case A - Found CNR {version_spec} in .disabled/, using enable/disable")

            # Disable currently active version (if any)
            active_node = self.get_active_pack(packname)
            if active_node is not None:
                logging.debug(f"[DEBUG] cnr_switch_version_instant: Disabling active package: id={active_node.id}, version={active_node.version}")
                # Use active_node.id instead of packname to properly handle compact URLs like "owner/repo"
                disable_result = self.unified_disable(active_node.id)
                if not disable_result.result:
                    return result.fail(f"Failed to disable current version: {disable_result.msg}")

            # Enable the disabled CNR version
            logging.debug(f"[DEBUG] cnr_switch_version_instant: Enabling CNR {version_spec} from .disabled/")
            enable_result = self.unified_enable(packname, version_spec=version_spec)

            if not enable_result.result:
                return result.fail(f"Failed to enable CNR version: {packname}@{version_spec}")

            # Execute postinstall for the enabled package
            install_path = enable_result.target_path
            result.target_version = version_spec
            result.target_path = install_path
            result.target = version_spec

            def postinstall():
                res = self.execute_install_script(f"{packname}@{version_spec}", install_path, instant_execution=instant_execution, no_deps=no_deps)
                return res

            if return_postinstall:
                return result.with_postinstall(postinstall)
            else:
                if not postinstall():
                    return result.fail(f"Failed to execute install script: {packname}@{version_spec}")

            logging.debug("[DEBUG] cnr_switch_version_instant: Case A completed successfully")
            return result

        # Case B: Requested CNR version doesn't exist in .disabled/
        # Continue with download and install
        logging.debug(f"[DEBUG] cnr_switch_version_instant: Case B - CNR {version_spec} not found in .disabled/, downloading...")

        # cancel if the specified nodepack is not installed
        active_node = self.get_active_pack(packname)

        if active_node is None:
            return result.fail(f"Failed to switch version: '{packname}' was not previously installed.")

        # Check if active package is Nightly (has .git directory)
        # If switching from Nightly → CNR, disable Nightly first to preserve git history
        git_dir = os.path.join(active_node.fullpath, '.git')
        is_active_nightly = os.path.isdir(git_dir)

        logging.debug(f"[DEBUG] cnr_switch_version_instant: active_node.id='{active_node.id}', active_node.fullpath='{active_node.fullpath}'")
        logging.debug(f"[DEBUG] cnr_switch_version_instant: is_active_nightly={is_active_nightly}, git_dir='{git_dir}'")

        if is_active_nightly:
            logging.debug(f"[DEBUG] cnr_switch_version_instant: Active package is Nightly, disabling to preserve git history")

            # Save original fullpath BEFORE disabling (preserves original case and path)
            original_enabled_path = active_node.fullpath
            logging.debug(f"[DEBUG] cnr_switch_version_instant: Saved original path = '{original_enabled_path}'")

            # Disable current Nightly to .disabled/ (preserves .git directory)
            disable_result = self.unified_disable(active_node.id)
            if not disable_result.result:
                return result.fail(f"Failed to disable Nightly version: {disable_result.msg}")

            logging.debug(f"[DEBUG] cnr_switch_version_instant: Nightly disabled successfully")

            # Use saved original path for CNR installation (ensures correct case and path)
            install_path = original_enabled_path
            logging.debug(f"[DEBUG] cnr_switch_version_instant: Using original path for CNR install = '{install_path}'")
        else:
            # CNR → CNR upgrade: in-place upgrade is acceptable
            install_path = active_node.fullpath
            logging.debug(f"[DEBUG] cnr_switch_version_instant: CNR→CNR upgrade, install_path = '{install_path}'")

        archive_name = f"CNR_temp_{str(uuid.uuid4())}.zip"  # should be unpredictable name - security precaution
        download_path = os.path.join(get_default_custom_nodes_path(), archive_name)
        logging.debug(f"[DEBUG] cnr_switch_version_instant: Downloading from '{node_info.download_url}' to '{download_path}'")
        manager_downloader.basic_download_url(node_info.download_url, get_default_custom_nodes_path(), archive_name)
        logging.debug(f"[DEBUG] cnr_switch_version_instant: Download complete")

        # 2. extract files into <packname>
        logging.debug(f"[DEBUG] cnr_switch_version_instant: Extracting '{download_path}' to '{install_path}'")
        extracted = manager_util.extract_package_as_zip(download_path, install_path)
        logging.debug(f"[DEBUG] cnr_switch_version_instant: Extraction result: {extracted is not None}, files={len(extracted) if extracted else 0}")
        os.remove(download_path)
        logging.debug(f"[DEBUG] cnr_switch_version_instant: Archive file removed")

        if extracted is None:
            if len(os.listdir(install_path)) == 0:
                rmtree(install_path)

            return result.fail(f'Empty archive file: {packname}@{version_spec}')

        # 3. Calculate garbage files (.tracking - extracted)
        # Note: .tracking file won't exist when switching from Nightly or on first CNR install
        tracking_info_file = os.path.join(install_path, '.tracking')
        prev_files = set()
        if os.path.exists(tracking_info_file):
            with open(tracking_info_file, 'r') as f:
                for line in f:
                    prev_files.add(line.strip())
        else:
            logging.debug(f"[DEBUG] cnr_switch_version_instant: No previous .tracking file (first CNR install or switched from Nightly)")

        garbage = prev_files.difference(extracted)
        garbage = [os.path.join(install_path, x) for x in garbage]

        # 4-1. Remove garbage files
        for x in garbage:
            if os.path.isfile(x):
                os.remove(x)

        # 4-2. Remove garbage dir if empty
        for x in garbage:
            if os.path.isdir(x):
                if not os.listdir(x):
                    os.rmdir(x)

        # 6. create .tracking file
        tracking_info_file = os.path.join(install_path, '.tracking')
        with open(tracking_info_file, "w", encoding='utf-8') as file:
            file.write('\n'.join(list(extracted)))

        # 7. post install
        result.target_version = version_spec
        result.target_path = install_path
        result.target = version_spec  # Maintain backward compatibility

        def postinstall():
            res = self.execute_install_script(f"{packname}@{version_spec}", install_path, instant_execution=instant_execution, no_deps=no_deps)
            return res

        if return_postinstall:
            return result.with_postinstall(postinstall)
        else:
            if not postinstall():
                return result.fail(f"Failed to execute install script: {packname}@{version_spec}")

        return result

    def switch_version(self, packname, mode=None, instant_execution=True, no_deps=False, return_postinstall=False):
        """
        Universal version switch function that handles:
        - CNR version switching (mode = specific version like "1.0.1")
        - Nightly switching (mode = "nightly")
        - Latest switching (mode = None or "latest")

        This function coordinates enable/disable operations to switch between versions.

        Args:
            packname: Package name or CNR ID (e.g., "ComfyUI_SigmoidOffsetScheduler")
            mode: Target version mode:
                  - "nightly": Switch to nightly version
                  - "1.0.1", "1.0.2", etc.: Switch to specific CNR version
                  - "latest" or None: Switch to latest CNR version available
            instant_execution: Whether to execute install scripts immediately
            no_deps: Skip dependency installation
            return_postinstall: Return postinstall callback instead of executing

        Returns:
            ManagedResult with success/failure status
        """
        result = ManagedResult('switch-version')

        logging.info(f"[DEBUG] switch_version: packname={packname}, mode={mode}")

        # Handle switching to Nightly
        if mode == "nightly":
            logging.debug(f"[DEBUG] switch_version: Switching to Nightly for {packname}")

            # Check if Nightly version exists in disabled
            inactive_nightly = self.get_inactive_pack(packname, version_spec="nightly")
            if inactive_nightly is None:
                return result.fail(f"Nightly version not installed for {packname}. Please install it first.")

            # Disable current active version
            active_node = self.get_active_pack(packname)
            if active_node is not None:
                logging.debug(f"[DEBUG] switch_version: Disabling current active version: {active_node.id}@{active_node.version}")
                disable_result = self.unified_disable(active_node.id)
                if not disable_result.result:
                    return result.fail(f"Failed to disable current version: {disable_result.msg}")

            # Enable Nightly version
            logging.debug("[DEBUG] switch_version: Enabling Nightly version")
            enable_result = self.unified_enable(packname, version_spec="nightly")
            if not enable_result.result:
                return result.fail(f"Failed to enable Nightly version: {enable_result.msg}")

            # Execute postinstall for the enabled package
            install_path = enable_result.target_path
            result.target_path = install_path
            result.target = "nightly"

            def postinstall():
                res = self.execute_install_script(f"{packname}@nightly", install_path, instant_execution=instant_execution, no_deps=no_deps)
                return res

            if return_postinstall:
                return result.with_postinstall(postinstall)
            else:
                if not postinstall():
                    return result.fail(f"Failed to execute install script: {packname}@nightly")

            logging.info("[DEBUG] switch_version: Successfully switched to Nightly")
            return result

        # Handle switching to specific CNR version or latest
        else:
            version_spec = mode  # mode is the version number (e.g., "1.0.1") or None for latest
            logging.debug(f"[DEBUG] switch_version: Switching to CNR version {version_spec or 'latest'} for {packname}")

            # Delegate to existing CNR switch logic
            return self.cnr_switch_version_instant(
                packname=packname,
                version_spec=version_spec,
                instant_execution=instant_execution,
                no_deps=no_deps,
                return_postinstall=return_postinstall
            )

    def unified_enable(self, packname: str, version_spec=None):
        """
        priority if version_spec == None
        1. CNR latest in disk
        2. nightly

        remark: latest version_spec is not allowed. Must be resolved before call.
        """

        result = ManagedResult('enable')

        if version_spec is None:
            version_spec = self.resolve_unspecified_version(packname, guess_mode='inactive')
            if version is None:
                return result.fail(f'Specified inactive nodepack not exists: {packname}')

        if self.is_enabled(packname, version_spec):
            return ManagedResult('skip').with_msg('Already enabled')

        if not self.is_disabled(packname, version_spec):
            return ManagedResult('skip').with_msg('Not installed')

        inactive_node = self.get_inactive_pack(packname, version_spec=version_spec)
        if inactive_node is None:
            if version_spec is None:
                return result.fail(f'Specified inactive nodepack not exists: {packname}')
            else:
                return result.fail(f'Specified inactive nodepack not exists: {packname}@{version_spec}')

        from_path = inactive_node.fullpath
        base_path = extract_base_custom_nodes_dir(from_path)

        # Read original name from pyproject.toml to preserve case
        # Active directories MUST use original name (e.g., "ComfyUI_Foo")
        # not normalized name (e.g., "comfyui_foo")
        original_name = packname  # fallback to normalized name
        toml_path = os.path.join(from_path, 'pyproject.toml')
        if os.path.exists(toml_path):
            try:
                import toml
                with open(toml_path, 'r', encoding='utf-8') as f:
                    data = toml.load(f)
                    project = data.get('project', {})
                    if 'name' in project:
                        original_name = project['name'].strip()
            except Exception:
                # If reading fails, use the normalized name as fallback
                pass

        to_path = os.path.join(base_path, original_name)

        # move from disk
        shutil.move(from_path, to_path)

        return result.with_target_path(to_path)

    def _get_installed_version(self, fullpath: str) -> str:
        """
        Get version from installed package's pyproject.toml.

        This ensures we always use the INSTALLED version, not the registry version.

        Args:
            fullpath: Full path to the installed package directory

        Returns:
            Version string from pyproject.toml, or None if not found
        """
        info = cnr_utils.read_cnr_info(fullpath)
        if info and 'version' in info:
            return info['version']
        return None

    def unified_disable(self, packname: str):
        """
        Disable specified nodepack

        NOTE: no more support 'unknown' version
        """
        result = ManagedResult('disable')

        matched = None
        matched_active = None

        # Get packages by CNR ID or normalized URL
        packages = self._get_packages_by_name_or_url(packname)
        for x in packages:
            matched = x
            if x.is_enabled:
                matched_active = x

        # Report for items that are either not installed or already disabled
        if matched is None:
            return ManagedResult('skip').with_msg('Not installed')

        if matched_active is None:
            return ManagedResult('skip').with_msg('Already disabled')

        # disable
        base_path = extract_base_custom_nodes_dir(matched_active.fullpath)
        # Use normalized package name for the disabled folder name
        # This prevents nested directories when packname contains '/' (e.g., "owner/repo")
        if self.is_url_like(packname):
            folder_name = os.path.basename(matched_active.fullpath).lower()
        else:
            # For compact URLs like "owner/repo", extract basename first
            base_name = os.path.basename(packname) if '/' in packname else packname
            # Then normalize (lowercase, strip whitespace)
            folder_name = cnr_utils.normalize_package_name(base_name)

        # Get actual installed version from package directory (not from cache)
        installed_version = self._get_installed_version(matched_active.fullpath)
        if not installed_version:
            # Fallback to cached version if filesystem read fails
            installed_version = matched_active.version
            logging.warning(f"[ComfyUI-Manager] Could not read version from {matched_active.fullpath}, using cached version {installed_version}")
        else:
            logging.info(f"[ComfyUI-Manager] Disabling {packname}: using installed version {installed_version}")

        to_path = os.path.join(base_path, '.disabled', f"{folder_name}@{installed_version.replace('.', '_')}")

        # Remove existing disabled version if present
        if os.path.exists(to_path):
            shutil.rmtree(to_path)

        shutil.move(matched_active.fullpath, to_path)
        moving_info = matched_active.fullpath, to_path
        result.append(moving_info)

        return result

    def unified_uninstall(self, packname: str):
        """
        Remove whole installed custom nodes including inactive nodes
        """
        result = ManagedResult('uninstall')

        # Get packages by CNR ID or normalized URL
        packages_to_uninstall = self._get_packages_by_name_or_url(packname)

        # Debug logging
        logging.debug(f"[ComfyUI-Manager] Uninstall request for: {packname}")
        logging.debug(f"[ComfyUI-Manager] Found {len(packages_to_uninstall)} package(s) to uninstall")
        logging.debug(f"[ComfyUI-Manager] Available keys in installed_node_packages: {list(self.installed_node_packages.keys())}")

        for x in packages_to_uninstall:
            logging.info(f"[ComfyUI-Manager] Uninstalling: {x.fullpath}")
            try_rmtree(packname, x.fullpath)
            result.items.append((x.version, x.fullpath))

        if len(result.items) == 0:
            logging.warning(f"[ComfyUI-Manager] Package not found for uninstall: {packname}")
            return ManagedResult('skip').with_msg('Not installed')

        return result

    def cnr_install(self, packname: str, version_spec=None, instant_execution=False, no_deps=False, return_postinstall=False):
        result = ManagedResult('install-cnr')

        if 'comfyui-manager' in packname.lower():
            return result.fail(f"ignored: installing '{packname}'")

        node_info = cnr_utils.install_node(packname, version_spec)
        if node_info is None or not node_info.download_url:
            return result.fail(f'not available node: {packname}@{version_spec}')

        archive_name = f"CNR_temp_{str(uuid.uuid4())}.zip"  # should be unpredictable name - security precaution
        download_path = os.path.join(get_default_custom_nodes_path(), archive_name)

        # re-download. I cannot trust existing file.
        if os.path.exists(download_path):
            os.remove(download_path)

        # install_path
        install_path = os.path.join(get_default_custom_nodes_path(), packname)
        if os.path.exists(install_path):
            return result.fail(f'Install path already exists: {install_path}')

        manager_downloader.download_url(node_info.download_url, get_default_custom_nodes_path(), archive_name)
        os.makedirs(install_path, exist_ok=True)
        extracted = manager_util.extract_package_as_zip(download_path, install_path)
        os.remove(download_path)
        result.to_path = install_path

        if extracted is None:
            rmtree(install_path)
            return result.fail(f'Empty archive file: {packname}@{version_spec}')

        # create .tracking file
        tracking_info_file = os.path.join(install_path, '.tracking')
        with open(tracking_info_file, "w", encoding='utf-8') as file:
            file.write('\n'.join(extracted))

        result.target_version = version_spec
        result.target_path = install_path
        result.target = version_spec  # Maintain backward compatibility

        def postinstall():
            return self.execute_install_script(packname, install_path, instant_execution=instant_execution, no_deps=no_deps)

        if return_postinstall:
            return result.with_postinstall(postinstall)
        else:
            if not postinstall():
                return result.fail(f"Failed to execute install script: {packname}@{version_spec}")

        return result

    def repo_install(self, url: str, repo_path: str, instant_execution=False, no_deps=False, return_postinstall=False):
        result = ManagedResult('install-git')
        result.append(url)

        if 'comfyui-manager' in url.lower():
            return result.fail(f"ignored: installing '{url}'")

        if not is_valid_url(url):
            return result.fail(f"Invalid git url: {url}")

        if url.endswith("/"):
            url = url[:-1]
        try:
            # Clone the repository from the remote URL
            clone_url = git_utils.get_url_for_clone(url)
            print(f"Download: git clone '{clone_url}'")

            if not instant_execution and platform.system() == 'Windows':
                res = manager_funcs.run_script([sys.executable, context.git_script_path, "--clone", get_default_custom_nodes_path(), clone_url, repo_path], cwd=get_default_custom_nodes_path())
                if res != 0:
                    return result.fail(f"Failed to clone repo: {clone_url}")
            else:
                repo = git.Repo.clone_from(clone_url, repo_path, recursive=True, progress=GitProgress())
                repo.git.clear_cache()
                repo.close()

            # Set target information for successful git installation
            result.target_path = repo_path
            result.target_version = 'nightly'  # Git installs are always nightly
            result.target = repo_path  # Maintain backward compatibility

            def postinstall():
                return self.execute_install_script(url, repo_path, instant_execution=instant_execution, no_deps=no_deps)

            if return_postinstall:
                return result.with_postinstall(postinstall)
            else:
                if not postinstall():
                    return result.fail(f"Failed to execute install script: {url}")

        except Exception as e:
            traceback.print_exc()
            return result.fail(f"Install(git-clone) error[2]: {url} / {e}")

        print("Installation was successful.")
        return result

    def repo_update(self, repo_path, instant_execution=False, no_deps=False, return_postinstall=False):
        result = ManagedResult('update-git')

        if not os.path.exists(os.path.join(repo_path, '.git')):
            return result.fail(f'Path not found: {repo_path}')

        # version check
        with git.Repo(repo_path) as repo:
            if repo.head.is_detached:
                if not switch_to_default_branch(repo):
                    return result.fail(f"Failed to switch to default branch: {repo_path}")

            current_branch = repo.active_branch
            branch_name = current_branch.name

            if current_branch.tracking_branch() is None:
                print(f"[ComfyUI-Manager] There is no tracking branch ({current_branch})")
                remote_name = get_remote_name(repo)
            else:
                remote_name = current_branch.tracking_branch().remote_name

            if remote_name is None:
                return result.fail(f"Failed to get remote when installing: {repo_path}")

            remote = repo.remote(name=remote_name)

            try:
                remote.fetch()
            except Exception as e:
                if 'detected dubious' in str(e):
                    print(f"[ComfyUI-Manager] Try fixing 'dubious repository' error on '{repo_path}' repository")
                    safedir_path = repo_path.replace('\\', '/')
                    subprocess.run(['git', 'config', '--global', '--add', 'safe.directory', safedir_path])
                    try:
                        remote.fetch()
                    except Exception:
                        print("\n[ComfyUI-Manager] Failed to fixing repository setup. Please execute this command on cmd: \n"
                              "-----------------------------------------------------------------------------------------\n"
                              f'git config --global --add safe.directory "{safedir_path}"\n'
                              "-----------------------------------------------------------------------------------------\n")

            commit_hash = repo.head.commit.hexsha
            if f'{remote_name}/{branch_name}' in repo.refs:
                remote_commit_hash = repo.refs[f'{remote_name}/{branch_name}'].object.hexsha
            else:
                return result.fail(f"Not updatable branch: {branch_name}")

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

    def unified_update(self, packname: str, instant_execution=False, no_deps=False, return_postinstall=False):
        orig_print(f"\x1b[2K\rUpdating: {packname}", end='')

        pack = self.get_active_pack(packname)

        if pack is None:
            return ManagedResult('update').fail(f"Update failed: '{packname}' is not installed.")

        if pack.is_nightly:
            return self.repo_update(pack.fullpath, instant_execution=instant_execution, no_deps=no_deps, return_postinstall=return_postinstall).with_target_version('nightly').with_ver('nightly')
        else:
            return self.cnr_switch_version(packname, instant_execution=instant_execution, no_deps=no_deps, return_postinstall=return_postinstall).with_ver('cnr')

    async def install_by_id(self, packname: str, version_spec=None, channel=None, mode=None, instant_execution=False, no_deps=False, return_postinstall=False):
        """
        1. If it is already installed and active, skip.
        2. If it is already installed but disabled, enable it.
        3. Otherwise, new installation
        4. Handle URL-like packnames for direct git installation
        """

        if 'comfyui-manager' in packname.lower():
            return ManagedResult('skip').fail(f"ignored: installing '{packname}'")

        # Parse packname if it contains @hash format (e.g., "NodeName@707779fb...")
        # Extract node name and git hash separately
        git_hash_for_checkout = None

        if '@' in packname and not self.is_url_like(packname):
            # Try to parse node spec
            node_spec = self.resolve_node_spec(packname)
            if node_spec is not None:
                parsed_name, parsed_version, is_specified = node_spec
                logging.debug(
                    "[ComfyUI-Manager] install_by_id parsed node spec: name=%s, version=%s",
                    parsed_name,
                    parsed_version
                )
                # If version looks like a git hash (40 hex chars), save it for checkout
                if parsed_version and len(parsed_version) == 40 and all(c in '0123456789abcdef' for c in parsed_version.lower()):
                    git_hash_for_checkout = parsed_version
                    packname = parsed_name  # Use just the node name for the rest of the logic
                    logging.debug(
                        "[ComfyUI-Manager] Detected git hash in packname: hash=%s, using node name=%s",
                        git_hash_for_checkout[:8],
                        packname
                    )

        # Handle URL-like packnames - prioritize CNR over direct git installation
        if self.is_url_like(packname):
            repo_name = os.path.basename(packname)
            if repo_name.endswith('.git'):
                repo_name = repo_name[:-4]
            
            # Check if this URL corresponds to a CNR-registered package
            try:
                compact_url = git_utils.compact_url(packname)
                cnr_package_info = cnr_utils.get_nodepack_by_url(compact_url)
            except Exception as e:
                print(f"[ComfyUI-Manager] Warning: Failed to lookup CNR package for URL '{packname}': {e}")
                cnr_package_info = None
            
            if cnr_package_info:
                # Package is registered in CNR - use CNR installation instead of direct git
                cnr_packname = cnr_package_info['id']
                print(f"[ComfyUI-Manager] URL '{packname}' corresponds to CNR package '{cnr_packname}', using CNR installation")
                
                if version_spec is None:
                    version_spec = 'nightly'

                return await self.install_by_id(
                    cnr_packname, 
                    version_spec='nightly', 
                    channel=channel, 
                    mode=mode, 
                    instant_execution=instant_execution, 
                    no_deps=no_deps, 
                    return_postinstall=return_postinstall
                )
            else:
                # Package not registered in CNR - proceed with direct git installation
                print(f"[ComfyUI-Manager] URL '{packname}' is not registered in CNR, attempting direct git installation")
                
                # Check security level for unregistered nodes
                current_security_level = get_config()['security_level']
                if current_security_level != SecurityLevel.weak.value:
                    return ManagedResult('fail').fail(f"Cannot install from URL '{packname}': security_level must be 'weak' for direct URL installation. Current level: {current_security_level}")
                
                repo_path = os.path.join(get_default_custom_nodes_path(), repo_name)
                result = self.repo_install(packname, repo_path, instant_execution=instant_execution, no_deps=no_deps, return_postinstall=return_postinstall)
                
                # Enhance result information to distinguish unregistered git installations
                if result.result:
                    result.action = 'install-git'  # Use standard action
                    result.target_path = repo_path  # Target path for unregistered installations
                    result.target_version = 'nightly'  # Version is nightly for direct git installs
                    result.target = repo_path  # Maintain backward compatibility
                    result.ver = 'nightly'
                
                return result

        # ensure target version
        if version_spec is None:
            if self.is_enabled(packname):
                # If git hash was specified but package is already enabled, check if we need to checkout
                if git_hash_for_checkout:
                    packs = self._get_packages_by_name_or_url(packname)
                    for pack in packs:
                        if pack.is_enabled and pack.is_nightly:
                            checkout_success = checkout_git_commit(pack.fullpath, git_hash_for_checkout)
                            if checkout_success:
                                logging.info(
                                    "[ComfyUI-Manager] Checked out commit %s for already-enabled %s",
                                    git_hash_for_checkout[:8],
                                    packname
                                )
                            return ManagedResult('skip')
                return ManagedResult('skip')
            elif self.is_disabled(packname):
                result = self.unified_enable(packname)
                # If git hash was specified and enable succeeded, checkout the hash
                if git_hash_for_checkout and result.result and result.target_path:
                    checkout_success = checkout_git_commit(result.target_path, git_hash_for_checkout)
                    if checkout_success:
                        logging.info(
                            "[ComfyUI-Manager] Checked out commit %s for %s",
                            git_hash_for_checkout[:8],
                            packname
                        )
                    else:
                        logging.warning(
                            "[ComfyUI-Manager] Enable succeeded but failed to checkout commit %s for %s",
                            git_hash_for_checkout[:8],
                            packname
                        )
                return result
            else:
                version_spec = self.resolve_unspecified_version(packname)

        # Reload to ensure we have current package state for is_enabled/is_disabled checks
        # This is needed because these checks look up existing installations
        self.reload()

        # Normalize packname for case-insensitive comparison with CNR packages
        # Do this BEFORE is_enabled/is_disabled checks so they can find CNR packages
        packname_for_checks = cnr_utils.normalize_package_name(packname)

        logging.debug(f"install_by_id: packname={packname}, version_spec={version_spec}, packname_for_checks={packname_for_checks}")

        # Check if the exact target version is already enabled - if so, skip
        if self.is_enabled(packname_for_checks, version_spec):
            logging.debug("install_by_id: package already enabled with target version, skipping")
            return ManagedResult('skip').with_target_version(version_spec)

        # IMPLICIT VERSION SWITCHING: Check if a different version is currently enabled
        # If so, switch to the requested version instead of failing
        active_pack = self.get_active_pack(packname_for_checks)
        logging.debug(f"install_by_id: active_pack={active_pack}")
        if active_pack is not None:
            # Check if the target version already exists (in disabled state)
            # If it does, we can do a simple switch. If not, we need to install it first.
            inactive_target = self.get_inactive_pack(packname_for_checks, version_spec)
            logging.debug(f"install_by_id: inactive_target={inactive_target}")

            if inactive_target is not None:
                # Target version exists in disabled state - we can switch directly
                logging.info(
                    f"Package '{packname_for_checks}' is already installed "
                    f"with version '{active_pack.version}', switching to version '{version_spec}'"
                )
                return self.switch_version(
                    packname_for_checks,
                    mode=version_spec,
                    instant_execution=instant_execution,
                    no_deps=no_deps,
                    return_postinstall=return_postinstall
                )
            else:
                # Target version doesn't exist yet - need to install it
                # The install flow will handle disabling the current version
                print(
                    f"[IMPLICIT-SWITCH-NOTICE] Package '{packname_for_checks}' version '{active_pack.version}' "
                    f"is enabled, but target version '{version_spec}' not found. Will install and switch."
                )
                # Continue to normal install flow below

        elif self.is_disabled(packname_for_checks, version_spec):
            # This ensures proper version switching for both Archive ↔ Nightly transitions
            # Disable any currently enabled version before enabling the requested version
            logging.debug(f"[DEBUG] install_by_id: enabling disabled package: {packname_for_checks}@{version_spec}")
            if self.is_enabled(packname_for_checks):
                logging.debug("[DEBUG] install_by_id: disabling currently enabled version first")
                self.unified_disable(packname_for_checks)

            return self.unified_enable(packname_for_checks, version_spec)

        # case: nightly
        if version_spec == 'nightly':
            pack_info = cnr_utils.get_nodepack(packname)

            if pack_info is None:
                return ManagedResult('fail').fail(f"'{packname}' is not a node pack registered in the registry.")

            repo_url = pack_info.get('repository')

            if repo_url is None:
                return ManagedResult('fail').fail(f"No nightly version available for installation for '{packname}'.")

            # Reload to ensure we have the latest package state before checking
            self.reload()

            # Normalize packname to lowercase for case-insensitive comparison
            # CNR packages are indexed with lowercase IDs from pyproject.toml
            packname_normalized = cnr_utils.normalize_package_name(packname)

            # ensure no active pack: disable any currently enabled version (CNR or Archive)
            if self.is_enabled(packname_normalized):
                self.unified_disable(packname_normalized)

            to_path = os.path.abspath(os.path.join(get_default_custom_nodes_path(), packname))
            res = self.repo_install(repo_url, to_path, instant_execution=instant_execution, no_deps=no_deps, return_postinstall=return_postinstall)

            if not res.result:
                return res

            return res.with_target_version(version_spec)

        # Normalize packname for case-insensitive comparison
        packname_normalized = cnr_utils.normalize_package_name(packname)

        # Reload to ensure we have current state before checking
        logging.debug("install_by_id: calling reload() to load current state")
        self.reload()
        logging.debug("install_by_id: reload() completed")

        # Disable ANY currently enabled version (CNR or Nightly) before installing new version
        # This ensures proper version switching for both Archive ↔ Nightly transitions
        # Must use _get_packages_by_name_or_url() to find both CNR and GitHub URL matches
        logging.debug(f"install_by_id: finding all enabled versions of '{packname_normalized}'")
        enabled_packages = self._get_packages_by_name_or_url(packname_normalized)
        logging.debug(f"install_by_id: found {len(enabled_packages)} enabled package(s)")

        for pkg in enabled_packages:
            if pkg.disabled:
                logging.debug(f"install_by_id: skipping disabled package id='{pkg.id}'")
                continue
            logging.debug(f"install_by_id: disabling enabled package id='{pkg.id}', version='{pkg.version}'")
            self.unified_disable(pkg.id)

        if enabled_packages:
            # Reload to update installed_node_packages after disabling
            logging.debug("install_by_id: calling reload() after disabling")
            self.reload()
            logging.debug("install_by_id: reload() completed")

        # Check if archive version exists in .disabled/ and validate it before restoring
        # This implements the fast toggle mechanism for CNR ↔ Nightly switching
        # is_disabled() already validates package type using reload() data
        logging.debug(f"install_by_id: checking is_disabled('{packname_normalized}', '{version_spec}')")
        disabled_result = self.is_disabled(packname_normalized, version_spec)
        logging.debug(f"install_by_id: is_disabled returned {disabled_result}")
        if disabled_result:
            return self.unified_enable(packname_normalized, version_spec)

        # No valid disabled package found, download fresh copy
        return self.cnr_install(packname, version_spec, instant_execution=instant_execution, no_deps=no_deps, return_postinstall=return_postinstall)


unified_manager = UnifiedManager()


def get_installed_nodepacks():
    res = {}
    # Track enabled package identities to prevent duplicates
    # Store both cnr_id and aux_id for cross-matching (CNR vs Nightly of same package)
    enabled_cnr_ids = set()  # CNR IDs of enabled packages
    enabled_aux_ids = set()  # GitHub aux_ids of enabled packages

    for x in get_custom_nodes_paths():
        # First pass: Add all enabled packages and track their identities
        for y in os.listdir(x):
            if y == '__pycache__' or y == '.disabled':
                continue

            fullpath = os.path.join(x, y)
            info = identify_node_pack_from_path(fullpath)
            if info is None:
                continue

            # Packages in custom_nodes/ (not in .disabled/) are always enabled
            is_enabled = True

            res[info[0]] = { 'ver': info[1], 'cnr_id': info[2], 'aux_id': info[4], 'enabled': is_enabled }

            # Track identities of enabled packages
            # info[2] = cnr_id (can be empty string for pure nightly)
            # info[4] = aux_id (GitHub repo for nightly)
            if info[2]:  # Has cnr_id
                enabled_cnr_ids.add(info[2].lower())
            if info[4]:  # Has aux_id (GitHub repo)
                enabled_aux_ids.add(info[4].lower())

        # Second pass: Add disabled packages only if no enabled version exists
        # When both are disabled, CNR takes priority over Nightly
        disabled_dirs = os.path.join(x, '.disabled')
        if os.path.exists(disabled_dirs):
            # Track disabled package identities to handle CNR vs Nightly priority
            disabled_cnr_ids = set()  # CNR IDs of disabled packages
            disabled_packages = []  # Store all disabled packages for priority sorting

            for y in os.listdir(disabled_dirs):
                if y == '__pycache__':
                    continue

                fullpath = os.path.join(disabled_dirs, y)
                info = identify_node_pack_from_path(fullpath)
                if info is None:
                    continue

                # Check if an enabled version of this package exists
                # Match by cnr_id OR aux_id to catch CNR vs Nightly of same package
                has_enabled_version = False

                if info[2] and info[2].lower() in enabled_cnr_ids:
                    # Same CNR package is enabled
                    has_enabled_version = True

                if info[4] and info[4].lower() in enabled_aux_ids:
                    # Same GitHub repo is enabled (Nightly)
                    has_enabled_version = True

                # For CNR packages, also check if enabled nightly exists from same repo
                # CNR packages have cnr_id but may not have aux_id
                # We need to derive aux_id from cnr_id to match against enabled nightlies
                if info[2] and not has_enabled_version:
                    # Check if any enabled aux_id matches this CNR's identity
                    # The aux_id pattern is typically "author/PackageName"
                    # The cnr_id is typically "PackageName"
                    cnr_id_lower = info[2].lower()
                    for aux_id in enabled_aux_ids:
                        # Check if this aux_id ends with the cnr_id
                        # e.g., "silveroxides/ComfyUI_SigmoidOffsetScheduler" matches "ComfyUI_SigmoidOffsetScheduler"
                        if aux_id.endswith('/' + cnr_id_lower) or aux_id.split('/')[-1].lower() == cnr_id_lower:
                            has_enabled_version = True
                            break

                if has_enabled_version:
                    # Skip this disabled version - an enabled version exists
                    continue

                # Store disabled package info for priority processing
                # Determine package type: CNR has cnr_id and aux_id=null, Nightly has aux_id
                is_cnr = bool(info[2] and not info[4])
                disabled_packages.append((info, is_cnr))

                if info[2]:
                    disabled_cnr_ids.add(info[2].lower())

            # Process disabled packages with CNR priority
            # When both CNR and Nightly disabled versions exist, show only CNR
            for info, is_cnr in disabled_packages:
                # Check if there's a disabled CNR version of this package
                has_disabled_cnr = False

                if not is_cnr and info[4]:
                    # This is a Nightly package, check if CNR version exists
                    # Extract package name from aux_id (e.g., "silveroxides/ComfyUI_SigmoidOffsetScheduler" -> "comfyui_sigmoidoffsetscheduler")
                    aux_id_lower = info[4].lower()
                    package_name = aux_id_lower.split('/')[-1] if '/' in aux_id_lower else aux_id_lower

                    # Check if this package name matches any disabled CNR
                    for cnr_id in disabled_cnr_ids:
                        if cnr_id == package_name or package_name.endswith('/' + cnr_id) or package_name.split('/')[-1] == cnr_id:
                            has_disabled_cnr = True
                            break

                if has_disabled_cnr:
                    # Skip this disabled Nightly - a disabled CNR version exists (CNR priority)
                    continue

                # Add disabled package to result
                res[info[0]] = { 'ver': info[1], 'cnr_id': info[2], 'aux_id': info[4], 'enabled': False }

    return res


def refresh_channel_dict():
    if channel_dict is None:
        get_channel_dict()
        

def get_channel_dict():
    global channel_dict
    global valid_channels

    if channel_dict is None:
        channel_dict = {}

        if not os.path.exists(context.manager_channel_list_path):
            shutil.copy(context.channel_list_template_path, context.manager_channel_list_path)

        with open(context.manager_channel_list_path, 'r') as file:
            channels = file.read()
            for x in channels.split('\n'):
                channel_info = x.split("::")
                if len(channel_info) == 2:
                    channel_dict[channel_info[0]] = channel_info[1]
                    valid_channels.add(channel_info[1])

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

    def run_script(self, cmd, cwd='.'):
        if len(cmd) > 0 and cmd[0].startswith("#"):
            print(f"[ComfyUI-Manager] Unexpected behavior: `{cmd}`")
            return 0

        subprocess.check_call(cmd, cwd=cwd, env=get_script_env())

        return 0


manager_funcs = ManagerFuncs()


def write_config():
    config = configparser.ConfigParser(strict=False)

    config['default'] = {
        'git_exe': get_config()['git_exe'],
        'use_uv': get_config()['use_uv'],
        'channel_url': get_config()['channel_url'],
        'share_option': get_config()['share_option'],
        'bypass_ssl': get_config()['bypass_ssl'],
        "file_logging": get_config()['file_logging'],
        'component_policy': get_config()['component_policy'],
        'update_policy': get_config()['update_policy'],
        'windows_selector_event_loop_policy': get_config()['windows_selector_event_loop_policy'],
        'model_download_by_agent': get_config()['model_download_by_agent'],
        'downgrade_blacklist': get_config()['downgrade_blacklist'],
        'security_level': get_config()['security_level'],
        'always_lazy_install': get_config()['always_lazy_install'],
        'network_mode': get_config()['network_mode'],
        'db_mode': get_config()['db_mode'],
    }

    directory = os.path.dirname(context.manager_config_path)
    if not os.path.exists(directory):
        os.makedirs(directory)

    with open(context.manager_config_path, 'w') as configfile:
        config.write(configfile)


def read_config():
    try:
        config = configparser.ConfigParser(strict=False)
        config.read(context.manager_config_path)
        default_conf = config['default']

        def get_bool(key, default_value):
            return default_conf[key].lower() == 'true' if key in default_conf else False

        manager_util.use_uv = default_conf['use_uv'].lower() == 'true' if 'use_uv' in default_conf else False
        manager_util.bypass_ssl = get_bool('bypass_ssl', False)

        return {
                    'http_channel_enabled': get_bool('http_channel_enabled', False),
                    'git_exe': default_conf.get('git_exe', ''),
                    'use_uv': get_bool('use_uv', True),
                    'channel_url': default_conf.get('channel_url', DEFAULT_CHANNEL),
                    'default_cache_as_channel_url': get_bool('default_cache_as_channel_url', False),
                    'share_option': default_conf.get('share_option', 'all').lower(),
                    'bypass_ssl': get_bool('bypass_ssl', False),
                    'file_logging': get_bool('file_logging', True),
                    'component_policy': default_conf.get('component_policy', 'workflow').lower(),
                    'update_policy': default_conf.get('update_policy', 'stable-comfyui').lower(),
                    'windows_selector_event_loop_policy': get_bool('windows_selector_event_loop_policy', False),
                    'model_download_by_agent': get_bool('model_download_by_agent', False),
                    'downgrade_blacklist': default_conf.get('downgrade_blacklist', '').lower(),
                    'always_lazy_install': get_bool('always_lazy_install', False),
                    'network_mode': default_conf.get('network_mode', NetworkMode.public.value).lower(),
                    'security_level': default_conf.get('security_level', SecurityLevel.normal.value).lower(),
                    'db_mode': default_conf.get('db_mode', 'cache').lower(), # backward compatibility
               }

    except Exception:
        import importlib.util
        # temporary disable `uv` on Windows by default (https://github.com/Comfy-Org/ComfyUI-Manager/issues/1969)
        manager_util.use_uv = importlib.util.find_spec("uv") is not None and platform.system() != "Windows"
        manager_util.bypass_ssl = False

        return {
            'http_channel_enabled': False,
            'git_exe': '',
            'use_uv': manager_util.use_uv,
            'channel_url': DEFAULT_CHANNEL,
            'default_cache_as_channel_url': False,
            'share_option': 'all',
            'bypass_ssl': manager_util.bypass_ssl,
            'file_logging': True,
            'component_policy': 'workflow',
            'update_policy': 'stable-comfyui',
            'windows_selector_event_loop_policy': False,
            'model_download_by_agent': False,
            'downgrade_blacklist': '',
            'always_lazy_install': False,
            'network_mode': NetworkMode.public.value,
            'security_level': SecurityLevel.normal.value,
            'db_mode': 'cache',
        }


def get_config():
    global cached_config

    if cached_config is None:
        cached_config = read_config()
        if cached_config['http_channel_enabled']:
            print("[ComfyUI-Manager] Warning: http channel enabled, make sure server in secure env")

    return cached_config


def get_remote_name(repo):
    available_remotes = [remote.name for remote in repo.remotes]
    if 'origin' in available_remotes:
        return 'origin'
    elif 'upstream' in available_remotes:
        return 'upstream'
    elif len(available_remotes) > 0:
        return available_remotes[0]

    if not available_remotes:
        print(f"[ComfyUI-Manager] No remotes are configured for this repository: {repo.working_dir}")
    else:
        print(f"[ComfyUI-Manager] Available remotes in '{repo.working_dir}': ")
        for remote in available_remotes:
            print(f"- {remote}")

    return None


def switch_to_default_branch(repo):
    remote_name = get_remote_name(repo)

    try:
        if remote_name is None:
            return False

        default_branch = repo.git.symbolic_ref(f'refs/remotes/{remote_name}/HEAD').replace(f'refs/remotes/{remote_name}/', '')
        repo.git.checkout(default_branch)
        return True
    except Exception:
        # try checkout master
        # try checkout main if failed
        try:
            repo.git.checkout(repo.heads.master)
            return True
        except Exception:
            try:
                if remote_name is not None:
                    repo.git.checkout('-b', 'master', f'{remote_name}/master')
                    return True
            except Exception:
                try:
                    repo.git.checkout(repo.heads.main)
                    return True
                except Exception:
                    try:
                        if remote_name is not None:
                            repo.git.checkout('-b', 'main', f'{remote_name}/main')
                            return True
                    except Exception:
                        pass

    print("[ComfyUI Manager] Failed to switch to the default branch")
    return False


def reserve_script(repo_path, install_cmds):
    if not os.path.exists(context.manager_startup_script_path):
        os.makedirs(context.manager_startup_script_path)

    script_path = os.path.join(context.manager_startup_script_path, "install-scripts.txt")
    with open(script_path, "a") as file:
        obj = [repo_path] + install_cmds
        file.write(f"{obj}\n")


def try_rmtree(title, fullpath):
    try:
        rmtree(fullpath)
    except Exception as e:
        logging.warning(f"[ComfyUI-Manager] An error occurred while deleting '{fullpath}', so it has been scheduled for deletion upon restart.\nEXCEPTION: {e}")
        reserve_script(title, ["#LAZY-DELETE-NODEPACK", fullpath])


def try_install_script(url, repo_path, install_cmd, instant_execution=False):
    if not instant_execution and (
            (len(install_cmd) > 0 and install_cmd[0].startswith('#')) or platform.system() == "Windows" or get_config()['always_lazy_install']
    ):
        reserve_script(repo_path, install_cmd)
        return True
    else:
        if len(install_cmd) == 5 and install_cmd[2:4] == ['pip', 'install']:
            if is_blacklisted(install_cmd[4]):
                print(f"[ComfyUI-Manager] skip black listed pip installation: '{install_cmd[4]}'")
                return True
        elif len(install_cmd) == 6 and install_cmd[3:5] == ['pip', 'install']:  # uv mode
            if is_blacklisted(install_cmd[5]):
                print(f"[ComfyUI-Manager] skip black listed pip installation: '{install_cmd[5]}'")
                return True

        print(f"\n## ComfyUI-Manager: EXECUTE => {install_cmd}")
        code = manager_funcs.run_script(install_cmd, cwd=repo_path)

        if platform.system() != "Windows":
            try:
                if not os.environ.get('__COMFYUI_DESKTOP_VERSION__') and comfy_ui_commit_datetime.date() < comfy_ui_required_commit_datetime.date():
                    print("\n\n###################################################################")
                    print(f"[WARN] ComfyUI-Manager: Your ComfyUI version ({comfy_ui_revision})[{comfy_ui_commit_datetime.date()}] is too old. Please update to the latest version.")
                    print("[WARN] The extension installation feature may not work properly in the current installed ComfyUI version on Windows environment.")
                    print("###################################################################\n\n")
            except Exception:
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
        command = [sys.executable, context.git_script_path, "--fetch", path]
    elif do_update:
        command = [sys.executable, context.git_script_path, "--pull", path]
    else:
        command = [sys.executable, context.git_script_path, "--check", path]

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
    command = [sys.executable, context.git_script_path, "--pull", path]
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
            pip_fixer = manager_util.PIPFixer(manager_util.get_installed_packages(), context.comfy_path, context.manager_files_path)
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
                            install_cmd = manager_util.make_pip_cmd(["install", s[0].strip(), '--index-url', s[1].strip()])
                        else:
                            install_cmd = manager_util.make_pip_cmd(["install", package_name])

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

        remote_name = get_remote_name(repo)

        if remote_name is None:
            raise ValueError(f"No remotes are configured for this repository: {path}")

        remote = repo.remote(name=remote_name)

        if not do_update and repo.head.is_detached:
            if do_fetch:
                remote.fetch()

            return True, True  # detached branch is treated as updatable

        if repo.head.is_detached:
            if not switch_to_default_branch(repo):
                raise ValueError(f"Failed to switch detached branch to default branch: {path}")

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
                if not switch_to_default_branch(repo):
                    raise ValueError(f"Failed to switch to default branch while updating: {path}")

                current_branch = repo.active_branch
                branch_name = current_branch.name

            if f'{remote_name}/{branch_name}' in repo.refs:
                remote_commit_hash = repo.refs[f'{remote_name}/{branch_name}'].object.hexsha
            else:
                return False, False

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

    def __call__(self, op_code: int, cur_count, max_count=None, message: str = '') -> None:
        self.update(op_code, cur_count, max_count, message)

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
            if not switch_to_default_branch(repo):
                raise ValueError(f"Failed to switch to default branch while pulling: {path}")

        current_branch = repo.active_branch
        remote_name = current_branch.tracking_branch().remote_name
        remote = repo.remote(name=remote_name)

        remote.pull()
        repo.git.submodule('update', '--init', '--recursive')

        repo.close()

    return True


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
                dir_name:str = os.path.splitext(os.path.basename(url))[0].replace(".git", "")
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


def update_to_stable_comfyui(repo_path):
    try:
        repo = git.Repo(repo_path)
        try:
            repo.git.checkout(repo.heads.master)
        except Exception:
            logging.error(f"[ComfyUI-Manager] Failed to checkout 'master' branch.\nrepo_path={repo_path}\nAvailable branches:")
            for branch in repo.branches:
                logging.error('\t'+branch.name)
            return "fail", None

        versions, current_tag, _ = get_comfyui_versions(repo)
        
        if len(versions) == 0 or (len(versions) == 1 and versions[0] == 'nightly'):
            logging.info("[ComfyUI-Manager] Unable to update to the stable ComfyUI version.")
            return "fail", None
            
        if versions[0] == 'nightly':
            latest_tag = versions[1]
        else:
            latest_tag = versions[0]

        if current_tag == latest_tag:
            return "skip", None
        else:
            logging.info(f"[ComfyUI-Manager] Updating ComfyUI: {current_tag} -> {latest_tag}")
            repo.git.checkout(latest_tag)
            return 'updated', latest_tag
    except Exception:
        traceback.print_exc()
        return "fail", None
            

def update_path(repo_path, instant_execution=False, no_deps=False):
    if not os.path.exists(os.path.join(repo_path, '.git')):
        return "fail"

    # version check
    repo = git.Repo(repo_path)

    is_switched = False
    if repo.head.is_detached:
        if not switch_to_default_branch(repo):
            return "fail"
        else:
            is_switched = True

    current_branch = repo.active_branch
    branch_name = current_branch.name

    if current_branch.tracking_branch() is None:
        print(f"[ComfyUI-Manager] There is no tracking branch ({current_branch})")
        remote_name = get_remote_name(repo)
    else:
        remote_name = current_branch.tracking_branch().remote_name
    remote = repo.remote(name=remote_name)

    try:
        remote.fetch()
    except Exception as e:
        if 'detected dubious' in str(e):
            print(f"[ComfyUI-Manager] Try fixing 'dubious repository' error on '{repo_path}' repository")
            safedir_path = repo_path.replace('\\', '/')
            subprocess.run(['git', 'config', '--global', '--add', 'safe.directory', safedir_path])
            try:
                remote.fetch()
            except Exception:
                print(f"\n[ComfyUI-Manager] Failed to fixing repository setup. Please execute this command on cmd: \n"
                      f"-----------------------------------------------------------------------------------------\n"
                      f'git config --global --add safe.directory "{safedir_path}"\n'
                      f"-----------------------------------------------------------------------------------------\n")
                return "fail"

    commit_hash = repo.head.commit.hexsha

    if f'{remote_name}/{branch_name}' in repo.refs:
        remote_commit_hash = repo.refs[f'{remote_name}/{branch_name}'].object.hexsha
    else:
        return "fail"

    if commit_hash != remote_commit_hash:
        git_pull(repo_path)
        execute_install_script("ComfyUI", repo_path, instant_execution=instant_execution, no_deps=no_deps)
        return "updated"
    elif is_switched:
        return "updated"
    else:
        return "skipped"


def simple_check_custom_node(url):
    dir_name = os.path.splitext(os.path.basename(url))[0].replace(".git", "")
    dir_path = os.path.join(get_default_custom_nodes_path(), dir_name)
    if os.path.exists(dir_path):
        return 'installed'
    elif os.path.exists(dir_path+'.disabled'):
        return 'disabled'

    return 'not-installed'


def get_installed_pip_packages():
    # extract pip package infos
    cmd = manager_util.make_pip_cmd(['freeze'])
    pips = subprocess.check_output(cmd, text=True).split('\n')

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


async def get_current_snapshot(custom_nodes_only = False):
    # Get ComfyUI hash
    repo_path = context.comfy_path

    comfyui_commit_hash = None
    if not custom_nodes_only:
        if os.path.exists(os.path.join(repo_path, '.git')):
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
                        commit_hash = git_utils.get_commit_hash(fullpath)
                        url = git_utils.git_url(fullpath)
                        git_custom_nodes[url] = dict(hash=commit_hash, disabled=is_disabled)
                except Exception:
                    print(f"Failed to extract snapshots for the custom node '{path}'.")

            elif path.endswith('.py'):
                is_disabled = path.endswith(".py.disabled")
                filename = os.path.basename(path)
                item = {
                    'filename': filename,
                    'disabled': is_disabled
                }

                file_custom_nodes.append(item)

    pip_packages = None if custom_nodes_only else get_installed_pip_packages()

    return {
        'comfyui': comfyui_commit_hash,
        'git_custom_nodes': git_custom_nodes,
        'cnr_custom_nodes': cnr_custom_nodes,
        'file_custom_nodes': file_custom_nodes,
        'pips': pip_packages,
    }


async def save_snapshot_with_postfix(postfix, path=None, custom_nodes_only = False):
    if path is None:
        now = datetime.now()

        date_time_format = now.strftime("%Y-%m-%d_%H-%M-%S")
        file_name = f"{date_time_format}_{postfix}"

        path = os.path.join(context.manager_snapshot_path, f"{file_name}.json")
    else:
        file_name = path.replace('\\', '/').split('/')[-1]
        file_name = file_name.split('.')[-2]

    snapshot = await get_current_snapshot(custom_nodes_only)
    if path.endswith('.json'):
        with open(path, "w") as json_file:
            json.dump(snapshot, json_file, indent=4)

        return file_name + '.json'

    elif path.endswith('.yaml'):
        with open(path, "w") as yaml_file:
            snapshot = {'custom_nodes': snapshot}
            yaml.dump(snapshot, yaml_file, allow_unicode=True)

        return path


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


def checkout_git_commit(repo_path, target_hash):
    """Checkout a specific commit in a git repository"""
    if not target_hash:
        return False
    
    try:
        import git
        with git.Repo(repo_path) as repo:
            current_hash = repo.head.commit.hexsha
            if current_hash != target_hash:
                print(f"[ComfyUI-Manager] Checkout: {os.path.basename(repo_path)} [{target_hash}]")
                repo.git.checkout(target_hash)
                return True
    except Exception as e:
        print(f"[ComfyUI-Manager] Warning: Failed to checkout commit {target_hash}: {e}")
        return False
    
    return False


def resolve_package_identifier(repo_url, cnr_lookup_cache):
    """Resolve package identifier from repository URL using CNR cache"""
    try:
        compact_url = git_utils.compact_url(repo_url)
        cnr_package_info = cnr_lookup_cache.get(compact_url)
        if cnr_package_info:
            return cnr_package_info['id']
    except Exception:
        pass  # If lookup fails, use compact URL
    
    return git_utils.compact_url(repo_url)


def handle_package_commit_checkout(packname, commit_hash, tracking_lists):
    """
    Handle git commit checkout for a package and update appropriate tracking lists
    
    Args:
        packname: Package name 
        commit_hash: Target commit hash (can be None)
        tracking_lists: Dictionary with lists for checkout_nodepacks, enabled_nodepacks, skip_nodepacks
        
    Returns:
        bool: True if checkout was performed, False otherwise
    """
    if not commit_hash:
        return False
        
    active_pack = unified_manager.get_active_pack(packname)
    if not active_pack:
        return False
        
    if checkout_git_commit(active_pack.fullpath, commit_hash):
        tracking_lists['checkout_nodepacks'].append(f"{packname}@{commit_hash}")
        return True
    else:
        return False


def process_git_restore_result(ps, packname, commit_hash, repo_url, tracking_lists):
    """
    Process git restoration result and update tracking lists accordingly
    
    Args:
        ps: ManagedResult object from installation/restoration operation
        packname: Package name
        commit_hash: Target commit hash (can be None)
        repo_url: Repository URL for error reporting
        tracking_lists: Dictionary containing all tracking lists
        
    Returns:
        bool: True if postinstall should be collected, False otherwise
    """
    if not ps.result:
        # Handle failed operations
        compact_url = git_utils.compact_url(repo_url)
        if ps.msg and 'security_level' in ps.msg:
            error_msg = f"{compact_url} (security: {ps.msg.split('Current level: ')[-1] if 'Current level:' in ps.msg else 'insufficient'})"
        else:
            error_msg = f"{compact_url} ({ps.action})"
        tracking_lists['failed'].append(error_msg)
        return False
    
    # Handle successful operations
    if ps.action == 'install-git':
        tracking_lists['cloned_nodepacks'].append(packname)
        
    elif ps.action == 'enable':
        # Enable case: always report as enabled regardless of commit changes
        if handle_package_commit_checkout(packname, commit_hash, tracking_lists):
            # Commit was changed, but still report as enabled since package was previously disabled
            tracking_lists['enabled_nodepacks'].append(packname)
        else:
            tracking_lists['enabled_nodepacks'].append(packname)
            
    elif ps.action == 'skip':
        # Skip case: package was already enabled, but may need commit checkout
        if handle_package_commit_checkout(packname, commit_hash, tracking_lists):
            # Commit was changed - this should NOT be treated as skip since work was done
            # The commit checkout already added to checkout_nodepacks, so no additional action needed
            pass
        else:
            # No commit change needed, truly a skip
            tracking_lists['skip_nodepacks'].append(packname)
            
    elif ps.action == 'update-git':
        if commit_hash and ps.target_path:
            if checkout_git_commit(ps.target_path, commit_hash):
                tracking_lists['checkout_nodepacks'].append(f"{packname}@{commit_hash}")
            else:
                tracking_lists['skip_nodepacks'].append(packname)
        else:
            tracking_lists['skip_nodepacks'].append(packname)
            
    else:
        # Handle unexpected action types
        print(f"[ComfyUI-Manager] Warning: Unexpected action type '{ps.action}' for {repo_url}")
        tracking_lists['skip_nodepacks'].append(packname)
    
    return True  # Collect postinstall for successful operations


def print_restore_summary(tracking_lists):
    """Print a summary of all restore operations"""
    summary_formats = [
        ('cloned_nodepacks', '[ INSTALLED (NIGHTLY) ]'),
        ('installed_nodepacks', '[ INSTALLED (CNR) ]'),
        ('checkout_nodepacks', '[  SWITCHED (NIGHTLY) ]'),
        ('switched_nodepacks', '[  SWITCHED (CNR) ]'),
        ('enabled_nodepacks', '[  ENABLED  ]'),
        ('disabled_cnr_nodepacks', '[ DISABLED (CNR) ]'),
        ('disabled_git_nodepacks', '[ DISABLED (NIGHTLY) ]'),
        ('skip_nodepacks', '[  SKIPPED  ]'),
        ('failed', '[  FAILED   ]'),
    ]
    
    for list_name, prefix in summary_formats:
        for item in tracking_lists.get(list_name, []):
            print(f"{prefix} {item}")


async def restore_snapshot(snapshot_path, git_helper_extras=None):
    # Initialize all tracking lists in a unified structure
    tracking_lists = {
        'cloned_nodepacks': [],
        'checkout_nodepacks': [],
        'enabled_nodepacks': [],
        'skip_nodepacks': [],
        'failed': [],
        'disabled_cnr_nodepacks': [],
        'disabled_git_nodepacks': [],
        'switched_nodepacks': [],
        'installed_nodepacks': []
    }

    print("Restore snapshot.")

    postinstalls = []

    with open(snapshot_path, 'r', encoding="UTF-8") as snapshot_file:
        if snapshot_path.endswith('.json'):
            info = json.load(snapshot_file)
        elif snapshot_path.endswith('.yaml'):
            info = yaml.load(snapshot_file, Loader=yaml.SafeLoader)
            info = info['custom_nodes']

        if 'pips' in info and info['pips']:
            pips = info['pips']
        else:
            pips = {}

        unified_manager.reload()

        # Disable nodes not in snapshot
        cnr_info = info.get('cnr_custom_nodes', {})
        git_info_raw = info.get('git_custom_nodes', {})
        
        # Get all node IDs that should exist after restore
        snapshot_cnr_ids = set(cnr_info.keys())  # CNR packages from snapshot
        snapshot_git_ids = set()  # Git packages from snapshot
        
        # Cache CNR lookups to avoid duplicate calls during installation
        cnr_lookup_cache = {}
        
        # Add git repository node names to snapshot set
        for repo_url in git_info_raw.keys():
            compact_url = git_utils.compact_url(repo_url)
            
            # First check if it's an installed nightly package
            if compact_url in unified_manager.repo_nodepack_map:
                node_package = unified_manager.repo_nodepack_map[compact_url]
                # Only add to git_ids if not already in CNR
                if node_package.id not in snapshot_cnr_ids:
                    snapshot_git_ids.add(node_package.id)
                # Cache the lookup for later use
                cnr_lookup_cache[compact_url] = {'id': node_package.id}
            else:
                # For uninstalled packages, query CNR to get packname
                nodepack_info = cnr_utils.get_nodepack_by_url(compact_url)
                if nodepack_info:
                    # Only add to git_ids if not already in CNR
                    if nodepack_info['id'] not in snapshot_cnr_ids:
                        snapshot_git_ids.add(nodepack_info['id'])
                # Cache the lookup result (whether successful or None)
                cnr_lookup_cache[compact_url] = nodepack_info
        
        # Combine both sets for node disabling logic
        snapshot_packnames = snapshot_cnr_ids | snapshot_git_ids
        # Disable all currently enabled nodes that are not in snapshot
        all_installed_packages = set(unified_manager.installed_node_packages.keys())
        for packname in all_installed_packages:
            if 'comfyui-manager' in packname:
                continue
                
            if packname not in snapshot_packnames:
                if unified_manager.is_enabled(packname):
                    unified_manager.unified_disable(packname)
                    
                    # Check if it's a CNR or git package for separate reporting
                    node_packages = unified_manager.installed_node_packages[packname]
                    is_cnr_package = any(x.is_from_cnr for x in node_packages)
                    
                    if is_cnr_package:
                        tracking_lists['disabled_cnr_nodepacks'].append(packname)
                    else:
                        tracking_lists['disabled_git_nodepacks'].append(packname)

        # CNR restore - install/switch packages from snapshot
        if cnr_info:
            for k, v in cnr_info.items():
                if 'comfyui-manager' in k:
                    continue

                ps = await unified_manager.install_by_id(k, version_spec=v, instant_execution=True, return_postinstall=True)
                if ps.action == 'install-cnr' and ps.result:
                    tracking_lists['installed_nodepacks'].append(f"{k}@{v}")
                elif ps.action == 'switch-cnr' and ps.result:
                    tracking_lists['switched_nodepacks'].append(f"{k}@{v}")
                elif ps.action == 'enable' and ps.result:
                    tracking_lists['enabled_nodepacks'].append(f"{k}@{v}")
                elif ps.action == 'skip':
                    tracking_lists['skip_nodepacks'].append(f"{k}@{v}")
                elif not ps.result:
                    tracking_lists['failed'].append(f"{k}@{v}")

                if ps is not None and ps.result:
                    if hasattr(ps, 'postinstall'):
                        postinstalls.append(ps.postinstall)
                    else:
                        print("cm-cli: unexpected [0001]")

        # Git(nightly) restore - handle nightly installations
        _git_info = info.get('git_custom_nodes')
        if _git_info:
            git_info = {}
            
            # normalize github repo URLs
            for k, v in _git_info.items():
                if 'comfyui-manager' in k.lower():
                    continue

                norm_k = git_utils.normalize_url(k)
                git_info[norm_k] = v

            # Use existing tracking_lists dictionary for helper functions
            
            # Install/restore git repositories using install_by_id with 'nightly'
            for repo_url, repo_info in git_info.items():
                commit_hash = repo_info.get('hash')
                
                # Resolve package identifier using cached lookup
                packname = resolve_package_identifier(repo_url, cnr_lookup_cache)
                
                # Install as nightly using the repository URL directly
                ps = await unified_manager.install_by_id(repo_url, version_spec='nightly', instant_execution=True, return_postinstall=True)
                
                # Handle post-installation commit switching for new installations
                if ps.result and ps.action == 'install-git' and commit_hash and ps.target_path:
                    if checkout_git_commit(ps.target_path, commit_hash):
                        tracking_lists['checkout_nodepacks'].append(f"{packname}@{commit_hash}")
                
                # Process results using unified handler
                should_collect_postinstall = process_git_restore_result(ps, packname, commit_hash, repo_url, tracking_lists)

                # Collect postinstall for successful operations
                if should_collect_postinstall and ps is not None and hasattr(ps, 'postinstall'):
                    postinstalls.append(ps.postinstall)

    manager_util.restore_pip_snapshot(pips, git_helper_extras)
    
    # Execute all collected postinstall functions
    for postinstall in postinstalls:
        try:
            postinstall()
        except Exception as e:
            print(f"[ComfyUI-Manager] Warning: postinstall failed: {e}")

    # Print comprehensive summary using helper function
    summary_data = {
        'cloned_nodepacks': tracking_lists['cloned_nodepacks'],
        'installed_nodepacks': tracking_lists['installed_nodepacks'],
        'checkout_nodepacks': tracking_lists['checkout_nodepacks'],
        'switched_nodepacks': tracking_lists['switched_nodepacks'],
        'enabled_nodepacks': tracking_lists['enabled_nodepacks'],
        'disabled_cnr_nodepacks': tracking_lists['disabled_cnr_nodepacks'],
        'disabled_git_nodepacks': tracking_lists['disabled_git_nodepacks'],
        'skip_nodepacks': tracking_lists['skip_nodepacks'],
        'failed': tracking_lists['failed'],
    }
    print_restore_summary(summary_data)


def get_comfyui_versions(repo=None):
    if repo is None:
        repo = git.Repo(context.comfy_path)

    try:
        remote = get_remote_name(repo)   
        repo.remotes[remote].fetch()    
    except Exception:
        logging.error("[ComfyUI-Manager] Failed to fetch ComfyUI")

    versions = [x.name for x in repo.tags if x.name.startswith('v')]

    # nearest tag
    versions = sorted(versions, key=lambda v: repo.git.log('-1', '--format=%ct', v), reverse=True)
    versions = versions[:4]

    current_tag = repo.git.describe('--tags')

    if current_tag not in versions:
        versions = sorted(versions + [current_tag], key=lambda v: repo.git.log('-1', '--format=%ct', v), reverse=True)
        versions = versions[:4]

    main_branch = repo.heads.master
    latest_commit = main_branch.commit
    latest_tag = repo.git.describe('--tags', latest_commit.hexsha)

    if latest_tag != versions[0]:
        versions.insert(0, 'nightly')
    else:
        versions[0] = 'nightly'
        current_tag = 'nightly'

    return versions, current_tag, latest_tag


def switch_comfyui(tag):
    repo = git.Repo(context.comfy_path)

    if tag == 'nightly':
        repo.git.checkout('master')
        tracking_branch = repo.active_branch.tracking_branch()
        remote_name = tracking_branch.remote_name
        repo.remotes[remote_name].pull()
        print("[ComfyUI-Manager] ComfyUI version is switched to the latest 'master' version")
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

    config = configparser.ConfigParser(strict=False)
    config.read(git_config_path)

    for k, v in config.items():
        if k.startswith('remote ') and 'url' in v:
            return v['url'].replace("git@github.com:", "https://github.com/")

    return None


