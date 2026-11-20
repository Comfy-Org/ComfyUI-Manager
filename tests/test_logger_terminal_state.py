"""The startup logger reports the terminal state of the stream it wraps (#3259).

A logger that always answered "not a terminal" made colorama, and any other library that
asks, strip its colors and hide its progress display for the whole session.

Other cases are about what is written once the log file is closed: the restart under
comfy-cli closes it and then exits, and what is logged on the way out must not fail.
"""
import ast
import errno
import io
import logging
import os
import re
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


def assigned(name):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    return next(ast.literal_eval(n.value) for n in ast.walk(tree)
                if isinstance(n, ast.Assign) and [t.id for t in n.targets if isinstance(t, ast.Name)] == [name])


def writing_loggers(stdout, stderr, log_file):
    return loggers(stdout, stderr, log_file=log_file, log_lock=threading.Lock(), std_log_lock=threading.Lock(),
                   current_timestamp=lambda: "12:00:00", write_stdout=stdout.write, write_stderr=stderr.write,
                   re=re, pat_tqdm=assigned("pat_tqdm"), message_collapses=[], is_start_mode=False)


def recording_stream():
    written = []
    return SimpleNamespace(write=written.append, flush=lambda: None), written


def writing_logger(log_file):
    """The stderr logger with what its writes need, and the list of what reached the console."""
    stream, console = recording_stream()
    _, err = writing_loggers(stream, stream, log_file)
    return err, console


def logging_handler(console, log_file):
    source = SOURCE.read_text(encoding="utf-8")
    node = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ClassDef) and n.name == "LoggingHandler")
    _, err = writing_loggers(console, console, log_file)
    scope = {"logging": logging, "is_start_mode": False, "stderr_wrapper": err, "original_stderr": console}
    exec(textwrap.dedent("\n".join(source.splitlines()[node.lineno - 1:node.end_lineno])), scope)
    return scope["LoggingHandler"]()


def pipe_without_a_reader(unbuffered):
    read_end, write_end = os.pipe()
    os.close(read_end)
    if unbuffered:
        return io.TextIOWrapper(io.FileIO(write_end, "w"), encoding="utf-8", write_through=True)
    return open(write_end, "w", encoding="utf-8")


def terminal_that_has_hung_up():
    if not hasattr(os, "openpty"):
        pytest.skip("no pseudo-terminal on this platform")
    master, slave = os.openpty()
    stream = open(slave, "w", encoding="utf-8")
    os.close(master)
    return stream


@pytest.fixture(params=["pipe", "unbuffered pipe", "terminal"])
def console_that_is_gone(request):
    """A pipe whose reader has exited fails with EPIPE: at the flush, or at the write when the
    stream is unbuffered, as it is with -u. A terminal that has hung up fails with EIO, at
    the write of a line, since the stream of a terminal is line-buffered."""
    if request.param == "terminal":
        stream = terminal_that_has_hung_up()
    else:
        stream = pipe_without_a_reader(unbuffered=request.param == "unbuffered pipe")
    yield stream
    try:
        stream.close()
    except OSError:
        pass


class CountingWrites:
    def __init__(self, stream):
        self.stream = stream
        self.writes = 0

    def write(self, text):
        self.writes += 1
        return self.stream.write(text)

    def flush(self):
        return self.stream.flush()


def run_progress_bar(logger):
    tqdm = pytest.importorskip("tqdm")
    for _ in tqdm.tqdm(range(3), file=logger, mininterval=0, miniters=1, disable=False):
        pass


def write_a_line(logger):
    logger.write("second\n")


class Unprintable:
    def __str__(self):
        raise RuntimeError("no text for this")


class UnprintableWithItsError:
    def __str__(self):
        raise RuntimeError(self)


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


def test_progress_of_a_bar_is_shown_and_only_the_finished_bar_is_logged():
    log_file = LogFile()
    logger, console = writing_logger(log_file)

    run_progress_bar(logger)

    shown, logged = "".join(console), "".join(log_file.written)
    assert "1/3" in shown and "3/3" in shown
    assert "3/3" in logged and "1/3" not in logged


