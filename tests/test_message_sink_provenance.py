"""Inventory the current direct message-sink calls and reviewed error builders.

These sinks accept HTML because some callers render buttons and server-escaped
metadata. Unknown arguments or assignments require a provenance review. Runtime
rendering tests separately verify that raw text stays inert and escaped titles
remain readable; this source inventory is not a general JavaScript dataflow check.
"""
import re
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from js_lift import _skip_literal

REPO_ROOT = Path(__file__).resolve().parent.parent
JS_DIR = REPO_ROOT / "js"

SINK_FILES = [
    "common.js",
    "custom-nodes-manager.js",
    "model-manager.js",
    "node-usage-analyzer.js",
]

SINK_METHODS = r"showStatus|showMessage|showError|showSelection"

# Capture receivers so a new alias is reviewed instead of silently omitted.
CALL_RE = re.compile(
    r"(?<![\w$.])([\w$]+(?:\??\.[\w$]+)*)"
    rf"\??\.({SINK_METHODS})\("
)
SINK_CALL_RE = re.compile(
    rf"(?:\.(?:{SINK_METHODS})|\[\s*['\"](?:{SINK_METHODS})['\"]\s*\])"
    r"\s*(?:\?\.\s*)?\("
)

PINNED_RECEIVERS = frozenset({"this", "self", "this.ui"})

# Destructuring would hide calls from the receiver-based inventory.
DESTRUCTURE_RE = re.compile(
    r"(?:const|let|var)\s*\{[^}]*\b"
    rf"(?:{SINK_METHODS})"
    r"\b[^}]*\}"
)

SERVER_ESCAPED = "server-escaped"   # already display-ready; caller must NOT escape
RAW = "raw"                         # not display-ready; caller MUST escape
NO_DATA = "no-data"                 # no channel/registry value interpolated
FORWARDED = "forwarded"             # showError's own delegation; see HtmlByDesignSinkTest


def _argument(source: str, start: int) -> str:
    """Read a complete argument, including multiline templates."""
    depth = 1
    end = start
    while depth:
        skipped = _skip_literal(source, end)
        if skipped != end:
            end = skipped
            continue
        if source[end] == "(":
            depth += 1
        elif source[end] == ")":
            depth -= 1
        end += 1
    if source[end:end + 1] == ";":
        end += 1
    return re.sub(r"\s+", " ", source[start:end].strip())


def _call_sites():
    """Return (file, line, receiver, method, argument) for direct calls."""
    sites = []
    for name in SINK_FILES:
        source = (JS_DIR / name).read_text(encoding="utf-8")
        matches = list(CALL_RE.finditer(source))
        parsed = {match.end() for match in matches}
        for candidate in SINK_CALL_RE.finditer(source):
            if candidate.end() not in parsed:
                lineno = source.count("\n", 0, candidate.start()) + 1
                raise AssertionError(f"Unsupported message-sink call at {name}:{lineno}")
        for match in matches:
            lineno = source.count("\n", 0, match.start()) + 1
            sites.append((name, lineno, match.group(1), match.group(2),
                          _argument(source, match.end())))
    return sites


