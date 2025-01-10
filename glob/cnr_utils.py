import requests
from dataclasses import dataclass
from typing import List
import manager_util
import toml
import os

base_url = "https://api.comfy.org"


async def get_cnr_data(page=1, limit=1000, cache_mode=True):
    try:
        uri = f'{base_url}/nodes?page={page}&limit={limit}'
        json_obj = await manager_util.get_data_with_cache(uri, cache_mode=cache_mode)

        for v in json_obj['nodes']:
            if 'latest_version' not in v:
                v['latest_version'] = dict(version='nightly')

        return json_obj['nodes']
    except:
        res = {}
        print("Cannot connect to comfyregistry.")

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

    response = requests.get(url)
    if response.status_code == 200:
        # Convert the API response to a NodeVersion object
        return map_node_version(response.json())
    else:
        return None


def all_versions_of_node(node_id):
    url = f"https://api.comfy.org/nodes/{node_id}/versions?statuses=NodeVersionStatusActive&statuses=NodeVersionStatusPending"

    response = requests.get(url)
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
            name = project.get('name')
            version = project.get('version')

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

