"""
description:
    `manager_util` is the lightest module shared across the prestartup_script, main code, and cm-cli of ComfyUI-Manager.
"""
import importlib.metadata
import traceback
import ipaddress
import socket

import aiohttp
import json
import threading
import os
import shutil
from datetime import datetime
import subprocess
import tempfile
import sys
import re
import logging
import platform
import shlex
import time
from functools import lru_cache
from html import escape, unescape
from html.entities import html5
from urllib.parse import urlsplit, urlunsplit


cache_lock = threading.Lock()

comfyui_manager_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
cache_dir = os.path.join(comfyui_manager_path, '.cache')  # This path is also updated together in **manager_core.update_user_directory**.

use_uv = False
bypass_ssl = False

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
    'Restart ComfyUI after changing the listener or configuration. '
    'All other installation security checks still apply.'
)


def is_loopback_listener(listen_address: str) -> bool:
    """All addresses bound by --listen must resolve exclusively to loopback."""
    if not isinstance(listen_address, str) or not listen_address:
        return False
    for address in listen_address.split(','):
        address = address.strip()
        if not address:
            return False
        try:
            if ipaddress.ip_address(address).is_loopback:
                continue
        except ValueError:
            pass
        try:
            resolved = socket.getaddrinfo(address, None, type=socket.SOCK_STREAM)
        except OSError:
            return False
        if not resolved or any(not ipaddress.ip_address(item[4][0]).is_loopback for item in resolved):
            return False
    return True


def is_cnr_install_allowed(status: str, allow_flagged: bool, listen_address: str) -> bool:
    """Only flagged versions require loopback or the private-network opt-in."""
    return status != 'NodeVersionStatusFlagged' or bool(allow_flagged) or is_loopback_listener(listen_address)


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
            logging.warning("[ComfyUI-Manager] `python -m pip` not available. Falling back to `uv`.")

    # Try uv (either forced or pip failed)
    import shutil

    # Try uv as Python module
    try:
        test_cmd = [sys.executable] + (['-s'] if embedded else []) + ['-m', 'uv', '--version']
        subprocess.check_output(test_cmd, stderr=subprocess.DEVNULL, timeout=5)
        logging.info("[ComfyUI-Manager] Using `uv` as Python module for pip operations.")
        return [sys.executable] + (['-s'] if embedded else []) + ['-m', 'uv', 'pip']
    except Exception:
        pass

    # Try standalone uv
    if shutil.which('uv'):
        logging.info("[ComfyUI-Manager] Using standalone `uv` for pip operations.")
        return ['uv', 'pip']

    # Nothing worked
    logging.error("[ComfyUI-Manager] Neither `python -m pip` nor `uv` are available. Cannot proceed with package operations.")
    raise Exception("Neither `pip` nor `uv` are available for package management")


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
        # A pre-release follows the third number after '.' or '-': '0.1.3.post1', '1.8.0-beta.1'.
        # __str__ writes it with '-', so a version that was already normalized is read as well.
        m = re.fullmatch(r'(\d+)(?:\.(\d+)(?:\.(\d+)(?:[.-](.+))?)?)?', self.version_string)
        if m is None:
            raise ValueError(f"Invalid version: {self.version_string!r}")

        self.major = int(m.group(1))
        self.minor = int(m.group(2) or 0)
        self.patch = int(m.group(3) or 0)
        self.pre_release = m.group(4)

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
    # mtime, not ctime: on Windows ctime is the CREATION time, and rewriting
    # a cache file in place does not change it — after the first day every
    # rewritten cache was 'expired' forever, so each start and each
    # fetch_updates refetched the whole registry.
    if not os.path.exists(file_path):
        return False

    file_modified_time = os.path.getmtime(file_path)
    current_time = datetime.now().timestamp()
    time_difference = current_time - file_modified_time

    return time_difference <= 86400


def aiohttp_connector():
    # aiohttp before 3.9.2 reads ssl=True as "do not check", so ssl is passed only to turn the check off
    return aiohttp.TCPConnector(ssl=False) if bypass_ssl else None


async def get_data(uri, silent=False):
    if not silent:
        print(f"FETCH DATA from: {uri}", end="")

    if uri.startswith("http"):
        async with aiohttp.ClientSession(trust_env=True, connector=aiohttp_connector()) as session:
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

        if uri.startswith("http"):
            raise

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


