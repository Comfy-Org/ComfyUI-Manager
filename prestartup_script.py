import os
import subprocess
import sys
import atexit
import threading
import re
import locale
import platform
import json
import ast
import logging

glob_path = os.path.join(os.path.dirname(__file__), "glob")
sys.path.append(glob_path)

import security_check
import manager_util
import cm_global
import manager_downloader
from datetime import datetime
import folder_paths

security_check.security_check()

cm_global.pip_blacklist = ['torch', 'torchsde', 'torchvision']
cm_global.pip_downgrade_blacklist = ['torch', 'torchsde', 'torchvision', 'transformers', 'safetensors', 'kornia']


def skip_pip_spam(x):
    return ('Requirement already satisfied:' in x) or ("DEPRECATION: Loading egg at" in x)


message_collapses = [skip_pip_spam]
import_failed_extensions = set()
cm_global.variables['cm.on_revision_detected_handler'] = []
enable_file_logging = True


def register_message_collapse(f):
    global message_collapses
    message_collapses.append(f)


def is_import_failed_extension(name):
    global import_failed_extensions
    return name in import_failed_extensions


def check_file_logging():
    global enable_file_logging
    try:
        import configparser
        config = configparser.ConfigParser()
        config.read(manager_config_path)
        default_conf = config['default']

        if 'file_logging' in default_conf and default_conf['file_logging'].lower() == 'false':
            enable_file_logging = False
    except Exception:
        pass


check_file_logging()

comfy_path = os.environ.get('COMFYUI_PATH')
if comfy_path is None:
    comfy_path = os.path.abspath(os.path.dirname(sys.modules['__main__'].__file__))

sys.__comfyui_manager_register_message_collapse = register_message_collapse
sys.__comfyui_manager_is_import_failed_extension = is_import_failed_extension
cm_global.register_api('cm.register_message_collapse', register_message_collapse)
cm_global.register_api('cm.is_import_failed_extension', is_import_failed_extension)


comfyui_manager_path = os.path.abspath(os.path.dirname(__file__))

custom_nodes_base_path = folder_paths.get_folder_paths('custom_nodes')[0]
manager_files_path = os.path.abspath(os.path.join(folder_paths.get_user_directory(), 'default', 'ComfyUI-Manager'))
manager_pip_overrides_path = os.path.join(manager_files_path, "pip_overrides.json")
restore_snapshot_path = os.path.join(manager_files_path, "startup-scripts", "restore-snapshot.json")
manager_config_path = os.path.join(manager_files_path, 'config.ini')

cm_cli_path = os.path.join(comfyui_manager_path, "cm-cli.py")


cm_global.pip_overrides = {'numpy': 'numpy<2', 'ultralytics': 'ultralytics==8.3.40'}
if os.path.exists(manager_pip_overrides_path):
    with open(manager_pip_overrides_path, 'r', encoding="UTF-8", errors="ignore") as json_file:
        cm_global.pip_overrides = json.load(json_file)
        cm_global.pip_overrides['numpy'] = 'numpy<2'
        cm_global.pip_overrides['ultralytics'] = 'ultralytics==8.3.40'  # for security


def remap_pip_package(pkg):
    if pkg in cm_global.pip_overrides:
        res = cm_global.pip_overrides[pkg]
        print(f"[ComfyUI-Manager] '{pkg}' is remapped to '{res}'")
        return res
    else:
        return pkg


std_log_lock = threading.Lock()


def handle_stream(stream, prefix):
    stream.reconfigure(encoding=locale.getpreferredencoding(), errors='replace')
    for msg in stream:
        if prefix == '[!]' and ('it/s]' in msg or 's/it]' in msg) and ('%|' in msg or 'it [' in msg):
            if msg.startswith('100%'):
                print('\r' + msg, end="", file=sys.stderr),
            else:
                print('\r' + msg[:-1], end="", file=sys.stderr),
        else:
            if prefix == '[!]':
                print(prefix, msg, end="", file=sys.stderr)
            else:
                print(prefix, msg, end="")


def process_wrap(cmd_str, cwd_path, handler=None, env=None):
    process = subprocess.Popen(cmd_str, cwd=cwd_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)

    if handler is None:
        handler = handle_stream

    stdout_thread = threading.Thread(target=handler, args=(process.stdout, ""))
    stderr_thread = threading.Thread(target=handler, args=(process.stderr, "[!]"))

    stdout_thread.start()
    stderr_thread.start()

    stdout_thread.join()
    stderr_thread.join()

    return process.wait()


