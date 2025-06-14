import os
import logging
import folder_paths

from comfyui_manager.glob import manager_core as core
from comfyui_manager.glob.constants import model_dir_name_map


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
