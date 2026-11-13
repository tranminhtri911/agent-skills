"""Real browser capture through Playwright (skipped when Playwright/Chromium are unavailable)."""

import functools
import importlib.util
import json
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from tests._support import make_temp_dir, run_cli, write

PAGE = """<!doctype html>
<html><head><title>checkout</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter">
<style>body { font-family: sans-serif; margin: 16px; } .spin { animation: spin 1s infinite; }</style></head>
<body><h1>Hello checkout</h1><p id="total">Total: 125,000 VND</p><div class="spin">*</div>
<script>console.error("synthetic error for the test")</script></body></html>
"""


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def browser_available() -> bool:
    if importlib.util.find_spec("playwright") is None:
        return False
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            playwright.chromium.launch(headless=True).close()
        return True
    except Exception:  # noqa: BLE001 — missing browser binaries or sandbox restrictions: the test is skipped, not failed.
        return False


@unittest.skipUnless(browser_available(), "Playwright for Python with Chromium is not available")
class ScreenshotTest(unittest.TestCase):
    def setUp(self):
        self.site = make_temp_dir(self)
        write(self.site, "checkout/index.html", PAGE)
        handler = functools.partial(QuietHandler, directory=str(self.site))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/checkout/index.html"
        self.repo = make_temp_dir(self)
        self.out = self.repo / "shots"

    def capture(self, *extra):
        completed = run_cli("screenshot", "--repo", str(self.repo), "--url", self.url, "--name", "checkout", "--viewport", "320x240",
                            "--wait-text", "Hello checkout", "--out-dir", str(self.out), "--json", *extra, timeout=180)
        return completed.returncode, json.loads(completed.stdout)

    def test_capture_only_then_baseline_lifecycle(self):
        code, record = self.capture()
        self.assertEqual(code, 0, record)
        manifest = record["details"]["manifests"][0]
        self.assertEqual(manifest["visual_status"], "CAPTURE_ONLY")
        self.assertTrue((self.out / "checkout-320x240.png").is_file())
        self.assertTrue(any("fonts.googleapis.com" in url for url in manifest["blocked_requests"]))
        self.assertTrue(any("synthetic error" in message for message in manifest["console_errors"]))
        self.assertEqual(manifest["viewport"], {"width": 320, "height": 240})
        self.assertIn("UI-EXTERNAL-REQUEST-BLOCKED", [finding["rule_id"] for finding in record["findings"]])

        baselines = self.repo / "baselines"
        code, record = self.capture("--baseline-dir", str(baselines))
        self.assertEqual((code, record["details"]["manifests"][0]["visual_status"]), (4, "NEEDS_BASELINE"))
        accepted = run_cli("accept-baseline", "--repo", str(self.repo), "--current", str(self.out / "checkout-320x240.png"),
                           "--baseline", str(baselines / "checkout-320x240.png"), "--approved-by", "reviewer", "--reason", "first baseline")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        code, record = self.capture("--baseline-dir", str(baselines))
        self.assertEqual((code, record["details"]["manifests"][0]["visual_status"]), (0, "PASS"), record["summary"])

    def test_remote_url_is_refused(self):
        completed = run_cli("screenshot", "--repo", str(self.repo), "--url", "https://example.com/")
        self.assertEqual(completed.returncode, 2)


class ViewportTest(unittest.TestCase):
    def test_default_is_mobile_and_laptop(self):
        from devskills.screenshot import parse_viewports

        self.assertEqual(parse_viewports([]), [("mobile", 390, 844), ("laptop", 1280, 800)])
        self.assertEqual(parse_viewports(["tablet", "1920x1080"]), [("tablet", 768, 1024), ("1920x1080", 1920, 1080)])


if __name__ == "__main__":
    unittest.main()
