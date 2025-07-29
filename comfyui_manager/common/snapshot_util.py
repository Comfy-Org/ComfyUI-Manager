from . import manager_util
from . import git_utils
import json
import yaml
import logging

def read_snapshot(snapshot_path):
    try:

        with open(snapshot_path, 'r', encoding="UTF-8") as snapshot_file:
            if snapshot_path.endswith('.json'):
                info = json.load(snapshot_file)
            elif snapshot_path.endswith('.yaml'):
                info = yaml.load(snapshot_file, Loader=yaml.SafeLoader)
                info = info['custom_nodes']

            return info
    except Exception as e:
        logging.warning(f"Failed to read snapshot file: {snapshot_path}\nError: {e}")

    return None


def diff_snapshot(a, b):
    if not a or not b:
        return None

    nodepack_diff = {
        'added': {},
        'removed': [],
        'upgraded': {},
        'downgraded': {},
        'changed': []
    }

    pip_diff = {
        'added': {},
        'upgraded': {},
        'downgraded': {}
    }
    
    # check: comfyui
    if a.get('comfyui_version') != b.get('comfyui_version'):
        nodepack_diff['changed'].append('comfyui')
    
    # check: cnr nodes
    a_cnrs = a.get('cnr_custom_nodes', {})
    b_cnrs = b.get('cnr_custom_nodes', {})

    if 'comfyui-manager' in a_cnrs:
        del a_cnrs['comfyui-manager']
    if 'comfyui-manager' in b_cnrs:
        del b_cnrs['comfyui-manager']

    for k, v in a_cnrs.items():
        if k not in b_cnrs.keys():
            nodepack_diff['removed'].append(k)
        elif a_cnrs[k] != b_cnrs[k]:
            a_ver = manager_util.StrictVersion(a_cnrs[k])
            b_ver = manager_util.StrictVersion(b_cnrs[k])
            if a_ver < b_ver:
                nodepack_diff['upgraded'][k] = {'from': a_cnrs[k], 'to': b_cnrs[k]}
            elif a_ver > b_ver:
                nodepack_diff['downgraded'][k] = {'from': a_cnrs[k], 'to': b_cnrs[k]}

    added_cnrs = set(b_cnrs.keys()) - set(a_cnrs.keys())
    for k in added_cnrs:
        nodepack_diff['added'][k] = b_cnrs[k]

    # check: git custom nodes
    a_gits = a.get('git_custom_nodes', {})
    b_gits = b.get('git_custom_nodes', {})

    a_gits = {git_utils.normalize_url(k): v for k, v in a_gits.items() if k.lower() != 'comfyui-manager'}
    b_gits = {git_utils.normalize_url(k): v for k, v in b_gits.items() if k.lower() != 'comfyui-manager'}

    for k, v in a_gits.items():
        if k not in b_gits.keys():
            nodepack_diff['removed'].append(k)
        elif not v['disabled'] and b_gits[k]['disabled']:
            nodepack_diff['removed'].append(k)
        elif v['disabled'] and not b_gits[k]['disabled']:
            nodepack_diff['added'].append(k)
        elif v['hash'] != b_gits[k]['hash']:
            a_date = v.get('commit_timestamp')
            b_date = b_gits[k].get('commit_timestamp')
            if a_date is not None and b_date is not None:
                if a_date < b_date:
                    nodepack_diff['upgraded'].append(k)
                elif a_date > b_date:
                    nodepack_diff['downgraded'].append(k)
            else:
                nodepack_diff['changed'].append(k)

    # check: pip packages
    a_pip = a.get('pips', {})
    b_pip = b.get('pips', {})
    for k, v in a_pip.items():
        if '==' in k:
            package_name, version = k.split('==', 1)
        else:
            package_name, version = k, None
        
        for k2, v2 in b_pip.items():
            if '==' in k2:
                package_name2, version2 = k2.split('==', 1)
            else:
                package_name2, version2 = k2, None
            
            if package_name.lower() == package_name2.lower():
                if version != version2:
                    a_ver = manager_util.StrictVersion(version) if version else None
                    b_ver = manager_util.StrictVersion(version2) if version2 else None
                    if a_ver and b_ver:
                        if a_ver < b_ver:
                            pip_diff['upgraded'][package_name] = {'from': version, 'to': version2}
                        elif a_ver > b_ver:
                            pip_diff['downgraded'][package_name] = {'from': version, 'to': version2}
                    elif not a_ver and b_ver:
                        pip_diff['added'][package_name] = version2

    a_pip_names = {k.split('==', 1)[0].lower() for k in a_pip.keys()}

    for k in b_pip.keys():
        if '==' in k:
            package_name = k.split('==', 1)[0]
            package_version = k.split('==', 1)[1]
        else:
            package_name = k
            package_version = None
        
        if package_name.lower() not in a_pip_names:
            if package_version:
                pip_diff['added'][package_name] = package_version

    return {'nodepack_diff': nodepack_diff, 'pip_diff': pip_diff}