try:
    if '--port' in sys.argv:
        port_index = sys.argv.index('--port')
        if port_index + 1 < len(sys.argv):
            port = int(sys.argv[port_index + 1])
            postfix = f"_{port}"
        else:
            postfix = ""
    else:
        postfix = ""

    # Logger setup
    log_path_base = None
    if enable_file_logging:
        log_path_base = os.path.join(folder_paths.user_directory, 'comfyui')

        if os.path.exists(f"{log_path_base}{postfix}.log"):
            if os.path.exists(f"{log_path_base}{postfix}.prev.log"):
                if os.path.exists(f"{log_path_base}{postfix}.prev2.log"):
                    os.remove(f"{log_path_base}{postfix}.prev2.log")
                os.rename(f"{log_path_base}{postfix}.prev.log", f"{log_path_base}{postfix}.prev2.log")
            os.rename(f"{log_path_base}{postfix}.log", f"{log_path_base}{postfix}.prev.log")

        log_file = open(f"{log_path_base}{postfix}.log", "w", encoding="utf-8", errors="ignore")

    log_lock = threading.Lock()

    original_stdout = sys.stdout
    original_stderr = sys.stderr

    if original_stdout.encoding.lower() == 'utf-8':
        write_stdout = original_stdout.write
        write_stderr = original_stderr.write
    else:
        def wrapper_stdout(msg):
            original_stdout.write(msg.encode('utf-8').decode(original_stdout.encoding, errors="ignore"))
            
        def wrapper_stderr(msg):
            original_stderr.write(msg.encode('utf-8').decode(original_stderr.encoding, errors="ignore"))

        write_stdout = wrapper_stdout
        write_stderr = wrapper_stderr

    pat_tqdm = r'\d+%.*\[(.*?)\]'
    pat_import_fail = r'seconds \(IMPORT FAILED\):(.*)$'

    is_start_mode = True


    class ComfyUIManagerLogger:
        def __init__(self, is_stdout):
            self.is_stdout = is_stdout
            self.encoding = "utf-8"
            self.last_char = ''

        def fileno(self):
            try:
                if self.is_stdout:
                    return original_stdout.fileno()
                else:
                    return original_stderr.fileno()
            except AttributeError:
                # Handle error
                raise ValueError("The object does not have a fileno method")

        def isatty(self):
            return False

        def write(self, message):
            global is_start_mode

            if any(f(message) for f in message_collapses):
                return

            if is_start_mode:
                match = re.search(pat_import_fail, message)
                if match:
                    import_failed_extensions.add(match.group(1).strip())

                if 'Starting server' in message:
                    is_start_mode = False

            if not self.is_stdout:
                match = re.search(pat_tqdm, message)
                if match:
                    message = re.sub(r'([#|])\d', r'\1▌', message)
                    message = re.sub('#', '█', message)
                    if '100%' in message:
                        self.sync_write(message)
                    else:
                        write_stderr(message)
                        original_stderr.flush()
                else:
                    self.sync_write(message)
            else:
                self.sync_write(message)

        def sync_write(self, message, file_only=False):
            with log_lock:
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                if self.last_char != '\n':
                    log_file.write(message)
                else:
                    log_file.write(f"[{timestamp}] {message}")
                log_file.flush()
                self.last_char = message if message == '' else message[-1]

            if not file_only:
                with std_log_lock:
                    if self.is_stdout:
                        write_stdout(message)
                        original_stdout.flush()
                    else:
                        write_stderr(message)
                        original_stderr.flush()

        def flush(self):
            log_file.flush()

            with std_log_lock:
                if self.is_stdout:
                    original_stdout.flush()
                else:
                    original_stderr.flush()

        def close(self):
            self.flush()

        def reconfigure(self, *args, **kwargs):
            pass

        # You can close through sys.stderr.close_log()
        def close_log(self):
            sys.stderr = original_stderr
            sys.stdout = original_stdout
            log_file.close()
            
    def close_log():
        sys.stderr = original_stderr
        sys.stdout = original_stdout
        log_file.close()


    if enable_file_logging:
        sys.stdout = ComfyUIManagerLogger(True)
        stderr_wrapper = ComfyUIManagerLogger(False)
        sys.stderr = stderr_wrapper

        atexit.register(close_log)
    else:
        sys.stdout.close_log = lambda: None
        stderr_wrapper = None


    class LoggingHandler(logging.Handler):
        def emit(self, record):
            global is_start_mode

            message = record.getMessage()

            if is_start_mode:
                match = re.search(pat_import_fail, message)
                if match:
                    import_failed_extensions.add(match.group(1).strip())

                if 'Starting server' in message:
                    is_start_mode = False

            if stderr_wrapper:
                stderr_wrapper.sync_write(message+'\n', file_only=True)


    logging.getLogger().addHandler(LoggingHandler())


