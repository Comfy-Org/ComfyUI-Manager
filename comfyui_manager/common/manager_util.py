"""
description:
    `manager_util` is the lightest module shared across the prestartup_script, main code, and cm-cli of ComfyUI-Manager.
"""
import traceback

import aiohttp
import json
import threading
import os
import subprocess
import sys
import re
import logging
import platform
import shlex
import time
from functools import lru_cache

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, Specifier
from packaging.version import InvalidVersion, Version


cache_lock = threading.Lock()
session_lock = threading.Lock()

comfyui_manager_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
cache_dir = os.path.join(comfyui_manager_path, '.cache')  # This path is also updated together in **manager_core.update_user_directory**.

use_uv = False
use_unified_resolver = False
bypass_ssl = False

def is_manager_pip_package():
    return not os.path.exists(os.path.join(comfyui_manager_path, '..', 'custom_nodes'))

def add_python_path_to_env():
    if platform.system() != "Windows":
        sep = ':'
    else:
        sep = ';'

    os.environ['PATH'] = os.path.dirname(sys.executable)+sep+os.environ['PATH']


@lru_cache(maxsize=2)
def get_pip_cmd(force_uv=False):
    """
    Get the base pip command, with automatic fallback to uv if pip is unavailable.

    Args:
        force_uv (bool): If True, use uv directly without trying pip

    Returns:
        list: Base command for pip operations
    """
    embedded = 'python_embeded' in sys.executable

    # Try pip first (unless forcing uv)
    if not force_uv:
        try:
            test_cmd = [sys.executable] + (['-s'] if embedded else []) + ['-m', 'pip', '--version']
            subprocess.check_output(test_cmd, stderr=subprocess.DEVNULL, timeout=5)
            return [sys.executable] + (['-s'] if embedded else []) + ['-m', 'pip']
        except Exception:
            logging.warning("[ComfyUI-Manager] python -m pip not available. Falling back to uv.")

    # Try uv (either forced or pip failed)
    import shutil

    # Try uv as Python module
    try:
        test_cmd = [sys.executable] + (['-s'] if embedded else []) + ['-m', 'uv', '--version']
        subprocess.check_output(test_cmd, stderr=subprocess.DEVNULL, timeout=5)
        logging.info("[ComfyUI-Manager] Using uv as Python module for pip operations.")
        return [sys.executable] + (['-s'] if embedded else []) + ['-m', 'uv', 'pip']
    except Exception:
        pass

    # Try standalone uv
    if shutil.which('uv'):
        logging.info("[ComfyUI-Manager] Using standalone uv for pip operations.")
        return ['uv', 'pip']

    # Nothing worked
    logging.error("[ComfyUI-Manager] Neither python -m pip nor uv are available. Cannot proceed with package operations.")
    raise Exception("Neither pip nor uv are available for package management")


def make_pip_cmd(cmd):
    """
    Create a pip command by combining the cached base pip command with the given arguments.

    Args:
        cmd (list): List of pip command arguments (e.g., ['install', 'package'])

    Returns:
        list: Complete command list ready for subprocess execution
    """
    global use_uv
    base_cmd = get_pip_cmd(force_uv=use_uv)
    return base_cmd + cmd


# DON'T USE StrictVersion - cannot handle pre_release version
# try:
#     from distutils.version import StrictVersion
# except Exception:
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
    current_time = time.time()
    time_difference = current_time - file_creation_time

    return time_difference <= 86400


async def get_data(uri, silent=False):
    if not silent:
        print(f"FETCH DATA from: {uri}", end="")

    if uri.startswith("http"):
        async with aiohttp.ClientSession(trust_env=True, connector=aiohttp.TCPConnector(verify_ssl=not bypass_ssl)) as session:
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

    try:
        json_obj = json.loads(json_text)
    except Exception as e:
        logging.error(f"[ComfyUI-Manager] An error occurred while fetching '{uri}': {e}")

        return {}

    if not silent:
        print(" [DONE]")

    return json_obj


