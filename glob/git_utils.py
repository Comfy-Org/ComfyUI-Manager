import os
import configparser


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
                # detached HEAD: the file holds the sha followed by a newline;
                # without the strip the pinned hash carries that newline into
                # snapshots, and the next restore's checkout of that hash fails
                return line.strip().decode('ascii', errors='replace')

    return "unknown"


def git_url(fullpath):
    """
    resolve version of unclassified custom node based on remote url in .git/config
    """
    git_config_path = os.path.join(fullpath, '.git', 'config')

    if not os.path.exists(git_config_path):
        return None

    # Set `strict=False` to allow duplicate `vscode-merge-base` sections, addressing <https://github.com/ltdrdata/ComfyUI-Manager/issues/1529>
    config = configparser.ConfigParser(strict=False)
    config.read(git_config_path)

    for k, v in config.items():
        if k.startswith('remote ') and 'url' in v:
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

    return None


def get_url_for_clone(url):
    url = normalize_url(url)

    if GITHUB_ENDPOINT is not None and url.startswith('https://github.com/'):
        url = GITHUB_ENDPOINT + url[18:] # url[18:] -> remove `https://github.com`

    return url
    