except Exception as e:
    print(f"[ComfyUI-Manager] Logging failed: {e}")


try:
    import git  # noqa: F401
    import toml  # noqa: F401
except ModuleNotFoundError:
    my_path = os.path.dirname(__file__)
    requirements_path = os.path.join(my_path, "requirements.txt")

    print("## ComfyUI-Manager: installing dependencies. (GitPython)")
    try:
        result = subprocess.check_output([sys.executable, '-s', '-m', 'pip', 'install', '-r', requirements_path])
    except subprocess.CalledProcessError:
        print("## [ERROR] ComfyUI-Manager: Attempting to reinstall dependencies using an alternative method.")
        try:
            result = subprocess.check_output([sys.executable, '-s', '-m', 'pip', 'install', '--user', '-r', requirements_path])
        except subprocess.CalledProcessError:
            print("## [ERROR] ComfyUI-Manager: Failed to install the GitPython package in the correct Python environment. Please install it manually in the appropriate environment. (You can seek help at https://app.element.io/#/room/%23comfyui_space%3Amatrix.org)")

try:
    print("## ComfyUI-Manager: installing dependencies done.")
except:
    # maybe we should sys.exit() here? there is at least two screens worth of error messages still being pumped after our error messages
    print("## [ERROR] ComfyUI-Manager: GitPython package seems to be installed, but failed to load somehow. Make sure you have a working git client installed")


print("** ComfyUI startup time:", datetime.now())
print("** Platform:", platform.system())
print("** Python version:", sys.version)
print("** Python executable:", sys.executable)
print("** ComfyUI Path:", comfy_path)
print("** User directory:", folder_paths.user_directory)
print("** ComfyUI-Manager config path:", manager_config_path)


if log_path_base is not None:
    print("** Log path:", os.path.abspath(f'{log_path_base}.log'))
else:
    print("** Log path: file logging is disabled")


def read_downgrade_blacklist():
    try:
        import configparser
        config = configparser.ConfigParser()
        config.read(manager_config_path)
        default_conf = config['default']

        if 'downgrade_blacklist' in default_conf:
            items = default_conf['downgrade_blacklist'].split(',')
            items = [x.strip() for x in items if x != '']
            cm_global.pip_downgrade_blacklist += items
            cm_global.pip_downgrade_blacklist = list(set(cm_global.pip_downgrade_blacklist))
    except:
        pass


read_downgrade_blacklist()


def check_bypass_ssl():
    try:
        import configparser
        import ssl
        config = configparser.ConfigParser()
        config.read(manager_config_path)
        default_conf = config['default']

        if 'bypass_ssl' in default_conf and default_conf['bypass_ssl'].lower() == 'true':
            print(f"[ComfyUI-Manager] WARN: Unsafe - SSL verification bypass option is Enabled. (see {manager_config_path})")
            ssl._create_default_https_context = ssl._create_unverified_context  # SSL certificate error fix.
    except Exception:
        pass


check_bypass_ssl()


# Perform install
processed_install = set()
script_list_path = os.path.join(folder_paths.user_directory, "default", "ComfyUI-Manager", "startup-scripts", "install-scripts.txt")
pip_fixer = manager_util.PIPFixer(manager_util.get_installed_packages())


