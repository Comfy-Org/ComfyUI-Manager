import subprocess
import sys
import os
import traceback

import git
import json
import yaml
import requests
from tqdm.auto import tqdm
from git.remote import RemoteProgress


comfy_path = os.environ.get('COMFYUI_PATH')
git_exe_path = os.environ.get('GIT_EXE_PATH')

if comfy_path is None:
    print("\nWARN: The `COMFYUI_PATH` environment variable is not set. Assuming `custom_nodes/ComfyUI-Manager/../../` as the ComfyUI path.", file=sys.stderr)
    comfy_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def download_url(url, dest_folder, filename=None):
    # Ensure the destination folder exists
    if not os.path.exists(dest_folder):
        os.makedirs(dest_folder)

    # Extract filename from URL if not provided
    if filename is None:
        filename = os.path.basename(url)

    # Full path to save the file
    dest_path = os.path.join(dest_folder, filename)

    # Download the file
    response = requests.get(url, stream=True)
    if response.status_code == 200:
        with open(dest_path, 'wb') as file:
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    file.write(chunk)
    else:
        print(f"Failed to download file from {url}")


nodelist_path = os.path.join(os.path.dirname(__file__), "custom-node-list.json")
working_directory = os.getcwd()

if os.path.basename(working_directory) != 'custom_nodes':
    print("WARN: This script should be executed in custom_nodes dir")
    print(f"DBG: INFO {working_directory}")
    print(f"DBG: INFO {sys.argv}")
    # exit(-1)


class GitProgress(RemoteProgress):
    def __init__(self):
        super().__init__()
        self.pbar = tqdm(ascii=True)

    def update(self, op_code, cur_count, max_count=None, message=''):
        self.pbar.total = max_count
        self.pbar.n = cur_count
        self.pbar.pos = 0
        self.pbar.refresh()


def gitclone(custom_nodes_path, url, target_hash=None, repo_path=None):
    repo_name = os.path.splitext(os.path.basename(url))[0]

    if repo_path is None:
        repo_path = os.path.join(custom_nodes_path, repo_name)

    # Clone the repository from the remote URL
    repo = git.Repo.clone_from(url, repo_path, recursive=True, progress=GitProgress())

    if target_hash is not None:
        print(f"CHECKOUT: {repo_name} [{target_hash}]")
        repo.git.checkout(target_hash)
            
    repo.git.clear_cache()
    repo.close()


def gitcheck(path, do_fetch=False):
    try:
        # Fetch the latest commits from the remote repository
        repo = git.Repo(path)

        if repo.head.is_detached:
            print("CUSTOM NODE CHECK: True")
            return

        current_branch = repo.active_branch
        branch_name = current_branch.name

        remote_name = current_branch.tracking_branch().remote_name
        remote = repo.remote(name=remote_name)

        if do_fetch:
            remote.fetch()

        # Get the current commit hash and the commit hash of the remote branch
        commit_hash = repo.head.commit.hexsha

        if f'{remote_name}/{branch_name}' in repo.refs:
            remote_commit_hash = repo.refs[f'{remote_name}/{branch_name}'].object.hexsha
        else:
            print("CUSTOM NODE CHECK: True")  # non default branch is treated as updatable
            return

        # Compare the commit hashes to determine if the local repository is behind the remote repository
        if commit_hash != remote_commit_hash:
            # Get the commit dates
            commit_date = repo.head.commit.committed_datetime
            remote_commit_date = repo.refs[f'{remote_name}/{branch_name}'].object.committed_datetime

            # Compare the commit dates to determine if the local repository is behind the remote repository
            if commit_date < remote_commit_date:
                print("CUSTOM NODE CHECK: True")
        else:
            print("CUSTOM NODE CHECK: False")
    except Exception as e:
        print(e)
        print("CUSTOM NODE CHECK: Error")


def get_remote_name(repo):
    available_remotes = [remote.name for remote in repo.remotes]
    if 'origin' in available_remotes:
        return 'origin'
    elif 'upstream' in available_remotes:
        return 'upstream'
    elif len(available_remotes) > 0:
        return available_remotes[0]

    if not available_remotes:
        print(f"[ComfyUI-Manager] No remotes are configured for this repository: {repo.working_dir}")
    else:
        print(f"[ComfyUI-Manager] Available remotes in '{repo.working_dir}': ")
        for remote in available_remotes:
            print(f"- {remote}")

    return None


def switch_to_default_branch(repo):
    remote_name = get_remote_name(repo)

    try:
        if remote_name is None:
            return False

        default_branch = repo.git.symbolic_ref(f'refs/remotes/{remote_name}/HEAD').replace(f'refs/remotes/{remote_name}/', '')
        repo.git.checkout(default_branch)
        return True
    except:
        # try checkout master
        # try checkout main if failed
        try:
            repo.git.checkout(repo.heads.master)
            return True
        except:
            try:
                if remote_name is not None:
                    repo.git.checkout('-b', 'master', f'{remote_name}/master')
                    return True
            except:
                try:
                    repo.git.checkout(repo.heads.main)
                    return True
                except:
                    try:
                        if remote_name is not None:
                            repo.git.checkout('-b', 'main', f'{remote_name}/main')
                            return True
                    except:
                        pass

    print("[ComfyUI Manager] Failed to switch to the default branch")
    return False