def get_cache_path(uri):
    cache_uri = str(simple_hash(uri)) + '_' + os.path.basename(uri).replace('&', "_").replace('?', "_").replace('=', "_")
    return os.path.join(cache_dir, cache_uri+'.json')


def get_cache_state(uri):
    cache_uri = get_cache_path(uri)

    if not os.path.exists(cache_uri):
        return "not-cached"
    elif is_file_created_within_one_day(cache_uri):
        return "cached"

    return "expired"


def save_to_cache(uri, json_obj, silent=False):
    cache_uri = get_cache_path(uri)

    with cache_lock:
        with open(cache_uri, "w", encoding='utf-8') as file:
            json.dump(json_obj, file, indent=4, sort_keys=True)
            if not silent:
                logging.info(f"[ComfyUI-Manager] default cache updated: {uri}")


async def get_data_with_cache(uri, silent=False, cache_mode=True, dont_wait=False, dont_cache=False):
    cache_uri = get_cache_path(uri)

    if cache_mode and dont_wait:
        # NOTE: return the cache if possible, even if it is expired, so do not cache
        if not os.path.exists(cache_uri):
            logging.error(f"[ComfyUI-Manager] The network connection is unstable, so it is operating in fallback mode: {uri}")

            return {}
        else:
            if not is_file_created_within_one_day(cache_uri):
                logging.error(f"[ComfyUI-Manager] The network connection is unstable, so it is operating in outdated cache mode: {uri}")

            return await get_data(cache_uri, silent=silent)

    if cache_mode and is_file_created_within_one_day(cache_uri):
        json_obj = await get_data(cache_uri, silent=silent)
    else:
        json_obj = await get_data(uri, silent=silent)
        if not dont_cache:
            with cache_lock:
                with open(cache_uri, "w", encoding='utf-8') as file:
                    json.dump(json_obj, file, indent=4, sort_keys=True)
                    if not silent:
                        logging.info(f"[ComfyUI-Manager] default cache updated: {uri}")

    return json_obj


def sanitize_tag(x):
    return x.replace('<', '&lt;').replace('>', '&gt;')


def extract_package_as_zip(file_path, extract_path):
    import zipfile
    try:
        with zipfile.ZipFile(file_path, "r") as zip_ref:
            zip_ref.extractall(extract_path)
            extracted_files = zip_ref.namelist()
        logging.info(f"Extracted zip file to {extract_path}")
        return extracted_files
    except zipfile.BadZipFile:
        logging.error(f"File '{file_path}' is not a zip or is corrupted.")
        return None


def normalize_pip_name(name):
    """Return the key used to compare pip package names.

    Case is ignored and runs of '-', '_' and '.' are one separator (PEP 503), written
    as '_'. `get_installed_packages()` returns its keys in this form.
    """
    return re.sub(r'[-_.]+', '_', name.strip()).lower()


_PIP_LINE_TAIL_PATTERN = re.compile(r'\s[#-]')    # a comment or a pip option after the requirement
_PIP_MALFORMED_PATTERN = re.compile(r'([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\]\s*)?[<>=!~(]')


def parse_pip_spec(spec):
    """Read a requirement line into (normalized name, has extras, version clauses).

    Clauses are (operator, version) pairs, one per clause of the requirement. A direct
    reference ('name @ url') has the single clause ('@', url), and a version that cannot
    be parsed has ('?', text); neither can be compared with an installed version. A
    trailing comment, an environment marker and pip options are ignored.

    Returns (None, False, []) when the line does not name a package: URLs, paths and options.
    """
    text = spec.strip()
    tail = _PIP_LINE_TAIL_PATTERN.search(text)
    if tail is not None:
        text = text[:tail.start()]

    try:
        requirement = Requirement(text)
    except InvalidRequirement:
        match = _PIP_MALFORMED_PATTERN.match(text)
        if match is None:
            return None, False, []
        return normalize_pip_name(match.group(1)), match.group(2) is not None, [('?', text[match.end(1):].strip())]

    name = normalize_pip_name(requirement.name)
    extras = bool(requirement.extras)
    if requirement.url:
        return name, extras, [('@', requirement.url)]
    return name, extras, [(specifier.operator, specifier.version) for specifier in requirement.specifier]


