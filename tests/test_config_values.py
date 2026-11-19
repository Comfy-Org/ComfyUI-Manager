import logging

import pytest

from _install_flags_testutil import import_context, import_reader

VALUES = {
    "security_level": ["normal", "strong", "normal-", "weak"],
    "network_mode": ["public", "private", "offline", "personal_cloud"],
    "db_mode": ["cache", "channel", "local", "remote"],
    "update_policy": ["stable-comfyui", "nightly-comfyui", "stable", "nightly"],
}
NON_DEFAULT = {key: values[1] for key, values in VALUES.items()}
DEFAULTS = {key: values[0] for key, values in VALUES.items()}


@pytest.fixture(params=["glob", "legacy"])
def read(request, monkeypatch, tmp_path, caplog):
    core = import_reader(request.param)
    path = tmp_path / "config.ini"
    monkeypatch.setattr(import_context(), "manager_config_path", str(path))
    monkeypatch.setattr(core, "cached_config", None)

    def read_text(written, changes=()):
        if written is not None:
            path.write_bytes(written if isinstance(written, bytes) else written.encode("utf-8"))
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            settings = dict(core.get_config())
            for key, value in changes:
                core.get_config()[key] = value
            if changes:
                core.write_config()
        warnings = "\n".join(record.getMessage() for record in caplog.records)
        return settings, warnings, path.read_bytes() if path.exists() else None

    return read_text


def section(settings):
    return "[default]\n" + "".join(f"{key} = {value}\n" for key, value in settings.items())


@pytest.mark.parametrize("value", ["100%", "%(downgrade_blacklist)s", "%", "bogus", "weak,normal", "<b>weak</b>", "nor mal",
                                   "[/x]", "[bold]weak", "cache[/]"])
@pytest.mark.parametrize("key", sorted(VALUES))
def test_a_value_that_a_setting_cannot_have_gives_its_default_and_changes_no_other_setting(read, key, value):
    text = section({**NON_DEFAULT, key: value, "downgrade_blacklist": "kornia"})

    settings, printed, file = read(text)

    assert {name: settings[name] for name in VALUES} == {**NON_DEFAULT, key: DEFAULTS[key]}
    assert settings["downgrade_blacklist"] == "kornia"
    assert f"{key} = {value!r} in config.ini is not valid; '{DEFAULTS[key]}' is used." in printed
    assert file == text.encode("utf-8")


@pytest.mark.parametrize("key", sorted(VALUES))
def test_a_value_that_a_setting_cannot_have_stays_in_config_ini_when_another_setting_is_saved(read, key):
    text = section({**NON_DEFAULT, key: "bogus"})

    _, _, file = read(text, changes=[("share_option", "none")])

    assert f"{key} = bogus\n".encode() in file
    assert b"share_option = none\n" in file


@pytest.mark.parametrize("key, value", [(key, value) for key, values in sorted(VALUES.items()) for value in values])
@pytest.mark.parametrize("written", [str.lower, str.upper], ids=["lower case", "upper case"])
def test_a_value_that_a_setting_can_have_is_read_and_nothing_is_said(read, key, value, written):
    settings, printed, _ = read(section({key: written(value)}))

    assert settings[key] == value
    assert printed == ""


def test_a_config_ini_without_these_settings_has_their_defaults_and_nothing_is_said(read):
    settings, printed, _ = read(section({"file_logging": "True"}))

    assert {name: settings[name] for name in VALUES} == DEFAULTS
    assert printed == ""


@pytest.mark.parametrize("key, value", [
    ("downgrade_blacklist", "100%"), ("downgrade_blacklist", "%(security_level)s"), ("git_exe", "/opt/100%/git"),
    ("channel_url", "https://example.invalid/some%20one/channel"), ("channel_url", "%"), ("git_exe", "/opt/100%%/git"),
], ids=["a percent sign", "the form of a reference", "a path", "a percent-encoded url", "only a percent sign",
        "two percent signs"])
def test_a_percent_sign_is_plain_text_and_the_other_settings_are_read(read, key, value):
    text = section({**NON_DEFAULT, key: value})

    settings, printed, file = read(text)

    assert settings[key] == value
    assert {name: settings[name] for name in VALUES} == NON_DEFAULT
    assert printed == ""
    assert file == text.encode("utf-8")


def test_a_setting_is_written_beside_a_value_with_a_percent_sign_and_one_with_it_is_written(read):
    text = section({"security_level": "strong", "downgrade_blacklist": "100%"})

    _, _, file = read(text, changes=[("db_mode", "local"), ("channel_url", "https://example.invalid/some%20one/channel")])

    for line in (b"security_level = strong\n", b"downgrade_blacklist = 100%\n", b"db_mode = local\n",
                 b"channel_url = https://example.invalid/some%20one/channel\n"):
        assert line in file


@pytest.mark.parametrize("text", ["security_level = strong\n", "\ufeff[default]\nsecurity_level = strong\n",
                                  "[default\nsecurity_level = strong\n", "[other]\nsecurity_level = strong\n", "",
                                  "[default]\nsecurity_level = strong\nnot a setting [/x]\n",
                                  b"[default]\nsecurity_level = strong\ngit_exe = \xff\xfe\n"],
                         ids=["no section", "a byte order mark", "an unclosed section", "no default section", "empty",
                              "a line that is not a setting", "bytes that are not text"])
def test_a_config_ini_that_cannot_be_read_gives_the_defaults_and_says_so(read, text):
    settings, printed, file = read(text)

    assert {name: settings[name] for name in VALUES} == DEFAULTS
    assert "could not be read" in printed and "the default settings are used" in printed
    assert file == (text if isinstance(text, bytes) else text.encode("utf-8"))


def test_without_a_config_ini_the_defaults_are_used_and_nothing_is_said(read):
    settings, printed, file = read(None)

    assert {name: settings[name] for name in VALUES} == DEFAULTS
    assert printed == ""
    assert file is None
