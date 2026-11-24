"""Security helpers for CSRF protection and Content-Type gating.

reject_non_json_post() is applied to every POST handler that changes something.
A page of another origin can make a browser send a POST without a CORS
preflight: as a form, or with no Content-Type at all, with or without a body.
``request.json()`` parses a body whatever its Content-Type. The page cannot
send ``application/json`` without a preflight.
"""

import logging
import os
from enum import Enum
from typing import Optional

from aiohttp import web

is_personal_cloud_mode = False
handler_policy = {}

FLAGGED_NODEPACK_WHITELIST_FILE = 'nodepack-whitelist.list'

FLAGGED_NODEPACK_INSTALL_ERROR = (
    'This action is not allowed by the current security configuration. '
    'See the terminal for details.'
)
FLAGGED_NODEPACK_INSTALL_GUIDANCE = (
    'Installation of this flagged CNR version is blocked. To satisfy the additional '
    'flagged-version requirement, choose one of the following:\n'
    '1. Run ComfyUI with loopback-only listeners, for example --listen 127.0.0.1 '
    'or --listen ::1. All configured listen addresses must be loopback.\n'
    '   Do not use bare --listen or any non-loopback address, such as 0.0.0.0 or ::.\n'
    '2. For a trusted private network, set allow_flagged_nodepack_install = true '
    'in the [default] section of ComfyUI-Manager\'s config.ini.\n'
    '3. To allow specific packs, add their Registry pack IDs (case-insensitive), one per line, '
    f'to {FLAGGED_NODEPACK_WHITELIST_FILE} beside ComfyUI-Manager\'s config.ini. '
    'Whitelist changes apply to subsequent installations without a restart.\n'
    'Restart ComfyUI after changing the listener or config.ini. '
    'All other installation security checks still apply.'
)


def reject_non_json_post(request) -> Optional[web.Response]:
    if request.content_type != 'application/json':
        return web.Response(
            status=400,
            text='Invalid Content-Type for this endpoint. Use application/json.',
        )
    return None

class HANDLER_POLICY(Enum):
    MULTIPLE_REMOTE_BAN_NON_LOCAL = 1
    MULTIPLE_REMOTE_BAN_NOT_PERSONAL_CLOUD = 2
    BANNED = 3


def is_loopback(address):
    import ipaddress
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


def is_loopback_listener(listen_address: Optional[str]) -> bool:
    """All addresses bound by --listen must resolve exclusively to loopback."""
    import socket

    if not isinstance(listen_address, str) or not listen_address:
        return False
    for address in listen_address.split(','):
        address = address.strip()
        if not address:
            return False
        if is_loopback(address):
            continue
        try:
            resolved = socket.getaddrinfo(address, None, type=socket.SOCK_STREAM)
        except OSError:
            return False
        if not resolved or any(not is_loopback(item[4][0]) for item in resolved):
            return False
    return True


def ensure_nodepack_whitelist(manager_files_path):
    """Create a commented template without replacing an existing whitelist."""
    path = os.path.join(manager_files_path, FLAGGED_NODEPACK_WHITELIST_FILE)
    try:
        os.makedirs(manager_files_path, exist_ok=True)
        with open(path, 'x', encoding='utf-8') as file:
            file.write(
                '# Allow selected flagged CNR nodepacks on non-local listeners.\n'
                '# One Registry ID per line; IDs are case-insensitive and apply to all versions.\n'
                '# Blank lines and # comments are ignored. Changes apply without restarting.\n'
                '# Other installation security checks still apply.\n'
                '#\n'
                '# Example entries (commented out; uncomment to allow):\n'
                '# comfyui-impact-pack\n'
                '# comfyui-inspire-pack # Optional inline comment\n'
            )
    except OSError as exc:
        if isinstance(exc, FileExistsError) and os.path.isfile(path):
            return
        logging.warning('[ComfyUI-Manager] Cannot create nodepack whitelist %s: %s', path, exc)


def is_flagged_nodepack_whitelisted(node_id: str, manager_files_path) -> bool:
    """Match a whole Registry ID, ignoring case, in the current Manager whitelist."""
    if not manager_files_path:
        return False
    path = os.path.join(manager_files_path, FLAGGED_NODEPACK_WHITELIST_FILE)
    try:
        with open(path, encoding='utf-8-sig') as file:
            contents = file.read()
        if '\x00' in contents:
            raise UnicodeError('NUL characters found; save the file as UTF-8')
        entries = (line.split('#', 1)[0].strip() for line in contents.split('\n'))
        if node_id.lower() in {entry.lower() for entry in entries if entry}:
            logging.warning('[ComfyUI-Manager] CNR installation of %r permitted by nodepack whitelist (%s).', node_id, path)
            return True
        return False
    except FileNotFoundError:
        return False
    except (OSError, UnicodeError) as exc:
        logging.warning('[ComfyUI-Manager] Cannot read flagged nodepack whitelist %s: %s', path, exc)
        return False


def is_cnr_install_allowed(
    status: str, allow_flagged: bool, listen_address: Optional[str], *,
    node_id: Optional[str] = None, manager_files_path=None,
) -> bool:
    """Flagged versions require loopback, explicit permission, or a whitelisted ID.

    Restore children pass their parent's resolved permission and no listener.
    """
    return (status != 'NodeVersionStatusFlagged'
            or bool(allow_flagged)
            or is_loopback_listener(listen_address)
            or (node_id is not None and is_flagged_nodepack_whitelisted(node_id, manager_files_path)))


def is_dedicated_install_allowed(flag_value: bool, listen_address: str, network_mode: str) -> bool:
    """P-direct predicate for the dedicated install flags (goal265-spec.md §1.2).

    allowed iff flag AND (loopback listener OR network_mode == 'personal_cloud').

    Gates the git-URL / standalone-pip install surfaces via the dedicated
    ``allow_git_url_install`` / ``allow_pip_install`` config flags, fully
    decoupled from ``security_level`` (REPLACE, not AND — spec §1.1 inv. 1).
    The network-position term retains today's invariant that a public
    (non-loopback, non-personal_cloud) listener stays denied regardless of
    the flags (spec §1.1 inv. 2).

    Pure function — NO config access; callers resolve ``flag_value`` and
    ``network_mode`` through their own config reader and pass values in
    (preserves common/ layering: this module must stay config-import-free).
    """
    return bool(flag_value) and (is_loopback(listen_address) or network_mode.lower() == 'personal_cloud')


def do_nothing():
    pass


def get_handler_policy(x):
    return handler_policy.get(x) or set()

def add_handler_policy(x, policy):
    s = handler_policy.get(x)
    if s is None:
        s = set()
        handler_policy[x] = s
    
    s.add(policy)
    
    
multiple_remote_alert = do_nothing


def is_safe_path_target(target: str) -> bool:
    """
    Check if target string is safe from path traversal attacks.

    Args:
        target: User-provided filename or identifier

    Returns:
        True if safe, False if contains path traversal characters
    """
    if '/' in target or '\\' in target or '..' in target or '\x00' in target:
        return False
    return True


def get_safe_file_path(target: str, base_dir: str, extension: str = ".json") -> Optional[str]:
    """
    Safely construct a file path, preventing path traversal attacks.

    Args:
        target: User-provided filename (without extension)
        base_dir: Base directory path
        extension: File extension to append (default: ".json")

    Returns:
        Safe file path or None if input contains path traversal attempts
    """
    if not is_safe_path_target(target):
        return None
    return os.path.join(base_dir, f"{target}{extension}")