def _atomic_write_json(cache_uri, json_obj):
    # A kill mid-dump used to leave a truncated cache that parsed as valid
    # (fresh mtime) but returned {} — or blew up the CNR consumer. Temp file
    # + os.replace: readers see the old cache or the new one, never a corpse.
    # Returns whether the cache was replaced: one that stays open elsewhere is
    # left as it is, with a warning.
    tmp_uri = f"{cache_uri}.{os.getpid()}.tmp"
    try:
        with open(tmp_uri, "w", encoding="utf-8") as file:
            json.dump(json_obj, file, indent=4, sort_keys=True)
        try:
            # the cache keeps the mode it had; a new one gets the default mode
            if os.path.exists(cache_uri):
                os.chmod(tmp_uri, os.stat(cache_uri).st_mode & 0o777)
        except OSError:
            # a file system that refuses chmod sets the mode itself
            pass
        for attempt in range(3):
            try:
                os.replace(tmp_uri, cache_uri)
                return True
            except OSError as e:
                # Windows does not replace a file that is open elsewhere. A
                # reader has it open for a moment only, so try again shortly.
                refusal = e
                if attempt < 2:
                    time.sleep(0.1)
        # still refused: keep the cache as it is. Writing over it in place
        # could be cut short, and the caller has the data it fetched anyway.
        logging.warning(f"[ComfyUI-Manager] The cache could not be replaced and is left as it is: {cache_uri}\n=> {refusal}")
        return False
    finally:
        # gone after a replace; otherwise remove it if nothing holds it open
        try:
            os.remove(tmp_uri)
        except OSError:
            pass


def save_to_cache(uri, json_obj, silent=False):
    cache_uri = get_cache_path(uri)

    with cache_lock:
        if _atomic_write_json(cache_uri, json_obj) and not silent:
            logging.info(f"[ComfyUI-Manager] default cache updated: {uri}")


def write_cache_file(cache_uri, json_obj):
    # for callers that compute their own cache path (get_data_by_mode's
    # hash_filename scheme differs from get_cache_path) — same atomic
    # guarantee: readers see the old cache or the new one, never a corpse.
    # Returns whether the cache was replaced.
    with cache_lock:
        return _atomic_write_json(cache_uri, json_obj)


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
                if _atomic_write_json(cache_uri, json_obj) and not silent:
                    logging.info(f"[ComfyUI-Manager] default cache updated: {uri}")

    return json_obj


def sanitize_tag(x):
    return x.replace('<', '&lt;').replace('>', '&gt;')


SAFE_URL_SCHEMES = frozenset({'http', 'https'})
_URL_SCHEME_NOISE = re.compile(r'[\x00-\x20\x7f]')
_URL_HEAD_DELIMITERS = ('/', '?', '#')


def escape_html_attribute(value):
    """Escape a value for a quoted HTML attribute."""
    return escape(str(value), quote=True)


_HTML_ENTITY = re.compile(r'&(#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);')
_HTML_TEXT_TOKEN = re.compile(_HTML_ENTITY.pattern + "|[&<>\"']")


def unescape_html_entities(text):
    """Decode complete entities once, leaving query keys such as &notebook intact."""
    def replace(match):
        entity = match.group(1)
        if entity.startswith('#'):
            return unescape(match.group(0))
        return html5.get(entity + ';', match.group(0))

    return _HTML_ENTITY.sub(replace, text)


def escape_html_text(value):
    """Escape HTML text without double-escaping existing entities."""
    return _HTML_TEXT_TOKEN.sub(
        lambda m: m.group(0) if m.group(1) else escape_html_attribute(m.group(0)),
        str(value).replace('\x00', ''),
    )


def sanitize_url(url):
    """Allow HTTP(S), relative URLs and anchors.

    HTML callers must also escape the result as an attribute."""
    raw = '' if url is None else str(url)
    probe = _URL_SCHEME_NOISE.sub('', raw)
    if not probe:
        return '#'

    cut = len(probe)
    for delimiter in _URL_HEAD_DELIMITERS:
        found = probe.find(delimiter)
        if found != -1:
            cut = min(cut, found)
    head = probe[:cut]

    if ':' in head:
        return raw.strip() if head.split(':', 1)[0].lower() in SAFE_URL_SCHEMES else '#'

    return raw.strip()


def sanitize_html_fragment(fragment):
    """Sanitize notice HTML, preserving its formatting and opening links safely."""
    # prestartup_script imports this module before installing dependencies.
    import nh3

    return nh3.clean(
        '' if fragment is None else str(fragment),
        tags=nh3.ALLOWED_TAGS | {'font'},
        attributes={
            **nh3.ALLOWED_ATTRIBUTES,
            '*': {'class', 'title', 'align', 'width', 'height'},
            'font': {'color'},
        },
        # These elements previously hid their contents from the notice.
        clean_content_tags={
            'script', 'style', 'iframe', 'object', 'embed', 'svg', 'math',
            'template', 'noscript', 'textarea', 'title',
        },
        url_schemes=SAFE_URL_SCHEMES,
        set_tag_attribute_values={'a': {'target': '_blank'}},
    )


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


