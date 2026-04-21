"""Security helpers for CSRF protection and Content-Type gating.

reject_simple_form_post() is applied ONLY to POST handlers that do not consume
a request body (e.g., snapshot/save, queue/reset, queue/start, reboot). These
are vulnerable to cross-origin <form method=POST> attacks because the server
accepts the request without parsing any body — the attacker needs no ability
to forge a valid payload, only to point a hidden form at the URL.

Handlers that DO read a body via ``await request.json()`` (install/git_url,
install/pip, queue/install_model, db_mode POST, policy/update POST,
channel_url_list POST, queue/batch, queue/task, import_fail_info, etc.) are
NOT gated here — a cross-origin <form method=POST> cannot forge a valid JSON
body because the browser refuses to send ``application/json`` without a CORS
preflight, which this server rejects by not responding with an appropriate
Access-Control-Allow-Origin.

DO NOT add the gate to body-reading handlers (redundant + UX-breaking).
DO NOT remove the gate from no-body handlers (this is the bypass vector).
"""

import os
from enum import Enum
from typing import Optional

from aiohttp import web

is_personal_cloud_mode = False
handler_policy = {}


# CORS "simple request" Content-Type set per Fetch spec §3.2.3. Browsers send
# <form method=POST> submissions with one of these three MIME types and do NOT
# trigger a CORS preflight, so a malicious cross-origin page can silently POST
# into state-changing endpoints if we only gate on HTTP method. Blocking these
# three Content-Types on our mutation endpoints forces any non-same-origin POST
# to use a non-simple Content-Type (e.g. application/json), which triggers a
# preflight that this server rejects (no Access-Control-Allow-Origin response).
_SIMPLE_FORM_CONTENT_TYPES = frozenset({
    'application/x-www-form-urlencoded',
    'multipart/form-data',
    'text/plain',
})


def reject_simple_form_post(request) -> Optional[web.Response]:
    """Reject Content-Types that enable preflight-less <form method=POST> CSRF.

    These 3 MIME types are the complete CORS "simple request" Content-Type set
    (Fetch spec §3.2.3 "CORS-safelisted request-header"). Blocking them
    eliminates the <form method=POST> cross-origin CSRF vector, because any
    other Content-Type triggers a browser-enforced CORS preflight — and this
    server does not answer preflights with ``Access-Control-Allow-Origin``,
    effectively blocking cross-origin requests that use non-simple types.

    Returns:
        web.Response(status=400) when the request has a simple-form
        Content-Type that must be rejected. None when the request is allowed
        to proceed (no body, application/json, or any non-simple Content-Type).

    Note:
        aiohttp's ``request.content_type`` normalizes the header (lower-cases,
        strips parameters), so a ``multipart/form-data; boundary=----X`` header
        is compared as ``multipart/form-data``.
    """
    if request.content_type in _SIMPLE_FORM_CONTENT_TYPES:
        return web.Response(
            status=400,
            text='Invalid Content-Type for this endpoint. Use application/json or omit body.',
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
