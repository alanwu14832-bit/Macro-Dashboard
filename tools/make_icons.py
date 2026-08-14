#!/usr/bin/env python3
"""產生 PWA 圖示——純標準庫，不用 PIL。

畫面：深藍底、白色上行折線、綠色端點——「把序列收斂成一個判斷」的主視覺。
輸出到 macro/render/static/，由 copy_static 帶進 site/。設計不變就不必重跑；
改了設計重跑一次、把新 PNG commit 進 repo 即可。

    python3 tools/make_icons.py
"""
from __future__ import annotations

import os
import struct
import zlib

NAVY = (18, 34, 58)
WHITE = (247, 248, 250)
GREEN = (27, 175, 122)

STATIC = os.path.join(os.path.dirname(__file__), "..", "macro", "render", "static")

# 折線控制點（0~1 相對座標，y 向下）
POINTS = [(0.10, 0.82), (0.40, 0.50), (0.58, 0.64), (0.90, 0.22)]


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def write_png(path: str, size: int, rows: list[list[tuple[int, int, int]]]) -> None:
    raw = b"".join(b"\x00" + bytes(v for px in row for v in px) for row in rows)
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n"
                 + _chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
                 + _chunk(b"IDAT", zlib.compress(raw, 9))
                 + _chunk(b"IEND", b""))


def _seg_dist(px, py, ax, ay, bx, by) -> float:
    vx, vy = bx - ax, by - ay
    length2 = vx * vx + vy * vy
    t = 0.0 if not length2 else max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / length2))
    dx, dy = px - (ax + t * vx), py - (ay + t * vy)
    return (dx * dx + dy * dy) ** 0.5


def _mix(base, top, alpha):
    return tuple(round(b + (t - b) * alpha) for b, t in zip(base, top))


def render(size: int, pad: float) -> list[list[tuple[int, int, int]]]:
    span = size * (1 - 2 * pad)
    origin = size * pad
    pts = [(origin + x * span, origin + y * span) for x, y in POINTS]
    line_w = size * 0.070
    dot_r = size * 0.085
    cx, cy = pts[-1]

    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            px, py = x + 0.5, y + 0.5
            color = NAVY
            d = min(_seg_dist(px, py, *pts[i], *pts[i + 1])
                    for i in range(len(pts) - 1))
            a = max(0.0, min(1.0, line_w / 2 + 0.7 - d))
            if a:
                color = _mix(color, WHITE, a)
            dd = ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5
            a = max(0.0, min(1.0, dot_r + 0.7 - dd))
            if a:
                color = _mix(color, GREEN, a)
            row.append(color)
        rows.append(row)
    return rows


def main() -> None:
    jobs = [
        ("icon-192.png", 192, 0.14),
        ("icon-512.png", 512, 0.14),
        # maskable：系統會裁圓，內容要縮進安全區
        ("icon-maskable-512.png", 512, 0.24),
        ("apple-touch-icon.png", 180, 0.16),
    ]
    for name, size, pad in jobs:
        path = os.path.join(STATIC, name)
        write_png(path, size, render(size, pad))
        print(f"  ✓ {name}（{size}×{size}，{os.path.getsize(path)} bytes）")


if __name__ == "__main__":
    main()
