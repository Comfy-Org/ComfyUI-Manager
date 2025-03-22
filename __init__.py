import os
import sys

cli_mode_flag = os.path.join(os.path.dirname(__file__), '.enable-cli-only-mode')

if not os.path.exists(cli_mode_flag):
    sys.path.append(os.path.join(os.path.dirname(__file__), "glob"))
    import manager_server  # noqa: F401
    import share_3rdparty  # noqa: F401
    import cm_global

    if not cm_global.disable_front and not 'DISABLE_COMFYUI_MANAGER_FRONT' in os.environ:
        WEB_DIRECTORY = "js"
else:
    print("\n[ComfyUI-Manager] !! cli-only-mode is enabled !!\n")

NODE_CLASS_MAPPINGS = {}
__all__ = ['NODE_CLASS_MAPPINGS']



