# -*- coding: utf-8 -*-
"""win_icon.py —— 用纯 Python 画托盘图标（不依赖 Pillow / 任何第三方库）

做法：内置一套 3x5 点阵数字，按电量数值渲染成 RGBA 位图，
再手写 ICO 文件格式，最后交给 LoadImageW 变成 HICON。
支持 16/24/32 三种尺寸，Windows 会按 DPI 自动挑合适的那张。
"""

from __future__ import annotations

import ctypes
import os
import struct
import tempfile
from ctypes import wintypes
from typing import Optional

# ---- 3x5 点阵数字（每行 3 位，"1" 点亮）----
DIGITS = {
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00110", "01000", "10000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
    "?": ("01110", "10001", "00001", "00110", "00100", "00000", "00100"),
    "!": ("00100", "00100", "00100", "00100", "00100", "00000", "00100"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
}

# 紧凑 3×5 字体：两位数、三位数时用，能比 5×7 大一倍
DIGITS_TINY = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
    "?": ("110", "001", "011", "000", "010"),
    "%": ("101", "001", "010", "100", "101"),
    "-": ("000", "000", "111", "000", "000"),
}

# 竖长 3×7 字体：两位数时能比 3×5 高一倍（16px 图标里 13×14）
DIGITS_TALL = {
    "0": ("111", "101", "101", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "010", "010", "111"),
    "2": ("111", "001", "001", "011", "100", "100", "111"),
    "3": ("111", "001", "001", "011", "001", "001", "111"),
    "4": ("101", "101", "101", "111", "001", "001", "001"),
    "5": ("111", "100", "100", "111", "001", "001", "111"),
    "6": ("111", "100", "100", "111", "101", "101", "111"),
    "7": ("111", "001", "001", "010", "010", "010", "010"),
    "8": ("111", "101", "101", "111", "101", "101", "111"),
    "9": ("111", "101", "101", "111", "001", "001", "111"),
    "?": ("110", "001", "011", "000", "010", "000", "000"),
    "-": ("000", "000", "000", "111", "000", "000", "000"),
}

FONTS = (
    (DIGITS, 5, 7),        # 宽体：单个数字
    (DIGITS_TALL, 3, 7),   # 竖长：两位数字（最高）
    (DIGITS_TINY, 3, 5),   # 紧凑：三位数字
)

GLYPH_W, GLYPH_H = 5, 7


