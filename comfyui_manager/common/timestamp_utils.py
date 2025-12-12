"""
Robust timestamp utilities with datetime fallback.

Some environments (especially Mac) have issues with the datetime module
due to local file name conflicts or Homebrew Python module path issues.
"""

import logging
import time as time_module
import uuid

_datetime_available = None
_dt_datetime = None


def _init_datetime():
    """Initialize datetime availability check (lazy, once)."""
    global _datetime_available, _dt_datetime
    if _datetime_available is not None:
        return

    try:
        import datetime as dt
        if hasattr(dt, 'datetime'):
            from datetime import datetime as dt_datetime
            _dt_datetime = dt_datetime
            _datetime_available = True
            return
    except Exception as e:
        logging.debug(f"[ComfyUI-Manager] datetime import failed: {e}")

    _datetime_available = False
    logging.warning("[ComfyUI-Manager] datetime unavailable, using time module fallback")


def current_timestamp() -> str:
    """
    Get current timestamp for logging.
    Format: YYYY-MM-DD HH:MM:SS.mmm (or Unix timestamp if fallback)
    """
    _init_datetime()
    if _datetime_available:
        return _dt_datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    return str(time_module.time()).split('.')[0]


def get_timestamp_for_filename() -> str:
    """
    Get timestamp suitable for filenames.
    Format: YYYYMMDD_HHMMSS
    """
    _init_datetime()
    if _datetime_available:
        return _dt_datetime.now().strftime('%Y%m%d_%H%M%S')
    return time_module.strftime('%Y%m%d_%H%M%S')


def get_timestamp_for_path() -> str:
    """
    Get timestamp for path/directory names.
    Format: YYYY-MM-DD_HH-MM-SS
    """
    _init_datetime()
    if _datetime_available:
        return _dt_datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    return time_module.strftime('%Y-%m-%d_%H-%M-%S')


def get_backup_branch_name(repo=None) -> str:
    """
    Get backup branch name with current timestamp.
    Format: backup_YYYYMMDD_HHMMSS (or backup_YYYYMMDD_HHMMSS_N if exists)

    Args:
        repo: Optional git.Repo object. If provided, checks for name collisions
              and adds sequential suffix if needed.

    Returns:
        Unique backup branch name.
    """
    base_name = f'backup_{get_timestamp_for_filename()}'

    if repo is None:
        return base_name

    # Check if branch exists
    try:
        existing_branches = {b.name for b in repo.heads}
    except Exception:
        return base_name

    if base_name not in existing_branches:
        return base_name

    # Add sequential suffix
    for i in range(1, 100):
        new_name = f'{base_name}_{i}'
        if new_name not in existing_branches:
            return new_name

    # Ultimate fallback: use UUID (very unlikely to reach here)
    return f'{base_name}_{uuid.uuid4().hex[:6]}'


def get_now():
    """
    Get current datetime object.
    Returns datetime.now() if available, otherwise a FakeDatetime object
    that supports basic operations (timestamp(), strftime()).
    """
    _init_datetime()
    if _datetime_available:
        return _dt_datetime.now()

    # Fallback: return object with basic datetime-like interface
    t = time_module.localtime()

    class FakeDatetime:
        def timestamp(self):
            return time_module.time()

        def strftime(self, fmt):
            return time_module.strftime(fmt, t)

        def isoformat(self):
            return time_module.strftime('%Y-%m-%dT%H:%M:%S', t)

    return FakeDatetime()


def get_unix_timestamp() -> float:
    """Get current Unix timestamp."""
    _init_datetime()
    if _datetime_available:
        return _dt_datetime.now().timestamp()
    return time_module.time()
