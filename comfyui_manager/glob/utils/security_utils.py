from comfyui_manager.glob import manager_core as core
from comfy.cli_args import args
from comfyui_manager.data_models import SecurityLevel, RiskLevel


def is_loopback(address):
    import ipaddress
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


def is_allowed_security_level(level):
    is_local_mode = is_loopback(args.listen)
    is_personal_cloud = core.get_config()['network_mode'].lower() == 'personal_cloud'

    if level == RiskLevel.block.value:
        return False
    elif level == RiskLevel.high_.value:
        if is_local_mode:
            return core.get_config()['security_level'] in [SecurityLevel.weak.value, SecurityLevel.normal_.value]
        elif is_personal_cloud:
            return core.get_config()['security_level'] == SecurityLevel.weak.value
        else:
            return False
    elif level == RiskLevel.high.value:
        if is_local_mode:
            return core.get_config()['security_level'] in [SecurityLevel.weak.value, SecurityLevel.normal_.value]
        else:
            return core.get_config()['security_level'] == SecurityLevel.weak.value
    elif level == RiskLevel.middle_.value:
        if is_local_mode or is_personal_cloud:
            return core.get_config()['security_level'] in [SecurityLevel.weak.value, SecurityLevel.normal.value, SecurityLevel.normal_.value]
        else:
            return False
    elif level == RiskLevel.middle.value:
        return core.get_config()['security_level'] in [SecurityLevel.weak.value, SecurityLevel.normal.value, SecurityLevel.normal_.value]
    else:
        return True