def is_installed(name):
    name = name.strip()

    if name.startswith('#'):
        return True

    pattern = r'([^<>!=]+)([<>!=]=?)([0-9.a-zA-Z]*)'
    match = re.search(pattern, name)

    if match:
        name = match.group(1)

    if name in cm_global.pip_blacklist:
        return True

    if name in cm_global.pip_downgrade_blacklist:
        pips = manager_util.get_installed_packages()

        if match is None:
            if name in pips:
                return True
        elif match.group(2) in ['<=', '==', '<']:
            if name in pips:
                if manager_util.StrictVersion(pips[name]) >= manager_util.StrictVersion(match.group(3)):
                    print(f"[ComfyUI-Manager] skip black listed pip installation: '{name}'")
                    return True

    pkg = manager_util.get_installed_packages().get(name.lower())
    if pkg is None:
        return False  # update if not installed

    if match is None:
        return True   # don't update if version is not specified

    if match.group(2) in ['>', '>=']:
        if manager_util.StrictVersion(pkg) < manager_util.StrictVersion(match.group(3)):
            return False
        elif manager_util.StrictVersion(pkg) > manager_util.StrictVersion(match.group(3)):
            print(f"[SKIP] Downgrading pip package isn't allowed: {name.lower()} (cur={pkg})")

    if match.group(2) == '==':
        if manager_util.StrictVersion(pkg) < manager_util.StrictVersion(match.group(3)):
            return False

    if match.group(2) == '~=':
        if manager_util.StrictVersion(pkg) == manager_util.StrictVersion(match.group(3)):
            return False

    return True       # prevent downgrade


if os.path.exists(restore_snapshot_path):
    try:
        cloned_repos = []

        def msg_capture(stream, prefix):
            stream.reconfigure(encoding=locale.getpreferredencoding(), errors='replace')
            for msg in stream:
                if msg.startswith("CLONE: "):
                    cloned_repos.append(msg[7:])
                    if prefix == '[!]':
                        print(prefix, msg, end="", file=sys.stderr)
                    else:
                        print(prefix, msg, end="")

                elif prefix == '[!]' and ('it/s]' in msg or 's/it]' in msg) and ('%|' in msg or 'it [' in msg):
                    if msg.startswith('100%'):
                        print('\r' + msg, end="", file=sys.stderr),
                    else:
                        print('\r'+msg[:-1], end="", file=sys.stderr),
                else:
                    if prefix == '[!]':
                        print(prefix, msg, end="", file=sys.stderr)
                    else:
                        print(prefix, msg, end="")

        print("[ComfyUI-Manager] Restore snapshot.")
        new_env = os.environ.copy()
        new_env["COMFYUI_PATH"] = comfy_path

        cmd_str = [sys.executable, cm_cli_path, 'restore-snapshot', restore_snapshot_path]
        exit_code = process_wrap(cmd_str, custom_nodes_base_path, handler=msg_capture, env=new_env)

        if exit_code != 0:
            print("[ComfyUI-Manager] Restore snapshot failed.")
        else:
            print("[ComfyUI-Manager] Restore snapshot done.")

    except Exception as e:
        print(e)
        print("[ComfyUI-Manager] Restore snapshot failed.")

    os.remove(restore_snapshot_path)


def execute_lazy_install_script(repo_path, executable):
    global processed_install

    install_script_path = os.path.join(repo_path, "install.py")
    requirements_path = os.path.join(repo_path, "requirements.txt")

    if os.path.exists(requirements_path):
        print(f"Install: pip packages for '{repo_path}'")
        with open(requirements_path, "r") as requirements_file:
            for line in requirements_file:
                package_name = remap_pip_package(line.strip())
                if package_name and not is_installed(package_name):
                    if '--index-url' in package_name:
                        s = package_name.split('--index-url')
                        install_cmd = [sys.executable, "-m", "pip", "install", s[0].strip(), '--index-url', s[1].strip()]
                    else:
                        install_cmd = [sys.executable, "-m", "pip", "install", package_name]

                    process_wrap(install_cmd, repo_path)

    if os.path.exists(install_script_path) and f'{repo_path}/install.py' not in processed_install:
        processed_install.add(f'{repo_path}/install.py')
        print(f"Install: install script for '{repo_path}'")
        install_cmd = [executable, "install.py"]

        new_env = os.environ.copy()
        new_env["COMFYUI_PATH"] = comfy_path
        process_wrap(install_cmd, repo_path, env=new_env)