def is_inside(directory, name):
    directory = os.path.abspath(directory)
    try:
        return os.path.commonpath((directory, os.path.abspath(os.path.join(directory, name)))) == directory
    except ValueError:
        # on Windows, a path of another drive
        return False


def switch_package_files(file_path, path):
    import zipfile
    try:
        with zipfile.ZipFile(file_path, "r") as zip_ref:
            extracted = zip_ref.namelist()
    except zipfile.BadZipFile:
        logging.error(f"File '{file_path}' is not a zip or is corrupted.")
        return None

    with open(os.path.join(path, '.tracking'), 'r', encoding='utf-8') as f:
        # as the list is written: a name can start or end with a space
        prev_files = {line.rstrip('\n') for line in f}
    root = os.path.abspath(path)
    garbage = prev_files - set(extracted)
    garbage = [os.path.abspath(os.path.join(root, x)) for x in garbage if is_inside(root, x)]

    for x in garbage:
        try:
            if os.path.isfile(x):
                os.remove(x)
        except OSError as e:
            logging.warning(f"[ComfyUI-Manager] A file of the old version is left: {e}")

    folders = set()
    for x in garbage:
        while len(x) > len(root):
            folders.add(x)
            x = os.path.dirname(x)

    real_root = os.path.realpath(root)

    def reached_without_a_link(x):
        return os.path.normcase(os.path.realpath(x)) == os.path.normcase(real_root + x[len(root):])

    for x in sorted(folders, key=len, reverse=True):
        try:
            if not os.path.isdir(x) or not reached_without_a_link(x):
                continue

            # the files of a `__pycache__` are caches of the modules that were there, as those of Python and of numba
            cache = os.path.join(x, '__pycache__')
            if os.listdir(x) == ['__pycache__'] and reached_without_a_link(cache):
                for name in os.listdir(cache):
                    os.remove(os.path.join(cache, name))
                os.rmdir(cache)

            if not os.listdir(x):
                os.rmdir(x)
        except OSError as e:
            logging.warning(f"[ComfyUI-Manager] A folder of the old version is left: {e}")

    # after the files are removed: two names can be one file, as names that differ in case alone are on Windows
    return extract_package_as_zip(file_path, path)


# The functions below import packaging where they use it: prestartup_script imports this module
# before its ensure_dependencies() has installed a missing dependency.
def normalize_pip_name(name):
    """Return the key used to compare pip package names.

    Case is ignored and runs of '-', '_' and '.' are one separator (PEP 503), written
    as '_'. `get_installed_packages()` returns its keys in this form.
    """
    return re.sub(r'[-_.]+', '_', name.strip()).lower()


_PIP_LINE_TAIL_PATTERN = re.compile(r'\s[#-]')    # a comment or a pip option after the requirement
_PIP_COMMENT_PATTERN = re.compile(r'(^|\s)#.*')    # as pip reads it: the '#' of a URL fragment starts no comment
_PIP_INDEX_OPTIONS = {'--index-url', '--extra-index-url'}
_PIP_EDITABLE_PATTERN = re.compile(r'(?:-e\s*|--editable(?:\s+|=))(\S+)')    # how pip reads -e and its target
_PIP_MALFORMED_PATTERN = re.compile(r'([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\]\s*)?[<>=!~(]')
_PIP_URL_PATTERN = re.compile(r'[A-Za-z][A-Za-z0-9+.-]*://')


def parse_pip_spec(spec):
    """Read a requirement line into (normalized name, has extras, version clauses).

    Clauses are (operator, version) pairs, one per clause of the requirement. A direct
    reference ('name @ url') has the single clause ('@', url), and a version that cannot
    be parsed has ('?', text); neither can be compared with an installed version. A
    trailing comment, an environment marker and pip options are ignored.

    A line that is a URL is a direct reference without a name: (None, False, [('@', url)]).
    Returns (None, False, []) for the other lines that do not name a package: paths and options.
    """
    from packaging.requirements import InvalidRequirement, Requirement

    text = spec.strip()
    tail = _PIP_LINE_TAIL_PATTERN.search(text)
    if tail is not None:
        text = text[:tail.start()]

    try:
        requirement = Requirement(text)
    except InvalidRequirement:
        if _PIP_URL_PATTERN.match(text):
            # pip splits a URL from its environment marker at '; '
            return None, False, [('@', text.split('; ', 1)[0].rstrip())]
        match = _PIP_MALFORMED_PATTERN.match(text)
        if match is None:
            return None, False, []
        return normalize_pip_name(match.group(1)), match.group(2) is not None, [('?', text[match.end(1):].strip())]

    name = normalize_pip_name(requirement.name)
    extras = bool(requirement.extras)
    if requirement.url:
        return name, extras, [('@', requirement.url)]
    return name, extras, [(specifier.operator, specifier.version) for specifier in requirement.specifier]


