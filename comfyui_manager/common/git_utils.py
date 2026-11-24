import os
import configparser
import logging


GITHUB_ENDPOINT = os.getenv('GITHUB_ENDPOINT')


def is_git_repo(path: str) -> bool:
    """ Check if the path is a git repository. """
    # NOTE: Checking it through `git.Repo` must be avoided.
    #       It locks the file, causing issues on Windows.
    return os.path.exists(os.path.join(path, '.git'))


def file_name_of_git_for_windows(name):
    """The name that Git for Windows gives the file of a ref, whose name is `name` in bytes.

    A name that is not UTF-8 is no name of a file there: a byte that is not of a character becomes
    the character of its number, or below 0xa0 its two hex digits, as in `xutftowcsn` of compat/mingw.c of git."""
    file_name = ''
    at = 0
    while at < len(name):
        size = 1 if name[at] < 0xc2 else 2 if name[at] < 0xe0 else 3 if name[at] < 0xf0 else 4
        try:
            file_name += name[at:at + size].decode('utf-8', 'surrogatepass')
            at += size
        except UnicodeDecodeError:
            file_name += chr(name[at]) if name[at] >= 0xa0 else '%02x' % name[at]
            at += 1

    return file_name


def get_commit_hash(fullpath):
    git_dir = os.path.join(fullpath, '.git')
    try:
        with open(os.path.join(git_dir, 'HEAD'), 'rb') as f:
            line = f.readline().strip()

        if not line.startswith(b"ref:"):
            return line.decode('ascii', errors='replace')

        ref_name = line[4:].strip()
        # put together as git does it, and not with `os.path.join`, for which a name can lead elsewhere
        if os.name == 'nt':
            ref = git_dir + '/' + file_name_of_git_for_windows(ref_name)
        else:
            ref = os.fsencode(git_dir) + b'/' + ref_name
        # a folder there is no ref, as for git: a branch `feature/x` beside the unborn branch `feature`
        if os.path.isfile(ref):
            with open(ref, 'rb') as f:
                return f.readline().strip().decode('ascii', errors='replace')

        # after `git pack-refs` or `git gc` the ref is a line of packed-refs
        with open(os.path.join(git_dir, 'packed-refs'), 'rb') as f:
            for packed in f:
                fields = packed.split()
                if len(fields) == 2 and fields[1] == ref_name:
                    return fields[0].decode('ascii', errors='replace')
    except OSError:
        pass

    return "unknown"


warned_git_configs = set()


def lines_of_git_config(lines):
    """
    the lines as git takes them: a `\\` at the end of a line makes the next line more of the same value,
    and a line may be indented by any amount
    """
    whole, quoted = '', False
    for line in lines:
        line = line.rstrip('\n')
        goes_on = False
        i = 0
        while i < len(line):
            if line[i] == '\\':
                goes_on = i == len(line) - 1
                i += 1
            elif line[i] == '"':
                quoted = not quoted
            elif line[i] in '#;' and not quoted:
                break
            i += 1

        if goes_on:
            whole += line[:-1]
        else:
            yield (whole + line).lstrip() + '\n'
            whole, quoted = '', False

    if whole:
        yield whole.lstrip() + '\n'


def read_git_config(git_config_path) -> 'configparser.ConfigParser | None':
    # Set `strict=False` to allow duplicate `vscode-merge-base` sections, addressing <https://github.com/ltdrdata/ComfyUI-Manager/issues/1529>
    # a url may hold a `%`, git accepts a key without a value, the file may start with a BOM,
    # and a value that is not UTF-8 does not make the others unreadable
    config = configparser.ConfigParser(strict=False, interpolation=None, allow_no_value=True)
    try:
        with open(git_config_path, encoding='utf-8-sig', errors='replace') as f:
            # the parser would take a line that is indented more as more of the value before it
            config.read_file(lines_of_git_config(f))
    except (configparser.Error, OSError) as e:
        if git_config_path not in warned_git_configs:
            warned_git_configs.add(git_config_path)
            # the message of a parsing error holds lines of the file, and a url in them can hold a token
            reason = e.strerror if isinstance(e, OSError) else type(e).__name__
            logging.warning(f"[ComfyUI-Manager] Cannot read '{git_config_path}': {reason}")
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
    