def _upper_bound_state(operator, version, installed):
    """Where an installed version sits against one upper-bound clause.

    'above': pip would have to install an older version. 'at': the clause allows the
    installed version and nothing newer in its range needs installing. 'below': the
    clause does not constrain the installed version from above.
    """
    satisfied = Specifier(operator + version).contains(installed, prereleases=True)
    if operator == '<':
        return 'below' if satisfied else 'above'
    if satisfied:
        if operator == '<=' and not Specifier('==' + version).contains(installed, prereleases=True):
            return 'below'
        return 'at'
    bound = Version(version[:-2] if version.endswith('.*') else version)
    return 'above' if installed > bound else 'below'


def downgrade_protection(spec, clauses, extras, installed):
    """Decide whether a requirement may replace a downgrade-protected installed package.

    `clauses` and `extras` come from `parse_pip_spec()`; `installed` is the installed
    version. Returns (blocked, error).

    The requirement is blocked when any clause would make pip install an older version.
    Without extras it is also blocked when it has no version or allows exactly the
    installed version, where pip would change nothing. With extras pip would still add
    the extras' dependencies, so those two cases are allowed.

    It is blocked as well when a clause cannot be compared with the installed version;
    `error` then says what was skipped, why, and how to proceed.
    """
    if not clauses:
        return not extras, None

    try:
        current = Version(installed)
        states = set()
        for operator, version in clauses:
            if operator in ('>=', '>', '!='):
                continue
            if operator not in ('<', '<=', '==', '===', '~='):
                raise InvalidSpecifier(operator)
            states.add(_upper_bound_state(operator, version, current))
    except (InvalidSpecifier, InvalidVersion):
        return True, (
            f"Skipped '{spec.strip()}': this package is protected by downgrade_blacklist, and its installed "
            f"version ({installed}) cannot be compared with the requested version. Install it manually if it is "
            "needed, or remove the package from downgrade_blacklist in config.ini if it was added there.")

    return 'above' in states or ('at' in states and not extras), None


def requires_newer_version(clauses, installed):
    """Whether any clause sets a minimum that the installed version does not reach.

    Clauses that cannot be compared count as requiring it, so that pip decides.
    """
    try:
        current = Version(installed)
        for operator, version in clauses:
            if operator in ('>', '>=', '==', '===', '~='):
                bound = Version(version[:-2] if version.endswith('.*') else version)
                if current < bound or (operator == '>' and current == bound):
                    return True
            elif operator in ('@', '?'):
                return True
    except InvalidVersion:
        return True
    return False


def pip_block_reason(spec, blacklist, downgrade_blacklist):
    """Return why a requirement must not be installed, or None if it may be.

    'blacklisted': the package is in `blacklist`.
    'downgrade blacklisted': the package is in `downgrade_blacklist`, is installed, and
    `downgrade_protection()` blocks the requirement.

    Names are compared in normalized form, so 'opencv-python', 'opencv_python' and
    'OpenCV-Python' are the same package in both lists and in the requirement.
    """
    name, extras, clauses = parse_pip_spec(spec)
    if name is None:
        # The line does not name a package: only an identical blacklist entry applies.
        return 'blacklisted' if spec.strip() in blacklist else None

    if name in {normalize_pip_name(x) for x in blacklist}:
        return 'blacklisted'

    if name not in {normalize_pip_name(x) for x in downgrade_blacklist}:
        return None

    installed = get_installed_packages().get(name)
    if installed is None:
        return None

    blocked, error = downgrade_protection(spec, clauses, extras, installed)
    if error is not None:
        logging.error("[ComfyUI-Manager] %s", error)
    return 'downgrade blacklisted' if blocked else None