def test_each_logger_writes_to_its_own_console_stream():
    stdout, on_stdout = recording_stream()
    stderr, on_stderr = recording_stream()
    out, err = writing_loggers(stdout, stderr, LogFile())

    out.write("to stdout\n")
    err.write("to stderr\n")
    run_progress_bar(err)

    assert on_stdout == ["to stdout\n"]
    assert on_stderr[0] == "to stderr\n" and "3/3" in "".join(on_stderr)


def test_progress_bar_does_not_fail_once_the_console_is_gone(console_that_is_gone):
    log_file = LogFile()
    _, logger = writing_loggers(console_that_is_gone, console_that_is_gone, log_file)

    run_progress_bar(logger)

    assert "3/3" in "".join(log_file.written)


@pytest.mark.parametrize("which", [0, 1], ids=["stdout", "stderr"])
def test_text_does_not_fail_and_is_logged_once_the_console_is_gone(console_that_is_gone, which):
    log_file = LogFile()
    logger = writing_loggers(console_that_is_gone, console_that_is_gone, log_file)[which]

    logger.write("a line of a node\n")

    assert log_file.written == ["a line of a node\n"]


@pytest.mark.parametrize("then", [write_a_line, run_progress_bar], ids=["text", "progress bar"])
def test_console_that_has_failed_is_not_written_to_again(console_that_is_gone, then):
    gone = CountingWrites(console_that_is_gone)
    healthy, shown = recording_stream()
    out, err = writing_loggers(healthy, gone, LogFile())

    err.write("first\n")
    then(err)
    out.write("to stdout\n")

    assert gone.writes == 1
    assert shown == ["to stdout\n"]


def test_console_that_cannot_take_a_write_now_is_written_to_again():
    taken = []

    def write(text):
        if not taken:
            taken.append(None)
            raise BlockingIOError(errno.EAGAIN, "write could not complete without blocking")
        taken.append(text)

    console = SimpleNamespace(write=write, flush=lambda: None)
    out, _ = writing_loggers(console, console, LogFile())

    out.write("dropped\n")
    out.write("shown\n")

    assert taken == [None, "shown\n"]


def test_what_is_written_reaches_a_buffered_console_at_once():
    behind = io.BytesIO()
    console = io.TextIOWrapper(behind, encoding="utf-8")
    out, _ = writing_loggers(console, console, LogFile())

    out.write("a line")

    assert behind.getvalue() == b"a line"


def test_text_that_the_console_cannot_encode_fails_as_it_does_without_the_logger():
    console = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    out, _ = writing_loggers(console, console, LogFile())

    with pytest.raises(UnicodeEncodeError):
        out.write("half of a surrogate pair \udc80\n")


@pytest.mark.parametrize("message, arguments, error", [
    ("two values %s %s", ("only one",), "TypeError: not enough arguments for format string"),
    ("%(missing)s", ({"other": 1},), "KeyError: 'missing'"),
    (Unprintable(), (), "RuntimeError: no text for this"),
    (UnprintableWithItsError(), (), "RuntimeError"),
], ids=["too few arguments", "a missing key", "a message that cannot be printed",
        "a message whose error cannot be printed either"])
def test_record_that_cannot_be_formatted_is_logged_and_does_not_fail(message, arguments, error):
    console, shown = recording_stream()
    log_file = LogFile()
    handler = logging_handler(console, log_file)

    handler.emit(logging.LogRecord("root", logging.INFO, "a_node.py", 7, message, arguments, None))

    assert len(log_file.written) == 1
    assert log_file.written[0].endswith(f"<<logging error>>: a_node.py:7 - {error}\n")
    assert shown == []


def test_record_that_cannot_be_formatted_is_logged_and_does_not_fail_once_the_console_is_gone(console_that_is_gone):
    log_file = LogFile()
    handler = logging_handler(console_that_is_gone, log_file)

    handler.emit(logging.LogRecord("root", logging.INFO, "a_node.py", 7, "two values\n%s %s", ("only one",), None))

    assert len(log_file.written) == 1 and "a_node.py:7" in log_file.written[0]
