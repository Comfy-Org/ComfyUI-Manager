import ast
import re
import os
import json
from git import Repo
import concurrent
import datetime
import concurrent.futures
import requests
import warnings
import argparse

builtin_nodes = set()

import sys

from urllib.parse import urlparse
from github import Github, Auth


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
        raise Exception(f"Failed to download file from {url}")


def parse_arguments():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description='ComfyUI Manager Node Scanner',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Standard mode
  python3 scanner.py
  python3 scanner.py --skip-update

  # Scan-only mode
  python3 scanner.py --scan-only temp-urls-clean.list
  python3 scanner.py --scan-only urls.list --temp-dir /custom/temp
  python3 scanner.py --scan-only urls.list --skip-update
        '''
    )

    parser.add_argument('--scan-only', type=str, metavar='URL_LIST_FILE',
                       help='Scan-only mode: provide URL list file (one URL per line)')
    parser.add_argument('--temp-dir', type=str, metavar='DIR',
                       help='Temporary directory for cloned repositories')
    parser.add_argument('--skip-update', action='store_true',
                       help='Skip git clone/pull operations')
    parser.add_argument('--skip-stat-update', action='store_true',
                       help='Skip GitHub stats collection')
    parser.add_argument('--skip-all', action='store_true',
                       help='Skip all update operations')

    # Backward compatibility: positional argument for temp_dir
    parser.add_argument('temp_dir_positional', nargs='?', metavar='TEMP_DIR',
                       help='(Legacy) Temporary directory path')

    args = parser.parse_args()
    return args


# Module-level variables (will be set in main if running as script)
args = None
scan_only_mode = False
url_list_file = None
temp_dir = None
skip_update = False
skip_stat_update = True
g = None


parse_cnt = 0


def extract_nodes(code_text):
    global parse_cnt

    try:
        if parse_cnt % 100 == 0:
            print(".", end="", flush=True)
        parse_cnt += 1

        code_text = re.sub(r'\\[^"\']', '', code_text)
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', category=SyntaxWarning)
            warnings.filterwarnings('ignore', category=DeprecationWarning)
            parsed_code = ast.parse(code_text)

        # Support both ast.Assign and ast.AnnAssign (for type-annotated assignments)
        assignments = (node for node in parsed_code.body if isinstance(node, (ast.Assign, ast.AnnAssign)))

        for assignment in assignments:
            # Handle ast.AnnAssign (e.g., NODE_CLASS_MAPPINGS: Type = {...})
            if isinstance(assignment, ast.AnnAssign):
                if isinstance(assignment.target, ast.Name) and assignment.target.id in ['NODE_CONFIG', 'NODE_CLASS_MAPPINGS']:
                    node_class_mappings = assignment.value
                    break
            # Handle ast.Assign (e.g., NODE_CLASS_MAPPINGS = {...})
            elif isinstance(assignment.targets[0], ast.Name) and assignment.targets[0].id in ['NODE_CONFIG', 'NODE_CLASS_MAPPINGS']:
                node_class_mappings = assignment.value
                break
        else:
            node_class_mappings = None

        if node_class_mappings:
            s = set()

            for key in node_class_mappings.keys:
                    if key is not None and isinstance(key.value, str):
                        s.add(key.value.strip())

            return s
        else:
            return set()
    except:
        return set()


def has_comfy_node_base(class_node):
    """Check if class inherits from io.ComfyNode or ComfyNode"""
    for base in class_node.bases:
        # Case 1: ComfyNode
        if isinstance(base, ast.Name) and base.id == 'ComfyNode':
            return True
        # Case 2: io.ComfyNode
        elif isinstance(base, ast.Attribute):
            if base.attr == 'ComfyNode':
                return True
    return False


def extract_keyword_value(call_node, keyword):
    """
    Extract string value of keyword argument
    Schema(node_id="MyNode") -> "MyNode"
    """
    for kw in call_node.keywords:
        if kw.arg == keyword:
            # ast.Constant (Python 3.8+)
            if isinstance(kw.value, ast.Constant):
                if isinstance(kw.value.value, str):
                    return kw.value.value
            # ast.Str (Python 3.7-) - suppress deprecation warning
            else:
                with warnings.catch_warnings():
                    warnings.filterwarnings('ignore', category=DeprecationWarning)
                    if hasattr(ast, 'Str') and isinstance(kw.value, ast.Str):
                        return kw.value.s
    return None


def is_schema_call(call_node):
    """Check if ast.Call is io.Schema() or Schema()"""
    func = call_node.func
    if isinstance(func, ast.Name) and func.id == 'Schema':
        return True
    elif isinstance(func, ast.Attribute) and func.attr == 'Schema':
        return True
    return False


def extract_node_id_from_schema(class_node):
    """
    Extract node_id from define_schema() method
    """
    for item in class_node.body:
        if isinstance(item, ast.FunctionDef) and item.name == 'define_schema':
            # Walk through function body
            for stmt in ast.walk(item):
                if isinstance(stmt, ast.Call):
                    # Check if it's Schema() call
                    if is_schema_call(stmt):
                        node_id = extract_keyword_value(stmt, 'node_id')
                        if node_id:
                            return node_id
    return None


def extract_v3_nodes(code_text):
    """
    Extract V3 node IDs using AST parsing
    Returns: set of node_id strings
    """
    global parse_cnt

    try:
        if parse_cnt % 100 == 0:
            print(".", end="", flush=True)
        parse_cnt += 1

        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', category=SyntaxWarning)
            warnings.filterwarnings('ignore', category=DeprecationWarning)
            tree = ast.parse(code_text)
    except (SyntaxError, UnicodeDecodeError):
        return set()

    nodes = set()

    # Find io.ComfyNode subclasses
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            # Check if inherits from ComfyNode
            if has_comfy_node_base(node):
                node_id = extract_node_id_from_schema(node)
                if node_id:
                    nodes.add(node_id)

    return nodes


# scan
def scan_in_file(filename, is_builtin=False):
    global builtin_nodes

    with open(filename, encoding='utf-8', errors='ignore') as file:
        code = file.read()

    # Support type annotations (e.g., NODE_CLASS_MAPPINGS: Type = {...}) and line continuations (\)
    pattern = r"_CLASS_MAPPINGS\s*(?::\s*\w+\s*)?=\s*(?:\\\s*)?{([^}]*)}"
    regex = re.compile(pattern, re.MULTILINE | re.DOTALL)

    nodes = set()
    class_dict = {}

    # V1 nodes detection
    nodes |= extract_nodes(code)

    # V3 nodes detection
    nodes |= extract_v3_nodes(code)
    code = re.sub(r'^#.*?$', '', code, flags=re.MULTILINE)

    def extract_keys(pattern, code):
        keys = re.findall(pattern, code)
        return {key.strip() for key in keys}

    def update_nodes(nodes, new_keys):
        nodes |= new_keys

    patterns = [
        r'^[^=]*_CLASS_MAPPINGS\["(.*?)"\]',
        r'^[^=]*_CLASS_MAPPINGS\[\'(.*?)\'\]',
        r'@register_node\("(.+)",\s*\".+"\)',
        r'"(\w+)"\s*:\s*{"class":\s*\w+\s*'
    ]

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {executor.submit(extract_keys, pattern, code): pattern for pattern in patterns}
        for future in concurrent.futures.as_completed(futures):
            update_nodes(nodes, future.result())

    matches = regex.findall(code)
    for match in matches:
        dict_text = match

        key_value_pairs = re.findall(r"\"([^\"]*)\"\s*:\s*([^,\n]*)", dict_text)
        for key, value in key_value_pairs:
            class_dict[key.strip()] = value.strip()

        key_value_pairs = re.findall(r"'([^']*)'\s*:\s*([^,\n]*)", dict_text)
        for key, value in key_value_pairs:
            class_dict[key.strip()] = value.strip()

        for key, value in class_dict.items():
            nodes.add(key.strip())

        update_pattern = r"_CLASS_MAPPINGS.update\s*\({([^}]*)}\)"
        update_match = re.search(update_pattern, code)
        if update_match:
            update_dict_text = update_match.group(1)
            update_key_value_pairs = re.findall(r"\"([^\"]*)\"\s*:\s*([^,\n]*)", update_dict_text)
            for key, value in update_key_value_pairs:
                class_dict[key.strip()] = value.strip()
                nodes.add(key.strip())

    metadata = {}
    lines = code.strip().split('\n')
    for line in lines:
        if line.startswith('@'):
            if line.startswith("@author:") or line.startswith("@title:") or line.startswith("@nickname:") or line.startswith("@description:"):
                key, value = line[1:].strip().split(':', 1)
                metadata[key.strip()] = value.strip()

    if is_builtin:
        builtin_nodes += set(nodes)
    else:
        for x in builtin_nodes:
            if x in nodes:
                nodes.remove(x)

    return nodes, metadata


def get_py_file_paths(dirname):
    file_paths = []
    
    for root, dirs, files in os.walk(dirname):
        if ".git" in root or "__pycache__" in root:
            continue

        for file in files:
            if file.endswith(".py"):
                file_path = os.path.join(root, file)
                file_paths.append(file_path)
    
    return file_paths


def get_nodes(target_dir):
    py_files = []
    directories = []
    
    for item in os.listdir(target_dir):
        if ".git" in item or "__pycache__" in item:
            continue

        path = os.path.abspath(os.path.join(target_dir, item))
        
        if os.path.isfile(path) and item.endswith(".py"):
            py_files.append(path)
        elif os.path.isdir(path):
            directories.append(path)
    
    return py_files, directories


def get_urls_from_list_file(list_file):
    """
    Read URLs from list file for scan-only mode

    Args:
        list_file (str): Path to URL list file (one URL per line)

    Returns:
        list of tuples: [(url, "", None, None), ...]
        Format: (url, title, preemptions, nodename_pattern)
        - title: Empty string
        - preemptions: None
        - nodename_pattern: None

    File format:
        https://github.com/owner/repo1
        https://github.com/owner/repo2
        # Comments starting with # are ignored

    Raises:
        FileNotFoundError: If list_file does not exist
    """
    if not os.path.exists(list_file):
        raise FileNotFoundError(f"URL list file not found: {list_file}")

    urls = []
    with open(list_file, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue

            # Validate URL format (basic check)
            if not (line.startswith('http://') or line.startswith('https://')):
                print(f"WARNING: Line {line_num} is not a valid URL: {line}")
                continue

            # Add URL with empty metadata
            # (url, title, preemptions, nodename_pattern)
            urls.append((line, "", None, None))

    print(f"Loaded {len(urls)} URLs from {list_file}")
    return urls


def get_git_urls_from_json(json_file):
    with open(json_file, encoding='utf-8') as file:
        data = json.load(file)

        custom_nodes = data.get('custom_nodes', [])
        git_clone_files = []
        for node in custom_nodes:
            if node.get('install_type') == 'git-clone':
                files = node.get('files', [])
                if files:
                    git_clone_files.append((files[0], node.get('title'), node.get('preemptions'), node.get('nodename_pattern')))

    git_clone_files.append(("https://github.com/comfyanonymous/ComfyUI", "ComfyUI", None, None))

    return git_clone_files


def get_py_urls_from_json(json_file):
    with open(json_file, encoding='utf-8') as file:
        data = json.load(file)

        custom_nodes = data.get('custom_nodes', [])
        py_files = []
        for node in custom_nodes:
            if node.get('install_type') == 'copy':
                files = node.get('files', [])
                if files:
                    py_files.append((files[0], node.get('title'), node.get('preemptions'), node.get('nodename_pattern')))

    return py_files


def clone_or_pull_git_repository(git_url):
    repo_name = git_url.split("/")[-1]
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]
        
    repo_dir = os.path.join(temp_dir, repo_name)

    if os.path.exists(repo_dir):
        try:
            repo = Repo(repo_dir)
            origin = repo.remote(name="origin")
            origin.pull()
            repo.git.submodule('update', '--init', '--recursive')
            print(f"Pulling {repo_name}...")
        except Exception as e:
            print(f"Failed to pull '{repo_name}': {e}")
    else:
        try:
            Repo.clone_from(git_url, repo_dir, recursive=True)
            print(f"Cloning {repo_name}...")
        except Exception as e:
            print(f"Failed to clone '{repo_name}': {e}")


def update_custom_nodes(scan_only_mode=False, url_list_file=None):
    """
    Update custom nodes by cloning/pulling repositories

    Args:
        scan_only_mode (bool): If True, use URL list file instead of custom-node-list.json
        url_list_file (str): Path to URL list file (required if scan_only_mode=True)

    Returns:
        dict: node_info mapping {repo_name: (url, title, preemptions, node_pattern)}
    """
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)

    node_info = {}

    # Select URL source based on mode
    if scan_only_mode:
        if not url_list_file:
            raise ValueError("url_list_file is required in scan-only mode")

        git_url_titles_preemptions = get_urls_from_list_file(url_list_file)
        print("\n[Scan-Only Mode]")
        print(f"  - URL source: {url_list_file}")
        print("  - GitHub stats: DISABLED")
        print(f"  - Git clone/pull: {'ENABLED' if not skip_update else 'DISABLED'}")
        print("  - Metadata: EMPTY")
    else:
        if not os.path.exists('custom-node-list.json'):
            raise FileNotFoundError("custom-node-list.json not found")

        git_url_titles_preemptions = get_git_urls_from_json('custom-node-list.json')
        print("\n[Standard Mode]")
        print("  - URL source: custom-node-list.json")
        print(f"  - GitHub stats: {'ENABLED' if not skip_stat_update else 'DISABLED'}")
        print(f"  - Git clone/pull: {'ENABLED' if not skip_update else 'DISABLED'}")
        print("  - Metadata: FULL")

    def process_git_url_title(url, title, preemptions, node_pattern):
        name = os.path.basename(url)
        if name.endswith(".git"):
            name = name[:-4]
        
        node_info[name] = (url, title, preemptions, node_pattern)
        if not skip_update:
            clone_or_pull_git_repository(url)

    def process_git_stats(git_url_titles_preemptions):
        GITHUB_STATS_CACHE_FILENAME = 'github-stats-cache.json'
        GITHUB_STATS_FILENAME = 'github-stats.json'

        github_stats = {}
        try:
            with open(GITHUB_STATS_CACHE_FILENAME, 'r', encoding='utf-8') as file:
                github_stats = json.load(file)
        except FileNotFoundError:
            pass

        def is_rate_limit_exceeded():
            return g.rate_limiting[0] <= 20

        if is_rate_limit_exceeded():
            print(f"GitHub API Rate Limit Exceeded: remained - {(g.rate_limiting_resettime - datetime.datetime.now().timestamp())/60:.2f} min")
        else:
            def renew_stat(url):
                if is_rate_limit_exceeded():
                    return

                if 'github.com' not in url:
                    return None

                print('.', end="")
                sys.stdout.flush()
                try:
                    # Parsing the URL
                    parsed_url = urlparse(url)
                    domain = parsed_url.netloc
                    path = parsed_url.path
                    path_parts = path.strip("/").split("/")
                    if len(path_parts) >= 2 and domain == "github.com":
                        owner_repo = "/".join(path_parts[-2:])
                        repo = g.get_repo(owner_repo)
                        owner = repo.owner
                        now = datetime.datetime.now(datetime.timezone.utc)
                        author_time_diff = now - owner.created_at
                        
                        last_update = repo.pushed_at.strftime("%Y-%m-%d %H:%M:%S") if repo.pushed_at else 'N/A'
                        item = {
                            "stars": repo.stargazers_count,
                            "last_update": last_update,
                            "cached_time": now.timestamp(),
                            "author_account_age_days": author_time_diff.days,
                        }
                        return url, item
                    else:
                        print(f"\nInvalid URL format for GitHub repository: {url}\n")
                except Exception as e:
                    print(f"\nERROR on {url}\n{e}")

                return None

            # resolve unresolved urls
            with concurrent.futures.ThreadPoolExecutor(11) as executor:
                futures = []
                for url, title, preemptions, node_pattern in git_url_titles_preemptions:
                    if url not in github_stats:
                        futures.append(executor.submit(renew_stat, url))

                for future in concurrent.futures.as_completed(futures):
                    url_item = future.result()
                    if url_item is not None:
                        url, item = url_item
                        github_stats[url] = item

            # renew outdated cache
            outdated_urls = []
            for k, v in github_stats.items():
                elapsed = (datetime.datetime.now().timestamp() - v['cached_time'])
                if elapsed > 60*60*12:  # 12 hours
                    outdated_urls.append(k)

            with concurrent.futures.ThreadPoolExecutor(11) as executor:
                for url in outdated_urls:
                    futures.append(executor.submit(renew_stat, url))

                for future in concurrent.futures.as_completed(futures):
                    url_item = future.result()
                    if url_item is not None:
                        url, item = url_item
                        github_stats[url] = item
                        
            with open('github-stats-cache.json', 'w', encoding='utf-8') as file:
                json.dump(github_stats, file, ensure_ascii=False, indent=4)

        with open(GITHUB_STATS_FILENAME, 'w', encoding='utf-8') as file:
            for v in github_stats.values():
                if "cached_time" in v:
                    del v["cached_time"]

            github_stats = dict(sorted(github_stats.items()))

            json.dump(github_stats, file, ensure_ascii=False, indent=4)

        print(f"Successfully written to {GITHUB_STATS_FILENAME}.")

    if not skip_stat_update:
        process_git_stats(git_url_titles_preemptions)

    # Git clone/pull for all repositories
    with concurrent.futures.ThreadPoolExecutor(11) as executor:
        for url, title, preemptions, node_pattern in git_url_titles_preemptions:
            executor.submit(process_git_url_title, url, title, preemptions, node_pattern)

    # .py file download (skip in scan-only mode - only process git repos)
    if not scan_only_mode:
        py_url_titles_and_pattern = get_py_urls_from_json('custom-node-list.json')

        def download_and_store_info(url_title_preemptions_and_pattern):
            url, title, preemptions, node_pattern = url_title_preemptions_and_pattern
            name = os.path.basename(url)
            if name.endswith(".py"):
                node_info[name] = (url, title, preemptions, node_pattern)

            try:
                download_url(url, temp_dir)
            except:
                print(f"[ERROR] Cannot download '{url}'")

        with concurrent.futures.ThreadPoolExecutor(10) as executor:
            executor.map(download_and_store_info, py_url_titles_and_pattern)

    return node_info


def gen_json(node_info, scan_only_mode=False):
    """
    Generate extension-node-map.json from scanned node information

    Args:
        node_info (dict): Repository metadata mapping
        scan_only_mode (bool): If True, exclude metadata from output
    """
    # scan from .py file
    node_files, node_dirs = get_nodes(temp_dir)

    comfyui_path = os.path.abspath(os.path.join(temp_dir, "ComfyUI"))
    # Only reorder if ComfyUI exists in the list
    if comfyui_path in node_dirs:
        node_dirs.remove(comfyui_path)
        node_dirs = [comfyui_path] + node_dirs

    data = {}
    for dirname in node_dirs:
        py_files = get_py_file_paths(dirname)
        metadata = {}

        nodes = set()
        for py in py_files:
            nodes_in_file, metadata_in_file = scan_in_file(py, dirname == "ComfyUI")
            nodes.update(nodes_in_file)
            # Include metadata from .py files in both modes
            metadata.update(metadata_in_file)
        
        dirname = os.path.basename(dirname)

        if 'Jovimetrix' in dirname:
            pass

        if len(nodes) > 0 or (dirname in node_info and node_info[dirname][3] is not None):
            nodes = list(nodes)
            nodes.sort()

            if dirname in node_info:
                git_url, title, preemptions, node_pattern = node_info[dirname]

                # Conditionally add metadata based on mode
                if not scan_only_mode:
                    # Standard mode: include all metadata
                    metadata['title_aux'] = title

                    if preemptions is not None:
                        metadata['preemptions'] = preemptions

                    if node_pattern is not None:
                        metadata['nodename_pattern'] = node_pattern
                # Scan-only mode: metadata remains empty

                data[git_url] = (nodes, metadata)
            else:
                # Scan-only mode: Repository not in node_info (expected behavior)
                # Construct URL from dirname (author_repo format)
                if '_' in dirname:
                    parts = dirname.split('_', 1)
                    git_url = f"https://github.com/{parts[0]}/{parts[1]}"
                    data[git_url] = (nodes, metadata)
                else:
                    print(f"WARN: {dirname} is removed from custom-node-list.json")

    for file in node_files:
        nodes, metadata = scan_in_file(file)

        if len(nodes) > 0 or (dirname in node_info and node_info[dirname][3] is not None):
            nodes = list(nodes)
            nodes.sort()

            file = os.path.basename(file)

            if file in node_info:
                url, title, preemptions, node_pattern = node_info[file]

                # Conditionally add metadata based on mode
                if not scan_only_mode:
                    metadata['title_aux'] = title

                    if preemptions is not None:
                        metadata['preemptions'] = preemptions

                    if node_pattern is not None:
                        metadata['nodename_pattern'] = node_pattern

                data[url] = (nodes, metadata)
            else:
                print(f"Missing info: {file}")

    # scan from node_list.json file
    extensions = [name for name in os.listdir(temp_dir) if os.path.isdir(os.path.join(temp_dir, name))]

    for extension in extensions:
        node_list_json_path = os.path.join(temp_dir, extension, 'node_list.json')
        if os.path.exists(node_list_json_path):
            # Skip if extension not in node_info (scan-only mode with limited URLs)
            if extension not in node_info:
                continue

            git_url, title, preemptions, node_pattern = node_info[extension]

            with open(node_list_json_path, 'r', encoding='utf-8') as f:
                try:
                    node_list_json = json.load(f)
                except Exception as e:
                    print(f"\nERROR: Invalid json format '{node_list_json_path}'")
                    print("------------------------------------------------------")
                    print(e)
                    print("------------------------------------------------------")
                    node_list_json = {}

            metadata_in_url = {}
            if git_url not in data:
                nodes = set()
            else:
                nodes_in_url, metadata_in_url = data[git_url]
                nodes = set(nodes_in_url)

            try:
                for x, desc in node_list_json.items():
                    nodes.add(x.strip())
            except Exception as e:
                print(f"\nERROR: Invalid json format '{node_list_json_path}'")
                print("------------------------------------------------------")
                print(e)
                print("------------------------------------------------------")
                node_list_json = {}

            # Conditionally add metadata based on mode
            if not scan_only_mode:
                metadata_in_url['title_aux'] = title

                if preemptions is not None:
                    metadata_in_url['preemptions'] = preemptions

                if node_pattern is not None:
                    metadata_in_url['nodename_pattern'] = node_pattern

            nodes = list(nodes)
            nodes.sort()
            data[git_url] = (nodes, metadata_in_url)

    json_path = "extension-node-map.json"
    with open(json_path, "w", encoding='utf-8') as file:
        json.dump(data, file, indent=4, sort_keys=True)


if __name__ == "__main__":
    # Parse arguments
    args = parse_arguments()

    # Determine mode
    scan_only_mode = args.scan_only is not None
    url_list_file = args.scan_only if scan_only_mode else None

    # Determine temp_dir
    if args.temp_dir:
        temp_dir = args.temp_dir
    elif args.temp_dir_positional:
        temp_dir = args.temp_dir_positional
    else:
        temp_dir = os.path.join(os.getcwd(), ".tmp")

    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)

    # Determine skip flags
    skip_update = args.skip_update or args.skip_all
    skip_stat_update = args.skip_stat_update or args.skip_all or scan_only_mode

    if not skip_stat_update:
        auth = Auth.Token(os.environ.get('GITHUB_TOKEN'))
        g = Github(auth=auth)
    else:
        g = None

    print("### ComfyUI Manager Node Scanner ###")

    if scan_only_mode:
        print(f"\n# [Scan-Only Mode] Processing URL list: {url_list_file}\n")
    else:
        print("\n# [Standard Mode] Updating extensions\n")

    # Update/clone repositories and collect node info
    updated_node_info = update_custom_nodes(scan_only_mode, url_list_file)

    print("\n# Generating 'extension-node-map.json'...\n")

    # Generate extension-node-map.json
    gen_json(updated_node_info, scan_only_mode)

    print("\n✅ DONE.\n")

    if scan_only_mode:
        print("Output: extension-node-map.json (node mappings only)")
    else:
        print("Output: extension-node-map.json (full metadata)")