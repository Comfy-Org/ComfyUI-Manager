import json
import subprocess
import sys
import textwrap

import pytest

from manager_test_utils import GLOB_DIR

VALUES = {
    "security_level": ["normal", "strong", "normal-", "weak"],
    "network_mode": ["public", "private", "offline"],
    "db_mode": ["cache", "local", "remote"],
    "update_policy": ["stable-comfyui", "nightly-comfyui"],
    "component_policy": ["workflow", "higher", "mine"],
}
NON_DEFAULT = {key: values[1] for key, values in VALUES.items()}

CHILD = textwrap.dedent(
    """
    import sys, types, tempfile, os, json, io, contextlib, logging
    tmp = tempfile.mkdtemp(prefix="cm_config_values_")
    stub = types.ModuleType("folder_paths")
    stub.get_user_directory = lambda: tmp
    stub.get_system_user_directory = lambda *a, **k: os.path.join(tmp, "sysuser")
    sys.modules["folder_paths"] = stub
    written, changes, glob_dir = json.loads(sys.argv[1])
    sys.path.insert(0, glob_dir)
    with contextlib.redirect_stdout(io.StringIO()):
        import manager_core
    path = os.path.join(tmp, "config.ini")
    manager_core.manager_config_path = path
    manager_core.cached_config = None
    if written is not None:
        with open(path, "wb") as f:
            f.write(written.encode("latin-1"))
    warnings = []
    handler = logging.Handler(logging.WARNING)
    handler.emit = lambda record: warnings.append(record.getMessage())
    logging.getLogger().addHandler(handler)
    with contextlib.redirect_stdout(io.StringIO()):
        settings = dict(manager_core.get_config())
        for key, value in changes:
            manager_core.get_config()[key] = value
        if changes:
            manager_core.write_config()
    after = open(path, "rb").read().decode("latin-1") if os.path.exists(path) else None
    print(json.dumps({"settings": settings, "warnings": warnings, "file": after}))
    """
)


def read(written, changes=()):
    done = subprocess.run([sys.executable, "-c", CHILD, json.dumps([written, list(changes), str(GLOB_DIR)])],
                          capture_output=True, text=True, timeout=180)
    assert done.returncode == 0, done.stderr[-2000:]
    result = json.loads(done.stdout.strip().splitlines()[-1])
    return result["settings"], "\n".join(result["warnings"]), result["file"]


def section(settings):
    return "[default]\n" + "".join(f"{key} = {value}\n" for key, value in settings.items())


@pytest.mark.parametrize("value", ["100%", "%(downgrade_blacklist)s", "%", "bogus", "weak,normal", "<b>weak</b>", "nor mal",
                                   "[/x]", "[bold]weak", "cache[/]"])
@pytest.mark.parametrize("key", sorted(VALUES))
def test_a_value_that_a_setting_cannot_have_gives_its_default_and_changes_no_other_setting(key, value):
    text = section({**NON_DEFAULT, key: value, "downgrade_blacklist": "kornia"})

    settings, printed, file = read(text)

    assert {name: settings[name] for name in VALUES} == {**NON_DEFAULT, key: VALUES[key][0]}
    assert settings["downgrade_blacklist"] == "kornia"
    assert f"{key} = {value!r} in config.ini is not valid; '{VALUES[key][0]}' is used." in printed
    assert file == text


@pytest.mark.parametrize("key", sorted(VALUES))
def test_a_value_that_a_setting_cannot_have_stays_in_config_ini_when_another_setting_is_saved(key):
    text = section({**NON_DEFAULT, key: "bogus"})

    _, _, file = read(text, changes=[("share_option", "none")])

    assert f"{key} = bogus\n" in file
    assert "share_option = none\n" in file


@pytest.mark.parametrize("key, value", [(key, value) for key, values in sorted(VALUES.items()) for value in values])
@pytest.mark.parametrize("written", [str.lower, str.upper], ids=["lower case", "upper case"])
def test_a_value_that_a_setting_can_have_is_read_and_nothing_is_said(key, value, written):
    settings, printed, _ = read(section({key: written(value)}))

    assert settings[key] == value
    assert printed == ""


def test_a_config_ini_without_these_settings_has_their_defaults_and_nothing_is_said():
    settings, printed, _ = read(section({"file_logging": "True"}))

    assert {name: settings[name] for name in VALUES} == {key: values[0] for key, values in VALUES.items()}
    assert printed == ""


@pytest.mark.parametrize("key, value", [
    ("downgrade_blacklist", "100%"), ("downgrade_blacklist", "%(security_level)s"), ("git_exe", "/opt/100%/git"),
    ("channel_url", "https://example.invalid/some%20one/channel"), ("channel_url", "%"), ("git_exe", "/opt/100%%/git"),
], ids=["a percent sign", "the form of a reference", "a path", "a percent-encoded url", "only a percent sign",
        "two percent signs"])
def test_a_percent_sign_is_plain_text_and_the_other_settings_are_read(key, value):
    text = section({**NON_DEFAULT, key: value})

    settings, printed, file = read(text)

    assert settings[key] == value
    assert {name: settings[name] for name in VALUES} == NON_DEFAULT
    assert printed == ""
    assert file == text


def test_a_setting_is_written_beside_a_value_with_a_percent_sign_and_one_with_it_is_written():
    text = section({"security_level": "strong", "downgrade_blacklist": "100%"})

    _, _, file = read(text, changes=[("db_mode", "local"), ("channel_url", "https://example.invalid/some%20one/channel")])

    assert "security_level = strong\n" in file and "downgrade_blacklist = 100%\n" in file
    assert "db_mode = local\n" in file and "channel_url = https://example.invalid/some%20one/channel\n" in file


@pytest.mark.parametrize("text", ["security_level = strong\n", "\ufeff[default]\nsecurity_level = strong\n".encode("utf-8").decode("latin-1"),
                                  "[default\nsecurity_level = strong\n", "[other]\nsecurity_level = strong\n", "",
                                  "[default]\nsecurity_level = strong\nnot a setting [/x]\n"],
                         ids=["no section", "a byte order mark", "an unclosed section", "no default section", "empty",
                              "a line that is not a setting"])
def test_a_config_ini_that_cannot_be_read_gives_the_defaults_and_says_so(text):
    settings, printed, file = read(text)

    assert {name: settings[name] for name in VALUES} == {key: values[0] for key, values in VALUES.items()}
    assert "could not be read" in printed and "the default settings are used" in printed
    assert file == text


def test_without_a_config_ini_the_defaults_are_used_and_nothing_is_said():
    settings, printed, file = read(None)

    assert {name: settings[name] for name in VALUES} == {key: values[0] for key, values in VALUES.items()}
    assert printed == ""
    assert file is None
