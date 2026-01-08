import os
from enum import Enum
from typing import Optional

is_personal_cloud_mode = False
handler_policy = {}

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