def installer_args(requirement):
    """The arguments of a requirement as the installer in use takes them.

    uv installs an editable from a local folder only: where the arguments are `-e`
    and a git URL, uv gets the URL alone, as a normal install, and a line says so.
    """
    if requirement[0] == '-e' and requirement[1].startswith('git+') and 'uv' in get_pip_cmd(force_uv=use_uv):
        print(f"[ComfyUI-Manager] uv installs an editable from a local folder only: '{requirement[1]}' is installed without -e")
        return requirement[1:]
    return requirement


def pip_install_args(line, overrides):
    """The arguments that a line of requirements.txt gives to `pip install`, or [] if it has none.

    Each line is installed on its own, and an option applies to its line only. The
    comment is left out as pip leaves it out, so a URL keeps its fragment. A line that
    `overrides` (pip_overrides.json) names is replaced. An editable requirement
    (`-e path`, `--editable=path`) is `-e` and its target. A requirement followed by
    index options, such as `--extra-index-url URL`, gives the requirement and the
    options; any other line with a requirement is one argument, with the spaces of an
    environment marker. Where `-e` and a git URL are two arguments, uv gets the URL
    alone: it installs an editable from a local folder only. A line that starts with
    another option than `-e`, such as `-r other.txt`, names no requirement and gives
    none.
    """
    text = _PIP_COMMENT_PATTERN.sub('', line).strip()
    if text in overrides:
        print(f"[ComfyUI-Manager] '{text}' is remapped to '{overrides[text]}'")
        text = overrides[text]
    if not text:
        return []
    editable = _PIP_EDITABLE_PATTERN.match(text)
    if editable is not None:
        requirement, options = ['-e', editable.group(1)], text[editable.end():].split()
    elif text.startswith('-'):
        print(f"[ComfyUI-Manager] skip '{text}': the Manager installs requirements one row at a time and does not apply this row")
        return []
    else:
        tail = _PIP_LINE_TAIL_PATTERN.search(text)
        if tail is None:
            return [text]
        requirement, options = [text[:tail.start()].rstrip()], text[tail.start():].split()
    if len(options) % 2 == 0 and set(options[::2]) <= _PIP_INDEX_OPTIONS:
        return [*installer_args(requirement), *options]
    return [text]


def _upper_bound_state(operator, version, installed):
    """Where an installed version sits against one upper-bound clause.

    'above': pip would have to install an older version. 'at': the clause allows the
    installed version and nothing newer in its range needs installing. 'below': the
    clause does not constrain the installed version from above.
    """
    from packaging.specifiers import Specifier
    from packaging.version import Version

    satisfied = Specifier(operator + version).contains(installed, prereleases=True)
    if operator == '<':
        return 'below' if satisfied else 'above'
    if satisfied:
        if operator == '<=' and not Specifier('==' + version).contains(installed, prereleases=True):
            return 'below'
        return 'at'
    bound = Version(version[:-2] if version.endswith('.*') else version)
    return 'above' if installed > bound else 'below'


def _is_met(clauses, installed):
    """Whether the installed version meets every clause."""
    from packaging.specifiers import Specifier

    return all(Specifier(operator + version).contains(installed, prereleases=True) for operator, version in clauses)


def _is_excluded(clauses, installed):
    """Whether a '!=' clause rejects the installed version."""
    from packaging.specifiers import Specifier

    return any(operator == '!=' and not Specifier('!=' + version).contains(installed, prereleases=True)
               for operator, version in clauses)


