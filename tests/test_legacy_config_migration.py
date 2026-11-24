import configparser
import importlib.util
import os
import shutil

import pytest

from manager_test_utils import GLOB_DIR

PREFERENCES = {
    "security_level": "strong", "network_mode": "private", "db_mode": "local", "preview_method": "taesd",
    "share_option": "none", "component_policy": "mine", "update_policy": "nightly-comfyui", "use_uv": "True",
    "file_logging": "False", "always_lazy_install": "True", "default_cache_as_channel_url": "True",
    "model_download_by_agent": "True", "downgrade_blacklist": "diffusers, kornia",
    "windows_selector_event_loop_policy": "True",
}
LEFT_BEHIND = ["allow_git_url_install", "allow_pip_install", "allow_flagged_nodepack_install",
               "channel_url", "http_channel_enabled", "bypass_ssl", "git_exe"]


@pytest.fixture
def migration(tmp_path):
    spec = importlib.util.spec_from_file_location("_manager_migration", GLOB_DIR / "manager_migration.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.legacy = tmp_path / "user" / "default" / "ComfyUI-Manager" / "config.ini"
    module.new = tmp_path / "user" / "__manager" / "config.ini"
    module.legacy.parent.mkdir(parents=True)
    return module


def migrated(migration, text):
    migration.legacy.write_text(text, encoding="utf-8")
    migration._migrate_config_with_security_check(str(migration.legacy), str(migration.new))
    config = configparser.ConfigParser(strict=False, interpolation=None)
    config.read(migration.new, encoding="utf-8")
    assert config.sections() in ([], ["default"])
    assert not config.defaults()
    return dict(config["default"]) if "default" in config else {}


def section(settings):
    return "[default]\n" + "".join(f"{key} = {value}\n" for key, value in settings.items())


def test_preferences_are_migrated_as_they_were_written(migration, capsys):
    assert migrated(migration, section(PREFERENCES)) == PREFERENCES
    assert "not migrated" not in capsys.readouterr().out
    assert migration.startup_notices == []


@pytest.mark.parametrize("value", ["True", "true", "1", "yes", "https://channel.example/list", "/usr/bin/other-git"])
@pytest.mark.parametrize("key", LEFT_BEHIND)
def test_a_setting_that_permits_an_install_or_changes_the_source_is_left_behind(migration, capsys, key, value):
    assert migrated(migration, section({**PREFERENCES, key: value})) == PREFERENCES
    assert key in capsys.readouterr().out
    assert [level for _, level in migration.startup_notices] == ["warning"]


AS_WRITTEN = {
    "allow_git_url_install": "False", "allow_pip_install": "False", "allow_flagged_nodepack_install": "False",
    "http_channel_enabled": "False", "bypass_ssl": "False", "git_exe": "",
    "channel_url": "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main",
}


@pytest.mark.parametrize("settings", [AS_WRITTEN, {key: value.upper() for key, value in AS_WRITTEN.items() if value in ("False",)},
                                      {key: value.lower() for key, value in AS_WRITTEN.items() if value in ("False",)}],
                         ids=["as written", "upper case", "lower case"])
def test_a_setting_that_was_never_changed_is_left_behind_without_a_warning(migration, capsys, settings):
    assert migrated(migration, section({**PREFERENCES, **settings})) == PREFERENCES
    assert "not migrated" not in capsys.readouterr().out
    assert migration.startup_notices == []


@pytest.mark.parametrize("key", LEFT_BEHIND)
def test_one_changed_setting_among_those_never_changed_is_the_one_reported(migration, capsys, key):
    changed = "True" if AS_WRITTEN[key] == "False" else "something-else"

    assert migrated(migration, section({**PREFERENCES, **AS_WRITTEN, key: changed})) == PREFERENCES

    printed = capsys.readouterr().out
    assert f"['{key}']" in printed
    assert len(migration.startup_notices) == 1


@pytest.mark.parametrize("key", ["ALLOW_GIT_URL_INSTALL", "Allow_Pip_Install", "allow_git_url_install ", "CHANNEL_URL"],
                         ids=["upper case", "mixed case", "trailing space", "upper case channel"])
def test_a_setting_is_left_behind_however_its_name_is_written(migration, key):
    assert migrated(migration, section({**PREFERENCES, key: "True"})) == PREFERENCES


@pytest.mark.parametrize("text", [
    "[DEFAULT]\nallow_git_url_install = True\n[default]\ndb_mode = local\n",
    "[DEFAULT]\nallow_git_url_install = True\ndb_mode = local\n[default]\n",
    "[default]\ndb_mode = local\nallow_git_url_install: True\n",
    "[default]\ndb_mode = local\n[other]\nallow_git_url_install = True\n",
    "[default]\ndb_mode = local\n[default2]\nallow_pip_install = True\n",
], ids=["in the DEFAULT section", "all in the DEFAULT section", "with a colon", "in another section",
        "in a section of a similar name"])
def test_a_setting_is_left_behind_wherever_the_file_has_it(migration, text):
    assert migrated(migration, text) == {"db_mode": "local"}


@pytest.mark.parametrize("value", ["True", "False", ""])
@pytest.mark.parametrize("key", ["a_setting_of_a_later_version", "allow_everything", "security_level2", "x"])
def test_a_setting_that_is_not_known_is_left_behind(migration, key, value):
    assert migrated(migration, section({**PREFERENCES, key: value})) == PREFERENCES


def test_all_of_them_at_once_leave_only_the_preferences(migration, capsys):
    assert migrated(migration, section({**PREFERENCES, **{key: "True" for key in LEFT_BEHIND}})) == PREFERENCES
    printed = capsys.readouterr().out
    assert all(key in printed for key in LEFT_BEHIND)
    assert len(migration.startup_notices) == 1


@pytest.mark.parametrize("name", ["<img src=x onerror=alert(1)>", "<b>bold</b>", "a&b", "\x1b[2Jcleared"],
                         ids=["an element", "a tag", "an ampersand", "an escape sequence"])
def test_the_text_of_the_file_does_not_reach_the_notice_or_the_terminal_as_written(migration, capsys, name):
    assert migrated(migration, section({name: "True", "db_mode": "local"})) == {"db_mode": "local"}

    message, _ = migration.startup_notices[0]
    assert name.lower() not in message.lower()
    assert "\x1b" not in capsys.readouterr().out


@pytest.mark.parametrize("level", ["\x1b[2Jcleared", "strong\x1b[31m", "\x07"], ids=["an escape sequence", "after a level", "a bell"])
def test_a_security_level_with_a_control_character_does_not_reach_the_terminal_as_written(migration, capsys, level):
    migrated(migration, section({"security_level": level}))

    printed = capsys.readouterr().out
    assert "\x1b" not in printed and "\x07" not in printed


@pytest.mark.parametrize("level, expected", [("weak", "normal"), ("normal-", "normal"), ("WEAK", "normal"),
                                             ("normal", "normal"), ("strong", "strong")])
def test_a_security_level_below_normal_is_raised(migration, level, expected):
    assert migrated(migration, section({"security_level": level, "allow_git_url_install": "True"})) == {"security_level": expected}


@pytest.mark.parametrize("value", ["100%", "%(db_mode)s", "a%%b", "50% off", "%"])
@pytest.mark.parametrize("key", sorted(set(PREFERENCES) - {"security_level"}))
def test_a_value_with_a_percent_sign_is_migrated_as_it_was_written(migration, key, value):
    assert migrated(migration, section({**PREFERENCES, key: value})) == {**PREFERENCES, key: value}


@pytest.mark.parametrize("level", ["100%", "%(downgrade_blacklist)s", "%(db_mode)s%(share_option)s", "storng", "high", "normal+", "0",
                                   "<b>weak</b>", "wea k", "weak,normal"])
def test_a_security_level_that_is_not_one_is_back_at_normal_and_no_other_setting_with_it(migration, capsys, level):
    settings = {**PREFERENCES, "security_level": level}

    assert migrated(migration, section(settings)) == {**settings, "security_level": "normal"}
    assert "is not a security level" in capsys.readouterr().out
    assert [level in message for message, _ in migration.startup_notices] == [False]


def test_a_legacy_file_without_a_security_level_gets_none(migration):
    assert migrated(migration, section({"db_mode": "local"})) == {"db_mode": "local"}


@pytest.mark.parametrize("text", ["", "\n", "[other]\ndb_mode = local\n"], ids=["empty", "a newline", "no default section"])
def test_a_file_without_settings_migrates_none(migration, text):
    assert migrated(migration, text) == {}


@pytest.mark.parametrize("text", ["db_mode = local\n", "[default\ndb_mode = local\n", "[default]\n[default]\n"],
                         ids=["no section", "an unclosed section", "a section twice"])
def test_a_file_that_cannot_be_parsed_is_not_migrated(migration, text):
    assert migrated(migration, text) == {}
    assert not migration.new.exists()


def test_the_migration_of_the_legacy_directory_leaves_the_install_settings_behind(migration, tmp_path, monkeypatch):
    monkeypatch.setattr(migration, "has_system_user_api", lambda: True)
    migration.legacy.write_text(section({**PREFERENCES, **{key: "True" for key in LEFT_BEHIND}}), encoding="utf-8")

    assert migration.migrate_legacy_config(str(tmp_path / "user"), str(migration.new.parent)) is True

    config = configparser.ConfigParser(interpolation=None)
    config.read(migration.new, encoding="utf-8")
    assert dict(config["default"]) == PREFERENCES
    assert not migration.legacy.exists()


def test_an_earlier_backup_of_the_legacy_directory_is_kept(migration, tmp_path, monkeypatch):
    monkeypatch.setattr(migration, "has_system_user_api", lambda: True)
    backups = [migration.new.parent / ".legacy-manager-backup", migration.new.parent / ".legacy-manager-backup-2",
               migration.new.parent / ".legacy-manager-backup-3"]

    for number, backup in enumerate(backups):
        migration.legacy.parent.mkdir(parents=True, exist_ok=True)
        migration.legacy.write_text(section({"db_mode": "local"}), encoding="utf-8")
        (migration.legacy.parent / "kept.txt").write_text(str(number), encoding="utf-8")

        assert migration.migrate_legacy_config(str(tmp_path / "user"), str(migration.new.parent)) is True

        assert not migration.legacy.parent.exists()
        assert [(b / "kept.txt").read_text(encoding="utf-8") for b in backups[:number + 1]] == [str(n) for n in range(number + 1)]


@pytest.mark.parametrize("backups", [[".legacy-manager-backup"], [".legacy-manager-backup-2"],
                                     [".legacy-manager-backup", ".legacy-manager-backup-2", ".legacy-manager-backup-3"]],
                         ids=["the first backup", "only a later backup", "three backups"])
def test_a_start_reminds_of_every_backup_that_is_there(migration, capsys, backups):
    for name in backups:
        (migration.new.parent / name).mkdir(parents=True)

    migration.check_legacy_backup(str(migration.new.parent))

    printed = capsys.readouterr().out
    assert [line.strip() for line in printed.splitlines() if ".legacy-manager-backup" in line] == \
        [str(migration.new.parent / name) for name in backups]
    assert [level for _, level in migration.startup_notices] == ["info"]


@pytest.mark.parametrize("there", [False, True], ids=["no data directory", "a data directory without a backup"])
def test_a_start_without_a_backup_reminds_of_nothing(migration, capsys, there):
    if there:
        migration.new.parent.mkdir(parents=True)
        migration.new.write_text(section({"db_mode": "local"}), encoding="utf-8")

    migration.check_legacy_backup(str(migration.new.parent))

    assert capsys.readouterr().out == ""
    assert migration.startup_notices == []


NAMES = ["kept.txt", "<img src=x>.json", "a&b.json", "\x1b[2Jcleared.json", "a'b\"c.json"]


@pytest.mark.parametrize("error", [
    *[lambda path, name=name: PermissionError(13, "Permission denied", path + name) for name in NAMES],
    lambda path: OSError("cannot move \x1b[2J" + path),
    lambda path: shutil.Error([(path + "\x1b[2Ja.json", path + "b.json", "[Errno 13] Permission denied: \x07")]),
], ids=["a plain name", "an element", "an ampersand", "an escape sequence", "quotes", "a text with an escape sequence",
        "the errors of a copy"])
def test_a_backup_that_fails_is_reported_without_the_text_of_the_error(migration, monkeypatch, capsys, error):
    migration.legacy.write_text(section({"db_mode": "local"}), encoding="utf-8")
    error = error(str(migration.legacy.parent) + "/")

    def move(source, destination):
        raise error

    monkeypatch.setattr(shutil, "move", move)

    assert migration._move_legacy_to_backup(str(migration.legacy.parent), str(migration.new.parent)) is None

    assert migration.startup_notices == [("[MIGRATION] Failed to backup legacy directory. See terminal for details.", "warning")]
    printed = capsys.readouterr().out
    assert "Failed to backup legacy directory: " + repr(str(error)) in printed
    assert "\x1b" not in printed and "\x07" not in printed
    assert migration.legacy.exists()


@pytest.mark.skipif(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), reason="needs a file that cannot be read")
def test_a_copy_that_fails_leaves_the_legacy_directory_and_no_part_of_a_backup(migration, tmp_path, monkeypatch):
    monkeypatch.setattr(migration, "has_system_user_api", lambda: True)
    monkeypatch.setattr(os, "rename", lambda source, destination: (_ for _ in ()).throw(OSError(18, "Invalid cross-device link")))
    migration.legacy.write_text(section({"db_mode": "local"}), encoding="utf-8")
    (migration.legacy.parent / "kept.txt").write_text("kept", encoding="utf-8")
    unreadable = migration.legacy.parent / "unreadable.json"
    unreadable.write_text("{}", encoding="utf-8")
    unreadable.chmod(0)

    for _ in range(3):
        migration.migrate_legacy_config(str(tmp_path / "user"), str(migration.new.parent))

        assert sorted(path.name for path in migration.legacy.parent.iterdir()) == ["config.ini", "kept.txt", "unreadable.json"]
        assert [path.name for path in migration.new.parent.iterdir() if path.name.startswith(".legacy-manager-backup")] == []

    unreadable.chmod(0o600)


def test_a_backup_that_was_copied_is_kept_when_the_legacy_directory_cannot_be_removed(migration, monkeypatch):
    monkeypatch.setattr(os, "rename", lambda source, destination: (_ for _ in ()).throw(OSError(18, "Invalid cross-device link")))
    migration.legacy.write_text(section({"db_mode": "local"}), encoding="utf-8")
    (migration.legacy.parent / "kept.txt").write_text("kept", encoding="utf-8")
    migration.new.parent.mkdir(parents=True)

    def rmtree(path, *args, **kwargs):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(shutil, "rmtree", rmtree)

    assert migration._move_legacy_to_backup(str(migration.legacy.parent), str(migration.new.parent)) is None

    backup = migration.new.parent / ".legacy-manager-backup"
    assert sorted(path.name for path in backup.iterdir()) == ["config.ini", "kept.txt"]
    assert (backup / "kept.txt").read_text(encoding="utf-8") == "kept"
