import os
import git
import logging
import traceback

from comfyui_manager.common import context
import folder_paths
from comfy.cli_args import args
import latent_preview

from comfyui_manager.glob import manager_core as core
from comfyui_manager.common import cm_global


comfy_ui_hash = "-"
comfyui_tag = None


def print_comfyui_version():
    global comfy_ui_hash
    global comfyui_tag

    is_detached = False
    try:
        repo = git.Repo(os.path.dirname(folder_paths.__file__))
        core.comfy_ui_revision = len(list(repo.iter_commits("HEAD")))

        comfy_ui_hash = repo.head.commit.hexsha
        cm_global.variables["comfyui.revision"] = core.comfy_ui_revision

        core.comfy_ui_commit_datetime = repo.head.commit.committed_datetime
        cm_global.variables["comfyui.commit_datetime"] = core.comfy_ui_commit_datetime

        is_detached = repo.head.is_detached
        current_branch = repo.active_branch.name

        comfyui_tag = context.get_comfyui_tag()

        try:
            if (
                not os.environ.get("__COMFYUI_DESKTOP_VERSION__")
                and core.comfy_ui_commit_datetime.date()
                < core.comfy_ui_required_commit_datetime.date()
            ):
                logging.warning(
                    f"\n\n## [WARN] ComfyUI-Manager: Your ComfyUI version ({core.comfy_ui_revision})[{core.comfy_ui_commit_datetime.date()}] is too old. Please update to the latest version. ##\n\n"
                )
        except Exception:
            pass

        # process on_revision_detected -->
        if "cm.on_revision_detected_handler" in cm_global.variables:
            for k, f in cm_global.variables["cm.on_revision_detected_handler"]:
                try:
                    f(core.comfy_ui_revision)
                except Exception:
                    logging.error(f"[ERROR] '{k}' on_revision_detected_handler")
                    traceback.print_exc()

            del cm_global.variables["cm.on_revision_detected_handler"]
        else:
            logging.warning(
                "[ComfyUI-Manager] Some features are restricted due to your ComfyUI being outdated."
            )
        # <--

        if current_branch == "master":
            if comfyui_tag:
                logging.info(
                    f"### ComfyUI Version: {comfyui_tag} | Released on '{core.comfy_ui_commit_datetime.date()}'"
                )
            else:
                logging.info(
                    f"### ComfyUI Revision: {core.comfy_ui_revision} [{comfy_ui_hash[:8]}] | Released on '{core.comfy_ui_commit_datetime.date()}'"
                )
        else:
            if comfyui_tag:
                logging.info(
                    f"### ComfyUI Version: {comfyui_tag} on '{current_branch}' | Released on '{core.comfy_ui_commit_datetime.date()}'"
                )
            else:
                logging.info(
                    f"### ComfyUI Revision: {core.comfy_ui_revision} on '{current_branch}' [{comfy_ui_hash[:8]}] | Released on '{core.comfy_ui_commit_datetime.date()}'"
                )
    except Exception:
        if is_detached:
            logging.info(
                f"### ComfyUI Revision: {core.comfy_ui_revision} [{comfy_ui_hash[:8]}] *DETACHED | Released on '{core.comfy_ui_commit_datetime.date()}'"
            )
        else:
            logging.info(
                "### ComfyUI Revision: UNKNOWN (The currently installed ComfyUI is not a Git repository)"
            )


def set_preview_method(method):
    if method == "auto":
        args.preview_method = latent_preview.LatentPreviewMethod.Auto
    elif method == "latent2rgb":
        args.preview_method = latent_preview.LatentPreviewMethod.Latent2RGB
    elif method == "taesd":
        args.preview_method = latent_preview.LatentPreviewMethod.TAESD
    else:
        args.preview_method = latent_preview.LatentPreviewMethod.NoPreviews

    core.get_config()["preview_method"] = method


def set_update_policy(mode):
    core.get_config()["update_policy"] = mode


def set_db_mode(mode):
    core.get_config()["db_mode"] = mode


def setup_environment():
    git_exe = core.get_config()["git_exe"]

    if git_exe != "":
        git.Git().update_environment(GIT_PYTHON_GIT_EXECUTABLE=git_exe)


def initialize_environment():
    context.comfy_path = os.path.dirname(folder_paths.__file__)
    core.js_path = os.path.join(context.comfy_path, "web", "extensions")

    # Legacy database paths - kept for potential future use
    # local_db_model = os.path.join(manager_util.comfyui_manager_path, "model-list.json")
    # local_db_alter = os.path.join(manager_util.comfyui_manager_path, "alter-list.json")
    # local_db_custom_node_list = os.path.join(
    #     manager_util.comfyui_manager_path, "custom-node-list.json"
    # )
    # local_db_extension_node_mappings = os.path.join(
    #     manager_util.comfyui_manager_path, "extension-node-map.json"
    # )

    set_preview_method(core.get_config()["preview_method"])
    print_comfyui_version()
    setup_environment()

    core.check_invalid_nodes()
