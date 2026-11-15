"""The startup logger reports the terminal state of the stream it wraps (#3259).

A logger that always answered "not a terminal" made colorama, and any other library that
asks, strip its colors and hide its progress display for the whole session.

The last cases are about what is written once the log file is closed: the restart under
comfy-cli closes it and then exits, and what is logged on the way out must not fail.
"""
import ast
import io
import textwrap
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parent.parent / "prestartup_script.py"


class Stream:
    def __init__(self, tty, closed=False):
        self._tty = tty
        self.closed = closed

    def isatty(self):
        return self._tty


class StreamWithoutClosed:
    def isatty(self):
        return True


class StreamThatCannotBeAsked:
    closed = False

    def isatty(self):
        raise OSError("The handle is invalid")


class LogFile:
    def __init__(self, closed=False):
        self.closed = closed
        self.written = []

    def write(self, text):
        if self.closed:
            raise ValueError("I/O operation on closed file.")
        self.written.append(text)

    def flush(self):
        pass


def loggers(stdout, stderr, log_closed=False, **module_globals):
    """Lift ComfyUIManagerLogger; importing prestartup_script would run the startup."""
    source = SOURCE.read_text(encoding="utf-8")
    node = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ClassDef) and n.name == "ComfyUIManagerLogger")
    scope = {"original_stdout": stdout, "original_stderr": stderr, "log_file": SimpleNamespace(closed=log_closed),
             **module_globals}
    exec(textwrap.dedent("\n".join(source.splitlines()[node.lineno - 1:node.end_lineno])), scope)
    return scope["ComfyUIManagerLogger"](True), scope["ComfyUIManagerLogger"](False)


def close_logs(log_file, log_lock):
    """The two ways to close the log file: the logger's method, and the function run at exit."""
    source = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    in_class = {id(n) for c in ast.walk(tree) if isinstance(c, ast.ClassDef) for n in ast.walk(c)}
    function = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "close_log" and id(n) not in in_class)
    scope = {"sys": SimpleNamespace(), "original_stdout": None, "original_stderr": None,
             "log_file": log_file, "log_lock": log_lock}
    exec(textwrap.dedent("\n".join(source.splitlines()[function.lineno - 1:function.end_lineno])), scope)
    out, _ = loggers(None, None, **{name: scope[name] for name in ("sys", "log_file", "log_lock")})
    return out.close_log, scope["close_log"]


def writing_logger(log_file):
    """The stderr logger with what its writes need, and the list of what reached the console."""
    console = []
    stream = SimpleNamespace(flush=lambda: None)
    _, err = loggers(stream, stream, log_file=log_file, log_lock=threading.Lock(), std_log_lock=threading.Lock(),
                     current_timestamp=lambda: "12:00:00", write_stdout=console.append, write_stderr=console.append)
    return err, console


@pytest.fixture
def ansitowin32(monkeypatch):
    """colorama's stream wrapper, with its probe of the Windows console answered.

    On a console that takes the Win32 calls colorama converts the codes itself and strips
    them from the text, whatever the stream answers, so the cases would depend on where
    they are run."""
    module = pytest.importorskip("colorama.ansitowin32")
    monkeypatch.setattr(module, "winapi_test", lambda *_: False)
    return module


def detached_stream():
    stream = io.TextIOWrapper(io.BytesIO())
    stream.detach()
    return stream


@pytest.mark.parametrize("stdout_tty, stderr_tty", [(True, True), (True, False), (False, True), (False, False)])
def test_isatty_follows_each_wrapped_stream(stdout_tty, stderr_tty):
    out, err = loggers(Stream(stdout_tty), Stream(stderr_tty))

    assert (out.isatty(), err.isatty()) == (stdout_tty, stderr_tty)


def test_closed_follows_each_wrapped_stream():
    out, err = loggers(Stream(True, closed=False), Stream(True, closed=True))

    assert (out.closed, err.closed) == (False, True)


@pytest.mark.parametrize("stream", [object(), StreamThatCannotBeAsked(), detached_stream()])
def test_stream_that_cannot_answer_is_not_a_terminal(stream):
    out, _ = loggers(stream, stream)

    assert out.isatty() is False


def test_stream_without_closed_is_open():
    out, _ = loggers(StreamWithoutClosed(), StreamWithoutClosed())

    assert out.closed is False


def test_detached_stream_is_closed():
    out, _ = loggers(detached_stream(), detached_stream())

    assert out.closed is True


def test_logger_is_closed_once_its_log_file_is_closed():
    out, err = loggers(Stream(True), Stream(True), log_closed=True)

    assert (out.closed, err.closed) == (True, True)


def test_colorama_writes_no_reset_at_exit_after_the_log_file_is_closed(ansitowin32):
    out, _ = loggers(Stream(True), Stream(True), log_closed=True)
    written = []
    out.write = written.append

    # what colorama's exit handler does with the stream it was given at init()
    ansitowin32.AnsiToWin32(out).reset_all()

    assert written == []


@pytest.mark.parametrize("stream, kept", [
    (Stream(True), True),
    (Stream(False), False),
    (StreamWithoutClosed(), True),
    (StreamThatCannotBeAsked(), False),
])
def test_colorama_keeps_ansi_codes_only_on_a_terminal(ansitowin32, stream, kept):
    out, _ = loggers(stream, stream)

    assert ansitowin32.AnsiToWin32(out).strip is (not kept)


def test_open_log_file_gets_what_is_written():
    log_file = LogFile()
    logger, console = writing_logger(log_file)

    logger.sync_write("first\n")
    logger.sync_write("logged only\n", file_only=True)

    assert log_file.written == ["first\n", "[12:00:00] logged only\n"]
    assert console == ["first\n"]


def test_closed_log_file_is_left_alone():
    log_file = LogFile(closed=True)
    logger, console = writing_logger(log_file)

    # what the logging handler does with a record that arrives after close_log()
    logger.sync_write("logged only\n", file_only=True)
    logger.sync_write("still shown\n")

    assert log_file.written == []
    assert console == ["still shown\n"]


@pytest.mark.parametrize("which", [0, 1])
def test_log_file_is_closed_under_the_lock_of_the_writes(which):
    log_lock = threading.Lock()
    held = []
    log_file = SimpleNamespace(close=lambda: held.append(log_lock.locked()))

    close_logs(log_file, log_lock)[which]()

    # a write checks that the file is open and writes to it under this lock
    assert held == [True]
