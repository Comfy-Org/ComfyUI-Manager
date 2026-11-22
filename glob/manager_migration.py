"""
ComfyUI-Manager migration module.
Handles migration from legacy paths to new __manager path structure.
"""

import os
import configparser

# Startup notices for notice board
startup_notices = []  # List of (message, level) tuples


def add_startup_notice(message, level='warning'):
    """Add a notice to be displayed on Manager notice board.

    Args:
        message: HTML-formatted message string
        level: 'warning', 'error', 'info'
    """
    global startup_notices
    startup_notices.append((message, level))


# Cache for API check (computed once per session)
_cached_has_system_user_api = None


def has_system_user_api():
    """Check if ComfyUI has the System User Protection API (PR #10966).

    Result is cached for performance.
    """
    global _cached_has_system_user_api
    if _cached_has_system_user_api is None:
        try:
            import folder_paths
            _cached_has_system_user_api = hasattr(folder_paths, 'get_system_user_directory')
        except Exception:
            _cached_has_system_user_api = False
    return _cached_has_system_user_api


def get_manager_path(user_dir):
    """Get the appropriate manager files path based on ComfyUI version.

    Returns:
        str: manager_files_path
    """
    if has_system_user_api():
        return os.path.abspath(os.path.join(user_dir, '__manager'))
    else:
        return os.path.abspath(os.path.join(user_dir, 'default', 'ComfyUI-Manager'))


def run_migration_checks(user_dir, manager_files_path):
    """Run all migration and security checks.

    Call this after get_manager_path() to handle:
    - Legacy config migration (new ComfyUI)
    - Legacy backup notification (every startup)
    - Suspicious directory detection (old ComfyUI)
    - Outdated ComfyUI warning (old ComfyUI)
    """
    if has_system_user_api():
        migrated = migrate_legacy_config(user_dir, manager_files_path)
        # Only check for legacy backup if migration didn't just happen
        # (migration already shows backup location in its message)
        if not migrated:
            check_legacy_backup(manager_files_path)
    else:
        check_suspicious_manager(user_dir)
        warn_outdated_comfyui()


LEGACY_BACKUP_NAME = '.legacy-manager-backup'


def check_legacy_backup(manager_files_path):
    """Check for legacy backup and notify user to verify and remove it.

    This runs on every startup to remind users about pending legacy backup.
    """
    if not os.path.isdir(manager_files_path):
        return

    backup_dirs = [os.path.join(manager_files_path, name) for name in sorted(os.listdir(manager_files_path))
                   if name.startswith(LEGACY_BACKUP_NAME)]
    if not backup_dirs:
        return

    # Terminal output
    print("\n" + "-"*70)
    print("[ComfyUI-Manager] NOTICE: Legacy backup exists")
    print("  - Your old Manager data was backed up to:")
    for backup_dir in backup_dirs:
        print(f"      {backup_dir}")
    print("  - Please verify and remove it when no longer needed.")
    print("-"*70 + "\n")

    # Notice board output
    add_startup_notice(
        "Legacy ComfyUI-Manager data backup exists. Please verify and remove when no longer needed. See terminal for details.",
        level='info'
    )


def check_suspicious_manager(user_dir):
    """Check for suspicious __manager directory on old ComfyUI.

    On old ComfyUI without System User API, if __manager exists with low security,
    warn the user to verify manually.

    Returns:
        bool: True if suspicious setup detected
    """
    if has_system_user_api():
        return False  # Not suspicious on new ComfyUI

    suspicious_path = os.path.abspath(os.path.join(user_dir, '__manager'))
    if not os.path.exists(suspicious_path):
        return False

    config_path = os.path.join(suspicious_path, 'config.ini')
    if not os.path.exists(config_path):
        return False

    config = configparser.ConfigParser(interpolation=None)
    config.read(config_path)
    sec_level = config.get('default', 'security_level', fallback='normal').lower()

    if sec_level in ['weak', 'normal-']:
        # Terminal output
        print("\n" + "!"*70)
        print("[ComfyUI-Manager] ERROR: Suspicious path detected!")
        print(f"  - '__manager' exists with low security level: '{sec_level}'")
        print("  - Please verify manually:")
        print(f"      {config_path}")
        print("!"*70 + "\n")

        # Notice board output
        add_startup_notice(
            "[Security Alert] Suspicious path detected. See terminal log for details.",
            level='error'
        )
        return True

    return False


