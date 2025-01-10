"""
description:
    `manager_util` is the lightest module shared across the prestartup_script, main code, and cm-cli of ComfyUI-Manager.
"""

import aiohttp
import json
import threading
import os
from datetime import datetime
import subprocess
import sys
import re

cache_lock = threading.Lock()

comfyui_manager_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
cache_dir = os.path.join(comfyui_manager_path, '.cache')  # This path is also updated together in **manager_core.update_user_directory**.


# DON'T USE StrictVersion - cannot handle pre_release version
# try:
#     from distutils.version import StrictVersion
# except:
#     print(f"[ComfyUI-Manager]  'distutils' package not found. Activating fallback mode for compatibility.")
class StrictVersion:
    def __init__(self, version_string):
        self.version_string = version_string
        self.major = 0
        self.minor = 0
        self.patch = 0
        self.pre_release = None
        self.parse_version_string()

    def parse_version_string(self):
        parts = self.version_string.split('.')
        if not parts:
            raise ValueError("Version string must not be empty")

        self.major = int(parts[0])
        self.minor = int(parts[1]) if len(parts) > 1 else 0
        self.patch = int(parts[2]) if len(parts) > 2 else 0

        # Handling pre-release versions if present
        if len(parts) > 3:
            self.pre_release = parts[3]

    def __str__(self):
        version = f"{self.major}.{self.minor}.{self.patch}"
        if self.pre_release:
            version += f"-{self.pre_release}"
        return version

    def __eq__(self, other):
        return (self.major, self.minor, self.patch, self.pre_release) == \
            (other.major, other.minor, other.patch, other.pre_release)

    def __lt__(self, other):
        if (self.major, self.minor, self.patch) == (other.major, other.minor, other.patch):
            return self.pre_release_compare(self.pre_release, other.pre_release) < 0
        return (self.major, self.minor, self.patch) < (other.major, other.minor, other.patch)

    @staticmethod
    def pre_release_compare(pre1, pre2):
        if pre1 == pre2:
            return 0
        if pre1 is None:
            return 1
        if pre2 is None:
            return -1
        return -1 if pre1 < pre2 else 1

    def __le__(self, other):
        return self == other or self < other

    def __gt__(self, other):
        return not self <= other

    def __ge__(self, other):
        return not self < other

    def __ne__(self, other):
        return not self == other


def simple_hash(input_string):
    hash_value = 0
    for char in input_string:
        hash_value = (hash_value * 31 + ord(char)) % (2**32)

    return hash_value


def is_file_created_within_one_day(file_path):
    if not os.path.exists(file_path):
        return False

    file_creation_time = os.path.getctime(file_path)
    current_time = datetime.now().timestamp()
    time_difference = current_time - file_creation_time

    return time_difference <= 86400


async def get_data(uri, silent=False):
    if not silent:
        print(f"FETCH DATA from: {uri}", end="")

    if uri.startswith("http"):
        async with aiohttp.ClientSession(trust_env=True, connector=aiohttp.TCPConnector(verify_ssl=False)) as session:
            headers = {
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache',
                'Expires': '0'
            }
            async with session.get(uri, headers=headers) as resp:
                json_text = await resp.text()
    else:
        with cache_lock:
            with open(uri, "r", encoding="utf-8") as f:
                json_text = f.read()

    json_obj = json.loads(json_text)

    if not silent:
        print(" [DONE]")

    return json_obj


async def get_data_with_cache(uri, silent=False, cache_mode=True):
    cache_uri = str(simple_hash(uri)) + '_' + os.path.basename(uri).replace('&', "_").replace('?', "_").replace('=', "_")
    cache_uri = os.path.join(cache_dir, cache_uri+'.json')

    if cache_mode and is_file_created_within_one_day(cache_uri):
        json_obj = await get_data(cache_uri, silent=silent)
    else:
        json_obj = await get_data(uri, silent=silent)

        with cache_lock:
            with open(cache_uri, "w", encoding='utf-8') as file:
                json.dump(json_obj, file, indent=4, sort_keys=True)
                if not silent:
                    print(f"[ComfyUI-Manager] default cache updated: {uri}")

    return json_obj


def sanitize_tag(x):
    return x.replace('<', '&lt;').replace('>', '&gt;')


def extract_package_as_zip(file_path, extract_path):
    import zipfile
    try:
        with zipfile.ZipFile(file_path, "r") as zip_ref:
            zip_ref.extractall(extract_path)
            extracted_files = zip_ref.namelist()
        print(f"Extracted zip file to {extract_path}")
        return extracted_files
    except zipfile.BadZipFile:
        print(f"File '{file_path}' is not a zip or is corrupted.")
        return None


pip_map = None


def get_installed_packages(renew=False):
    global pip_map

    if renew or pip_map is None:
        try:
            result = subprocess.check_output([sys.executable, '-m', 'pip', 'list'], universal_newlines=True)

            pip_map = {}
            for line in result.split('\n'):
                x = line.strip()
                if x:
                    y = line.split()
                    if y[0] == 'Package' or y[0].startswith('-'):
                        continue

                    pip_map[y[0]] = y[1]
        except subprocess.CalledProcessError:
            print("[ComfyUI-Manager] Failed to retrieve the information of installed pip packages.")
            return set()

    return pip_map


