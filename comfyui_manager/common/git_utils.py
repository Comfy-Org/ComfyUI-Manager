import os
import configparser
import logging


GITHUB_ENDPOINT = os.getenv('GITHUB_ENDPOINT')


def is_git_repo(path: str) -> bool:
    """ Check if the path is a git repository. """
    # NOTE: Checking it through `git.Repo` must be avoided.
    #       It locks the file, causing issues on Windows.
    return os.path.exists(os.path.join(path, '.git'))


def get_commit_hash(fullpath):
    git_head = os.path.join(fullpath, '.git', 'HEAD')
    if os.path.exists(git_head):
        # a ref can be named in any bytes, so the files are read as bytes and the names compared as they are
        with open(git_head, 'rb') as f:
            line = f.readline()

            if line.startswith(b"ref: "):
                ref_name = line[5:].strip()
                ref = os.path.join(os.fsencode(fullpath), b'.git', ref_name)
                if os.path.exists(ref):
                    with open(ref, 'rb') as f2:
                        return f2.readline().strip().decode('ascii', errors='replace')

                # after `git pack-refs` or `git gc` the ref is a line of packed-refs
                packed_refs = os.path.join(fullpath, '.git', 'packed-refs')
                if os.path.exists(packed_refs):
                    with open(packed_refs, 'rb') as f2:
                        for packed in f2:
                            fields = packed.split()
                            if len(fields) == 2 and fields[1] == ref_name:
                                return fields[0].decode('ascii', errors='replace')

                return "unknown"
            else:
                # Detached HEAD: the file holds the commit hash and a newline.
                return line.strip().decode('ascii', errors='replace')

    return "unknown"


unreadable_git_configs = set()


def read_git_config(git_config_path):
    """
    parse a .git/config; None if it cannot be read
    """
    # Set `strict=False` to allow duplicate `vscode-merge-base` sections, addressing <https://github.com/ltdrdata/ComfyUI-Manager/issues/1529>
    # a url may hold a `%`, git accepts a key without a value, the file may start with a BOM,
    # and a value that is not UTF-8 does not make the others unreadable
    config = configparser.ConfigParser(strict=False, interpolation=None, allow_no_value=True)
    try:
        with open(git_config_path, encoding='utf-8-sig', errors='replace') as f:
            # for git a line that is indented more is a key of its own; the parser would take it as more of the value before it
            config.read_file(line.lstrip() for line in f)
    except (configparser.Error, AttributeError, OSError) as e:
        # AttributeError: a line more indented than the key without a value before it
        # the files are read again at every reload of the node packs
        if git_config_path not in unreadable_git_configs:
            unreadable_git_configs.add(git_config_path)
            logging.warning(f"[ComfyUI-Manager] Cannot read '{git_config_path}': {e}")
        return None

    return config


def git_url(fullpath):
    """
    resolve version of unclassified custom node based on remote url in .git/config
    """
    git_config_path = os.path.join(fullpath, '.git', 'config')

    if not os.path.exists(git_config_path):
        return None

    config = read_git_config(git_config_path)
    if config is None:
        return None

    for k, v in config.items():
        if k.startswith('remote ') and v.get('url'):
            if 'Comfy-Org/ComfyUI-Manager' in v['url']:
                return "https://github.com/ltdrdata/ComfyUI-Manager"
            return v['url']

    return None


def normalize_url(url) -> str:
    github_id = normalize_to_github_id(url)
    if github_id is not None:
        url = f"https://github.com/{github_id}"

    return url


def normalize_to_github_id(url) -> str:
    if 'github' in url or (GITHUB_ENDPOINT is not None and GITHUB_ENDPOINT in url):
        author = os.path.basename(os.path.dirname(url))

        if author.startswith('git@github.com:'):
            author = author.split(':')[1]

        repo_name = os.path.basename(url)
        if repo_name.endswith('.git'):
            repo_name = repo_name[:-4]

        return f"{author}/{repo_name}"

    # Handle short format like "author/repo" (aux_id format)
    if '/' in url and not url.startswith('http'):
        parts = url.split('/')
        if len(parts) == 2 and parts[0] and parts[1]:
            return url

    return None


def get_url_for_clone(url):
    url = normalize_url(url)

    if GITHUB_ENDPOINT is not None and url.startswith('https://github.com/'):
        url = GITHUB_ENDPOINT + url[18:] # url[18:] -> remove `https://github.com`

    return url
    