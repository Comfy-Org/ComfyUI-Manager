import logging
import re
import subprocess
import sys
from types import SimpleNamespace

import pytest

from _install_flags_testutil import import_context

PIP = ("python", "-m", "pip")
UV_MODULE = ("python", "-m", "uv", "pip")
UV = ("uv", "pip")
FRONTEND_INSTALLED = {"comfyui_frontend_package": "1.30.6"}
FAILED = "[ComfyUI-Manager] Failed to restore PyTorch"
FROM_THE_CACHE = ("[ComfyUI-Manager] restore PyTorch: the command does not resolve with its indexes, "
                  "installing from uv's cache alone")
NOT_RESOLVED = ("[ComfyUI-Manager] restore PyTorch: no dry run of the command resolved, neither with its "
                "indexes nor from uv's cache alone")

NO_LABEL = {"torch": "2.14.0", "torchvision": "0.29.0"}
NO_LABEL_TA = {**NO_LABEL, "torchaudio": "2.11.0"}
CU130 = {"torch": "2.14.0+cu130", "torchvision": "0.29.0+cu130"}
CU130_TA = {**CU130, "torchaudio": "2.11.0+cu130"}
CU126 = {"torch": "2.10.0+cu126", "torchvision": "0.25.0+cu126"}
CU130_INDEX = "--extra-index-url https://download.pytorch.org/whl/cu130"
TORCH_CU130 = f"install torch===2.14.0+cu130 {CU130_INDEX}"
TORCHVISION_CU130 = f"install --no-deps torchvision===0.29.0+cu130 {CU130_INDEX}"
TORCHAUDIO_CU130 = f"install --no-deps torchaudio===2.11.0+cu130 {CU130_INDEX}"
TORCHAUDIO_FIT_CU130 = ("install torch===2.14.0+cu130 torchaudio<=2.14.0 "
                        "--index-url https://download.pytorch.org/whl/cu130")
OVERWRITTEN_CU130 = f"install --no-deps --force-reinstall nvidia_nccl_cu13==2.28.9 {CU130_INDEX}"
RESTORE_WITHOUT_A_LABEL = ["install torch===2.14.0", "install --no-deps torchvision===0.29.0",
                           "install torch===2.14.0 torchaudio<=2.14.0"]

NCCL_REQUIRED = ["nvidia-nccl-cu13==2.28.9; platform_system == 'Linux'", "nvidia-cudnn-cu13==9.13.0.50", "filelock"]
NCCL_BEFORE = {"nvidia_nccl_cu13": "2.28.9", "nvidia_cudnn_cu13": "9.13.0.50"}
NCCL_AFTER = {**NCCL_BEFORE, "nvidia_nccl_cu12": "2.27.5"}
NCCL_FILES = {
    "nvidia_nccl_cu13": {"nvidia/nccl/lib/libnccl.so.2": "nccl-cu13"},
    "nvidia_cudnn_cu13": {"nvidia/cudnn/lib/libcudnn.so.9": "cudnn-cu13"},
    "nvidia_nccl_cu12": {"nvidia/nccl/lib/libnccl.so.2": "nccl-cu12"},
}


@pytest.fixture
def commands_sent_before_each_list():
    return []


@pytest.fixture
def sent_and_logged():
    events = []

    class Recorder(logging.Handler):
        def emit(self, record):
            events.append((record.levelname, record.getMessage()))

    recorder = Recorder(logging.INFO)
    logging.getLogger().addHandler(recorder)
    yield events
    logging.getLogger().removeHandler(recorder)


