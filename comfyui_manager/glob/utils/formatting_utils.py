import locale
import sys


def handle_stream(stream, prefix):
    stream.reconfigure(encoding=locale.getpreferredencoding(), errors="replace")
    for msg in stream:
        if (
            prefix == "[!]"
            and ("it/s]" in msg or "s/it]" in msg)
            and ("%|" in msg or "it [" in msg)
        ):
            if msg.startswith("100%"):
                print("\r" + msg, end="", file=sys.stderr),
            else:
                print("\r" + msg[:-1], end="", file=sys.stderr),
        else:
            if prefix == "[!]":
                print(prefix, msg, end="", file=sys.stderr)
            else:
                print(prefix, msg, end="")
