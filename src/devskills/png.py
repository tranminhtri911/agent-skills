"""Minimal PNG reader/writer (stdlib only) for screenshot comparison.

Supports what browsers emit: 8-bit, non-interlaced grayscale, RGB, RGBA,
gray+alpha and palette images. Pillow is used instead when it is installed
because it is much faster; both paths return the same RGBA buffer.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

from devskills.fsutil import atomic_write_bytes

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# 40 megapixels ≈ 160 MB of RGBA: larger images are refused instead of exhausting memory.
MAX_PIXELS = 40_000_000
_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


class PngError(ValueError):
    """The file is not a PNG this module can decode."""


@dataclass
class RgbaImage:
    width: int
    height: int
    pixels: bytearray  # row-major RGBA, 4 bytes per pixel

    @property
    def stride(self) -> int:
        return self.width * 4


def read_png(path: Path, prefer_pillow: bool = True) -> RgbaImage:
    """Decode a PNG into RGBA, with Pillow when available and the pure decoder otherwise."""
    if prefer_pillow:
        try:
            from PIL import Image
        except ImportError:
            pass  # Pillow is optional; the pure-Python decoder below handles its absence.
        else:
            with Image.open(path) as image:
                if image.width * image.height > MAX_PIXELS:
                    raise PngError(f"{path}: image larger than {MAX_PIXELS} pixels")
                rgba = image.convert("RGBA")
                return RgbaImage(rgba.width, rgba.height, bytearray(rgba.tobytes()))
    return _read_pure(path)


def _read_pure(path: Path) -> RgbaImage:
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise PngError(f"{path}: not a PNG file")
    position = len(PNG_SIGNATURE)
    header = None
    palette = b""
    transparency = b""
    compressed_parts: list[bytes] = []
    while position + 8 <= len(data):
        length = int.from_bytes(data[position:position + 4], "big")
        chunk_type = data[position + 4:position + 8]
        chunk = data[position + 8:position + 8 + length]
        position += 12 + length
        if chunk_type == b"IHDR":
            header = struct.unpack(">IIBBBBB", chunk)
        elif chunk_type == b"PLTE":
            palette = chunk
        elif chunk_type == b"tRNS":
            transparency = chunk
        elif chunk_type == b"IDAT":
            compressed_parts.append(chunk)
        elif chunk_type == b"IEND":
            break
    if header is None:
        raise PngError(f"{path}: missing IHDR")
    width, height, bit_depth, color_type, _compression, _filter, interlace = header
    if bit_depth != 8 or interlace != 0 or color_type not in _CHANNELS:
        raise PngError(f"{path}: unsupported PNG (bit depth {bit_depth}, color type {color_type}, interlace {interlace}); install Pillow")
    if width * height > MAX_PIXELS:
        raise PngError(f"{path}: image larger than {MAX_PIXELS} pixels")
    channels = _CHANNELS[color_type]
    raw = zlib.decompress(b"".join(compressed_parts))
    rows = _unfilter(raw, width * channels, height, channels)
    return RgbaImage(width, height, _to_rgba(rows, width, height, color_type, palette, transparency))


def _unfilter(raw: bytes, stride: int, height: int, bytes_per_pixel: int) -> bytearray:
    """Reverse PNG scanline filters (None, Sub, Up, Average, Paeth)."""
    output = bytearray(stride * height)
    previous = bytearray(stride)
    position = 0
    for row_index in range(height):
        filter_type = raw[position]
        position += 1
        line = bytearray(raw[position:position + stride])
        position += stride
        if filter_type == 1:
            for index in range(bytes_per_pixel, stride):
                line[index] = (line[index] + line[index - bytes_per_pixel]) & 0xFF
        elif filter_type == 2:
            for index in range(stride):
                line[index] = (line[index] + previous[index]) & 0xFF
        elif filter_type == 3:
            for index in range(stride):
                left = line[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
                line[index] = (line[index] + ((left + previous[index]) >> 1)) & 0xFF
        elif filter_type == 4:
            for index in range(stride):
                left = line[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
                above = previous[index]
                upper_left = previous[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
                estimate = left + above - upper_left
                distance_left = abs(estimate - left)
                distance_above = abs(estimate - above)
                distance_upper_left = abs(estimate - upper_left)
                if distance_left <= distance_above and distance_left <= distance_upper_left:
                    predictor = left
                elif distance_above <= distance_upper_left:
                    predictor = above
                else:
                    predictor = upper_left
                line[index] = (line[index] + predictor) & 0xFF
        elif filter_type != 0:
            raise PngError(f"invalid filter type {filter_type} on row {row_index}")
        output[row_index * stride:(row_index + 1) * stride] = line
        previous = line
    return output


def _to_rgba(rows: bytearray, width: int, height: int, color_type: int, palette: bytes, transparency: bytes) -> bytearray:
    if color_type == 6:
        return rows
    pixel_count = width * height
    rgba = bytearray(pixel_count * 4)
    if color_type == 2:
        rgba[0::4] = rows[0::3]
        rgba[1::4] = rows[1::3]
        rgba[2::4] = rows[2::3]
        rgba[3::4] = b"\xff" * pixel_count
    elif color_type == 0:
        rgba[0::4] = rows
        rgba[1::4] = rows
        rgba[2::4] = rows
        rgba[3::4] = b"\xff" * pixel_count
    elif color_type == 4:
        gray = rows[0::2]
        rgba[0::4] = gray
        rgba[1::4] = gray
        rgba[2::4] = gray
        rgba[3::4] = rows[1::2]
    else:
        alpha_table = bytes(transparency) + b"\xff" * (256 - len(transparency))
        for index, palette_index in enumerate(rows):
            base = palette_index * 3
            rgba[index * 4:index * 4 + 3] = palette[base:base + 3]
            rgba[index * 4 + 3] = alpha_table[palette_index]
    return rgba


def encode_png(image: RgbaImage) -> bytes:
    """Encode RGBA pixels as a PNG (filter 0 rows, zlib level 6)."""
    stride = image.stride
    raw = bytearray()
    for row in range(image.height):
        raw.append(0)
        raw.extend(image.pixels[row * stride:(row + 1) * stride])

    def chunk(chunk_type: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + chunk_type + payload
                + struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", image.width, image.height, 8, 6, 0, 0, 0)
    return PNG_SIGNATURE + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b"")


def write_png(path: Path, image: RgbaImage) -> None:
    atomic_write_bytes(path, encode_png(image))
