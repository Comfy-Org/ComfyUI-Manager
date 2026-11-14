"""Exercise the logger without running Manager's startup/install hooks."""
import ast
import io
import re
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from colorama.ansitowin32 import AnsiToWin32


class Stream(io.StringIO):
    def __init__(self, tty):
        super().__init__()
        self.tty = tty

    def isatty(self):
        return self.tty


def load_logger(stdout, stderr):
    path = Path(__file__).resolve().parents[1] / "prestartup_script.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    definition = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "ComfyUIManagerLogger"
    )
    log_file = io.StringIO()
    namespace = {
        "original_stdout": stdout,
        "original_stderr": stderr,
        "write_stdout": stdout.write,
        "write_stderr": stderr.write,
        "log_file": log_file,
        "log_lock": threading.Lock(),
        "std_log_lock": threading.Lock(),
        "current_timestamp": lambda: "timestamp",
        "message_collapses": [],
        "is_start_mode": False,
        "pat_tqdm": r"\d+%.*\[(.*?)\]",
        "re": re,
    }
    exec(compile(ast.Module(body=[definition], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["ComfyUIManagerLogger"], log_file


@pytest.mark.parametrize("is_stdout", [True, False])
@pytest.mark.parametrize("tty", [True, False])
@pytest.mark.parametrize("platform_name", ["nt", "posix"])
def test_colorama_preserves_terminal_colors_and_strips_redirected_output(is_stdout, tty, platform_name, monkeypatch):
    target = Stream(tty)
    other = Stream(not tty)
    stdout, stderr = (target, other) if is_stdout else (other, target)
    logger_class, log_file = load_logger(stdout, stderr)
    logger = logger_class(is_stdout)
    # The in-memory stream has no Win32 handle; model a native ANSI terminal.
    monkeypatch.setattr("colorama.ansitowin32.os", SimpleNamespace(name=platform_name, environ={}))
    monkeypatch.setattr("colorama.ansitowin32.enable_vt_processing", lambda fd: True)
    converter = AnsiToWin32(logger)
    print("\x1b[31mred\x1b[0m", file=converter.stream)

    expected = "\x1b[31mred\x1b[0m\n" if tty else "red\n"
    assert target.getvalue() == expected
    assert log_file.getvalue() == expected
    assert other.getvalue() == ""
    assert converter.strip is not tty


@pytest.mark.parametrize("is_stdout", [True, False])
def test_stream_state_tracks_the_selected_original_stream(is_stdout):
    target = Stream(True)
    other = Stream(False)
    stdout, stderr = (target, other) if is_stdout else (other, target)
    logger_class, _ = load_logger(stdout, stderr)
    logger = logger_class(is_stdout)

    assert logger.isatty() is True
    assert logger.closed is False
    target.tty = False
    assert logger.isatty() is False
    other.close()
    assert logger.closed is False
    target.close()
    assert logger.closed is True
    assert AnsiToWin32(logger, convert=False).strip is True
