import os
import logging
from comfy.cli_args import args

def prestartup():
    from . import prestartup_script  # noqa: F401
    logging.info('[PRE] ComfyUI-Manager')


def start():
    logging.info('[START] ComfyUI-Manager')
    from .common import cm_global     # noqa: F401

    if not args.disable_manager:
        if args.enable_manager_legacy_ui:
            try:
                from .legacy import manager_server  # noqa: F401
                from .legacy import share_3rdparty  # noqa: F401
                import nodes

                logging.info("[ComfyUI-Manager] Legacy UI is enabled.")
                nodes.EXTENSION_WEB_DIRS['comfyui-manager-legacy'] = os.path.join(os.path.dirname(__file__), 'js')
            except Exception as e:
                print("Error enabling legacy ComfyUI Manager frontend:", e)
        else:
            from .glob import manager_server  # noqa: F401
            from .glob import share_3rdparty  # noqa: F401


def should_be_disabled(fullpath:str) -> bool:
    """
    1. Disables the legacy ComfyUI-Manager.
    2. The blocklist can be expanded later based on policies.
    """

    if not args.disable_manager:
        # In cases where installation is done via a zip archive, the directory name may not be comfyui-manager, and it may not contain a git repository.
        # It is assumed that any installed legacy ComfyUI-Manager will have at least 'comfyui-manager' in its directory name.
        dir_name = os.path.basename(fullpath).lower()
        if 'comfyui-manager' in dir_name:
            return True

    return False
