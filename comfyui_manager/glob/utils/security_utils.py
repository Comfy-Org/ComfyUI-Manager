from comfyui_manager.glob import manager_core as core
from comfy.cli_args import args
from comfyui_manager.data_models import SecurityLevel, RiskLevel, ManagerDatabaseSource


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


async def get_risky_level(files, pip_packages):
    json_data1 = await core.get_data_by_mode(ManagerDatabaseSource.local.value, "custom-node-list.json")
    json_data2 = await core.get_data_by_mode(
        ManagerDatabaseSource.cache.value,
        "custom-node-list.json",
        channel_url="https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main",
    )

    all_urls = set()
    for x in json_data1["custom_nodes"] + json_data2["custom_nodes"]:
        all_urls.update(x.get("files", []))

    for x in files:
        if x not in all_urls:
            return RiskLevel.high_.value

    all_pip_packages = set()
    for x in json_data1["custom_nodes"] + json_data2["custom_nodes"]:
        all_pip_packages.update(x.get("pip", []))

    for p in pip_packages:
        if p not in all_pip_packages:
            return RiskLevel.block.value

    return RiskLevel.middle_.value
