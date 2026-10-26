# -*- coding: utf-8 -*-
"""生成 README 用的预览图（纯标准库：手写 PNG）。"""
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import battery_tray as bt  # noqa: E402
import win_icon  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "preview")

BG = (24, 28, 36, 255)          # 深色底，和托盘深色主题接近
SAMPLES = (95, 85, 75, 65, 55, 45, 35, 25, 15, 5)


def write_png(path, rgba, w, h):
    raw = b"".join(b"\x00" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n"
                 + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                 + chunk(b"IDAT", zlib.compress(raw, 9))
                 + chunk(b"IEND", b""))


def tile(size: int, text: str, color, small: bool = False) -> bytes:
    """一块底色 + 数字，用来拼色板预览。"""
    body = win_icon.render_weighted(text, size, color, small=small)
    px = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            i = (y * size + x) * 4
            a = body[i + 3]
            if a:
                px[i:i + 4] = body[i:i + 4]
            else:
                px[i:i + 4] = bytes(BG)
    return bytes(px)


def compose(parts, gap: int = 4) -> tuple[bytes, int, int]:
    widths = [p[0] for p in parts]
    height = max(p[1] for p in parts)
    w = sum(widths) + gap * (len(parts) - 1)
    canvas = bytearray(bytes(BG) * (w * height))
    x0 = 0
    for (tw, th, data) in parts:
        for y in range(th):
            for x in range(tw):
                src = (y * tw + x) * 4
                dst = ((y * w) + x0 + x) * 4
                canvas[dst:dst + 4] = data[src:src + 4]
        x0 += tw + gap
    return bytes(canvas), w, height


def main():
    os.makedirs(OUT, exist_ok=True)

    # 1) 键鼠图标（16px 与 32px）
    for size in (16, 32):
        for tag, text, small in (("keyboard", "53", False), ("mouse", "27", True)):
            data = tile(size, text, bt.level_color(int(text)), small)
            write_png(os.path.join(OUT, "icon_%s_%d.png" % (tag, size)),
                      data, size, size)

    # 2) 10 档色板
    parts = []
    for lv in SAMPLES:
        data = tile(32, str(lv), bt.level_color(lv))
        parts.append((32, 32, data))
    canvas, w, h = compose(parts)
    write_png(os.path.join(OUT, "bands.png"), canvas, w, h)
    print("预览图已生成 ->", OUT)


if __name__ == "__main__":
    main()
