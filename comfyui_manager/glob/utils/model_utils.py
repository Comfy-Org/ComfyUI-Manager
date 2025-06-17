import os
import logging
import concurrent.futures
import folder_paths

from comfyui_manager.glob import manager_core as core
from comfyui_manager.glob.constants import model_dir_name_map, MODEL_DIR_NAMES


def get_model_dir(data, show_log=False):
    if "download_model_base" in folder_paths.folder_names_and_paths:
        models_base = folder_paths.folder_names_and_paths["download_model_base"][0][0]
    else:
        models_base = folder_paths.models_dir

    # NOTE: Validate to prevent path traversal.
    if any(char in data["filename"] for char in {"/", "\\", ":"}):
        return None

    def resolve_custom_node(save_path):
        save_path = save_path[13:]  # remove 'custom_nodes/'

        # NOTE: Validate to prevent path traversal.
        if save_path.startswith(os.path.sep) or ":" in save_path:
            return None

        repo_name = save_path.replace("\\", "/").split("/")[
            0
        ]  # get custom node repo name

        # NOTE: The creation of files within the custom node path should be removed in the future.
        repo_path = core.lookup_installed_custom_nodes_legacy(repo_name)
        if repo_path is not None and repo_path[0]:
            # Returns the retargeted path based on the actually installed repository
            return os.path.join(os.path.dirname(repo_path[1]), save_path)
        else:
            return None

    if data["save_path"] != "default":
        if ".." in data["save_path"] or data["save_path"].startswith("/"):
            if show_log:
                logging.info(
                    f"[WARN] '{data['save_path']}' is not allowed path. So it will be saved into 'models/etc'."
                )
            base_model = os.path.join(models_base, "etc")
        else:
            if data["save_path"].startswith("custom_nodes"):
                base_model = resolve_custom_node(data["save_path"])
                if base_model is None:
                    if show_log:
                        logging.info(
                            f"[ComfyUI-Manager] The target custom node for model download is not installed: {data['save_path']}"
                        )
                    return None
            else:
                base_model = os.path.join(models_base, data["save_path"])
    else:
        model_dir_name = model_dir_name_map.get(data["type"].lower())
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
        if data["filename"] == "<huggingface>":
            return os.path.join(base_model, os.path.basename(data["url"]))
        else:
            return os.path.join(base_model, data["filename"])


def check_model_installed(json_obj):
    def is_exists(model_dir_name, filename, url):
        if filename == "<huggingface>":
            filename = os.path.basename(url)

        dirs = folder_paths.get_folder_paths(model_dir_name)

        for x in dirs:
            if os.path.exists(os.path.join(x, filename)):
                return True

        return False

    total_models_files = set()
    for x in MODEL_DIR_NAMES:
        for y in folder_paths.get_filename_list(x):
            total_models_files.add(y)

    def process_model_phase(item):
        if (
            "diffusion" not in item["filename"]
            and "pytorch" not in item["filename"]
            and "model" not in item["filename"]
        ):
            # non-general name case
            if item["filename"] in total_models_files:
                item["installed"] = "True"
                return

        if item["save_path"] == "default":
            model_dir_name = model_dir_name_map.get(item["type"].lower())
            if model_dir_name is not None:
                item["installed"] = str(
                    is_exists(model_dir_name, item["filename"], item["url"])
                )
            else:
                item["installed"] = "False"
        else:
            model_dir_name = item["save_path"].split("/")[0]
            if model_dir_name in folder_paths.folder_names_and_paths:
                if is_exists(model_dir_name, item["filename"], item["url"]):
                    item["installed"] = "True"

            if "installed" not in item:
                if item["filename"] == "<huggingface>":
                    filename = os.path.basename(item["url"])
                else:
                    filename = item["filename"]

                fullpath = os.path.join(
                    folder_paths.models_dir, item["save_path"], filename
                )

                item["installed"] = "True" if os.path.exists(fullpath) else "False"

    with concurrent.futures.ThreadPoolExecutor(8) as executor:
        for item in json_obj["models"]:
            executor.submit(process_model_phase, item)


async def check_whitelist_for_model(item):
    from comfyui_manager.data_models import ManagerDatabaseSource
    
    json_obj = await core.get_data_by_mode(ManagerDatabaseSource.cache.value, "model-list.json")

    for x in json_obj.get("models", []):
        if (
            x["save_path"] == item["save_path"]
            and x["base"] == item["base"]
            and x["filename"] == item["filename"]
        ):
            return True

    json_obj = await core.get_data_by_mode(ManagerDatabaseSource.local.value, "model-list.json")

    for x in json_obj.get("models", []):
        if (
            x["save_path"] == item["save_path"]
            and x["base"] == item["base"]
            and x["filename"] == item["filename"]
        ):
            return True

    return False