def warn_outdated_comfyui():
    """Warn user about outdated ComfyUI without System User API."""
    if has_system_user_api():
        return

    # Terminal output
    print("\n" + "!"*70)
    print("[ComfyUI-Manager] ERROR: ComfyUI version is outdated!")
    print("  - Every operation but the update of ComfyUI is blocked for security.")
    print("  - ComfyUI update is still allowed.")
    print("  - Please update ComfyUI to use Manager normally.")
    print("!"*70 + "\n")

    # Notice board output
    add_startup_notice(
        "[Security Alert] ComfyUI outdated. Everything but its update is blocked.<BR>"
        "Update ComfyUI for normal operation.",
        level='error'
    )


def migrate_legacy_config(user_dir, manager_files_path):
    """Migrate ONLY config.ini to new __manager path if needed.

    IMPORTANT: Only config.ini is migrated. Other files (snapshots, cache, etc.)
    are NOT migrated - users must recreate them.

    Scenarios:
    1. Legacy exists, New doesn't exist → Migrate config.ini
    2. Legacy exists, New exists → First update after upgrade
       - Rename legacy to .backup
    3. Legacy doesn't exist → No migration needed

    Returns:
        bool: True if migration was performed
    """
    if not has_system_user_api():
        return False

    legacy_dir = os.path.join(user_dir, 'default', 'ComfyUI-Manager')
    legacy_config = os.path.join(legacy_dir, 'config.ini')
    new_config = os.path.join(manager_files_path, 'config.ini')

    if not os.path.exists(legacy_dir):
        return False  # No legacy directory, nothing to migrate

    # IMPORTANT: Check for config.ini existence, not just directory
    # (because makedirs() creates __manager before this function is called)

    # Case: Both configs exist (first update after ComfyUI upgrade)
    # This means user ran new ComfyUI at least once, creating __manager/config.ini
    if os.path.exists(legacy_config) and os.path.exists(new_config):
        _handle_first_update_migration(user_dir, legacy_dir, manager_files_path)
        return True

    # Case: Legacy config exists but new config doesn't (normal migration)
    # This is the first run after ComfyUI upgrade
    if os.path.exists(legacy_config) and not os.path.exists(new_config):
        pass  # Continue with normal migration below
    else:
        return False

    # Terminal output
    print("\n" + "-"*70)
    print("[ComfyUI-Manager] NOTICE: Legacy config.ini detected")
    print(f"  - Old: {legacy_config}")
    print(f"  - New: {new_config}")
    print("  - Migrating config.ini only (other files are NOT migrated).")
    print("  - Security level below 'normal' will be raised.")
    print("  - Settings that permit installs or change the channel are not migrated.")
    print("-"*70 + "\n")

    _migrate_config_with_security_check(legacy_config, new_config)

    # Move legacy directory to backup
    _move_legacy_to_backup(legacy_dir, manager_files_path)

    return True


def _handle_first_update_migration(user_dir, legacy_dir, manager_files_path):
    """Handle first ComfyUI update when both legacy and new directories exist.

    This scenario happens when:
    - User was on old ComfyUI (using default/ComfyUI-Manager)
    - ComfyUI was updated (now has System User API)
    - Manager already created __manager on first new run
    - But legacy directory still exists
    """
    # Terminal output
    print("\n" + "-"*70)
    print("[ComfyUI-Manager] NOTICE: First update after ComfyUI upgrade detected")
    print("  - Both legacy and new directories exist.")
    print("-"*70 + "\n")

    # Move legacy to backup inside __manager
    _move_legacy_to_backup(legacy_dir, manager_files_path)


def _move_legacy_to_backup(legacy_dir, manager_files_path):
    """Move legacy directory to backup inside __manager.

    Returns:
        str: Path to backup directory if successful, None if failed
    """
    import shutil

    backup_dir = os.path.join(manager_files_path, LEGACY_BACKUP_NAME)
    count = 1
    while os.path.exists(backup_dir):
        count += 1
        backup_dir = os.path.join(manager_files_path, f'{LEGACY_BACKUP_NAME}-{count}')

    try:
        shutil.move(legacy_dir, backup_dir)

        # Terminal output (full paths shown here only)
        print("\n" + "-"*70)
        print("[ComfyUI-Manager] NOTICE: Legacy settings migrated")
        print(f"  - Old location: {legacy_dir}")
        print(f"  - Backed up to: {backup_dir}")
        print("  - Please verify and remove the backup when no longer needed.")
        print("-"*70 + "\n")

        # Notice board output (no full paths for security)
        add_startup_notice(
            "Legacy ComfyUI-Manager data migrated. See terminal for details.",
            level='info'
        )
        return backup_dir
    except Exception as e:
        copy_failed = isinstance(e, shutil.Error)
        if copy_failed:
            shutil.rmtree(backup_dir, ignore_errors=True)

        print(f"[ComfyUI-Manager] WARNING: Failed to backup legacy directory: {str(e)!r}")
        add_startup_notice(
            "[MIGRATION] Failed to backup legacy directory. See terminal for details.",
            level='warning'
        )
        return None