def gitpull(path):
    # Check if the path is a git repository
    if not os.path.exists(os.path.join(path, '.git')):
        raise ValueError('Not a git repository')

    # Pull the latest changes from the remote repository
    repo = git.Repo(path)
    if repo.is_dirty():
        print(f"STASH: '{path}' is dirty.")
        repo.git.stash()

    commit_hash = repo.head.commit.hexsha
    try:
        if repo.head.is_detached:
            switch_to_default_branch(repo)

        current_branch = repo.active_branch
        branch_name = current_branch.name

        remote_name = current_branch.tracking_branch().remote_name
        remote = repo.remote(name=remote_name)

        if f'{remote_name}/{branch_name}' not in repo.refs:
            switch_to_default_branch(repo)
            current_branch = repo.active_branch
            branch_name = current_branch.name

        remote.fetch()
        if f'{remote_name}/{branch_name}' in repo.refs:
            remote_commit_hash = repo.refs[f'{remote_name}/{branch_name}'].object.hexsha
        else:
            print("CUSTOM NODE PULL: Fail")  # update fail
            return

        if commit_hash == remote_commit_hash:
            print("CUSTOM NODE PULL: None")  # there is no update
            repo.close()
            return

        remote.pull()

        repo.git.submodule('update', '--init', '--recursive')
        new_commit_hash = repo.head.commit.hexsha

        if commit_hash != new_commit_hash:
            print("CUSTOM NODE PULL: Success")  # update success
        else:
            print("CUSTOM NODE PULL: Fail")  # update fail
    except Exception as e:
        print(e)
        print("CUSTOM NODE PULL: Fail")  # unknown git error

    repo.close()


def checkout_comfyui_hash(target_hash):
    repo = git.Repo(comfy_path)
    commit_hash = repo.head.commit.hexsha

    if commit_hash != target_hash:
        try:
            print(f"CHECKOUT: ComfyUI [{target_hash}]")
            repo.git.checkout(target_hash)
        except git.GitCommandError as e:
            print(f"Error checking out the ComfyUI: {str(e)}")


def checkout_custom_node_hash(git_custom_node_infos):
    repo_name_to_url = {}

    for url in git_custom_node_infos.keys():
        repo_name = url.split('/')[-1]

        if repo_name.endswith('.git'):
            repo_name = repo_name[:-4]

        repo_name_to_url[repo_name] = url

    for path in os.listdir(working_directory):
        if path.endswith("ComfyUI-Manager"):
            continue

        fullpath = os.path.join(working_directory, path)

        if os.path.isdir(fullpath):
            is_disabled = path.endswith(".disabled")

            try:
                git_dir = os.path.join(fullpath, '.git')
                if not os.path.exists(git_dir):
                    continue

                need_checkout = False
                repo_name = os.path.basename(fullpath)

                if repo_name.endswith('.disabled'):
                    repo_name = repo_name[:-9]

                if repo_name not in repo_name_to_url:
                    if not is_disabled:
                        # should be disabled
                        print(f"DISABLE: {repo_name}")
                        new_path = fullpath + ".disabled"
                        os.rename(fullpath, new_path)
                        need_checkout = False
                else:
                    item = git_custom_node_infos[repo_name_to_url[repo_name]]
                    if item['disabled'] and is_disabled:
                        pass
                    elif item['disabled'] and not is_disabled:
                        # disable
                        print(f"DISABLE: {repo_name}")
                        new_path = fullpath + ".disabled"
                        os.rename(fullpath, new_path)

                    elif not item['disabled'] and is_disabled:
                        # enable
                        print(f"ENABLE: {repo_name}")
                        new_path = fullpath[:-9]
                        os.rename(fullpath, new_path)
                        fullpath = new_path
                        need_checkout = True
                    else:
                        need_checkout = True

                if need_checkout:
                    repo = git.Repo(fullpath)
                    commit_hash = repo.head.commit.hexsha

                    if commit_hash != item['hash']:
                        print(f"CHECKOUT: {repo_name} [{item['hash']}]")
                        repo.git.checkout(item['hash'])

            except Exception:
                print(f"Failed to restore snapshots for the custom node '{path}'")

    # clone missing
    for k, v in git_custom_node_infos.items():
        if 'ComfyUI-Manager' in k:
            continue

        if not v['disabled']:
            repo_name = k.split('/')[-1]
            if repo_name.endswith('.git'):
                repo_name = repo_name[:-4]

            path = os.path.join(working_directory, repo_name)
            if not os.path.exists(path):
                print(f"CLONE: {path}")
                gitclone(working_directory, k, target_hash=v['hash'])


