import asyncio
import json
import os
import platform
import time
from dataclasses import dataclass
from typing import List
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
import requests

import manager_core
import manager_util
import toml

base_url = "https://api.comfy.org"

memory_cache = {}  # In-memory cache for nodes and API responses
cnr_info_cache = {}  # Cache for read_cnr_info results

@lru_cache(maxsize=1)
def get_version_and_form_factor():
    """
    Get ComfyUI version and form factor once and cache result.

    Returns:
        tuple: (comfyui_version, form_factor)
    """
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
    
    return comfyui_ver, form_factor

def fetch_page(page, comfyui_ver, form_factor):
    """
    Fetch a single page from ComfyRegistry using requests.

    Args:
        page (int): Page number.
        comfyui_ver (str): ComfyUI version.
        form_factor (str): Form factor (e.g., desktop-win, git-linux).
    
    Returns:
        dict: Page data or None if failed.
    """
    # Add comfyui_version and form_factor to the API request
    sub_uri = f"{base_url}/nodes?page={page}&limit=30&comfyui_version={comfyui_ver}&form_factor={form_factor}"
    try:
        response = requests.get(sub_uri, timeout=10)
        if response.status_code == 200:
            return response.json()
        return None
    except Exception:
        return None

async def fetch_all(comfyui_ver, form_factor):
    """
    Fetch all nodes from ComfyRegistry using ThreadPoolExecutor.

    Args:
        comfyui_ver (str): ComfyUI version.
        form_factor (str): Form factor (e.g., desktop-win, git-linux).
    
    Returns:
        dict: Dictionary of nodes.
    """
    nodes = []
    first_page = fetch_page(1, comfyui_ver, form_factor)
    if not first_page:
        raise Exception("Failed to fetch first page")

    total_pages = first_page['totalPages']
    nodes.extend(first_page['nodes'])

    if total_pages > 1:
        with ThreadPoolExecutor(max_workers=10) as executor:
            tasks = [executor.submit(fetch_page, page, comfyui_ver, form_factor) 
                     for page in range(2, total_pages + 1)]
            for i, future in enumerate(tasks, 2):
                result = future.result()
                if result and 'nodes' in result:
                    nodes.extend(result['nodes'])
                if i % 50 == 0:  # Adjusted logging to reduce spam
                    print(f"FETCH ComfyRegistry Data: {i}/{total_pages}")

    print("FETCH ComfyRegistry Data [DONE]")

    for node in nodes:
        if 'latest_version' not in node:
            node['latest_version'] = dict(version='nightly')

    return {'nodes': nodes}

async def get_cnr_data(cache_mode=True, dont_wait=True):
    """
    Fetch or load cached ComfyRegistry data.

    Args:
        cache_mode (bool): Use cache if True.
        dont_wait (bool): Return immediately if cache is not ready.
    
    Returns:
        list: List of node data.
    """
    uri = f'{base_url}/nodes'
    
    if cache_mode:
        # Check memory cache first
        if uri in memory_cache:
            return memory_cache[uri]['nodes']
        
        cache_path = manager_util.get_cache_path(uri)
        if os.path.exists(cache_path):
            with open(cache_path, 'r', encoding="UTF-8", errors="ignore") as json_file:
                data = json.load(json_file)
                memory_cache[uri] = data
                return data['nodes']
        
        if dont_wait:
            print("[ComfyUI-Manager] The ComfyRegistry cache update is still in progress, so an outdated cache is being used.")
            return {}  # Return empty if no cache and dont_wait=True

    try:
        comfyui_ver, form_factor = get_version_and_form_factor()
        json_obj = await fetch_all(comfyui_ver, form_factor)
        manager_util.save_to_cache(uri, json_obj)
        memory_cache[uri] = json_obj
        return json_obj['nodes']
    except Exception as e:
        print(f"Cannot connect to ComfyRegistry: {e}")
        return {}

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
    cache_key = f"install_{node_id}_{version or 'latest'}"
    if cache_key in memory_cache:
        return memory_cache[cache_key]

    if version is None:
        url = f"{base_url}/nodes/{node_id}/install"
    else:
        url = f"{base_url}/nodes/{node_id}/install?version={version}"

    response = requests.get(url, timeout=10)
    if response.status_code == 200:
        # Convert the API response to a NodeVersion object
        data = response.json()
        result = map_node_version(data)
        memory_cache[cache_key] = result
        return result
    return None

def all_versions_of_node(node_id):
    """
    Fetch all versions of a node.

    Args:
        node_id (str): Node identifier.
    
    Returns:
        list: List of version data or None.
    """
    cache_key = f"versions_{node_id}"
    if cache_key in memory_cache:
        return memory_cache[cache_key]

    url = f"{base_url}/nodes/{node_id}/versions?statuses=NodeVersionStatusActive&statuses=NodeVersionStatusPending"
    response = requests.get(url, timeout=10)
    if response.status_code == 200:
        data = response.json()
        memory_cache[cache_key] = data
        return data
    return None

def read_cnr_info(fullpath):
    """
    Read CNR info from pyproject.toml and .tracking files.

    Args:
        fullpath (str): Path to node directory.
    
    Returns:
        dict: Node info or None if invalid.
    """
    if fullpath in cnr_info_cache:
        return cnr_info_cache[fullpath]

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
                result = {
                    "id": name,
                    "version": version,
                    "url": repository
                }
                cnr_info_cache[fullpath] = result
                return result

        return None
    except Exception:
        return None  # not valid CNR node pack

def generate_cnr_id(fullpath, cnr_id):
    """
    Generate .cnr-id file in the node's .git directory.

    Args:
        fullpath (str): Path to node directory.
        cnr_id (str): CNR ID to write.
    """
    cnr_id_path = os.path.join(fullpath, '.git', '.cnr-id')
    try:
        if not os.path.exists(cnr_id_path):
            with open(cnr_id_path, "w") as f:
                return f.write(cnr_id)
    except:
        print(f"[ComfyUI Manager] unable to create file: {cnr_id_path}")

def read_cnr_id(fullpath):
    """
    Read CNR ID from .cnr-id file in the node's .git directory.

    Args:
        fullpath (str): Path to node directory.
    
    Returns:
        str: CNR ID or None if not found.
    """
    cnr_id_path = os.path.join(fullpath, '.git', '.cnr-id')
    try:
        if os.path.exists(cnr_id_path):
            with open(cnr_id_path) as f:
                return f.read().strip()
    except:
        pass

    return None