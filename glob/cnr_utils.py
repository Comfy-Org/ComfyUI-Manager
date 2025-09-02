import asyncio
import json
import os
import platform
import time
from dataclasses import dataclass
from typing import List

import manager_core
import manager_util
import requests
import toml

base_url = "https://api.comfy.org"


lock = asyncio.Lock()

is_cache_loading = False

async def get_cnr_data(cache_mode=True, dont_wait=True):
    try:
        return await _get_cnr_data(cache_mode, dont_wait)
    except asyncio.TimeoutError:
        print("A timeout occurred during the fetch process from ComfyRegistry.")
        return await _get_cnr_data(cache_mode=True, dont_wait=True)  # timeout fallback

async def _get_cnr_data(cache_mode=True, dont_wait=True):
    global is_cache_loading

    uri = f'{base_url}/nodes'

    async def fetch_all():
        remained = True
        page = 1

        full_nodes = {}

        
        # Determine form factor based on environment and platform
        is_desktop = bool(os.environ.get('__COMFYUI_DESKTOP_VERSION__'))
        system = platform.system().lower()
        is_windows = system == 'windows'
        is_mac = system == 'darwin'
        is_linux = system == 'linux'

        # Get ComfyUI version tag
        if is_desktop:
            # extract version from pyproject.toml instead of git tag
            comfyui_ver = manager_core.get_current_comfyui_ver() or 'unknown'
        else:
            comfyui_ver = manager_core.get_comfyui_tag() or 'unknown'

        if is_desktop:
            if is_windows:
                form_factor = 'desktop-win'
            elif is_mac:
                form_factor = 'desktop-mac'
            else:
                form_factor = 'other'
        else:
            if is_windows:
                form_factor = 'git-windows'
            elif is_mac:
                form_factor = 'git-mac'
            elif is_linux:
                form_factor = 'git-linux'
            else:
                form_factor = 'other'
        
        while remained:
            # Add comfyui_version and form_factor to the API request
            sub_uri = f'{base_url}/nodes?page={page}&limit=30&comfyui_version={comfyui_ver}&form_factor={form_factor}'
            sub_json_obj = await asyncio.wait_for(manager_util.get_data_with_cache(sub_uri, cache_mode=False, silent=True, dont_cache=True), timeout=30)
            remained = page < sub_json_obj['totalPages']

            for x in sub_json_obj['nodes']:
                full_nodes[x['id']] = x

            if page % 5 == 0:
                print(f"FETCH ComfyRegistry Data: {page}/{sub_json_obj['totalPages']}")

            page += 1
            time.sleep(0.5)

        print("FETCH ComfyRegistry Data [DONE]")

        for v in full_nodes.values():
            if 'latest_version' not in v:
                v['latest_version'] = dict(version='nightly')

        return {'nodes': list(full_nodes.values())}

    if cache_mode:
        is_cache_loading = True
        cache_state = manager_util.get_cache_state(uri)

        if dont_wait:
            if cache_state == 'not-cached':
                return {}
            else:
                print("[ComfyUI-Manager] The ComfyRegistry cache update is still in progress, so an outdated cache is being used.")
                with open(manager_util.get_cache_path(uri), 'r', encoding="UTF-8", errors="ignore") as json_file:
                    return json.load(json_file)['nodes']

        if cache_state == 'cached':
            with open(manager_util.get_cache_path(uri), 'r', encoding="UTF-8", errors="ignore") as json_file:
                return json.load(json_file)['nodes']

    try:
        json_obj = await fetch_all()
        manager_util.save_to_cache(uri, json_obj)
        return json_obj['nodes']
    except:
        res = {}
        print("Cannot connect to comfyregistry.")
    finally:
        if cache_mode:
            is_cache_loading = False

    return res


@dataclass
class NodeVersion:
    changelog: str
    dependencies: List[str]
    deprecated: bool
    id: str
    version: str
    download_url: str


def map_node_version(api_node_version):
    """
    Maps node version data from API response to NodeVersion dataclass.

    Args:
        api_data (dict): The 'node_version' part of the API response.

    Returns:
        NodeVersion: An instance of NodeVersion dataclass populated with data from the API.
    """
    return NodeVersion(
        changelog=api_node_version.get(
            "changelog", ""
        ),  # Provide a default value if 'changelog' is missing
        dependencies=api_node_version.get(
            "dependencies", []
        ),  # Provide a default empty list if 'dependencies' is missing
        deprecated=api_node_version.get(
            "deprecated", False
        ),  # Assume False if 'deprecated' is not specified
        id=api_node_version[
            "id"
        ],  # 'id' should be mandatory; raise KeyError if missing
        version=api_node_version[
            "version"
        ],  # 'version' should be mandatory; raise KeyError if missing
        download_url=api_node_version.get(
            "downloadUrl", ""
        ),  # Provide a default value if 'downloadUrl' is missing
    )


def install_node(node_id, version=None):
    """
    Retrieves the node version for installation.

    Args:
      node_id (str): The unique identifier of the node.
      version (str, optional): Specific version of the node to retrieve. If omitted, the latest version is returned.

    Returns:
      NodeVersion: Node version data or error message.
    """
    if version is None:
        url = f"{base_url}/nodes/{node_id}/install"
    else:
        url = f"{base_url}/nodes/{node_id}/install?version={version}"

    response = requests.get(url, verify=not manager_util.bypass_ssl)
    if response.status_code == 200:
        # Convert the API response to a NodeVersion object
        return map_node_version(response.json())
    else:
        return None


def all_versions_of_node(node_id):
    url = f"{base_url}/nodes/{node_id}/versions?statuses=NodeVersionStatusActive&statuses=NodeVersionStatusPending"

    response = requests.get(url, verify=not manager_util.bypass_ssl)
    if response.status_code == 200:
        return response.json()
    else:
        return None


def read_cnr_info(fullpath):
    try:
        toml_path = os.path.join(fullpath, 'pyproject.toml')
        tracking_path = os.path.join(fullpath, '.tracking')

        if not os.path.exists(toml_path) or not os.path.exists(tracking_path):
            return None  # not valid CNR node pack

        with open(toml_path, "r", encoding="utf-8") as f:
            data = toml.load(f)

            project = data.get('project', {})
            name = project.get('name').strip().lower()

            # normalize version
            # for example: 2.5 -> 2.5.0
            version = str(manager_util.StrictVersion(project.get('version')))

            urls = project.get('urls', {})
            repository = urls.get('Repository')

            if name and version:  # repository is optional
                return {
                    "id": name,
                    "version": version,
                    "url": repository
                }

        return None
    except Exception:
        return None  # not valid CNR node pack


def generate_cnr_id(fullpath, cnr_id):
    cnr_id_path = os.path.join(fullpath, '.git', '.cnr-id')
    try:
        if not os.path.exists(cnr_id_path):
            with open(cnr_id_path, "w") as f:
                return f.write(cnr_id)
    except:
        print(f"[ComfyUI Manager] unable to create file: {cnr_id_path}")


def read_cnr_id(fullpath):
    cnr_id_path = os.path.join(fullpath, '.git', '.cnr-id')
    try:
        if os.path.exists(cnr_id_path):
            with open(cnr_id_path) as f:
                return f.read().strip()
    except:
        pass

    return None