# ---------------------------------------------------------------------------
# THE REGISTRY. Keyed by (file, method, argument-source). Every showStatus and
# showMessage call site must appear here with a provenance verdict and a reason.
# ---------------------------------------------------------------------------
REGISTRY = {
    # --- custom-nodes-manager.js -------------------------------------------
    ("custom-nodes-manager.js", "showStatus",
     "`${prevViewRowsLength.toLocaleString()} custom nodes`);"):
        (NO_DATA, "a formatted row count"),
    ("custom-nodes-manager.js", "showStatus",
     "`Loading node mappings (${mode}) ...`);"):
        (NO_DATA, "`mode` is a datasrc-combo value chosen in the UI, not channel data"),
    ("custom-nodes-manager.js", "showStatus",
     "`${label} ${item.title} ...`);"):
        (SERVER_ESCAPED,
         "item.title comes from /customnode/getlist, where populate_markdown -> "
         "sanitize_tag has already escaped it; escaping again shows entities"),
    ("custom-nodes-manager.js", "showStatus",
     "`${label} ${Object.keys(result).length} custom node(s) successfully`);"):
        (NO_DATA, "a count of queue results"),
    ("custom-nodes-manager.js", "showStatus",
     "`Loading missing nodes (${mode}) ...`);"):
        (NO_DATA, "UI-chosen mode"),
    ("custom-nodes-manager.js", "showStatus",
     "`Loading alternatives (${mode}) ...`);"):
        (NO_DATA, "UI-chosen mode"),
    ("custom-nodes-manager.js", "showStatus",
     "`Loading workflow usage analysis ...`);"):
        (NO_DATA, "hardcoded"),
    ("custom-nodes-manager.js", "showStatus",
     "`Loading custom nodes (${mode}) ...`);"):
        (NO_DATA, "UI-chosen mode"),
    ("custom-nodes-manager.js", "showMessage",
     "`To apply the installed/updated/disabled/enabled custom node, please restart "
     "ComfyUI. And refresh browser.`, \"red\");"):
        (NO_DATA, "hardcoded"),
    ("custom-nodes-manager.js", "showMessage", "\"\");"):
        (NO_DATA, "clears the banner"),

    # --- model-manager.js ---------------------------------------------------
    ("model-manager.js", "showStatus",
     "`${grid.viewRows.length.toLocaleString()} external models`);"):
        (NO_DATA, "a formatted row count"),
    ("model-manager.js", "showStatus", "`Install ${item.name} ...`);"):
        (SERVER_ESCAPED,
         "item.name comes from /externalmodel/getlist, where populate_markdown -> "
         "sanitize_tag has already escaped it. WI-112 added a caller escape here "
         "and it rendered '&lt;Flux&gt;' to the user; removing it is the fix"),
    ("model-manager.js", "showStatus", "`Install ${result.length} models successfully`);"):
        (NO_DATA, "a count of queue results"),
    ("model-manager.js", "showStatus", "`Loading external model list ...`);"):
        (NO_DATA, "hardcoded"),
    ("model-manager.js", "showMessage",
     "`To apply the installed model, please click the 'Refresh' button.`, \"red\")"):
        (NO_DATA, "hardcoded"),
    ("model-manager.js", "showMessage", "\"\");"):
        (NO_DATA, "clears the banner"),

    # --- node-usage-analyzer.js --------------------------------------------
    ("node-usage-analyzer.js", "showStatus",
     "`${grid.viewRows.length.toLocaleString()} installed packages`);"):
        (NO_DATA, "a formatted row count"),
    ("node-usage-analyzer.js", "showStatus",
     "`Install ${sanitizeHTML(String(item.name))} ...`);"):
        (RAW,
         "item.name is packKey (loadData sets `name: packKey`) — a raw dict key no "
         "server transform touches, so this caller escapes it. The ONLY raw-provenance "
         "showStatus caller in the four files"),
    ("node-usage-analyzer.js", "showStatus", "msg);"):
        (SERVER_ESCAPED,
         "uninstallNodes preserves the escaped title or escapes the raw name fallback; "
         "test_node_usage_escaping executes that path through the panel sink"),
    ("node-usage-analyzer.js", "showStatus",
     "`Uninstalled ${targets.length} custom node(s) successfully`);"):
        (NO_DATA, "a count of targets"),
    ("node-usage-analyzer.js", "showStatus",
     "`Install ${Object.keys(result).length} models successfully`);"):
        (NO_DATA, "a count of queue results"),
    ("node-usage-analyzer.js", "showStatus",
     "`Uninstall ${Object.keys(result).length} custom node(s) successfully`);"):
        (NO_DATA, "a count of queue results"),
    ("node-usage-analyzer.js", "showStatus", "`Analyzing node usage ...`);"):
        (NO_DATA, "hardcoded"),
    ("node-usage-analyzer.js", "showMessage",
     "`To apply the uninstalled custom nodes, please restart ComfyUI and refresh "
     "browser.`, \"red\");"):
        (NO_DATA, "hardcoded"),
    ("node-usage-analyzer.js", "showMessage",
     "`To apply the installed model, please click the 'Refresh' button.`, \"red\");"):
        (NO_DATA, "hardcoded"),
    ("node-usage-analyzer.js", "showMessage", "\"No workflows were found for analysis.\");"):
        (NO_DATA, "hardcoded"),
    ("node-usage-analyzer.js", "showMessage", "\"\");"):
        (NO_DATA, "clears the banner"),

    # --- showError's own delegation, in each of the three classes -----------
    # Not an application caller: this IS `showError(err) { this.showMessage(err,
    # "red"); }`. Whether `err` is display-ready is the showError CALLER's
    # responsibility, which HtmlByDesignSinkTest below enforces separately. It is
    # registered rather than pattern-excluded so that if showError ever stops
    # forwarding — or starts forwarding something else — this entry goes stale
    # and the guard says so.
    ("custom-nodes-manager.js", "showMessage", "err, \"red\");"):
        (FORWARDED, "showError delegation; err is escaped by the showError caller"),
    ("model-manager.js", "showMessage", "err, \"red\");"):
        (FORWARDED, "showError delegation; err is escaped by the showError caller"),
    ("node-usage-analyzer.js", "showMessage", "err, \"red\");"):
        (FORWARDED, "showError delegation; err is escaped by the showError caller"),
}

