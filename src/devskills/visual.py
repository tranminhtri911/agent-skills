"""Screenshot comparison and baseline lifecycle (plan §20.3, §20.4).

Statuses: PASS, FAIL, NEEDS_BASELINE, PROFILE_MISMATCH, CAPTURE_ONLY, BLOCKED.
Images are never resized to make them match, masks must carry a reason, and a
baseline changes only through `accept-baseline` with a named approver.
"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from devskills.fsutil import atomic_write_bytes, read_json, resolve_repo_root, sha256_file, utc_now_iso
from devskills.models import EXEC_COMPLETED, EXEC_TOOL_ERROR, GATE_BLOCKED, GATE_FAIL, GATE_PASS, CheckResult, Finding, UsageError
from devskills.output import emit_result, format_findings
from devskills.png import PngError, RgbaImage, read_png, write_png
from devskills.profile import load_profile

VISUAL_PASS = "PASS"
VISUAL_FAIL = "FAIL"
NEEDS_BASELINE = "NEEDS_BASELINE"
PROFILE_MISMATCH = "PROFILE_MISMATCH"
CAPTURE_ONLY = "CAPTURE_ONLY"
VISUAL_BLOCKED = "BLOCKED"

# Fields that must match between baseline and current capture profiles.
PROFILE_FIELDS = ("profile_id", "browser", "browser_version", "viewport", "device_scale_factor", "locale", "timezone",
                  "color_scheme", "platform")

# Lightens every channel (alpha stays 255) so differing pixels stand out in red.
_DIM_TABLE = bytes(min(255, value // 3 + 170) for value in range(256))


@dataclass
class MaskRect:
    x: int
    y: int
    width: int
    height: int


@dataclass
class CompareResult:
    status: str
    reason: str
    diff_pixels: int = 0
    total_pixels: int = 0
    bounding_box: dict[str, int] | None = None
    diff_image: RgbaImage | None = field(default=None, repr=False)

    @property
    def diff_ratio(self) -> float:
        return self.diff_pixels / self.total_pixels if self.total_pixels else 0.0


def parse_mask(spec: str) -> MaskRect:
    parts = spec.split(",")
    if len(parts) != 4 or not all(part.strip().isdigit() for part in parts):
        raise UsageError(f"--mask {spec!r}: expected X,Y,W,H in CSS pixels")
    x, y, width, height = (int(part) for part in parts)
    return MaskRect(x, y, width, height)


def _apply_masks(image: RgbaImage, masks: list[MaskRect]) -> RgbaImage:
    if not masks:
        return image
    pixels = bytearray(image.pixels)
    for mask in masks:
        x_start, x_end = max(0, mask.x), min(image.width, mask.x + mask.width)
        if x_start >= x_end:
            continue
        blank = bytes((x_end - x_start) * 4)
        for row in range(max(0, mask.y), min(image.height, mask.y + mask.height)):
            offset = row * image.stride
            pixels[offset + x_start * 4:offset + x_end * 4] = blank
    return RgbaImage(image.width, image.height, pixels)


def compare_images(baseline: RgbaImage, current: RgbaImage, pixel_threshold: int, max_diff_ratio: float,
                   masks: list[MaskRect] | None = None) -> CompareResult:
    """Count pixels whose largest channel delta exceeds `pixel_threshold`; build a diff image."""
    if (baseline.width, baseline.height) != (current.width, current.height):
        return CompareResult(VISUAL_FAIL, f"dimension mismatch: baseline {baseline.width}x{baseline.height}, "
                                          f"current {current.width}x{current.height} (images are never resized)")
    masks = masks or []
    baseline_masked = _apply_masks(baseline, masks)
    current_masked = _apply_masks(current, masks)
    stride = baseline.stride
    diff_pixels = 0
    min_x, min_y, max_x, max_y = baseline.width, baseline.height, -1, -1
    diff_buffer: bytearray | None = None
    for row in range(baseline.height):
        start = row * stride
        baseline_row = baseline_masked.pixels[start:start + stride]
        current_row = current_masked.pixels[start:start + stride]
        if baseline_row == current_row:
            continue
        for column in range(baseline.width):
            offset = column * 4
            delta = max(
                abs(baseline_row[offset] - current_row[offset]),
                abs(baseline_row[offset + 1] - current_row[offset + 1]),
                abs(baseline_row[offset + 2] - current_row[offset + 2]),
                abs(baseline_row[offset + 3] - current_row[offset + 3]),
            )
            if delta <= pixel_threshold:
                continue
            diff_pixels += 1
            min_x, min_y = min(min_x, column), min(min_y, row)
            max_x, max_y = max(max_x, column), max(max_y, row)
            if diff_buffer is None:
                diff_buffer = bytearray(baseline.pixels.translate(_DIM_TABLE))
            position = start + offset
            diff_buffer[position:position + 4] = b"\xff\x00\x00\xff"
    total_pixels = baseline.width * baseline.height
    bounding_box = None if max_x < 0 else {"x": min_x, "y": min_y, "width": max_x - min_x + 1, "height": max_y - min_y + 1}
    ratio = diff_pixels / total_pixels if total_pixels else 0.0
    status = VISUAL_PASS if ratio <= max_diff_ratio else VISUAL_FAIL
    reason = (f"{diff_pixels} of {total_pixels} pixels differ ({ratio:.4%}); "
              f"threshold {pixel_threshold}/255 per channel, allowed {max_diff_ratio:.4%}")
    diff_image = RgbaImage(baseline.width, baseline.height, diff_buffer) if diff_buffer is not None else None
    return CompareResult(status, reason, diff_pixels, total_pixels, bounding_box, diff_image)


def profile_mismatch(baseline_manifest: dict[str, Any] | None, current_manifest: dict[str, Any] | None) -> list[str]:
    """Fields whose values differ between the two capture profiles."""
    if not baseline_manifest or not current_manifest:
        return []
    return [name for name in PROFILE_FIELDS
            if name in baseline_manifest and name in current_manifest and baseline_manifest[name] != current_manifest[name]]


def compare_files(baseline_path: Path, current_path: Path, diff_path: Path | None, pixel_threshold: int, max_diff_ratio: float,
                  masks: list[MaskRect], baseline_manifest: dict | None = None, current_manifest: dict | None = None) -> dict[str, Any]:
    """Compare two PNG files and return a JSON-ready record including the visual status."""
    record: dict[str, Any] = {"baseline": str(baseline_path), "current": str(current_path),
                              "pixel_threshold": pixel_threshold, "max_diff_ratio": max_diff_ratio,
                              "masks": [mask.__dict__ for mask in masks]}
    if not current_path.is_file():
        return record | {"visual_status": VISUAL_BLOCKED, "reason": "current screenshot missing"}
    if not baseline_path.is_file():
        return record | {"visual_status": NEEDS_BASELINE, "reason": "no accepted baseline yet; review the capture and accept it explicitly"}
    mismatched = profile_mismatch(baseline_manifest, current_manifest)
    if mismatched:
        return record | {"visual_status": PROFILE_MISMATCH, "reason": f"capture profile differs: {', '.join(mismatched)}"}
    try:
        comparison = compare_images(read_png(baseline_path), read_png(current_path), pixel_threshold, max_diff_ratio, masks)
    except (PngError, OSError) as error:
        return record | {"visual_status": VISUAL_BLOCKED, "reason": f"cannot decode image: {error}"}
    record |= {
        "visual_status": comparison.status,
        "reason": comparison.reason,
        "diff_pixels": comparison.diff_pixels,
        "total_pixels": comparison.total_pixels,
        "diff_ratio": round(comparison.diff_ratio, 6),
        "bounding_box": comparison.bounding_box,
        "baseline_sha256": sha256_file(baseline_path),
        "current_sha256": sha256_file(current_path),
    }
    if comparison.diff_image is not None and diff_path is not None:
        write_png(diff_path, comparison.diff_image)
        record["diff"] = str(diff_path)
    return record


def gate_for_visual_status(status: str) -> str:
    if status == VISUAL_PASS:
        return GATE_PASS
    if status == VISUAL_FAIL:
        return GATE_FAIL
    # NEEDS_BASELINE, PROFILE_MISMATCH, CAPTURE_ONLY and BLOCKED are never a visual pass.
    return GATE_BLOCKED


def _load_manifest(path_text: str | None) -> dict | None:
    if not path_text:
        return None
    try:
        return read_json(Path(path_text))
    except (OSError, json.JSONDecodeError) as error:
        raise UsageError(f"cannot read manifest {path_text}: {error}") from error


def cmd_visual_diff(args: argparse.Namespace) -> int:
    """CLI handler for `visual-diff`: PASS/FAIL against the baseline; NEEDS_BASELINE/PROFILE_MISMATCH block."""
    repo_root = resolve_repo_root(args.repo)
    profile, _warnings = load_profile(repo_root)
    started_at = utc_now_iso()
    baseline_path = Path(args.baseline)
    current_path = Path(args.current)
    diff_path = Path(args.diff_out) if args.diff_out else current_path.with_name(current_path.stem + ".diff.png")
    pixel_threshold = args.pixel_threshold if args.pixel_threshold is not None else profile["visual"]["pixel_threshold"]
    max_diff_ratio = args.max_diff_ratio if args.max_diff_ratio is not None else profile["visual"]["max_diff_ratio"]
    if not 0 <= pixel_threshold <= 255 or not 0 <= max_diff_ratio <= 1:
        raise UsageError("--pixel-threshold must be 0-255 and --max-diff-ratio 0-1")
    record = compare_files(baseline_path, current_path, diff_path, pixel_threshold, max_diff_ratio,
                           [parse_mask(spec) for spec in args.mask],
                           _load_manifest(args.baseline_manifest), _load_manifest(args.current_manifest))
    status = record["visual_status"]
    findings = [] if status == VISUAL_PASS else [Finding("UI-VISUAL", "high" if status == VISUAL_FAIL else "medium",
                                                         f"{status}: {record['reason']}", str(current_path))]
    result = CheckResult(
        check_id=getattr(args, "check_id", "ui.visual"),
        tool="devskills.visual-diff",
        execution_status=EXEC_COMPLETED if status != VISUAL_BLOCKED else EXEC_TOOL_ERROR,
        gate_result=gate_for_visual_status(status),
        domain_result=status,
        summary=record["reason"],
        findings=findings,
        details=record,
        evidence_refs=[path for path in (record.get("current"), record.get("baseline"), record.get("diff")) if path],
        started_at=started_at,
    )
    lines = [f"visual-diff: {status}", f"  {record['reason']}"]
    if record.get("diff"):
        lines.append(f"  diff image: {record['diff']}")
    if status == NEEDS_BASELINE:
        lines.append("  A reviewer must look at the capture before it becomes a baseline (accept-baseline --approved-by).")
    lines.extend(format_findings(findings))
    return emit_result(args, repo_root, result, lines)


def cmd_accept_baseline(args: argparse.Namespace) -> int:
    """Promote a reviewed capture to baseline and append an approval record next to it."""
    current_path = Path(args.current)
    baseline_path = Path(args.baseline)
    approver = args.approved_by.strip()
    reason = args.reason.strip()
    if not approver or not reason:
        raise UsageError("--approved-by and --reason must not be empty")
    if not current_path.is_file():
        raise UsageError(f"current screenshot not found: {current_path}")
    previous_sha = sha256_file(baseline_path) if baseline_path.is_file() else None
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(baseline_path, current_path.read_bytes())
    manifest_source = current_path.with_suffix(".json")
    if manifest_source.is_file():
        shutil.copyfile(manifest_source, baseline_path.with_suffix(".json"))
    approval = {
        "baseline": baseline_path.name,
        "new_sha256": sha256_file(baseline_path),
        "previous_sha256": previous_sha,
        "approved_by": approver,
        "reason": reason,
        "approved_at": utc_now_iso(),
    }
    log_path = baseline_path.parent / "BASELINE_APPROVALS.jsonl"
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(approval, ensure_ascii=False) + "\n")
    if args.json:
        print(json.dumps(approval, indent=2, ensure_ascii=False))
    else:
        print(f"baseline updated: {baseline_path} (approved by {approver}); approval logged in {log_path}")
    return 0