def render_rgba(text: str, size: int, color: tuple[int, int, int],
                plate: bool = False, plate_color=(28, 30, 34, 235)) -> bytes:
    """把文字渲染成 size×size 的 RGBA 像素（返回 size*size*4 字节，行优先）。"""
    n = len(text)
    # 选一个能放下的最大缩放倍数
    gap = 1
    scale = 1
    while True:
        w = n * GLYPH_W * (scale + 1) + (n - 1) * gap
        h = GLYPH_H * (scale + 1)
        if w > size - 2 or h > size - 2:
            break
        scale += 1

    gw, gh = GLYPH_W * scale, GLYPH_H * scale
    ox = (size - total_w) // 2
    oy = (size - total_h) // 2

    px = bytearray(size * size * 4)

    def put(x: int, y: int, rgba):
        if 0 <= x < size and 0 <= y < size:
            i = (y * size + x) * 4
            px[i:i + 4] = bytes(rgba)

    def get(x: int, y: int):
        i = (y * size + x) * 4
        return (px[i], px[i + 1], px[i + 2], px[i + 3])

    # 底衬（耳机图标用，跟鼠标图标区分开）
    if plate:
        r = max(1, size // 8)
        for y in range(size):
            for x in range(size):
                # 圆角矩形
                cx = min(x, size - 1 - x)
                cy = min(y, size - 1 - y)
                if cx + cy < r and cx < r and cy < r:
                    continue
                put(x, y, plate_color)

    # 逐字画
    for k, ch in enumerate(text):
        glyph = glyphs.get(ch)
        if not glyph:
            continue
        gx = ox + k * (gw + gap)
        for gy, row in enumerate(glyph):
            for gxx, bit in enumerate(row):
                if bit != "1":
                    continue
                for dy in range(scale):
                    for dx in range(scale):
                        put(gx + gxx * scale + dx, oy + gy * scale + dy,
                            (*color, 255))

    # 描一圈深色轮廓，保证在浅色/深色任务栏上都看得清
    outline = (16, 17, 19, 190)
    edge = []
    for y in range(size):
        for x in range(size):
            if get(x, y)[3] == 0:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < size and 0 <= ny < size and get(nx, ny)[3] == 0:
                    edge.append((nx, ny))
    for x, y in edge:
        if get(x, y)[3] == 0:
            put(x, y, outline)
    return bytes(px)


def render_weighted(text: str, size: int, color: tuple[int, int, int],
                    weight: int = 0, plate: bool = False,
                    plate_color=(28, 30, 34, 235), ring: bool = False,
                    small: bool = False) -> bytes:
    """把文字画进 size×size 的 RGBA，`weight` 为描粗圈数（越大越粗）。"""
    n = len(text)
    weight = max(0, int(weight))
    # 16px 图标只有 7 行像素，描粗会把数字内部的缝隙填死糊成方块：
    # 无外环时小尺寸一律不加粗；有外环时数字缩到 5×7，允许加粗 1 圈
    if size < 24:
        weight = min(weight, 1) if ring else 0
    gap = 1
    # 正方形外环线宽：16px 只有 1px 可用，再粗就放不下数字
    t = max(1, size // 16) if ring else 0
    # 方环内留 1px 空隙
    inset = (2 * t + 2) if ring else 0

    def fit(font_w: int, font_h: int) -> tuple[int, int, int]:
        """返回 (scale, 总宽, 总高)，按可用空间取最大倍数。"""
        scale = 1
        while True:
            nxt = scale + 1
            w = n * font_w * nxt + (n - 1) * gap + 2 * weight + 2 + inset
            h = font_h * nxt + 2 * weight + 2 + inset
            if w > size or h > size:
                break
            scale = nxt
        return scale, n * font_w * scale + (n - 1) * gap, font_h * scale

    # 把各字体的可选尺寸排出来，按 (高, 宽) 挑“最大”或“次大”
    options = []
    for font, fw, fh in FONTS:
        sc, tw, th = fit(fw, fh)
        options.append((th, tw, sc, font, fw))
    options.sort(key=lambda o: (o[0], o[1]))
    heights = sorted({o[0] for o in options})
    if small and len(heights) > 1:
        target_h = heights[-2]          # 次大一档 → 小一号的字体
        pick = [o for o in options if o[0] == target_h][-1]
    else:
        pick = options[-1]
    total_h, total_w, scale, glyphs, fw = pick
    gw, gh = fw * scale, total_h
    ox = (size - total_w) // 2
    oy = (size - total_h) // 2

    px = bytearray(size * size * 4)

    def put(x: int, y: int, rgba):
        if 0 <= x < size and 0 <= y < size:
            i = (y * size + x) * 4
            px[i:i + 4] = bytes(rgba)

    def get(x: int, y: int):
        i = (y * size + x) * 4
        return (px[i], px[i + 1], px[i + 2], px[i + 3])

    if plate:
        r = max(1, size // 8)
        for y in range(size):
            for x in range(size):
                cx = min(x, size - 1 - x)
                cy = min(y, size - 1 - y)
                if cx + cy < r and cx < r and cy < r:
                    continue
                put(x, y, plate_color)

    lit: set[tuple[int, int]] = set()
    for k, ch in enumerate(text):
        glyph = glyphs.get(ch)
        if not glyph:
            continue
        gx = ox + k * (gw + gap)
        for gy, row in enumerate(glyph):
            for gxx, bit in enumerate(row):
                if bit != "1":
                    continue
                for dy in range(scale):
                    for dx in range(scale):
                        lit.add((gx + gxx * scale + dx, oy + gy * scale + dy))

    # 四邻域膨胀，实现「数字越低越粗」
    for _ in range(weight):
        grown = set(lit)
        for (x, y) in lit:
            grown.update(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
        lit = grown

    ring_pixels: set[tuple[int, int]] = set()
    if ring and t:
        # 正方形外环（同色），四角是直角、不是圆角
        for i in range(size):
            for k in range(t):
                for (x, y) in ((i, k), (i, size - 1 - k),
                               (k, i), (size - 1 - k, i)):
                    ring_pixels.add((x, y))
        lit |= ring_pixels

    for (x, y) in lit:
        put(x, y, (*color, 255))

    # 描一圈深色轮廓，浅色/深色任务栏都看得清。
    # 有方环时小尺寸只描环（数字只有 1px 笔画，再描黑就看不见红色了）
    outline = (16, 17, 19, 190)
    edge = []
    targets = ring_pixels if (ring and size < 24) else lit
    for y in range(size):
        for x in range(size):
            if (x, y) not in targets:
                continue
            if get(x, y)[3] == 0:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < size and 0 <= ny < size and get(nx, ny)[3] == 0:
                    edge.append((nx, ny))
    for x, y in edge:
        if get(x, y)[3] == 0:
            put(x, y, outline)
    return bytes(px)


def _load_icon(key, images, name: str) -> int:
    if key in _icon_cache:
        return _icon_cache[key]
    ico = build_ico(images)
    path = os.path.join(_ensure_tmp(), name + ".ico")
    try:
        with open(path, "wb") as f:
            f.write(ico)
    except OSError:
        return 0
    h = user32.LoadImageW(None, path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
    hicon = int(h) if h else 0
    _icon_cache[key] = hicon
    return hicon


def make_hicon_digit(text: str, color: tuple[int, int, int],
                     weight: int = 0, ring: bool = False,
                     small: bool = False) -> int:
    """按「文字 + 颜色 + 粗细 + 字号大小」生成托盘 HICON（带缓存）。"""
    key = ("digit", text, color, int(weight), bool(ring), bool(small))
    name = "d_%s_%02x%02x%02x_w%d%s%s" % (text, color[0], color[1], color[2],
                                         int(weight), "_r" if ring else "",
                                         "_s" if small else "")
    images = [(s, render_weighted(text, s, color, weight, ring=ring,
                                  small=small))
              for s in SIZES]
    return _load_icon(key, images, name)


def build_ico(pngs: list[tuple[int, bytes]]) -> bytes:
    """把多张 RGBA 位图打包成 ICO 文件内容。"""
    entries = []
    blobs = []
    offset = 6 + 16 * len(pngs)
    for size, rgba in pngs:
        # BITMAPINFOHEADER
        bih = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0,
                          size * size * 4, 0, 0, 0, 0)
        # XOR 位图：32bpp BGRA，自下而上
        xor = bytearray()
        for y in range(size - 1, -1, -1):
            row = rgba[y * size * 4:(y + 1) * size * 4]
            for x in range(size):
                r, g, b, a = row[x * 4:x * 4 + 4]
                # 预乘不必要，Windows 直接用 alpha
                xor += bytes((b, g, r, a))
        # AND 掩码：1bpp，每行按 4 字节对齐，全 0（靠 alpha 通道）
        row_bytes = ((size + 31) // 32) * 4
        mask = b"\x00" * (row_bytes * size)
        blob = bih + bytes(xor) + mask
        blobs.append(blob)
        entries.append(struct.pack("<BBBBHHII", size if size < 256 else 0,
                                   size if size < 256 else 0, 0, 0, 1, 32,
                                   len(blob), offset))
        offset += len(blob)
    return (struct.pack("<HHH", 0, 1, len(pngs)) + b"".join(entries)
            + b"".join(blobs))


# ---------------- HICON 缓存 ----------------
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010

user32.LoadImageW.restype = ctypes.c_void_p
user32.LoadImageW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, wintypes.UINT,
                              ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.DestroyIcon.restype = wintypes.BOOL
user32.DestroyIcon.argtypes = [ctypes.c_void_p]

SIZES = (16, 20, 24, 32, 40)
_icon_cache: dict[tuple, int] = {}
_tmp_dir: Optional[str] = None


def _ensure_tmp() -> str:
    global _tmp_dir
    if _tmp_dir is None:
        _tmp_dir = os.path.join(tempfile.gettempdir(), "device_battery_icons")
        os.makedirs(_tmp_dir, exist_ok=True)
    return _tmp_dir


def make_hicon(text: str, color: tuple[int, int, int], plate: bool = False) -> int:
    """按文字+颜色生成（带缓存的）HICON；失败返回 0。"""
    key = (text, color, plate)
    if key in _icon_cache:
        return _icon_cache[key]
    images = [(s, render_rgba(text, s, color, plate)) for s in SIZES]
    ico = build_ico(images)
    path = os.path.join(_ensure_tmp(), f"ico_{text}_{color[0]:02x}{color[1]:02x}"
                                       f"{color[2]:02x}_{int(plate)}.ico")
    try:
        with open(path, "wb") as f:
            f.write(ico)
    except OSError:
        return 0
    h = user32.LoadImageW(None, path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
    hicon = int(h) if h else 0
    _icon_cache[key] = hicon
    return hicon


def destroy_all() -> None:
    for h in _icon_cache.values():
        if h:
            try:
                user32.DestroyIcon(ctypes.c_void_p(h))
            except Exception:
                pass
    _icon_cache.clear()


def cleanup_files() -> None:
    """清掉临时目录里的 ico 文件。"""
    global _tmp_dir
    if _tmp_dir and os.path.isdir(_tmp_dir):
        for name in os.listdir(_tmp_dir):
            try:
                os.remove(os.path.join(_tmp_dir, name))
            except OSError:
                pass


if __name__ == "__main__":
    # 生成几个样例，方便肉眼检查
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_icon_preview")
    os.makedirs(out, exist_ok=True)
    for text, color, plate, name in (
        ("82", (93, 220, 138), False, "mouse82"),
        ("70", (93, 220, 138), True, "headset70"),
        ("9", (255, 107, 107), False, "mouse9"),
        ("100", (245, 196, 81), True, "headset100"),
        ("25", (245, 196, 81), False, "mouse25"),
    ):
        imgs = [(s, render_rgba(text, s, color, plate)) for s in SIZES]
        p = os.path.join(out, name + ".ico")
        with open(p, "wb") as f:
            f.write(build_ico(imgs))
        print("生成", p)