def pip_install_requirement(cmd):
    """Return the requirement of a `pip install` command built by `make_pip_cmd()`, or None.

    The base command varies (python -m pip, python -s -m pip, python -m uv pip, uv pip),
    and options such as --index-url may follow the requirement.

    The command must install one requirement, placed right after `install`. Only
    `pip_install()` builds a command with an option first and several packages; it is
    marked #FORCE and is not checked against the lists.
    """
    for i in range(len(cmd) - 2):
        if cmd[i] == 'pip' and cmd[i + 1] == 'install':
            return cmd[i + 2]
    return None


pip_map = None


def get_installed_packages(renew=False):
    global pip_map

    if renew or pip_map is None:
        try:
            result = subprocess.check_output(make_pip_cmd(['list']), universal_newlines=True)

            pip_map = {}
            for line in result.split('\n'):
                x = line.strip()
                if x:
                    y = line.split()
                    if y[0] == 'Package' or y[0].startswith('-'):
                        continue

                    pip_map[normalize_pip_name(y[0])] = y[1]
        except subprocess.CalledProcessError:
            logging.error("[ComfyUI-Manager] Failed to retrieve the information of installed pip packages.")
            return {}

    return pip_map


def clear_pip_cache():
    global pip_map
    pip_map = None


def parse_requirement_line(line):
    tokens = shlex.split(line)
    if not tokens:
        return None

    package_spec = tokens[0]

    pattern = re.compile(
        r'^(?P<package>[A-Za-z0-9_.+-]+)'
        r'(?P<operator>==|>=|<=|!=|~=|>|<)?'
        r'(?P<version>[A-Za-z0-9_.+-]*)$'
    )
    m = pattern.match(package_spec)
    if not m:
        return None

    package = m.group('package')
    operator = m.group('operator') or None
    version = m.group('version') or None

    index_url = None
    if '--index-url' in tokens:
        idx = tokens.index('--index-url')
        if idx + 1 < len(tokens):
            index_url = tokens[idx + 1]

    res = {'package': package}

    if operator is not None:
        res['operator'] = operator

    if version is not None:
        res['version'] = StrictVersion(version)

    if index_url is not None:
        res['index_url'] = index_url

    return res


torch_torchvision_torchaudio_version_map = {
    '2.7.0': ('0.22.0', '2.7.0'),
    '2.6.0': ('0.21.0', '2.6.0'),
    '2.5.1': ('0.20.0', '2.5.0'),
    '2.5.0': ('0.20.0', '2.5.0'),
    '2.4.1': ('0.19.1', '2.4.1'),
    '2.4.0': ('0.19.0', '2.4.0'),
    '2.3.1': ('0.18.1', '2.3.1'),
    '2.3.0': ('0.18.0', '2.3.0'),
    '2.2.2': ('0.17.2', '2.2.2'),
    '2.2.1': ('0.17.1', '2.2.1'),
    '2.2.0': ('0.17.0', '2.2.0'),
    '2.1.2': ('0.16.2', '2.1.2'),
    '2.1.1': ('0.16.1', '2.1.1'),
    '2.1.0': ('0.16.0', '2.1.0'),
    '2.0.1': ('0.15.2', '2.0.1'),
    '2.0.0': ('0.15.1', '2.0.0'),
}


def torch_rollback(prev):
    spec = prev.split('+')
    if len(spec) > 1:
        platform = spec[1]
    else:
        cmd = make_pip_cmd(['install', '--force', 'torch', 'torchvision', 'torchaudio'])
        subprocess.check_output(cmd, universal_newlines=True)
        logging.error(cmd)
        return

    torch_ver = StrictVersion(spec[0])
    torch_ver = f"{torch_ver.major}.{torch_ver.minor}.{torch_ver.patch}"
    torch_torchvision_torchaudio_ver = torch_torchvision_torchaudio_version_map.get(torch_ver)

    if torch_torchvision_torchaudio_ver is None:
        cmd = make_pip_cmd(['install', '--pre', 'torch', 'torchvision', 'torchaudio',
                            '--index-url', f"https://download.pytorch.org/whl/nightly/{platform}"])
        logging.info("[ComfyUI-Manager] restore PyTorch to nightly version")
    else:
        torchvision_ver, torchaudio_ver = torch_torchvision_torchaudio_ver
        cmd = make_pip_cmd(['install', f'torch=={torch_ver}', f'torchvision=={torchvision_ver}', f"torchaudio=={torchaudio_ver}",
                            '--index-url', f"https://download.pytorch.org/whl/{platform}"])
        logging.info(f"[ComfyUI-Manager] restore PyTorch to {torch_ver}+{platform}")

    subprocess.check_output(cmd, universal_newlines=True)


