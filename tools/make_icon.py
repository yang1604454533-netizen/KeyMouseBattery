# -*- coding: utf-8 -*-
"""生成程序图标 app.ico（电池造型，纯像素绘制，不依赖 Pillow）。"""
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import win_icon  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256)
PLATE = (26, 32, 44, 255)
GREEN = (72, 205, 108, 255)
DIM = (58, 70, 88, 255)
LIGHT = (232, 240, 250, 255)


def render_battery(size: int, level: float = 0.72) -> bytes:
    px = bytearray(size * size * 4)
    s = size

    def put(x, y, c):
        if 0 <= x < s and 0 <= y < s:
            i = (y * s + x) * 4
            px[i:i + 4] = bytes(c)

    # 圆角底板
    r = max(2, s // 6)
    for y in range(s):
        for x in range(s):
            cx = min(x, s - 1 - x)
            cy = min(y, s - 1 - y)
            if cx + cy < r and cx < r and cy < r:
                continue
            put(x, y, PLATE)

    # 电池外形
    bx0, bx1 = int(s * 0.14), int(s * 0.76)
    by0, by1 = int(s * 0.28), int(s * 0.72)
    nub0, nub1 = bx1, int(s * 0.86)
    ny0, ny1 = int(s * 0.42), int(s * 0.58)
    t = max(1, s // 24)
    for y in range(by0, by1):
        for x in range(bx0, bx1):
            edge = (x < bx0 + t or x >= bx1 - t or y < by0 + t or y >= by1 - t)
            put(x, y, LIGHT if edge else DIM)
    for y in range(ny0, ny1):
        for x in range(nub0, nub1):
            put(x, y, LIGHT)

    # 电量条
    fx0, fx1 = bx0 + 2 * t, bx1 - 2 * t
    fy0, fy1 = by0 + 2 * t, by1 - 2 * t
    cutoff = int(fx0 + (fx1 - fx0) * max(0.0, min(1.0, level)))
    for y in range(fy0, fy1):
        for x in range(fx0, cutoff):
            put(x, y, GREEN)
    return bytes(px)


def write_png(path, rgba, size):
    raw = b"".join(b"\x00" + rgba[y * size * 4:(y + 1) * size * 4]
                   for y in range(size))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n"
                 + chunk(b"IHDR",
                         struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
                 + chunk(b"IDAT", zlib.compress(raw, 9))
                 + chunk(b"IEND", b""))


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    images = [(s, render_battery(s)) for s in SIZES]
    ico = win_icon.build_ico(images)
    out = os.path.join(root, "app.ico")
    with open(out, "wb") as fh:
        fh.write(ico)
    os.makedirs(os.path.join(root, "preview"), exist_ok=True)
    write_png(os.path.join(root, "preview", "app_icon_256.png"),
              render_battery(256), 256)
    print("已生成", out, len(ico), "字节")


if __name__ == "__main__":
    main()