DISPLAY_READY_METHODS = ("showStatus", "showMessage")

# A caller escape is spelled this way throughout the UI files.
ESCAPE_MARKER = "sanitizeHTML"


class MessageSinkRegistryTest(unittest.TestCase):
    """The registry must account for every display-ready-sink call site."""

    @classmethod
    def setUpClass(cls):
        cls.sites = _call_sites()

    def test_the_four_sink_implementations_all_exist(self):
        # If a file stops defining its own sink (e.g. it starts delegating to
        # createUIStateManager) the registry's routing assumptions change and
        # this guard must be re-derived rather than silently kept.
        own = {
            "custom-nodes-manager.js": ".cn-manager-status",
            "model-manager.js": ".cmm-manager-status",
            "node-usage-analyzer.js": ".nu-manager-status",
        }
        for name, selector in own.items():
            source = (JS_DIR / name).read_text(encoding="utf-8")
            self.assertIn("showStatus(msg, color)", source, "%s lost its own sink" % name)
            self.assertIn(selector, source)
        common = (JS_DIR / "common.js").read_text(encoding="utf-8")
        self.assertIn("export function createUIStateManager(", common)
        self.assertIn("showStatus: (msg, color)", common)

    def test_every_caller_is_classified(self):
        """FAIL-CLOSED: an unregistered call site breaks the build."""
        observed = Counter((name, method, arg) for name, _, _, method, arg in self.sites
                           if method in DISPLAY_READY_METHODS)
        duplicates = {
            ('custom-nodes-manager.js', 'showStatus', '`Loading workflow usage analysis ...`);'),
            ('node-usage-analyzer.js', 'showMessage',
             '`To apply the uninstalled custom nodes, please restart ComfyUI and refresh browser.`, "red");'),
        }
        expected = Counter({key: 1 + (key in duplicates) for key in REGISTRY})
        self.assertEqual(observed, expected, 'Changed message calls require a provenance review')

    def test_the_observed_receivers_are_the_pinned_set(self):
        observed = {receiver for _name, _lineno, receiver, _m, _a in self.sites}
        self.assertEqual(
            observed, set(PINNED_RECEIVERS),
            "the set of receivers calling the message sinks changed: %s. These "
            "sinks assign innerHTML and DO NOT escape, so every route to them "
            "must be accounted for. Classify the new receiver's call sites in "
            "REGISTRY and add it to PINNED_RECEIVERS — do not narrow CALL_RE to "
            "make this pass." % (sorted(observed ^ set(PINNED_RECEIVERS)),),
        )

    def test_no_sink_method_is_destructured_out_of_its_receiver(self):
        for name in SINK_FILES:
            source = (JS_DIR / name).read_text(encoding="utf-8")
            with self.subTest(file=name):
                self.assertEqual(
                    DESTRUCTURE_RE.findall(source), [],
                    "%s destructures a message-sink method out of its receiver. "
                    "The resulting bare calls are invisible to this guard; call "
                    "them through their receiver instead." % (name,),
                )

    def test_unsupported_sink_calls_require_review(self):
        source = (JS_DIR / "common.js").read_text(encoding="utf-8")
        for call in ('this["showMessage"](raw);',
                     'createUIStateManager(element).showError(raw);'):
            with self.subTest(call=call), patch(__name__ + ".SINK_FILES", ["common.js"]):
                with patch.object(Path, "read_text", return_value=source + "\n" + call):
                    with self.assertRaisesRegex(AssertionError, "Unsupported message-sink call"):
                        _call_sites()

    def test_the_registry_has_no_stale_entries(self):
        """A registry entry whose call site is gone or whose argument changed."""
        live = {
            (name, method, arg)
            for name, _lineno, _receiver, method, arg in self.sites
            if method in DISPLAY_READY_METHODS
        }
        stale = sorted(key for key in REGISTRY if key not in live)
        self.assertEqual(
            stale, [],
            "REGISTRY entries no longer match any call site — the caller was removed "
            "or its argument changed, so its provenance verdict is unverified:\n  %s"
            % "\n  ".join("%s %s(%s" % key for key in stale),
        )

    def test_server_escaped_callers_do_not_escape_again(self):
        for (name, method, arg), (provenance, reason) in REGISTRY.items():
            if provenance != SERVER_ESCAPED:
                continue
            with self.subTest(file=name, method=method, arg=arg):
                self.assertNotIn(
                    ESCAPE_MARKER, arg,
                    "%s %s escapes an ALREADY-escaped value — the user reads "
                    "'&lt;Flux&gt;' instead of '<Flux>'. Reason on file: %s"
                    % (name, method, reason),
                )

    def test_raw_callers_escape(self):
        for (name, method, arg), (provenance, reason) in REGISTRY.items():
            if provenance != RAW:
                continue
            with self.subTest(file=name, method=method, arg=arg):
                self.assertIn(
                    ESCAPE_MARKER, arg,
                    "%s %s passes a RAW value into a sink that does not escape. "
                    "Reason on file: %s" % (name, method, reason),
                )

    def test_no_data_callers_interpolate_no_channel_value(self):
        # Interpolations are allowed, but only of things that cannot carry
        # channel/registry text: counts, lengths, and the UI-chosen mode.
        allowed = re.compile(
            r"^\$\{(?:[A-Za-z_.]*\.length|Object\.keys\([A-Za-z_.]+\)\.length"
            r"|[A-Za-z_.]+\.toLocaleString\(\)|mode|label"
            r"|[A-Za-z_.]*\.length\.toLocaleString\(\))\}$"
        )
        for (name, method, arg), (provenance, reason) in REGISTRY.items():
            if provenance != NO_DATA:
                continue
            for expr in re.findall(r"\$\{[^}]*\}", arg):
                with self.subTest(file=name, method=method, expr=expr):
                    self.assertRegex(
                        expr, allowed,
                        "%s %s is classified %s but interpolates %s, which is not a "
                        "count or a UI-chosen value. Re-classify it. Reason on file: %s"
                        % (name, method, NO_DATA, expr, reason),
                    )


