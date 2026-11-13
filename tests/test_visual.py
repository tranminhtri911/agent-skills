"""PNG codec, pixel comparison, visual statuses and baseline approval."""

import importlib.util
import json
import unittest
import zlib

from devskills.png import RgbaImage, _read_pure, encode_png, read_png, write_png
from devskills.visual import NEEDS_BASELINE, PROFILE_MISMATCH, VISUAL_FAIL, VISUAL_PASS, MaskRect, compare_files, compare_images
from tests._support import make_temp_dir, run_cli, run_cli_json

HAS_PILLOW = importlib.util.find_spec("PIL") is not None


def solid(width, height, rgba=(255, 255, 255, 255)):
    return RgbaImage(width, height, bytearray(bytes(rgba) * (width * height)))


class PngCodecTest(unittest.TestCase):
    def test_roundtrip_pure_decoder(self):
        image = solid(7, 5, (10, 20, 30, 255))
        image.pixels[4:8] = bytes((200, 100, 50, 128))
        path = make_temp_dir(self) / "a.png"
        write_png(path, image)
        decoded = _read_pure(path)
        self.assertEqual((decoded.width, decoded.height, bytes(decoded.pixels)), (7, 5, bytes(image.pixels)))

    def test_rgb_with_filters_matches_pillow(self):
        if not HAS_PILLOW:
            self.skipTest("Pillow not installed")
        from PIL import Image

        path = make_temp_dir(self) / "gradient.png"
        gradient = Image.new("RGB", (64, 32))
        gradient.putdata([((x * 4) % 256, (y * 8) % 256, (x * y) % 256) for y in range(32) for x in range(64)])
        gradient.save(path, optimize=True)
        self.assertEqual(bytes(_read_pure(path).pixels), bytes(read_png(path).pixels))

    def test_rejects_non_png(self):
        path = make_temp_dir(self) / "x.png"
        path.write_bytes(b"not a png" + zlib.compress(b"x"))
        with self.assertRaises(ValueError):
            _read_pure(path)
        self.assertTrue(encode_png(solid(1, 1)).startswith(b"\x89PNG"))


class CompareTest(unittest.TestCase):
    def test_identical_images_pass(self):
        result = compare_images(solid(20, 10), solid(20, 10), 16, 0.0)
        self.assertEqual((result.status, result.diff_pixels), (VISUAL_PASS, 0))

    def test_changed_pixel_is_counted_with_bounding_box(self):
        current = solid(20, 10)
        offset = (3 * 20 + 5) * 4
        current.pixels[offset:offset + 4] = bytes((0, 0, 0, 255))
        result = compare_images(solid(20, 10), current, 16, 0.0)
        self.assertEqual((result.status, result.diff_pixels), (VISUAL_FAIL, 1))
        self.assertEqual(result.bounding_box, {"x": 5, "y": 3, "width": 1, "height": 1})
        self.assertIsNotNone(result.diff_image)
        self.assertEqual(compare_images(solid(20, 10), current, 16, 0.01).status, VISUAL_PASS, "1/200 pixels is within 1%")
        self.assertEqual(compare_images(solid(20, 10), current, 255, 0.0).status, VISUAL_PASS, "below threshold")
        self.assertEqual(compare_images(solid(20, 10), current, 16, 0.0, [MaskRect(5, 3, 1, 1)]).status, VISUAL_PASS)

    def test_dimension_mismatch_fails_without_resizing(self):
        result = compare_images(solid(20, 10), solid(20, 11), 16, 1.0)
        self.assertEqual(result.status, VISUAL_FAIL)
        self.assertIn("never resized", result.reason)

    def test_compare_files_statuses(self):
        directory = make_temp_dir(self)
        current = directory / "current.png"
        write_png(current, solid(4, 4))
        self.assertEqual(compare_files(directory / "missing.png", current, None, 16, 0.0, [])["visual_status"], NEEDS_BASELINE)
        baseline = directory / "baseline.png"
        write_png(baseline, solid(4, 4))
        mismatch = compare_files(baseline, current, None, 16, 0.0, [], {"browser_version": "1"}, {"browser_version": "2"})
        self.assertEqual(mismatch["visual_status"], PROFILE_MISMATCH)
        self.assertEqual(compare_files(baseline, current, None, 16, 0.0, [])["visual_status"], VISUAL_PASS)


class VisualCliTest(unittest.TestCase):
    def test_cli_needs_baseline_then_accept_then_pass(self):
        directory = make_temp_dir(self)
        current = directory / "page.png"
        baseline = directory / "baselines" / "page.png"
        write_png(current, solid(8, 8, (1, 2, 3, 255)))
        code, record = run_cli_json("visual-diff", "--repo", str(directory), "--baseline", str(baseline), "--current", str(current))
        self.assertEqual((code, record["domain_result"]), (4, NEEDS_BASELINE))
        refused = run_cli("accept-baseline", "--repo", str(directory), "--current", str(current), "--baseline", str(baseline),
                          "--approved-by", " ", "--reason", "x")
        self.assertEqual(refused.returncode, 2)
        accepted = run_cli("accept-baseline", "--repo", str(directory), "--current", str(current), "--baseline", str(baseline),
                           "--approved-by", "reviewer", "--reason", "new checkout layout")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        approvals = (baseline.parent / "BASELINE_APPROVALS.jsonl").read_text().splitlines()
        self.assertEqual(json.loads(approvals[0])["approved_by"], "reviewer")
        code, record = run_cli_json("visual-diff", "--repo", str(directory), "--baseline", str(baseline), "--current", str(current))
        self.assertEqual((code, record["domain_result"]), (0, VISUAL_PASS))
        write_png(current, solid(8, 8, (250, 2, 3, 255)))
        code, record = run_cli_json("visual-diff", "--repo", str(directory), "--baseline", str(baseline), "--current", str(current))
        self.assertEqual((code, record["domain_result"]), (3, VISUAL_FAIL))
        self.assertTrue((directory / "page.diff.png").is_file())


if __name__ == "__main__":
    unittest.main()