# The settings that are carried over from config.ini of the legacy path. That file could be written
# through ComfyUI's /userdata, so a setting that permits an install or changes where Manager
# fetches from, and one that is not known here, is left behind.
MIGRATED_SETTINGS = {
    'security_level', 'network_mode', 'db_mode', 'preview_method', 'share_option', 'component_policy',
    'update_policy', 'use_uv', 'file_logging', 'always_lazy_install', 'default_cache_as_channel_url',
    'model_download_by_agent', 'downgrade_blacklist', 'windows_selector_event_loop_policy',
}

VALUES_WRITTEN_BY_DEFAULT = {'false', '', 'https://raw.githubusercontent.com/ltdrdata/comfyui-manager/main'}


def _migrate_config_with_security_check(legacy_path, new_path):
    legacy = configparser.ConfigParser(interpolation=None)
    try:
        legacy.read(legacy_path)
    except Exception as e:
        print(f"[ComfyUI-Manager] WARNING: Failed to parse config.ini: {e}")
        print("  - Creating fresh config with default settings.")
        add_startup_notice(
            "[MIGRATION] Failed to parse legacy config. Using defaults.",
            level='warning'
        )
        return  # Skip migration, let Manager create fresh config

    config = configparser.ConfigParser(interpolation=None)
    if 'default' in legacy:
        settings = dict(legacy.items('default'))
        config['default'] = {key: value for key, value in settings.items() if key in MIGRATED_SETTINGS}
        not_migrated = sorted(key for key, value in settings.items()
                              if key not in MIGRATED_SETTINGS and value.lower() not in VALUES_WRITTEN_BY_DEFAULT)

        if not_migrated:
            print("\n" + "="*70)
            print("[ComfyUI-Manager] WARNING: Settings not migrated")
            print(f"  - {not_migrated!r}")
            print("  - The legacy config.ini was not protected, so these are back at their defaults.")
            print(f"  - Set them again in {new_path} if you need them.")
            print("="*70 + "\n")

            add_startup_notice(
                f"[MIGRATION] Settings of the legacy config.ini that were not migrated: {len(not_migrated)}.<BR>"
                "That file was not protected, so they are back at their defaults. See terminal for details.",
                level='warning'
            )

    # Security level hierarchy: strong > normal > normal- > weak
    # Default is 'normal', only raise if below default
    if 'default' in config:
        current_level = config['default'].get('security_level', 'normal').lower()
        below_default_levels = ['weak', 'normal-']

        if current_level in below_default_levels:
            config['default']['security_level'] = 'normal'

            # Terminal output
            print("\n" + "="*70)
            print("[ComfyUI-Manager] WARNING: Security level adjusted")
            print(f"  - Previous: '{current_level}' → New: 'normal'")
            print("  - Raised to prevent unauthorized remote access.")
            print("="*70 + "\n")

            # Notice board output
            add_startup_notice(
                f"[MIGRATION] Security level raised: '{current_level}' → 'normal'.<BR>"
                "To prevent unauthorized remote access.",
                level='warning'
            )
        elif current_level not in ('strong', 'normal'):
            config['default']['security_level'] = 'normal'

            print("\n" + "="*70)
            print("[ComfyUI-Manager] WARNING: Security level adjusted")
            print(f"  - Previous: {current_level!r} is not a security level → New: 'normal'")
            print("="*70 + "\n")

            add_startup_notice(
                "[MIGRATION] The security level of the legacy config.ini was not a security level.<BR>"
                "It is back at 'normal'. See terminal for details.",
                level='warning'
            )
        else:
            print(f"  - Security level: {current_level!r} (no change needed)")

    # Ensure directory exists
    os.makedirs(os.path.dirname(new_path), exist_ok=True)

    with open(new_path, 'w') as f:
        config.write(f)
