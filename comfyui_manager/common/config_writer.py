"""Shared settings-file writer for glob and legacy."""
import configparser
import os
import tempfile

from rich import print


class DirtyTrackingConfig(dict):
    """Track keys assigned after loading the startup configuration."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dirty_keys = set()

    def __setitem__(self, key, value):
        self.dirty_keys.add(key)
        super().__setitem__(key, value)

    def update(self, *args, **kwargs):
        incoming = dict(*args, **kwargs)
        self.dirty_keys.update(incoming)
        super().update(incoming)


def write_config_merged(config_path, cached, written_config_keys):
    """Merge changed owned keys onto the latest settings on disk.

    Preserve parsed keys and values, not INI comments or formatting."""
    config = configparser.ConfigParser(strict=False)
    try:
        loaded = config.read(config_path)
    except (configparser.Error, UnicodeDecodeError) as e:
        # Preserve the existing fallback for malformed files.
        print(f"[ComfyUI-Manager] Warning: '{config_path}' could not be parsed ({e}); rewriting it from the current settings.")
        config = configparser.ConfigParser(strict=False)
    else:
        # ConfigParser.read silently skips unreadable files; do not overwrite one.
        if not loaded and os.path.exists(config_path):
            raise OSError(f"'{config_path}' exists but could not be read; refusing to overwrite it with default settings. Fix the file's permissions, then retry.")

    if config.has_section('default'):
        keys = [key for key in written_config_keys if key in cached.dirty_keys]
    else:
        config['default'] = {}
        keys = list(written_config_keys)

    section = config['default']
    for key in keys:
        section[key] = str(cached[key]).replace('\r', '').replace('\n', '').replace('\x00', '')

    directory = os.path.dirname(config_path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)

    # Replace from the same directory so readers never see a partial write.
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            'w', dir=directory or '.', prefix='.config-', suffix='.tmp', delete=False
        ) as configfile:
            tmp_path = configfile.name
            config.write(configfile)
            configfile.flush()
            os.fsync(configfile.fileno())
        # Retain the existing mode instead of the temporary file's 0600.
        if os.path.exists(config_path):
            os.chmod(tmp_path, os.stat(config_path).st_mode & 0o777)
        os.replace(tmp_path, config_path)
        tmp_path = None
    finally:
        if tmp_path is not None and os.path.exists(tmp_path):
            os.remove(tmp_path)

    # Clear only persisted keys, and only after a successful write.
    cached.dirty_keys.difference_update(keys)
