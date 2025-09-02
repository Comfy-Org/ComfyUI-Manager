import sys
import os
import logging
from . import manager_util
import toml
import git


# read env vars
comfy_path: str = os.environ.get('COMFYUI_PATH')
comfy_base_path = os.environ.get('COMFYUI_FOLDERS_BASE_PATH')

if comfy_path is None:
    try:
        comfy_path = os.path.abspath(os.path.dirname(sys.modules['__main__'].__file__))
        os.environ['COMFYUI_PATH'] = comfy_path
    except Exception:
        logging.error("[ComfyUI-Manager] environment variable 'COMFYUI_PATH' is not specified.")
        exit(-1)

if comfy_base_path is None:
    comfy_base_path = comfy_path

channel_list_template_path = os.path.join(manager_util.comfyui_manager_path, 'channels.list.template')
git_script_path = os.path.join(manager_util.comfyui_manager_path, "git_helper.py")

manager_files_path = None
manager_config_path = None
manager_channel_list_path = None
manager_startup_script_path:str = None
manager_snapshot_path = None
manager_pip_overrides_path = None
manager_pip_blacklist_path = None
manager_components_path = None
manager_batch_history_path = None

def update_user_directory(user_dir):
    global manager_files_path
    global manager_config_path
    global manager_channel_list_path
    global manager_startup_script_path
    global manager_snapshot_path
    global manager_pip_overrides_path
    global manager_pip_blacklist_path
    global manager_components_path
    global manager_batch_history_path

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
    manager_pip_blacklist_path = os.path.join(manager_files_path, "pip_blacklist.list")
    manager_components_path = os.path.join(manager_files_path, "components")
    manager_util.cache_dir = os.path.join(manager_files_path, "cache")
    manager_batch_history_path = os.path.join(manager_files_path, "batch_history")

    if not os.path.exists(manager_util.cache_dir):
        os.makedirs(manager_util.cache_dir)

    if not os.path.exists(manager_batch_history_path):
        os.makedirs(manager_batch_history_path)

try:
    import folder_paths
    update_user_directory(folder_paths.get_user_directory())

except Exception:
    # fallback:
    # This case is only possible when running with cm-cli, and in practice, this case is not actually used.
    update_user_directory(os.path.abspath(manager_util.comfyui_manager_path))


def get_current_comfyui_ver():
    """
    Extract version from pyproject.toml
    """
    toml_path = os.path.join(comfy_path, 'pyproject.toml')
    if not os.path.exists(toml_path):
        return None
    else:
        try:
            with open(toml_path, "r", encoding="utf-8") as f:
                data = toml.load(f)

                project = data.get('project', {})
                return project.get('version')
        except Exception:
            return None


def get_comfyui_tag():
    try:
        with git.Repo(comfy_path) as repo:
            return repo.git.describe('--tags')
    except Exception:
        return None