class HtmlByDesignSinkTest(unittest.TestCase):
    """showSelection / showError render real markup and are NOT display-ready sinks."""

    @classmethod
    def setUpClass(cls):
        cls.sites = _call_sites()

    def test_show_selection_receives_no_channel_data(self):
        expected = {
            "custom-nodes-manager.js": [
                '"");',
                '"");',
                # Unknown labels in this builder have behavioral coverage.
                'list.join(""));',
            ],
            "model-manager.js": [
                '"");',
                '"");',
                '`<span>Selected <b>${selectedList.length}</b> models <button '
                'class="cmm-btn-install p-button p-component" mode="install">Install</button>`);',
            ],
            "node-usage-analyzer.js": [
                '"");',
                '"");',
                '`<span>Selected <b>${selectedList.length}</b> packages (none can be uninstalled)</span>`);',
                '` <div class="nu-selected-buttons"> <span>Selected <b>${installedSelected.length}</b> '
                'installed packages</span> <button class="nu-btn-uninstall" mode="uninstall">'
                'Uninstall Selected</button> </div> `);',
            ],
        }
        actual = Counter((name, arg) for name, _, _, method, arg in self.sites if method == "showSelection")
        self.assertEqual(actual, Counter((name, arg) for name, args in expected.items() for arg in args))

    def test_show_error_arguments_are_escaped_or_literal(self):
        # showError forwards to showMessage, which does not escape, AND its
        # errorMsg is separately handed to ComfyUI-core show_message(). So every
        # non-literal argument must already be escaped at the call site.
        escaped = {
            "custom-nodes-manager.js": {
                '`Failed to get custom node mappings: ${sanitizeHTML(String(res.error))}`);',
                '`Failed to get alternatives: ${sanitizeHTML(String(res.error))}`);',
                '`Failed to get workflow data: ${sanitizeHTML(String(result.error))}`);',
            },
            "node-usage-analyzer.js": {'sanitizeHTML(String(result.error)));'},
        }
        for name, lineno, _receiver, method, arg in self.sites:
            if method != "showError":
                continue
            is_literal = re.fullmatch(
                r'''(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')\s*\);''', arg,
            ) is not None
            # These direct arguments are checked by the per-file guards below.
            is_error_var = re.fullmatch(r"errorMsg\s*\);", arg) is not None
            with self.subTest(file=name, line=lineno, arg=arg):
                if is_literal or is_error_var:
                    continue
                self.assertIn(
                    arg, escaped.get(name, set()),
                    "%s:%d passes an unescaped non-literal into showError, which does "
                    "not escape and whose text also reaches core show_message()"
                    % (name, lineno),
                )

    def test_every_error_message_builder_escapes_its_server_text(self):
        common = {
            'errorMsg = "";',
            "errorMsg += `This action is not allowed with this security level configuration.\\n`;",
            "errorMsg += sanitizeHTML(await res.text()) + '\\n';",
        }
        queue_error = "errorMsg += sanitizeHTML(String(v)) + '\\n';"
        outdated = "errorMsg += `ComfyUI version is outdated. Please update ComfyUI to use Manager normally.\\n`;"
        expected = {
            "custom-nodes-manager.js": common | {
                "errorMsg = `'${item.title}': `;",
                "errorMsg = `Not found custom node: ${hash}`;",
                queue_error, outdated,
            },
            "model-manager.js": common | {
                "errorMsg = `'${item.name}': `;", queue_error, outdated,
            },
            "node-usage-analyzer.js": common | {
                "errorMsg = `'${sanitizeHTML(String(item.name))}': `;", queue_error,
            },
            "common.js": common | {"errorMsg = `'${displayTitle}': `;"},
        }
        mutations = re.compile(r"(?<![\w$.])errorMsg\s*(?:[+*/%&|^?-]*=(?!=)|\+\+|--)[^;]*;")
        for name, statements in expected.items():
            source = (JS_DIR / name).read_text(encoding="utf-8")
            actual = {re.sub(r"\s+", " ", match) for match in mutations.findall(source)}
            with self.subTest(file=name):
                self.assertEqual(actual, statements)

    def test_error_guard_rejects_unclassified_arguments(self):
        for argument in (
            "err);", "errText);", "errorMsg$raw);", "err + extra);", "err.detail);",
            '"prefix " + errText);', "'prefix ' + errText);",
            "sanitizeHTML(err) + extra);",
        ):
            with self.subTest(argument=argument):
                guard = HtmlByDesignSinkTest("test_show_error_arguments_are_escaped_or_literal")
                guard.sites = [("custom-nodes-manager.js", 1, "this", "showError", argument)]
                result = unittest.TestResult()
                guard.run(result)
                self.assertEqual(len(result.failures), 1)
                self.assertEqual(result.errors, [])

    def test_html_guards_reject_unreviewed_source(self):
        cases = [
            ("custom-nodes-manager.js", 'this.showSelection(list.join(""));',
             'this.showSelection(selectedList[0].title);',
             "test_show_selection_receives_no_channel_data"),
            ("node-usage-analyzer.js", "${installedSelected.length}</b>",
             "${installedSelected[0].title}</b>",
             "test_show_selection_receives_no_channel_data"),
            ("custom-nodes-manager.js", 'let errorMsg = "";',
             'let errorMsg = "";\nerrorMsg += response.message;',
             "test_every_error_message_builder_escapes_its_server_text"),
            ("model-manager.js", "errorMsg += sanitizeHTML(String(v)) + '\\n';",
             "errorMsg += sanitizeHTML(String(v)) + response.message + '\\n';",
             "test_every_error_message_builder_escapes_its_server_text"),
        ]
        for name, before, after, test in cases:
            with self.subTest(file=name, replacement=after), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                for filename in SINK_FILES:
                    source = (JS_DIR / filename).read_text(encoding="utf-8")
                    if filename == name:
                        self.assertIn(before, source)
                        source = source.replace(before, after, 1)
                    (directory / filename).write_text(source, encoding="utf-8")
                with patch(__name__ + ".JS_DIR", directory):
                    guard = HtmlByDesignSinkTest(test)
                    guard.sites = _call_sites()
                    result = unittest.TestResult()
                    guard.run(result)
                self.assertTrue(result.failures)
                self.assertEqual(result.errors, [])

    def test_duplicate_calls_require_review(self):
        for cls, test, argument in (
            (MessageSinkRegistryTest, 'test_every_caller_is_classified', 'msg);'),
            (HtmlByDesignSinkTest, 'test_show_selection_receives_no_channel_data', 'list.join(""));'),
        ):
            with self.subTest(test=test):
                guard = cls(test)
                guard.sites = _call_sites()
                guard.sites.append(next(site for site in guard.sites if site[-1] == argument))
                result = unittest.TestResult()
                guard.run(result)
                self.assertTrue(result.failures)
                self.assertEqual(result.errors, [])


if __name__ == "__main__":
    unittest.main()