class PIPFixer:
    def __init__(self, prev_pip_versions, comfyui_path, manager_files_path):
        self.prev_pip_versions = { **prev_pip_versions }
        self.comfyui_path = comfyui_path
        self.manager_files_path = manager_files_path

    def fix_broken(self):
        new_pip_versions = get_installed_packages(True)

        # remove `comfy` python package
        try:
            if 'comfy' in new_pip_versions:
                cmd = make_pip_cmd(['uninstall', 'comfy'])
                subprocess.check_output(cmd, universal_newlines=True)

                logging.warning("[ComfyUI-Manager] 'comfy' python package is uninstalled.\nWARN: The 'comfy' package is completely unrelated to ComfyUI and should never be installed as it causes conflicts with ComfyUI.")
        except Exception as e:
            logging.error("[ComfyUI-Manager] Failed to uninstall `comfy` python package")
            logging.error(e)

        # fix torch - reinstall torch packages if version is changed
        try:
            if 'torch' not in self.prev_pip_versions or 'torchvision' not in self.prev_pip_versions or 'torchaudio' not in self.prev_pip_versions:
                logging.error("[ComfyUI-Manager] PyTorch is not installed")
            elif self.prev_pip_versions['torch'] != new_pip_versions['torch'] \
                or self.prev_pip_versions['torchvision'] != new_pip_versions['torchvision'] \
                or self.prev_pip_versions['torchaudio'] != new_pip_versions['torchaudio']:
                    torch_rollback(self.prev_pip_versions['torch'])
        except Exception as e:
            logging.error("[ComfyUI-Manager] Failed to restore PyTorch")
            logging.error(e)

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
                        cmd = make_pip_cmd(['install', f"{x}=={versions[0].version_string}"])
                        subprocess.check_output(cmd, universal_newlines=True)

                    logging.info(f"[ComfyUI-Manager] 'opencv' dependencies were fixed: {targets}")
        except Exception as e:
            logging.error("[ComfyUI-Manager] Failed to restore opencv")
            logging.error(e)

        # fix missing frontend
        try:
            # NOTE: package name in requirements is 'comfyui-frontend-package'
            #       but, package name from `pip freeze` is 'comfyui_frontend_package'
            #       but, package name from `uv pip freeze` is 'comfyui-frontend-package'
            #
            #       get_installed_packages returns normalized name (i.e. comfyui_frontend_package)
            if 'comfyui_frontend_package' not in new_pip_versions:
                requirements_path = os.path.join(self.comfyui_path, 'requirements.txt')

                with open(requirements_path, 'r') as file:
                    lines = file.readlines()
                
                front_line = next((line.strip() for line in lines if line.startswith('comfyui-frontend-package')), None)
                if front_line is None:
                    logging.info("[ComfyUI-Manager] Skipped fixing the 'comfyui-frontend-package' dependency because the ComfyUI is outdated.")
                else:
                    cmd = make_pip_cmd(['install', front_line])
                    subprocess.check_output(cmd , universal_newlines=True)
                    logging.info("[ComfyUI-Manager] 'comfyui-frontend-package' dependency were fixed")
        except Exception as e:
            logging.error("[ComfyUI-Manager] Failed to restore comfyui-frontend-package")
            logging.error(e)

        # restore based on custom list
        pip_auto_fix_path = os.path.join(self.manager_files_path, "pip_auto_fix.list")
        if os.path.exists(pip_auto_fix_path):
            with open(pip_auto_fix_path, 'r', encoding="UTF-8", errors="ignore") as f:
                fixed_list = []

                for x in f.readlines():
                    try:
                        parsed = parse_requirement_line(x)
                        need_to_reinstall = True

                        normalized_name = normalize_pip_name(parsed['package'])
                        if normalized_name in new_pip_versions:
                            if 'version' in parsed and 'operator' in parsed:
                                cur = StrictVersion(new_pip_versions[normalized_name])
                                dest = parsed['version']
                                op = parsed['operator']
                                if cur == dest:
                                    if op in ['==', '>=', '<=']:
                                        need_to_reinstall = False
                                elif cur < dest:
                                    if op in ['<=', '<', '~=', '!=']:
                                        need_to_reinstall = False
                                elif cur > dest:
                                    if op in ['>=', '>', '~=', '!=']:
                                        need_to_reinstall = False

                        if need_to_reinstall:
                            cmd_args = ['install']
                            if 'version' in parsed and 'operator' in parsed:
                                cmd_args.append(parsed['package']+parsed['operator']+parsed['version'].version_string)

                            if 'index_url' in parsed:
                                cmd_args.append('--index-url')
                                cmd_args.append(parsed['index_url'])

                            cmd = make_pip_cmd(cmd_args)
                            subprocess.check_output(cmd, universal_newlines=True)

                            fixed_list.append(parsed['package'])
                    except Exception as e:
                        traceback.print_exc()
                        logging.error(f"[ComfyUI-Manager] Failed to restore '{x}'")
                        logging.error(e)

                if len(fixed_list) > 0:
                    logging.info(f"[ComfyUI-Manager] dependencies in pip_auto_fix.json were fixed: {fixed_list}")

