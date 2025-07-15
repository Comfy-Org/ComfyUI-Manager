from enum import Enum

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