def _newer_version_allowed(clauses, installed):
    """Whether some version newer than the installed one meets every clause.

    Which versions exist is not known here. The clauses are asked about the versions
    next to the installed one and next to the version of each clause, where a range
    that a clause closes or excludes ends: the version itself, the one right after it,
    and the next one at each level, which for '4.57.0' are '4.57.0.1', '4.57.1', '4.58'
    and '5'; for a pre-release, a post-release or a development release, the next one
    of its kind as well. Versions are written as long as the longest of them, so that
    '1.0' beside '<1.0.1' is followed by '1.0.0.1'. The first post-release of a version
    is asked about too.

    A pre-release is asked about only when '==', '>=', '<=', '~=' or '===' names one:
    every pip takes a pre-release then. Otherwise pip may install an older release
    instead; pip before 25.0 does so even when '<' or '>' names a pre-release.

    Another local build of the installed version is not asked about unless a clause
    names it: a label says nothing about being newer, and pip would most often find
    the build without a label.
    """
    from packaging.specifiers import SpecifierSet
    from packaging.version import InvalidVersion, Version

    requirement = SpecifierSet(','.join(operator + version for operator, version in clauses))
    anchors = [installed]
    pre_release_named = False
    for operator, version in clauses:
        try:
            anchor = Version(version[:-2] if version.endswith('.*') else version)
        except InvalidVersion:
            continue    # '===' may name anything
        anchors.append(anchor)
        if operator in ('==', '>=', '<=', '~=', '===') and anchor.is_prerelease:
            pre_release_named = True

    width = max(len(anchor.release) for anchor in anchors)
    candidates = []
    for anchor in anchors:
        epoch = f'{anchor.epoch}!' if anchor.epoch else ''
        padded = anchor.release + (0,) * (width - len(anchor.release))
        releases = [padded, padded + (1,)]
        releases += [padded[:level] + (padded[level] + 1,) for level in range(width)]
        candidates += [epoch + '.'.join(map(str, release)) for release in releases]
        candidates.append(str(anchor))
        if anchor.pre is not None:
            candidates.append(f'{anchor.base_version}{anchor.pre[0]}{anchor.pre[1] + 1}')
        candidates.append(f'{anchor.base_version}.post{0 if anchor.post is None else anchor.post + 1}')
        if anchor.dev is not None:
            candidates.append(f"{anchor.public.rsplit('.dev', 1)[0]}.dev{anchor.dev + 1}")

    for candidate in map(Version, candidates):
        if candidate.is_prerelease and not pre_release_named:
            continue
        if candidate > installed and requirement.contains(candidate, prereleases=True):
            return True
    return False


def downgrade_protection(spec, clauses, extras, installed):
    """Decide whether a requirement may replace a downgrade-protected installed package.

    `clauses` and `extras` come from `parse_pip_spec()`; `installed` is the installed
    version. Returns (blocked, error).

    The requirement is blocked when any clause would make pip install an older version.
    Without extras it is also blocked when it has no version or allows exactly the
    installed version, where pip would change nothing. With extras pip would still add
    the extras' dependencies, so those two cases are allowed.

    The clauses are weighed together. A clause that allows the installed version does
    not block the requirement when another clause sets a minimum above that version or
    excludes it with '!=': pip then installs another version, and which one is left to
    pip. When the installed version does not meet the clauses and no newer version meets
    them either, the requirement is blocked, with or without extras, because pip has
    only older versions to install.

    An installed local build, such as a CUDA build, is given up only for a minimum above
    it. A requirement that allows it is blocked without extras, whatever its other
    clauses, and one that excludes it with '!=' is blocked unless it sets such a minimum:
    pip would replace the build with whatever it finds.

    It is blocked as well when a clause cannot be compared with the installed version;
    `error` then says what was skipped, why, and how to proceed.
    """
    from packaging.specifiers import InvalidSpecifier
    from packaging.version import InvalidVersion, Version

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
        only_older = not _is_met(clauses, current) and not _newer_version_allowed(clauses, current)
        local_kept = (_is_excluded(clauses, current) and current.local is not None
                      and not requires_newer_version(clauses, installed))
    except (InvalidSpecifier, InvalidVersion):
        return True, (
            f"Skipped '{spec.strip()}': this package is protected by downgrade_blacklist, and its installed "
            f"version ({installed}) cannot be compared with the requested version. Install it manually if it is "
            "needed, or remove the package from downgrade_blacklist in config.ini if it was added there.")

    if 'above' in states or only_older or local_kept:
        return True, None
    if 'at' in states and not extras:
        # requires_newer_version() is also true when '!=' excludes the installed version
        return current.local is not None or not requires_newer_version(clauses, installed), None
    return False, None


def requires_newer_version(clauses, installed):
    """Whether the installed version fails the requirement where a newer version can meet it.

    That is so when a clause sets a minimum above the installed version. It is also so
    when '!=' or '>' leaves out the installed version itself and a newer version meets
    every clause.

    An installed local build, such as a CUDA build, is replaced only for a minimum above
    it. '!=' is no ground for it, nor is '>' of its own version.

    A clause is read as pip reads it. '>' also leaves out a post-release and a local
    build of its version, and '==4.*' is met by a pre-release of 4.0. Clauses that
    cannot be compared count as requiring a newer version, so that pip decides.
    """
    from packaging.specifiers import Specifier
    from packaging.version import InvalidVersion, Version

    try:
        current = Version(installed)
        left_out = False    # by '>', although the installed version is not below its version
        for operator, version in clauses:
            if operator in ('>', '>=', '==', '===', '~='):
                if Specifier(operator + version).contains(current, prereleases=True):
                    continue
                bound = Version(version[:-2] if version.endswith('.*') else version)
                if current < bound:
                    return True
                left_out = left_out or operator == '>'
            elif operator in ('@', '?'):
                return True
        if current.local is not None:
            return False
        return (left_out or _is_excluded(clauses, current)) and _newer_version_allowed(clauses, current)
    except InvalidVersion:
        return True


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