def sanitize(data):
    return data.replace("<", "&lt;").replace(">", "&gt;")


def sanitize_filename(input_string):
    result_string = re.sub(r'[^a-zA-Z0-9_]', '_', input_string)
    return result_string


def robust_readlines(fullpath):
    import chardet
    try:
        with open(fullpath, "r") as f:
            return f.readlines()
    except Exception:
        encoding = None
        with open(fullpath, "rb") as f:
            raw_data = f.read()
            result = chardet.detect(raw_data)
            encoding = result['encoding']

        if encoding is not None:
            with open(fullpath, "r", encoding=encoding) as f:
                return f.readlines()

        print(f"[ComfyUI-Manager] Failed to recognize encoding for: {fullpath}")
        return []


def restore_pip_snapshot(pips, options):
    non_url = []
    local_url = []
    non_local_url = []

    for k, v in pips.items():
        # NOTE: skip torch related packages
        if k.startswith("torch==") or k.startswith("torchvision==") or k.startswith("torchaudio==") or k.startswith("nvidia-"):
            continue

        if v == "":
            non_url.append(k)
        else:
            if v.startswith('file:'):
                local_url.append(v)
            else:
                non_local_url.append(v)


    # restore other pips
    failed = []
    if '--pip-non-url' in options:
        # try all at once
        res = 1
        try:
            res = subprocess.check_output(make_pip_cmd(['install'] + non_url))
        except Exception:
            pass

        # fallback
        if res != 0:
            for x in non_url:
                res = 1
                try:
                    res = subprocess.check_output(make_pip_cmd(['install', '--no-deps', x]))
                except Exception:
                    pass

                if res != 0:
                    failed.append(x)

    if '--pip-non-local-url' in options:
        for x in non_local_url:
            res = 1
            try:
                res = subprocess.check_output(make_pip_cmd(['install', '--no-deps', x]))
            except Exception:
                pass

            if res != 0:
                failed.append(x)

    if '--pip-local-url' in options:
        for x in local_url:
            res = 1
            try:
                res = subprocess.check_output(make_pip_cmd(['install', '--no-deps', x]))
            except Exception:
                pass

            if res != 0:
                failed.append(x)

    print(f"Installation failed for pip packages: {failed}")
