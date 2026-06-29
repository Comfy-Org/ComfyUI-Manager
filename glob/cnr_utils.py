import asyncio
import json
import os
import platform
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List
from urllib.parse import urlencode

import logging
import manager_core
import manager_util
import requests
import toml

base_url = "https://api.comfy.org"


lock = asyncio.Lock()

is_cache_loading = False

async def get_cnr_data(sync_mode=None, dont_wait=True, **kwargs):
    # For backwards compatibility with keyword argument cache_mode
    if sync_mode is None:
        sync_mode = kwargs.get('cache_mode', 'cache')
    try:
        return await _get_cnr_data(sync_mode, dont_wait)
    except asyncio.TimeoutError:
        logging.error(f"[ComfyUI-Manager] A timeout occurred during the fetch process from ComfyRegistry.")
        return await _get_cnr_data(sync_mode='cache', dont_wait=True)  # timeout fallback

def get_comfyui_ver():
    is_desktop = bool(os.environ.get('__COMFYUI_DESKTOP_VERSION__'))
    if is_desktop:
        return manager_core.get_current_comfyui_ver() or 'unknown'
    else:
        return manager_core.get_comfyui_tag() or 'unknown'


def get_form_factor():
    is_desktop = bool(os.environ.get('__COMFYUI_DESKTOP_VERSION__'))
    system = platform.system().lower()
    is_windows = system == 'windows'
    is_mac = system == 'darwin'
    is_linux = system == 'linux'

    if is_desktop:
        if is_windows:
            return 'desktop-win'
        elif is_mac:
            return 'desktop-mac'
        else:
            return 'other'
    else:
        if is_windows:
            return 'git-windows'
        elif is_mac:
            return 'git-mac'
        elif is_linux:
            return 'git-linux'
        else:
            return 'other'


def get_node_timestamp(node):
    latest_ver = node.get('latest_version')
    if isinstance(latest_ver, dict):
        t = latest_ver.get('createdAt')
        if t:
            return t
    return node.get('created_at')