def invalidate_custom_node_file(file_custom_node_infos):
    global nodelist_path

    enabled_set = set()
    for item in file_custom_node_infos:
        if not item['disabled']:
            enabled_set.add(item['filename'])

    for path in os.listdir(working_directory):
        fullpath = os.path.join(working_directory, path)

        if not os.path.isdir(fullpath) and fullpath.endswith('.py'):
            if path not in enabled_set:
                print(f"DISABLE: {path}")
                new_path = fullpath+'.disabled'
                os.rename(fullpath, new_path)

        elif not os.path.isdir(fullpath) and fullpath.endswith('.py.disabled'):
            path = path[:-9]
            if path in enabled_set:
                print(f"ENABLE: {path}")
                new_path = fullpath[:-9]
                os.rename(fullpath, new_path)

    # download missing: just support for 'copy' style
    py_to_url = {}

    with open(nodelist_path, 'r', encoding="UTF-8") as json_file:
        info = json.load(json_file)
        for item in info['custom_nodes']:
            if item['install_type'] == 'copy':
                for url in item['files']:
                    if url.endswith('.py'):
                        py = url.split('/')[-1]
                        py_to_url[py] = url

        for item in file_custom_node_infos:
            filename = item['filename']
            if not item['disabled']:
                target_path = os.path.join(working_directory, filename)

                if not os.path.exists(target_path) and filename in py_to_url:
                    url = py_to_url[filename]
                    print(f"DOWNLOAD: {filename}")
                    download_url(url, working_directory)


def apply_snapshot(path):
    try:
        if os.path.exists(path):
            if not path.endswith('.json') and not path.endswith('.yaml'):
                print(f"Snapshot file not found: `{path}`")
                print("APPLY SNAPSHOT: False")
                return None

            with open(path, 'r', encoding="UTF-8") as snapshot_file:
                if path.endswith('.json'):
                    info = json.load(snapshot_file)
                elif path.endswith('.yaml'):
                    info = yaml.load(snapshot_file, Loader=yaml.SafeLoader)
                    info = info['custom_nodes']
                else:
                    # impossible case
                    print("APPLY SNAPSHOT: False")
                    return None

                comfyui_hash = info['comfyui']
                git_custom_node_infos = info['git_custom_nodes']
                file_custom_node_infos = info['file_custom_nodes']

                if comfyui_hash:
                    checkout_comfyui_hash(comfyui_hash)
                checkout_custom_node_hash(git_custom_node_infos)
                invalidate_custom_node_file(file_custom_node_infos)

                print("APPLY SNAPSHOT: True")
                if 'pips' in info and info['pips']:
                    return info['pips']
                else:
                    return None

        print(f"Snapshot file not found: `{path}`")
        print("APPLY SNAPSHOT: False")

        return None
    except Exception as e:
        print(e)
        traceback.print_exc()
        print("APPLY SNAPSHOT: False")

        return None


def restore_pip_snapshot(pips, options):
    non_url = []
    local_url = []
    non_local_url = []
    for k, v in pips.items():
        if v == "":
            non_url.append(k)
        else:
            if v.startswith('file:'):
                local_url.append(v)
            else:
                non_local_url.append(v)

    failed = []
    if '--pip-non-url' in options:
        # try all at once
        res = 1
        try:
            res = subprocess.check_call([sys.executable, '-m', 'pip', 'install'] + non_url)
        except:
            pass

        # fallback
        if res != 0:
            for x in non_url:
                res = 1
                try:
                    res = subprocess.check_call([sys.executable, '-m', 'pip', 'install', x])
                except:
                    pass

                if res != 0:
                    failed.append(x)

    if '--pip-non-local-url' in options:
        for x in non_local_url:
            res = 1
            try:
                res = subprocess.check_call([sys.executable, '-m', 'pip', 'install', x])
            except:
                pass

            if res != 0:
                failed.append(x)

    if '--pip-local-url' in options:
        for x in local_url:
            res = 1
            try:
                res = subprocess.check_call([sys.executable, '-m', 'pip', 'install', x])
            except:
                pass

            if res != 0:
                failed.append(x)

    print(f"Installation failed for pip packages: {failed}")


def setup_environment():
    if git_exe_path is not None:
        git.Git().update_environment(GIT_PYTHON_GIT_EXECUTABLE=git_exe_path)


setup_environment()


try:
    if sys.argv[1] == "--clone":
        repo_path = None
        if len(sys.argv) > 4:
            repo_path = sys.argv[4]

        gitclone(sys.argv[2], sys.argv[3], repo_path=repo_path)
    elif sys.argv[1] == "--check":
        gitcheck(sys.argv[2], False)
    elif sys.argv[1] == "--fetch":
        gitcheck(sys.argv[2], True)
    elif sys.argv[1] == "--pull":
        gitpull(sys.argv[2])
    elif sys.argv[1] == "--apply-snapshot":
        options = set()
        for x in sys.argv:
            if x in ['--pip-non-url', '--pip-local-url', '--pip-non-local-url']:
                options.add(x)

        pips = apply_snapshot(sys.argv[2])

        if pips and len(options) > 0:
            restore_pip_snapshot(pips, options)
    sys.exit(0)
except Exception as e:
    print(e)
    sys.exit(-1)


