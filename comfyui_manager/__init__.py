import os
import logging
from aiohttp import web
from .common.manager_security import HANDLER_POLICY
from .common import manager_security
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
                from .legacy import manager_core as core
                import nodes

                logging.info("[ComfyUI-Manager] Legacy UI is enabled.")
                nodes.EXTENSION_WEB_DIRS['comfyui-manager-legacy'] = os.path.join(os.path.dirname(__file__), 'js')
            except Exception as e:
                print("Error enabling legacy ComfyUI Manager frontend:", e)
                core = None
        else:
            from .glob import manager_server  # noqa: F401
            from .glob import share_3rdparty  # noqa: F401
            from .glob import manager_core as core

        if core is not None:
            manager_security.is_personal_cloud_mode = core.get_config()['network_mode'].lower() == 'personal_cloud'


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


def get_client_ip(request):
    peername = request.transport.get_extra_info("peername")
    if peername is not None:
        host, port = peername
        return host
    
    return "unknown"


def create_middleware():
    connected_clients = set()
    is_local_mode = manager_security.is_loopback(args.listen)

    @web.middleware
    async def manager_middleware(request: web.Request, handler):
        nonlocal connected_clients

        # security policy for remote environments
        prev_client_count = len(connected_clients)
        client_ip = get_client_ip(request)
        connected_clients.add(client_ip)
        next_client_count = len(connected_clients)

        if prev_client_count == 1 and next_client_count > 1:
            manager_security.multiple_remote_alert()

        policy = manager_security.get_handler_policy(handler)
        is_banned = False

        # policy check
        if len(connected_clients) > 1:
            if is_local_mode:
                if HANDLER_POLICY.MULTIPLE_REMOTE_BAN_NON_LOCAL in policy:
                    is_banned = True
                if HANDLER_POLICY.MULTIPLE_REMOTE_BAN_NOT_PERSONAL_CLOUD in policy:
                    is_banned = not manager_security.is_personal_cloud_mode

        if HANDLER_POLICY.BANNED in policy:
            is_banned = True

        if is_banned:
            logging.warning(f"[Manager] Banning request from {client_ip}: {request.path}")
            response = web.Response(text="[Manager] This request is banned.", status=403)
        else:
            response: web.Response = await handler(request)

        return response

    return manager_middleware
    