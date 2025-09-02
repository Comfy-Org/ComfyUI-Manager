import locale
import sys
import re


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


def convert_markdown_to_html(input_text):
    pattern_a = re.compile(r"\[a/([^]]+)]\(([^)]+)\)")
    pattern_w = re.compile(r"\[w/([^]]+)]")
    pattern_i = re.compile(r"\[i/([^]]+)]")
    pattern_bold = re.compile(r"\*\*([^*]+)\*\*")
    pattern_white = re.compile(r"%%([^*]+)%%")

    def replace_a(match):
        return f"<a href='{match.group(2)}' target='blank'>{match.group(1)}</a>"

    def replace_w(match):
        return f"<p class='cm-warn-note'>{match.group(1)}</p>"

    def replace_i(match):
        return f"<p class='cm-info-note'>{match.group(1)}</p>"

    def replace_bold(match):
        return f"<B>{match.group(1)}</B>"

    def replace_white(match):
        return f"<font color='white'>{match.group(1)}</font>"

    input_text = (
        input_text.replace("\\[", "&#91;")
        .replace("\\]", "&#93;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

    result_text = re.sub(pattern_a, replace_a, input_text)
    result_text = re.sub(pattern_w, replace_w, result_text)
    result_text = re.sub(pattern_i, replace_i, result_text)
    result_text = re.sub(pattern_bold, replace_bold, result_text)
    result_text = re.sub(pattern_white, replace_white, result_text)

    return result_text.replace("\n", "<BR>")