async def _get_cnr_data(sync_mode=None, dont_wait=True, **kwargs):
    global is_cache_loading

    # For backwards compatibility with keyword argument cache_mode
    if sync_mode is None:
        sync_mode = kwargs.get('cache_mode', 'cache')

    # Normalize sync_mode for backwards compatibility
    if sync_mode is True or sync_mode == 'cache' or sync_mode == 'local':
        normalized_mode = 'cache'
    elif sync_mode == 'force':
        normalized_mode = 'force'
    else:
        normalized_mode = 'remote'

    uri = f'{base_url}/nodes'
    cache_path = manager_util.get_cache_path(uri)

    comfyui_ver = get_comfyui_ver()
    form_factor = get_form_factor()

    cached_data = None
    last_updated = None
    full_nodes = {}
    is_cache_expired = True
    cache_built_at = None
    cache_created_at = None

    if normalized_mode != 'force' and manager_util.get_cache_state(uri, expired_days=None) == 'cached':
        try:
            with open(cache_path, 'r', encoding="UTF-8", errors="ignore") as json_file:
                cached_data = json.load(json_file)

            if (cached_data.get('comfyui_ver') == comfyui_ver and
                    cached_data.get('form_factor') == form_factor):
                last_updated = cached_data.get('last_updated')
                cache_created_at = cached_data.get('cache_created_at')
                for node in cached_data.get('nodes', []):
                    full_nodes[node['id']] = node
            else:
                logging.info("[ComfyUI-Manager] Environment change detected. Invalidating local ComfyRegistry cache.")
                cached_data = None
                full_nodes = {}
                last_updated = None
        except Exception as e:
            logging.error(f"[ComfyUI-Manager] Failed to read cached data: {e}")
            cached_data = None
            full_nodes = {}
            last_updated = None

    # Separate cache expiration check (1-day period)
    if cached_data is not None:
        cache_built_at = cached_data.get('cache_built_at')
        if cache_built_at:
            try:
                built_dt = datetime.fromisoformat(cache_built_at.replace('Z', '+00:00'))
                current_dt = datetime.now(timezone.utc)
                delta_dt = current_dt - built_dt
                if timedelta(seconds=0) <= delta_dt and delta_dt < timedelta(days=1):
                    is_cache_expired = False
            except Exception:
                pass

    if normalized_mode == 'cache':
        is_cache_loading = True

        if dont_wait:
            is_cache_loading = False
            if cached_data is not None:
                return cached_data.get('nodes', [])
            return []

        if cached_data is not None and (sync_mode == 'local' or not is_cache_expired):
            is_cache_loading = False
            return cached_data.get('nodes', [])

    async def fetch_all(timestamp_filter, existing_nodes):
        remained = True
        page = 1
        nodes_map = dict(existing_nodes)

        while remained:
            params = {
                'page': page,
                'limit': 30,
                'comfyui_version': comfyui_ver,
                'form_factor': form_factor,
            }
            if timestamp_filter:
                params['timestamp'] = timestamp_filter
            sub_uri = f'{base_url}/nodes?{urlencode(params)}'

            sub_json_obj = await asyncio.wait_for(
                manager_util.get_data_with_cache(sub_uri, cache_mode=False, silent=True, dont_cache=True),
                timeout=30
            )
            remained = page < sub_json_obj['totalPages']

            for x in sub_json_obj['nodes']:
                nodes_map[x['id']] = x

            if page % 5 == 0:
                logging.info(f"[ComfyUI-Manager] FETCH ComfyRegistry Data: {page}/{sub_json_obj['totalPages']}")

            page += 1
            await asyncio.sleep(0.5)

        logging.info(f"[ComfyUI-Manager] FETCH ComfyRegistry Data [DONE]")

        for v in nodes_map.values():
            if 'latest_version' not in v:
                v['latest_version'] = dict(version='nightly')

        return {'nodes': list(nodes_map.values())}

    try:
        json_obj = await fetch_all(last_updated, full_nodes)

        # Set cache's timestamp as the maximum timestamp from fetched nodes.
        # This way, in the next run, only the latest updates will be fetched.
        timestamps = [get_node_timestamp(node) for node in json_obj['nodes'] if get_node_timestamp(node)]
        max_timestamp = max(timestamps) if timestamps else None

        timestamp_format = "%Y-%m-%dT%H:%M:%SZ"

        if max_timestamp:
            try:
                ts_str = max_timestamp.replace('Z', '+00:00')
                dt = datetime.fromisoformat(ts_str) - timedelta(seconds=10)
                new_timestamp = dt.strftime(timestamp_format)
            except Exception:
                new_timestamp = max_timestamp
        else:
            new_timestamp = last_updated

        if is_cache_expired or normalized_mode == 'force' or not cache_built_at:
            new_cache_built_at = datetime.now(timezone.utc).strftime(timestamp_format)
        else:
            new_cache_built_at = cache_built_at

        if normalized_mode == 'force' or not cache_created_at:
            new_cache_created_at = datetime.now(timezone.utc).strftime(timestamp_format)
        else:
            new_cache_created_at = cache_created_at

        cache_to_save = {
            'nodes': json_obj['nodes'],
            'comfyui_ver': comfyui_ver,
            'form_factor': form_factor,
            'last_updated': new_timestamp,
            'cache_built_at': new_cache_built_at,
            'cache_created_at': new_cache_created_at
        }
        manager_util.save_to_cache(uri, cache_to_save)
        return json_obj['nodes']
    except asyncio.TimeoutError:
        raise
    except Exception as e:
        logging.error(f"[ComfyUI-Manager] Cannot connect to comfyregistry or failed sync: {e}")
        if cached_data is not None:
            return cached_data.get('nodes', [])
        return []
    finally:
        if normalized_mode == 'cache':
            is_cache_loading = False


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
        logging.error(f"[ComfyUI-Manager] unable to create file: {cnr_id_path}")


def read_cnr_id(fullpath):
    cnr_id_path = os.path.join(fullpath, '.git', '.cnr-id')
    try:
        if os.path.exists(cnr_id_path):
            with open(cnr_id_path) as f:
                return f.read().strip()
    except:
        pass

    return None