def installed_from(url, name=None):
    """The direct_url.json of the distribution that was installed from the URL of a direct reference, or None.

    A URL gives no name and no version to look up, and pip has to fetch and build it to
    learn them. pip and uv record where a distribution came from in its direct_url.json
    (PEP 610), and that record is compared here.

    A VCS URL is met by a distribution from that repository. Without a revision in the
    URL any commit meets it, and with one the distribution must have been installed with
    that revision, or be at that commit. The repository is not asked: a branch that has
    moved on is not followed. Any other URL is met by a distribution from that archive.
    A distribution from a local directory meets nothing: such a source is edited in
    place, and pip installs it without a download.

    A record holds the URL without its fragment, and the subdirectory that the fragment
    names in a key of its own. A git repository is the same with and without '.git'.

    `name` is the normalized name of a requirement that gives one ('name @ url'): only a
    distribution of that name meets it.

    Only a distribution whose name `get_installed_packages()` lists counts, and only when
    the distributions of that name agree on the version and on the record. What an install
    that was cut short leaves behind still has its record: alone its name is not listed,
    and beside what took its place the two differ, and the installer is left to decide.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    vcs, _, scheme = parts.scheme.rpartition('+')
    path, revision = parts.path, None
    if vcs and '@' in path:
        path, revision = path.rsplit('@', 1)
    paths = [path]
    if vcs == 'git':
        paths.append(path[:-4] if path.endswith('.git') else path + '.git')
    urls = [urlunsplit((scheme, parts.netloc, path, parts.query, '')) for path in paths]
    subdirectory = re.search(r'(?:^|&)subdirectory=([^&]*)', parts.fragment)
    subdirectory = subdirectory.group(1) if subdirectory else None

    listed = get_installed_packages()
    records, said = {}, {}
    for distribution in importlib.metadata.distributions():
        try:
            metadata = distribution.metadata
            record = distribution.read_text('direct_url.json')
            origin = json.loads(record or '{}')
        except (ValueError, OSError):
            continue    # cut short, or not text; Python 3.15 raises a FileNotFoundError for a folder without METADATA
        found = normalize_pip_name(metadata.get('Name') or '')
        said.setdefault(found, set()).add((metadata.get('Version'), record))    # a set: a folder that is on the path twice is read twice
        if not isinstance(origin, dict) or origin.get('url') not in urls or origin.get('subdirectory') != subdirectory:
            continue
        vcs_info = origin.get('vcs_info')
        if isinstance(vcs_info, dict):
            met = vcs_info.get('vcs') == vcs and revision in (None, vcs_info.get('requested_revision'), vcs_info.get('commit_id'))
        else:
            met = vcs_info is None and not vcs and 'archive_info' in origin
        if met and found in listed and name in (None, found):
            records.setdefault(found, origin)
    for found, origin in records.items():
        if len(said[found]) == 1:
            return origin
    return None


def fix_cmd(install_args):
    """The pip command with which a fix installs the arguments of a requirement line, from `pip_install_args()`.

    A direct reference is installed again by force, whatever is installed: nothing but
    its URL says what it should be. That command is run with `reinstall()`. Any other
    requirement is installed as an install does it.
    """
    cmd = make_pip_cmd(['install', *install_args])
    clauses = parse_pip_spec(install_args[0])[2]
    if clauses and clauses[0][0] == '@':
        # --no-deps: without it every package the distribution needs is installed again as well, torch among them.
        # The cache is left out: with it uv installs the wheel it has built of the commit before, forced or not, and so
        # does pip for a name with a commit. uv may link the files to its cache, and keeps none to link to here.
        uv = 'uv' in cmd[:cmd.index('install')]
        cmd += ['--force-reinstall', '--no-deps'] + (['--no-cache', '--link-mode', 'copy'] if uv else ['--no-cache-dir'])
    return cmd


def is_reinstall(cmd):
    """Whether the command is a forced install that `fix_cmd()` built."""
    requirement = pip_install_requirement(cmd)
    if requirement is None or '--force-reinstall' not in cmd:
        return False
    clauses = parse_pip_spec(requirement)[2]
    return bool(clauses) and clauses[0][0] == '@'


def is_git_remote_usable(url):
    try:
        done = subprocess.run(['git', 'ls-remote', url, 'HEAD'], capture_output=True, timeout=30,
                              env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0


def reinstall(cmd, run):
    """Fix the URL requirement of a forced install that `fix_cmd()` built, and return the exit code.

    `run(cmd)` runs one command and returns its exit code, or raises CalledProcessError
    for it as the `run_script` of cm-cli does. What it raised is raised again at the
    end when the fix has failed.

    The requirement is first installed as an install does it. That brings what the
    distribution at the URL needs now, which the forced install leaves out, and changes
    nothing when it cannot be had. Then the forced install puts a clean copy from the
    URL there. If only the forced install fails, what is installed stays and meets the
    requirement, so the exit code is 0 and the rest of the pack is fixed.

    A cache is used in one case: the first install fails and the repository does not
    answer. uv is then asked for the commit that `installed_from()` finds installed, from
    its cache. pip has no option for that.
    """
    install = cmd.index('install')
    base, requirement = cmd[:install + 1], cmd[install + 1]
    name, _, clauses = parse_pip_spec(requirement)
    raised = []

    def step(command):
        # flushed: cm-cli lets the command write to this stdout by itself
        print(f"\n## ComfyUI-Manager: EXECUTE => {command}", flush=True)
        try:
            return run(command)
        except subprocess.CalledProcessError as error:
            raised.append(error)
            return error.returncode

    code = step(base + [requirement])
    if code == 0:
        if step(cmd) != 0:
            print(f"[ComfyUI-Manager] could not install '{requirement}' again by force: what is installed is kept.")
        return 0

    origin = installed_from(clauses[0][1], name) or {}
    vcs_info = origin.get('vcs_info')
    if vcs_info and vcs_info.get('vcs') == 'git' and 'uv' in base and not is_git_remote_usable(origin['url']):
        subdirectory = f"#subdirectory={origin['subdirectory']}" if 'subdirectory' in origin else ''
        code = step(base + [f"git+{origin['url']}@{vcs_info.get('commit_id')}{subdirectory}", '--force-reinstall', '--no-deps', '--offline'])
    if code != 0 and raised:
        raise raised[0]
    return code


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
        res['version'] = version

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


def torch_rollback(prev, packages):
    spec = prev.split('+')
    if len(spec) > 1:
        platform = spec[1]
    else:
        cmd = make_pip_cmd(['install', '--force', *packages])
        subprocess.check_output(cmd, universal_newlines=True)
        logging.error(cmd)
        return

    torch_ver = StrictVersion(spec[0])
    torch_ver = f"{torch_ver.major}.{torch_ver.minor}.{torch_ver.patch}"
    torch_torchvision_torchaudio_ver = torch_torchvision_torchaudio_version_map.get(torch_ver)

    if torch_torchvision_torchaudio_ver is None:
        cmd = make_pip_cmd(['install', '--pre', *packages,
                            '--index-url', f"https://download.pytorch.org/whl/nightly/{platform}"])
        logging.info("[ComfyUI-Manager] restore PyTorch to nightly version")
    else:
        torchvision_ver, torchaudio_ver = torch_torchvision_torchaudio_ver
        versions = {'torch': torch_ver, 'torchvision': torchvision_ver, 'torchaudio': torchaudio_ver}
        cmd = make_pip_cmd(['install', *[f'{name}=={versions[name]}' for name in packages],
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
            if 'torch' not in self.prev_pip_versions or 'torchvision' not in self.prev_pip_versions:
                logging.error("[ComfyUI-Manager] PyTorch is not installed")
            elif self.prev_pip_versions['torch'] != new_pip_versions['torch'] \
                or self.prev_pip_versions['torchvision'] != new_pip_versions['torchvision']:
                    packages = [name for name in ('torch', 'torchvision', 'torchaudio')
                                if name in self.prev_pip_versions or name in new_pip_versions]
                    torch_rollback(self.prev_pip_versions['torch'], packages)
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
        if self.manager_files_path is None:
            return

        pip_auto_fix_path = os.path.join(self.manager_files_path, "pip_auto_fix.list")
        if os.path.exists(pip_auto_fix_path):
            from packaging.specifiers import Specifier  # imported on use, as in parse_pip_spec()

            with open(pip_auto_fix_path, 'r', encoding="UTF-8", errors="ignore") as f:
                fixed_list = []

                for x in f.readlines():
                    try:
                        parsed = parse_requirement_line(x)
                        need_to_reinstall = True

                        normalized_name = normalize_pip_name(parsed['package'])
                        if normalized_name in new_pip_versions:
                            if 'version' in parsed and 'operator' in parsed:
                                specifier = Specifier(parsed['operator'] + parsed['version'])
                                if specifier.contains(new_pip_versions[normalized_name], prereleases=True):
                                    need_to_reinstall = False

                        if need_to_reinstall:
                            cmd_args = ['install']
                            if 'version' in parsed and 'operator' in parsed:
                                cmd_args.append(parsed['package']+parsed['operator']+parsed['version'])

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
    except:
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


def build_restart_command(argv, drop_args=()):
    """
    Rebuild the command line used to re-exec the current ComfyUI process.

    `argv` is `sys.argv` of the running process; entries listed in `drop_args` are left out.
    The result is meant to be passed to `os.execv(sys.executable, ...)`.

    On Windows, `os.execv` does not quote anything: it joins the list with spaces into one
    command line and the new process splits it again. Every entry is therefore quoted with
    the MSVC rules (`subprocess.list2cmdline`), otherwise an argument such as `Profile 1`
    comes back as two arguments. Other platforms pass the list through untouched.
    """
    argv = [x for x in argv if x not in drop_args]

    if argv[0].endswith("__main__.py"):  # this is a python module
        module_name = os.path.basename(os.path.dirname(argv[0]))
        cmds = [sys.executable, '-m', module_name] + argv[1:]
    else:
        cmds = [sys.executable] + argv

    if sys.platform.startswith('win32'):
        cmds = [subprocess.list2cmdline([x]) for x in cmds]

    return cmds


def restore_pip_snapshot(pips, options):
    non_url = []
    local_url = []
    non_local_url = []

    for k, v in pips.items():
        # NOTE: skip torch related packages
        if k.startswith("torch==") or k.startswith("torchvision==") or k.startswith("torchaudio==") or k.startswith("nvidia-"):
            continue

        # pip freeze prints an editable install as `-e <path or url>`, after a comment line
        if k.startswith('#'):
            continue
        elif k.startswith('-e '):
            v = k[3:]
            args = ['-e', v]
        elif v == "":
            non_url.append(k)
            continue
        else:
            args = [v]

        if v.startswith('file:') or '://' not in v:
            local_url.append(args)
        else:
            non_local_url.append(args)


    # restore other pips
    failed = []
    if '--pip-non-url' in options:
        # try all at once
        res = 1
        try:
            res = subprocess.check_call(make_pip_cmd(['install'] + non_url))
        except Exception:
            pass

        # fallback
        if res != 0:
            for x in non_url:
                res = 1
                try:
                    res = subprocess.check_call(make_pip_cmd(['install', '--no-deps', x]))
                except Exception:
                    pass

                if res != 0:
                    failed.append(x)

    if '--pip-non-local-url' in options:
        for x in non_local_url:
            res = 1
            try:
                res = subprocess.check_call(make_pip_cmd(['install', '--no-deps', *installer_args(x)]))
            except Exception:
                pass

            if res != 0:
                failed.append(' '.join(x))

    if '--pip-local-url' in options:
        for x in local_url:
            res = 1
            try:
                res = subprocess.check_call(make_pip_cmd(['install', '--no-deps', *installer_args(x)]))
            except Exception:
                pass

            if res != 0:
                failed.append(' '.join(x))

    print(f"Installation failed for pip packages: {failed}")
    return failed


def which_on_path(name):
    """
    the file that the directories of PATH give for the name of a command
    `shutil.which` looks in the current directory first on Windows, and takes a directory of PATH that is not absolute
    """
    names = [name]
    if os.name == 'nt':
        extensions = [x for x in os.environ.get('PATHEXT', '.COM;.EXE;.BAT;.CMD').split(os.pathsep) if x]
        if not name.lower().endswith(tuple(x.lower() for x in extensions)):
            names = [name + x for x in extensions]

    for directory in os.get_exec_path():
        for x in names:
            path = os.path.join(directory, x)
            if os.path.isabs(directory) and os.path.isfile(path) and os.access(path, os.X_OK):
                return path

    return None


def find_git_executable(git_exe, timeout=10):
    # a name without a directory is a command of PATH; GitPython would take it as a file of the current directory
    path = shutil.which(git_exe) if os.path.dirname(git_exe) else which_on_path(git_exe)
    if path is None:
        return None

    try:
        # the answer goes to a file: with a pipe, Windows waits after the time is up for every program that holds the pipe
        with tempfile.TemporaryFile() as answer:
            res = subprocess.run([path, 'version'], stdout=answer, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=timeout)
            answer.seek(0)
            is_git = res.returncode == 0 and answer.read(11) == b'git version'
    except (OSError, subprocess.SubprocessError):
        return None

    return os.path.abspath(path) if is_git else None