@pytest.fixture
def fix_broken(monkeypatch, tmp_path, caplog, commands_sent_before_each_list, sent_and_logged):
    import_context()
    from comfyui_manager.common import manager_util

    def run(installed_before, left_by_the_nodepack, recorded_files=None, torch_requires=(), failing_commands=(),
            unresolved=(), tool=PIP, in_real_subprocesses=False):
        before = {**FRONTEND_INSTALLED, **installed_before}
        after = {**FRONTEND_INSTALLED, **left_by_the_nodepack}
        site_after_restore = tmp_path / "site-packages"
        restored = {name: before[name] for name in ("torch", "torchvision", "torchaudio") if name in before}
        for name, version in {**after, **restored}.items():
            info = site_after_restore / f"{name}-{version}.dist-info"
            info.mkdir(parents=True)
            requires = "".join(f"Requires-Dist: {line}\n" for line in torch_requires) if name == "torch" else ""
            (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n{requires}")
            recorded = (recorded_files or {}).get(name, {})
            (info / "RECORD").write_text("".join(f"{path},sha256={digest},0\n" for path, digest in recorded.items()))
            for path in recorded:
                (site_after_restore / path).parent.mkdir(parents=True, exist_ok=True)
                (site_after_restore / path).touch()
        monkeypatch.syspath_prepend(str(site_after_restore))

        commands = []

        def check_output(cmd, **options):
            pip_args = cmd[len(tool):]
            if pip_args == ["list"]:
                commands_sent_before_each_list.append(len(commands))
                return "Package Version\n------- -------\n" + "".join(f"{n} {v}\n" for n, v in after.items())
            commands.append(" ".join(pip_args))
            sent_and_logged.append(commands[-1])
            if pip_args[-1] == "--dry-run":
                exit_code = 2 if " ".join(pip_args[:-1]) in unresolved else 0
            else:
                exit_code = 1 if commands[-1] in failing_commands else 0
            if in_real_subprocesses:
                return subprocess.check_output(
                    [sys.executable, "-c", f"import sys; print('output of {commands[-1]}', file=sys.stderr); "
                                           f"sys.exit({exit_code})"], **options)
            if exit_code:
                raise subprocess.CalledProcessError(exit_code, cmd)
            return ""

        monkeypatch.setattr(manager_util, "make_pip_cmd", lambda cmd: [*tool, *cmd])
        monkeypatch.setattr(manager_util, "subprocess", SimpleNamespace(
            check_output=check_output, CalledProcessError=subprocess.CalledProcessError, DEVNULL=subprocess.DEVNULL))
        monkeypatch.setattr(manager_util, "pip_map", None)
        caplog.set_level(logging.INFO)
        manager_util.PIPFixer(before, str(tmp_path), str(tmp_path)).fix_broken()

        installs = [command for command in commands if not command.endswith(" --dry-run")]
        assert len(set(installs)) == len(installs), "an install command was sent twice"
        assert not any(command in failing_commands for command in commands[:-1]), \
            "a command was sent after an install command failed"
        return commands

    return run


def problems(caplog):
    return [(record.levelname, record.getMessage()) for record in caplog.records if record.levelno >= logging.WARNING]


def told(caplog):
    return [record.getMessage() for record in caplog.records if record.levelno == logging.INFO]


def failed(command, tool=PIP):
    return [("ERROR", FAILED), ("ERROR", str(subprocess.CalledProcessError(1, [*tool, *command.split()])))]


def test_an_install_without_torchaudio_is_not_reported_as_without_pytorch(fix_broken, caplog):
    assert fix_broken(NO_LABEL, NO_LABEL) == []
    assert problems(caplog) == []


@pytest.mark.parametrize("before, after", [
    (NO_LABEL_TA, {**NO_LABEL_TA, "torchaudio": "2.11.1"}),
    (NO_LABEL_TA, NO_LABEL),
    (NO_LABEL, NO_LABEL_TA),
], ids=["torchaudio of another version", "torchaudio removed", "torchaudio added"])
def test_a_nodepack_that_changed_only_torchaudio_starts_no_restore(fix_broken, caplog, before, after):
    assert fix_broken(before, after) == []
    assert problems(caplog) == []


@pytest.mark.parametrize("before, index", [
    (NO_LABEL, ""),
    (CU130, f" {CU130_INDEX}"),
    ({"torch": "2.6.0+cu124", "torchvision": "0.21.0+cu124"},
     " --extra-index-url https://download.pytorch.org/whl/cu124"),
    ({"torch": "2.16.0.dev20261120+cu130", "torchvision": "0.31.0.dev20261120+cu130"},
     " --pre --extra-index-url https://download.pytorch.org/whl/nightly/cu130"),
    ({"torch": "2.16.0.dev20261120", "torchvision": "0.31.0.dev20261120"},
     " --pre --extra-index-url https://download.pytorch.org/whl/nightly/cpu"),
], ids=["without a label", "with a label", "with a label, of 2.6.0", "development build with a label",
        "development build without a label"])
def test_a_restore_installs_torch_alone_and_then_torchvision_without_its_dependencies(fix_broken, caplog, before,
                                                                                    index):
    assert fix_broken(before, CU126) == [
        f"install torch==={before['torch']}{index}",
        f"install --no-deps torchvision==={before['torchvision']}{index}",
    ]
    assert (f"[ComfyUI-Manager] restore PyTorch: torch {before['torch']}, torchvision {before['torchvision']}"
            in caplog.messages)
    assert problems(caplog) == []


@pytest.mark.parametrize("before, after, commands", [
    ({**CU130, "torchaudio": "2.11.1"}, {"torch": "2.10.0", "torchvision": "0.25.0", "torchaudio": "2.10.0"},
     [TORCH_CU130, TORCHVISION_CU130, "install --no-deps torchaudio===2.11.1"]),
    ({"torch": "2.14.0+cu130", "torchvision": "0.29.0"}, {"torch": "2.13.0", "torchvision": "0.28.0"},
     [TORCH_CU130, "install --no-deps torchvision===0.29.0"]),
    ({**CU130, "torchaudio": "2.11.0+cu126"}, {**CU126, "torchaudio": "2.10.0+cu126"},
     [TORCH_CU130, TORCHVISION_CU130,
      "install --no-deps torchaudio===2.11.0+cu126 --extra-index-url https://download.pytorch.org/whl/cu126"]),
    ({"torch": "2.14.0", "torchvision": "0.29.0+cpu"}, CU126,
     ["install torch===2.14.0",
      "install --no-deps torchvision===0.29.0+cpu --extra-index-url https://download.pytorch.org/whl/cpu"]),
    ({"torch": "2.14.0+cu130", "torchvision": "0.31.0.dev20261120"}, CU126,
     [TORCH_CU130,
      "install --no-deps torchvision===0.31.0.dev20261120 --pre "
      "--extra-index-url https://download.pytorch.org/whl/nightly/cpu"]),
], ids=["torchaudio without a label beside a torch with one", "torchvision without a label beside a torch with one",
        "torchaudio with another label", "torchvision with a label beside a torch without one",
        "torchvision as a development build without a label beside a torch with a label"])
def test_each_build_is_installed_from_the_index_it_comes_from(fix_broken, caplog, before, after, commands):
    assert fix_broken(before, after) == commands
    assert problems(caplog) == []


@pytest.mark.parametrize("after, commands, restored", [
    ({**CU130_TA, "torch": "2.13.0+cu130"}, [TORCH_CU130], "torch 2.14.0+cu130"),
    ({**CU130_TA, "torchvision": "0.28.0+cu130"}, [TORCHVISION_CU130], "torchvision 0.29.0+cu130"),
    ({**CU130, "torch": "2.13.0+cu130", "torchaudio": "2.10.0+cu130"}, [TORCH_CU130, TORCHAUDIO_CU130],
     "torch 2.14.0+cu130, torchaudio 2.11.0+cu130"),
], ids=["torch", "torchvision", "torch and torchaudio"])
def test_only_the_packages_that_the_nodepack_changed_are_installed_again(fix_broken, caplog, after, commands,
                                                                         restored):
    assert fix_broken(CU130_TA, after) == commands
    assert f"[ComfyUI-Manager] restore PyTorch: {restored}" in caplog.messages
    assert problems(caplog) == []


@pytest.mark.parametrize("after, commands", [
    ({"torch": "2.14.0+cpu", "torchvision": "0.29.0+cu130"}, [TORCH_CU130]),
    ({"torch": "2.14.0+cu130", "torchvision": "0.29.0+cpu"}, [TORCHVISION_CU130]),
], ids=["torch", "torchvision"])
def test_a_build_of_the_same_version_with_another_label_is_replaced_by_the_build_from_before(fix_broken, after,
                                                                                          commands):
    assert fix_broken(CU130, after) == commands


@pytest.mark.parametrize("removed, commands", [
    ("torch", [TORCH_CU130]),
    ("torchvision", [TORCHVISION_CU130]),
])
def test_torch_or_torchvision_that_a_nodepack_removed_is_installed_again(fix_broken, caplog, removed, commands):
    after = {name: version for name, version in CU130.items() if name != removed}
    assert fix_broken(CU130, after) == commands
    assert problems(caplog) == []


@pytest.mark.parametrize("torchaudio_before, torchaudio_after, last", [
    (None, None, []),
    ("2.11.0+cu130", "2.11.0+cu130", []),
    ("2.11.0+cu130", "2.10.0+cu126", [TORCHAUDIO_CU130]),
    ("2.11.0+cu130", None, [TORCHAUDIO_CU130]),
    (None, "2.10.0+cu126", [TORCHAUDIO_FIT_CU130]),
], ids=["absent before and after", "present before and after", "changed by the nodepack", "removed by the nodepack",
        "added by the nodepack"])
def test_a_restore_installs_torchaudio_when_the_nodepack_changed_removed_or_added_it(
        fix_broken, caplog, torchaudio_before, torchaudio_after, last):
    before = {**CU130, **({"torchaudio": torchaudio_before} if torchaudio_before else {})}
    after = {**CU126, **({"torchaudio": torchaudio_after} if torchaudio_after else {})}
    assert fix_broken(before, after) == [TORCH_CU130, TORCHVISION_CU130, *last]
    assert problems(caplog) == []


@pytest.mark.parametrize("before, fit", [
    (NO_LABEL, "install torch===2.14.0 torchaudio<=2.14.0"),
    (CU130, TORCHAUDIO_FIT_CU130),
    ({"torch": "2.16.0.dev20261120+cu130", "torchvision": "0.31.0.dev20261120+cu130"},
     "install torch===2.16.0.dev20261120+cu130 torchaudio<=2.16.0.dev20261120 --pre "
     "--index-url https://download.pytorch.org/whl/nightly/cu130"),
    ({"torch": "2.16.0.dev20261120", "torchvision": "0.31.0.dev20261120"},
     "install torch===2.16.0.dev20261120 torchaudio<=2.16.0.dev20261120 --pre "
     "--index-url https://download.pytorch.org/whl/nightly/cpu"),
], ids=["without a label", "with a label", "development build with a label", "development build without a label"])
def test_a_torchaudio_that_the_nodepack_added_is_fitted_last_from_the_index_of_the_restored_torch_alone(
        fix_broken, before, fit):
    assert fix_broken(before, {"torch": "2.10.0", "torchaudio": "2.10.0"})[-1] == fit


def test_a_torchaudio_that_the_nodepack_added_beside_the_same_torch_is_left_as_it_is(fix_broken):
    assert fix_broken(CU130, {**CU130, "torchvision": "0.28.0+cu130", "torchaudio": "2.11.0+cu130"}) == [
        TORCHVISION_CU130]


@pytest.mark.parametrize("before, torch_command, index", [
    ({**NO_LABEL, **NCCL_BEFORE}, "install torch===2.14.0", ""),
    ({**CU130, **NCCL_BEFORE}, TORCH_CU130, f" {CU130_INDEX}"),
    ({**NO_LABEL, **NCCL_BEFORE, "nvidia_nccl_cu12": "2.21.5"}, "install torch===2.14.0", ""),
], ids=["without a label", "with a label", "by a distribution that the nodepack upgraded"])
def test_a_required_distribution_whose_file_the_nodepack_overwrote_is_installed_again_after_torch(
        fix_broken, caplog, before, torch_command, index):
    commands = fix_broken(before, {**CU126, **NCCL_AFTER}, NCCL_FILES, NCCL_REQUIRED)

    assert commands == [torch_command, f"install --no-deps --force-reinstall nvidia_nccl_cu13==2.28.9{index}",
                        f"install --no-deps torchvision==={before['torchvision']}{index}"]
    assert problems(caplog) == []


@pytest.mark.parametrize("before, after, files", [
    (NCCL_BEFORE, {**NCCL_BEFORE, "nvidia_nccl_cu12": "2.27.5"},
     {**NCCL_FILES, "nvidia_nccl_cu12": {"nvidia/nccl/lib/libnccl.so.2": "nccl-cu13"}}),
    (NCCL_AFTER, NCCL_AFTER, NCCL_FILES),
    (NCCL_BEFORE, {**NCCL_AFTER, "nvidia_nccl_cu13": "2.28.3"}, NCCL_FILES),
    (NCCL_BEFORE, NCCL_AFTER, {**NCCL_FILES, "nvidia_nccl_cu12": {"nvidia/nccl/lib/libnccl.so.2.27": "nccl-cu12"}}),
], ids=["the same file", "written by a distribution that was installed before",
        "the required distribution has another version", "another file"])
def test_a_required_distribution_is_not_installed_again_when_the_nodepack_did_not_overwrite_its_files(
        fix_broken, before, after, files):
    assert fix_broken({**NO_LABEL, **before}, {**CU126, **after}, files, NCCL_REQUIRED) == [
        "install torch===2.14.0", "install --no-deps torchvision===0.29.0"]


def test_a_required_distribution_is_not_installed_again_when_torch_was_not_restored(fix_broken):
    commands = fix_broken({**NO_LABEL, **NCCL_BEFORE}, {**NO_LABEL, "torchvision": "0.28.0", **NCCL_AFTER}, NCCL_FILES,
                          NCCL_REQUIRED)

    assert commands == ["install --no-deps torchvision===0.29.0"]


RESTORED_CU130 = "[ComfyUI-Manager] restore PyTorch: torch 2.14.0+cu130, torchvision 0.29.0+cu130"
UV_FORMS = pytest.mark.parametrize("tool", [UV_MODULE, UV], ids=["python -m uv", "uv"])
PUTTING_BACK_A_BUILD = pytest.mark.parametrize("torchaudio_before, putting_back", [
    (None, TORCH_CU130),
    (None, OVERWRITTEN_CU130),
    (None, TORCHVISION_CU130),
    ("2.11.0+cu130", TORCHAUDIO_CU130),
], ids=["torch", "overwritten requirement", "torchvision", "torchaudio"])
TORCH_DEV_CU130 = ("install torch===2.16.0.dev20261120+cu130 --pre "
                   "--extra-index-url https://download.pytorch.org/whl/nightly/cu130")
TORCHVISION_DEV_CU130 = ("install --no-deps torchvision===0.31.0.dev20261120+cu130 --pre "
                         "--extra-index-url https://download.pytorch.org/whl/nightly/cu130")
TORCH_DEV = "install torch===2.16.0.dev20261120 --pre --extra-index-url https://download.pytorch.org/whl/nightly/cpu"
TORCHVISION_DEV = ("install --no-deps torchvision===0.31.0.dev20261120 --pre "
                   "--extra-index-url https://download.pytorch.org/whl/nightly/cpu")
RESTORES = {
    "a release without a label": (NO_LABEL, ["install torch===2.14.0", "install --no-deps torchvision===0.29.0"]),
    "a release with a label": (CU130, [TORCH_CU130, TORCHVISION_CU130]),
    "a development build with a label": ({"torch": "2.16.0.dev20261120+cu130",
                                          "torchvision": "0.31.0.dev20261120+cu130"},
                                         [TORCH_DEV_CU130, TORCHVISION_DEV_CU130]),
    "a development build without a label": ({"torch": "2.16.0.dev20261120", "torchvision": "0.31.0.dev20261120"},
                                            [TORCH_DEV, TORCHVISION_DEV]),
}


def dry_run(command):
    return f"{command} --dry-run"


def offline(command):
    return f"{command} --offline"


def offline_without_the_pytorch_index(command):
    return offline(re.sub(r" --extra-index-url https://download\.pytorch\.org/whl/\S+", "", command))


def resolving_as_they_are(commands):
    return [sent for command in commands for sent in (dry_run(command), command)]


def restored(before):
    return "INFO", f"[ComfyUI-Manager] restore PyTorch: torch {before['torch']}, torchvision {before['torchvision']}"


def restore_cu130(torchaudio_before):
    before = {**CU130, **NCCL_BEFORE, **({"torchaudio": torchaudio_before} if torchaudio_before else {})}
    after = {**CU126, **NCCL_AFTER, "torchaudio": "2.10.0+cu126"}
    putting_back = [TORCH_CU130, OVERWRITTEN_CU130, TORCHVISION_CU130,
                    *([TORCHAUDIO_CU130] if torchaudio_before else [])]
    fit = [] if torchaudio_before else [TORCHAUDIO_FIT_CU130]
    told_first = ("INFO", RESTORED_CU130 + (f", torchaudio {torchaudio_before}" if torchaudio_before else ""))
    return before, after, putting_back, fit, told_first


@pytest.mark.parametrize("tool", [PIP, UV_MODULE, UV], ids=["pip", "python -m uv", "uv"])
@pytest.mark.parametrize("torchaudio_before", [None, "2.11.0+cu130"], ids=["torchaudio added", "torchaudio changed"])
def test_a_restore_in_which_every_command_resolves_as_it_is_sends_the_same_install_commands_with_pip_and_uv(
        fix_broken, sent_and_logged, commands_sent_before_each_list, tool, torchaudio_before):
    before, after, putting_back, fit, told_first = restore_cu130(torchaudio_before)

    fix_broken(before, after, NCCL_FILES, NCCL_REQUIRED, tool=tool)

    assert sent_and_logged == [told_first, *(putting_back if tool == PIP else resolving_as_they_are(putting_back)),
                               *fit]
    assert commands_sent_before_each_list == [0]


@UV_FORMS
@PUTTING_BACK_A_BUILD
def test_with_uv_a_command_that_does_not_resolve_with_its_indexes_is_sent_once_with_offline(
        fix_broken, sent_and_logged, tool, torchaudio_before, putting_back):
    before, after, commands, fit, told_first = restore_cu130(torchaudio_before)
    position = commands.index(putting_back)

    fix_broken(before, after, NCCL_FILES, NCCL_REQUIRED, unresolved=[putting_back], tool=tool)

    assert sent_and_logged == [
        told_first, *resolving_as_they_are(commands[:position]),
        dry_run(putting_back), dry_run(offline(putting_back)), ("INFO", FROM_THE_CACHE), offline(putting_back),
        *resolving_as_they_are(commands[position + 1:]), *fit]


@UV_FORMS
@pytest.mark.parametrize("restore, position", [
    ("a release without a label", 0),
    ("a release without a label", 1),
    ("a development build with a label", 0),
    ("a development build without a label", 1),
], ids=["torch, a release without a label", "torchvision, a release without a label",
        "torch, a development build with a label", "torchvision, a development build without a label"])
def test_with_uv_the_offline_form_keeps_the_index_options_and_pre(fix_broken, sent_and_logged, tool, restore,
                                                                 position):
    before, commands = RESTORES[restore]
    command = commands[position]

    fix_broken(before, CU126, unresolved=[command], tool=tool)

    assert sent_and_logged == [
        restored(before), *resolving_as_they_are(commands[:position]),
        dry_run(command), dry_run(offline(command)), ("INFO", FROM_THE_CACHE), offline(command),
        *resolving_as_they_are(commands[position + 1:])]


@UV_FORMS
@PUTTING_BACK_A_BUILD
def test_with_uv_a_command_that_resolves_only_without_the_pytorch_index_is_sent_once_in_that_form(
        fix_broken, sent_and_logged, tool, torchaudio_before, putting_back):
    before, after, commands, fit, told_first = restore_cu130(torchaudio_before)
    position = commands.index(putting_back)

    fix_broken(before, after, NCCL_FILES, NCCL_REQUIRED, unresolved=[putting_back, offline(putting_back)], tool=tool)

    assert sent_and_logged == [
        told_first, *resolving_as_they_are(commands[:position]),
        dry_run(putting_back), dry_run(offline(putting_back)), dry_run(offline_without_the_pytorch_index(putting_back)),
        ("INFO", FROM_THE_CACHE), offline_without_the_pytorch_index(putting_back),
        *resolving_as_they_are(commands[position + 1:]), *fit]


@UV_FORMS
@pytest.mark.parametrize("restore, position, third_form", [
    ("a release with a label", 0, "install torch===2.14.0+cu130 --offline"),
    ("a release with a label", 1, "install --no-deps torchvision===0.29.0+cu130 --offline"),
    ("a development build with a label", 0, "install torch===2.16.0.dev20261120+cu130 --pre --offline"),
    ("a development build without a label", 1, "install --no-deps torchvision===0.31.0.dev20261120 --pre --offline"),
], ids=["torch, a release with a label", "torchvision, a release with a label",
        "torch, a development build with a label", "torchvision, a development build without a label"])
def test_with_uv_the_form_without_the_pytorch_index_keeps_pre(fix_broken, sent_and_logged, tool, restore, position,
                                                             third_form):
    before, commands = RESTORES[restore]
    command = commands[position]

    fix_broken(before, CU126, unresolved=[command, offline(command)], tool=tool)

    assert sent_and_logged == [
        restored(before), *resolving_as_they_are(commands[:position]),
        dry_run(command), dry_run(offline(command)), dry_run(third_form), ("INFO", FROM_THE_CACHE), third_form,
        *resolving_as_they_are(commands[position + 1:])]


@UV_FORMS
@pytest.mark.parametrize("before, commands, position", [
    (NO_LABEL, ["install torch===2.14.0", "install --no-deps torchvision===0.29.0"], 0),
    (NO_LABEL, ["install torch===2.14.0", "install --no-deps torchvision===0.29.0"], 1),
    ({"torch": "2.14.0+cu130", "torchvision": "0.29.0"}, [TORCH_CU130, "install --no-deps torchvision===0.29.0"], 1),
], ids=["torch", "torchvision", "torchvision beside a torch with a label"])
def test_with_uv_a_command_for_a_release_without_a_label_has_no_third_form(fix_broken, sent_and_logged, tool,
                                                                          before, commands, position):
    command = commands[position]

    fix_broken(before, CU126, unresolved=[command, offline(command)], tool=tool)

    assert sent_and_logged == [
        restored(before), *resolving_as_they_are(commands[:position]),
        dry_run(command), dry_run(offline(command)), command,
        *resolving_as_they_are(commands[position + 1:])]


@UV_FORMS
@PUTTING_BACK_A_BUILD
@pytest.mark.parametrize("completes", [True, False], ids=["completes", "fails"])
def test_with_uv_a_command_that_resolves_in_no_form_is_sent_as_it_is_once(
        fix_broken, sent_and_logged, tool, torchaudio_before, putting_back, completes):
    before, after, commands, fit, told_first = restore_cu130(torchaudio_before)
    position = commands.index(putting_back)
    forms = [putting_back, offline(putting_back), offline_without_the_pytorch_index(putting_back)]

    fix_broken(before, after, NCCL_FILES, NCCL_REQUIRED, unresolved=forms,
               failing_commands=[] if completes else [putting_back], tool=tool)

    assert sent_and_logged == [
        told_first, *resolving_as_they_are(commands[:position]), *map(dry_run, forms), putting_back,
        *([*resolving_as_they_are(commands[position + 1:]), *fit] if completes else
          [("WARNING", NOT_RESOLVED), *failed(putting_back, tool)])]


@UV_FORMS
@PUTTING_BACK_A_BUILD
@pytest.mark.parametrize("chosen", [0, 1, 2], ids=["as it is", "with --offline", "without the PyTorch index"])
def test_with_uv_a_form_that_resolves_and_then_fails_to_install_ends_the_restore(
        fix_broken, sent_and_logged, tool, torchaudio_before, putting_back, chosen):
    before, after, commands, fit, told_first = restore_cu130(torchaudio_before)
    forms = [putting_back, offline(putting_back), offline_without_the_pytorch_index(putting_back)]

    fix_broken(before, after, NCCL_FILES, NCCL_REQUIRED, unresolved=forms[:chosen], failing_commands=[forms[chosen]],
               tool=tool)

    assert sent_and_logged == [
        told_first, *resolving_as_they_are(commands[:commands.index(putting_back)]), *map(dry_run, forms[:chosen + 1]),
        *([("INFO", FROM_THE_CACHE)] if chosen else []), forms[chosen], *failed(forms[chosen], tool)]


def test_with_uv_what_a_dry_run_prints_does_not_reach_the_console_and_the_install_commands_print_as_before(
        fix_broken, capfd):
    commands = fix_broken(NO_LABEL, CU126, unresolved=["install torch===2.14.0"], tool=UV, in_real_subprocesses=True)

    assert commands == ["install torch===2.14.0 --dry-run", "install torch===2.14.0 --offline --dry-run",
                        "install torch===2.14.0 --offline", "install --no-deps torchvision===0.29.0 --dry-run",
                        "install --no-deps torchvision===0.29.0"]
    assert [line for line in capfd.readouterr().err.splitlines() if line.startswith("output of ")] == [
        "output of install torch===2.14.0 --offline", "output of install --no-deps torchvision===0.29.0"]


@pytest.mark.parametrize("before, failing", [
    (CU130, TORCH_CU130),
    ({**CU130, **NCCL_BEFORE}, OVERWRITTEN_CU130),
    (CU130, TORCHVISION_CU130),
    (CU130_TA, TORCHAUDIO_CU130),
    (NO_LABEL, "install torch===2.14.0"),
    (NO_LABEL, "install --no-deps torchvision===0.29.0"),
], ids=["torch", "overwritten requirement", "torchvision", "torchaudio", "torch without a label",
        "torchvision without a label"])
def test_with_pip_a_command_that_fails_is_sent_once_with_no_dry_run(
        fix_broken, caplog, commands_sent_before_each_list, before, failing):
    commands = fix_broken(before, {**CU126, **NCCL_AFTER, "torchaudio": "2.10.0+cu126"}, NCCL_FILES, NCCL_REQUIRED,
                          failing_commands=[failing])

    assert commands[-1] == failing and commands.count(failing) == 1
    assert not any(command.endswith(" --dry-run") for command in commands)
    assert commands_sent_before_each_list == [0]
    assert FROM_THE_CACHE not in told(caplog)
    assert problems(caplog) == failed(failing)


@pytest.mark.parametrize("tool", [PIP, UV_MODULE, UV], ids=["pip", "python -m uv", "uv"])
@pytest.mark.parametrize("before, sent", [
    (CU130, [TORCH_CU130, TORCHVISION_CU130, TORCHAUDIO_FIT_CU130]),
    ({"torch": "2.16.0.dev20261120+cu130", "torchvision": "0.31.0.dev20261120+cu130"},
     ["install torch===2.16.0.dev20261120+cu130 --pre --extra-index-url https://download.pytorch.org/whl/nightly/cu130",
      "install --no-deps torchvision===0.31.0.dev20261120+cu130 --pre "
      "--extra-index-url https://download.pytorch.org/whl/nightly/cu130",
      "install torch===2.16.0.dev20261120+cu130 torchaudio<=2.16.0.dev20261120 --pre "
      "--index-url https://download.pytorch.org/whl/nightly/cu130"]),
    ({"torch": "2.16.0.dev20261120", "torchvision": "0.31.0.dev20261120"},
     ["install torch===2.16.0.dev20261120 --pre --extra-index-url https://download.pytorch.org/whl/nightly/cpu",
      "install --no-deps torchvision===0.31.0.dev20261120 --pre "
      "--extra-index-url https://download.pytorch.org/whl/nightly/cpu",
      "install torch===2.16.0.dev20261120 torchaudio<=2.16.0.dev20261120 --pre "
      "--index-url https://download.pytorch.org/whl/nightly/cpu"]),
], ids=["with a label", "development build with a label", "development build without a label"])
def test_a_fit_of_an_added_torchaudio_that_fails_is_sent_once_with_no_dry_run(fix_broken, caplog, tool, before, sent):
    assert fix_broken(before, {"torch": "2.10.0", "torchaudio": "2.10.0"}, tool=tool, failing_commands=[sent[-1]]) == [
        *(sent[:-1] if tool == PIP else resolving_as_they_are(sent[:-1])), sent[-1]]
    assert FROM_THE_CACHE not in told(caplog)
    assert problems(caplog) == failed(sent[-1], tool)


@pytest.mark.parametrize("before, sent, failing", [
    (NO_LABEL, RESTORE_WITHOUT_A_LABEL, 0),
    (NO_LABEL, RESTORE_WITHOUT_A_LABEL, 1),
    (NO_LABEL, RESTORE_WITHOUT_A_LABEL, 2),
    ({"torch": "2.14.0+cu130", "torchvision": "0.29.0"},
     [TORCH_CU130, "install --no-deps torchvision===0.29.0", TORCHAUDIO_FIT_CU130], 1),
], ids=["torch", "torchvision", "fit of an added torchaudio", "torchvision beside a torch with a label"])
def test_a_command_without_a_pytorch_index_that_fails_is_not_sent_again(fix_broken, caplog, before, sent, failing):
    assert fix_broken(before, {**CU126, "torchaudio": "2.10.0+cu126"}, failing_commands=[sent[failing]]) == \
        sent[:failing + 1]
    assert problems(caplog) == [
        ("ERROR", FAILED), ("ERROR", str(subprocess.CalledProcessError(1, [*PIP, *sent[failing].split()])))]
