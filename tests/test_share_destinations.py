"""Keep retired/unknown preferences usable without restoring a retired service."""
import json
import unittest
from pathlib import Path
from js_lift import NODE, slice_braced
import subprocess

@unittest.skipIf(NODE is None, "node required")
class ShareDestinationsTest(unittest.TestCase):
    def test_retired_preference_falls_back_and_supported_destinations_are_preserved(self):
        source = (Path(__file__).resolve().parents[1] / "js/comfyui-manager.js").read_text()
        start = source.index("const share_options = [")
        options = source[start:source.index("];", start)+2]
        function = slice_braced(source, "function normalizeShareOption(value)")
        script = options + function + "\nconsole.log(JSON.stringify(['copus','unknown','','none','openart','youml','matrix','comfyworkflows','all'].map(normalizeShareOption)));"
        result = subprocess.run([NODE, "-e", script], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout), ['all','all','all','none','openart','youml','matrix','comfyworkflows','all'])