def clear_pip_cache():
    global pip_map
    pip_map = None


torch_torchvision_version_map = {
    '2.5.1': '0.20.1',
    '2.5.0': '0.20.0',
    '2.4.1': '0.19.1',
    '2.4.0': '0.19.0',
    '2.3.1': '0.18.1',
    '2.3.0': '0.18.0',
    '2.2.2': '0.17.2',
    '2.2.1': '0.17.1',
    '2.2.0': '0.17.0',
    '2.1.2': '0.16.2',
    '2.1.1': '0.16.1',
    '2.1.0': '0.16.0',
    '2.0.1': '0.15.2',
    '2.0.0': '0.15.1',
}


class PIPFixer:
    def __init__(self, prev_pip_versions):
        self.prev_pip_versions = { **prev_pip_versions }

    def torch_rollback(self):
        spec = self.prev_pip_versions['torch'].split('+')
        if len(spec) > 0:
            platform = spec[1]
        else:
            cmd = [sys.executable, '-m', 'pip', 'install', '--force', 'torch', 'torchvision', 'torchaudio']
            subprocess.check_output(cmd, universal_newlines=True)
            print(cmd)
            return

        torch_ver = StrictVersion(spec[0])
        torch_ver = f"{torch_ver.major}.{torch_ver.minor}.{torch_ver.patch}"
        torchvision_ver = torch_torchvision_version_map.get(torch_ver)

        if torchvision_ver is None:
            cmd = [sys.executable, '-m', 'pip', 'install', '--pre',
                   'torch', 'torchvision', 'torchaudio',
                   '--index-url', f"https://download.pytorch.org/whl/nightly/{platform}"]
            print("[manager-core] restore PyTorch to nightly version")
        else:
            cmd = [sys.executable, '-m', 'pip', 'install',
                   f'torch=={torch_ver}', f'torchvision=={torchvision_ver}', f"torchaudio=={torch_ver}",
                   '--index-url', f"https://download.pytorch.org/whl/{platform}"]
            print(f"[manager-core] restore PyTorch to {torch_ver}+{platform}")

        subprocess.check_output(cmd, universal_newlines=True)

    def fix_broken(self):
        new_pip_versions = get_installed_packages(True)

        # remove `comfy` python package
        try:
            if 'comfy' in new_pip_versions:
                cmd = [sys.executable, '-m', 'pip', 'uninstall', 'comfy']
                subprocess.check_output(cmd, universal_newlines=True)

                print("[manager-core] 'comfy' python package is uninstalled.\nWARN: The 'comfy' package is completely unrelated to ComfyUI and should never be installed as it causes conflicts with ComfyUI.")
        except Exception as e:
            print("[manager-core] Failed to uninstall `comfy` python package")
            print(e)

        # fix torch - reinstall torch packages if version is changed
        try:
            if self.prev_pip_versions['torch'] != new_pip_versions['torch'] \
                or self.prev_pip_versions['torchvision'] != new_pip_versions['torchvision'] \
                or self.prev_pip_versions['torchaudio'] != new_pip_versions['torchaudio']:
                    self.torch_rollback()
        except Exception as e:
            print("[manager-core] Failed to restore PyTorch")
            print(e)

        # fix opencv
        try:
            ocp = new_pip_versions.get('opencv-contrib-python')
            ocph = new_pip_versions.get('opencv-contrib-python-headless')
            op = new_pip_versions.get('opencv-python')
            oph = new_pip_versions.get('opencv-python-headless')

            versions = [ocp, ocph, op, oph]
            versions = [StrictVersion(x) for x in versions if x is not None]
            versions.sort(reverse=True)

            if len(versions) > 0:
                # upgrade to maximum version
                targets = []
                cur = versions[0]
                if ocp is not None and StrictVersion(ocp) != cur:
                    targets.append('opencv-contrib-python')
                if ocph is not None and StrictVersion(ocph) != cur:
                    targets.append('opencv-contrib-python-headless')
                if op is not None and StrictVersion(op) != cur:
                    targets.append('opencv-python')
                if oph is not None and StrictVersion(oph) != cur:
                    targets.append('opencv-python-headless')

                if len(targets) > 0:
                    for x in targets:
                        cmd = [sys.executable, '-m', 'pip', 'install', f"{x}=={versions[0].version_string}"]
                        subprocess.check_output(cmd, universal_newlines=True)

                    print(f"[manager-core] 'opencv' dependencies were fixed: {targets}")
        except Exception as e:
            print("[manager-core] Failed to restore opencv")
            print(e)

        # fix numpy
        try:
            np = new_pip_versions.get('numpy')
            if np is not None:
                if StrictVersion(np) >= StrictVersion('2'):
                    subprocess.check_output([sys.executable, '-m', 'pip', 'install', "numpy<2"], universal_newlines=True)
        except Exception as e:
            print("[manager-core] Failed to restore numpy")
            print(e)


def sanitize(data):
    return data.replace("<", "&lt;").replace(">", "&gt;")


def sanitize_filename(input_string):
    result_string = re.sub(r'[^a-zA-Z0-9_]', '_', input_string)
    return result_string