def execute_lazy_cnr_switch(target, zip_url, from_path, to_path, no_deps, custom_nodes_path):
    import uuid
    import shutil

    # 1. download
    archive_name = f"CNR_temp_{str(uuid.uuid4())}.zip"  # should be unpredictable name - security precaution
    download_path = os.path.join(custom_nodes_path, archive_name)
    manager_downloader.download_url(zip_url, custom_nodes_path, archive_name)

    # 2. extract files into <node_id>@<cur_ver>
    extracted = manager_util.extract_package_as_zip(download_path, from_path)
    os.remove(download_path)

    if extracted is None:
        if len(os.listdir(from_path)) == 0:
            shutil.rmtree(from_path)

        print(f'Empty archive file: {target}')
        return False


    # 3. calculate garbage files (.tracking - extracted)
    tracking_info_file = os.path.join(from_path, '.tracking')
    prev_files = set()
    with open(tracking_info_file, 'r') as f:
        for line in f:
            prev_files.add(line.strip())
    garbage = prev_files.difference(extracted)
    garbage = [os.path.join(custom_nodes_path, x) for x in garbage]

    # 4-1. remove garbage files
    for x in garbage:
        if os.path.isfile(x):
            os.remove(x)

    # 4-2. remove garbage dir if empty
    for x in garbage:
        if os.path.isdir(x):
            if not os.listdir(x):
                os.rmdir(x)

    # 5. rename dir name <node_id>@<prev_ver> ==> <node_id>@<cur_ver>
    print(f"'{from_path}' is moved to '{to_path}'")
    shutil.move(from_path, to_path)

    # 6. create .tracking file
    tracking_info_file = os.path.join(to_path, '.tracking')
    with open(tracking_info_file, "w", encoding='utf-8') as file:
        file.write('\n'.join(list(extracted)))


def execute_migration(moves):
    import shutil
    for x in moves:
        if os.path.exists(x[0]) and not os.path.exists(x[1]):
            shutil.move(x[0], x[1])
            print(f"[ComfyUI-Manager] MIGRATION: '{x[0]}' -> '{x[1]}'")


# Check if script_list_path exists
if os.path.exists(script_list_path):
    print("\n#######################################################################")
    print("[ComfyUI-Manager] Starting dependency installation/(de)activation for the extension\n")

    executed = set()
    # Read each line from the file and convert it to a list using eval
    with open(script_list_path, 'r', encoding="UTF-8", errors="ignore") as file:
        for line in file:
            if line in executed:
                continue

            executed.add(line)

            try:
                script = ast.literal_eval(line)

                if script[1].startswith('#') and script[1] != '#FORCE':
                    if script[1] == "#LAZY-INSTALL-SCRIPT":
                        execute_lazy_install_script(script[0], script[2])

                    elif script[1] == "#LAZY-CNR-SWITCH-SCRIPT":
                        execute_lazy_cnr_switch(script[0], script[2], script[3], script[4], script[5], script[6])
                        execute_lazy_install_script(script[3], script[7])

                    elif script[1] == "#LAZY-MIGRATION":
                        execute_migration(script[2])

                elif os.path.exists(script[0]):
                    if script[1] == "#FORCE":
                        del script[1]
                    else:
                        if 'pip' in script[1:] and 'install' in script[1:] and is_installed(script[-1]):
                            continue

                    print(f"\n## ComfyUI-Manager: EXECUTE => {script[1:]}")
                    print(f"\n## Execute install/(de)activation script for '{script[0]}'")

                    new_env = os.environ.copy()
                    new_env["COMFYUI_PATH"] = comfy_path
                    exit_code = process_wrap(script[1:], script[0], env=new_env)

                    if exit_code != 0:
                        print(f"install/(de)activation script failed: {script[0]}")
                else:
                    print(f"\n## ComfyUI-Manager: CANCELED => {script[1:]}")

            except Exception as e:
                print(f"[ERROR] Failed to execute install/(de)activation script: {line} / {e}")

    # Remove the script_list_path file
    if os.path.exists(script_list_path):
        os.remove(script_list_path)
        
    print("\n[ComfyUI-Manager] Startup script completed.")
    print("#######################################################################\n")

pip_fixer.fix_broken()

del processed_install
del pip_fixer
manager_util.clear_pip_cache()


def check_windows_event_loop_policy():
    try:
        import configparser
        config = configparser.ConfigParser()
        config.read(manager_config_path)
        default_conf = config['default']

        if 'windows_selector_event_loop_policy' in default_conf and default_conf['windows_selector_event_loop_policy'].lower() == 'true':
            try:
                import asyncio
                import asyncio.windows_events
                asyncio.set_event_loop_policy(asyncio.windows_events.WindowsSelectorEventLoopPolicy())
                print("[ComfyUI-Manager] Windows event loop policy mode enabled")
            except Exception as e:
                print(f"[ComfyUI-Manager] WARN: Windows initialization fail: {e}")
    except Exception:
        pass


if platform.system() == 'Windows':
    check_windows_event_loop_policy()
