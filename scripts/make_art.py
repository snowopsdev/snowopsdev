#!/usr/bin/env python3
"""Convert assets/avatar.jpg into ASCII-art variants: card/art/<variant>_<mode>.txt

  classic, sketch: ink -> glyphs in both modes (like the reference README)
  shaded:          ink -> blocks in light mode; in dark mode a positive image
                   (bright skin -> dense blocks, paper background masked out)

Needs ImageMagick (`magick`) on PATH; everything else is stdlib.
Run once, or whenever the avatar changes: python3 scripts/make_art.py
"""
import math
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # repo root
SRC = ROOT / "assets" / "avatar.jpg"
OUT = ROOT / "card" / "art"

COLS, ROWS = 52, 31          # art size in characters
SS = 4                       # supersampling per cell for edge detection
CROP = "280x370+90+28"       # head-and-shoulders crop of the 460x460 avatar
CLAHE = ["-clahe", "18x18%+128+2.2"]

# Subject mask: flood-fill the white paper from the top corners.
MASK_OPS = ["-blur", "0x3", "-threshold", "88%", "-morphology", "Open", "Disk:3",
            "-morphology", "Close", "Disk:6", "-fill", "gray50", "-fuzz", "0",
            "-draw", "color 2,2 floodfill", "-draw", "color 457,2 floodfill",
            "-fill", "white", "+opaque", "gray50", "-fill", "black", "-opaque", "gray50",
            "-morphology", "Close", "Disk:10", "-morphology", "Erode", "Disk:2"]


def grid(w, h, ops):
    """Run the avatar through ImageMagick and return a 2D list of 0..1 floats."""
    cmd = ["magick", str(SRC), "-colorspace", "gray", *ops,
           "-crop", CROP, "+repage", "-resize", f"{w}x{h}!", "-depth", "8", "gray:-"]
    raw = subprocess.run(cmd, check=True, capture_output=True).stdout
    return [[raw[y * w + x] / 255 for x in range(w)] for y in range(h)]


def stretch(v, lo, hi):
    return min(max((v - lo) / (hi - lo), 0.0), 1.0)


def density(mode, w=COLS, h=ROWS):
    """0..1 'how much glyph' per cell for the given mode."""
    if mode == "light":
        lum = grid(w, h, CLAHE)
        return [[(1 - stretch(v, 0.10, 0.88)) ** 1.1 for v in row] for row in lum]
    # positive: plain luminance (no CLAHE), background masked out, hair kept as a faint floor
    lum = grid(w, h, ["-blur", "0x0.6"])
    mask = grid(w, h, MASK_OPS)
    return [[m * (0.12 + 0.88 * stretch(v, 0.25, 0.96) ** 1.3)
             for v, m in zip(lr, mr)] for lr, mr in zip(lum, mask)]


def dither(d, ramp, strength=0.55):
    """Floyd-Steinberg (partial) over a density grid -> lines of glyphs."""
    h, w, n = len(d), len(d[0]), len(ramp)
    d = [row[:] for row in d]
    lines = []
    for y in range(h):
        row = []
        for x in range(w):
            old = min(max(d[y][x], 0.0), 1.0)
            i = round(old * (n - 1))
            err = (old - i / (n - 1)) * strength
            for dx, dy, f in ((1, 0, 7), (-1, 1, 3), (0, 1, 5), (1, 1, 1)):
                if 0 <= x + dx < w and y + dy < h:
                    d[y + dy][x + dx] += err * f / 16
            row.append(ramp[i])
        lines.append("".join(row).rstrip())
    return lines


# --- Variant 1: classic tone ramp (like the reference README) ------------------
CLASSIC = " .',:;!|il}?1tjxkJ%&H#@M"


def classic(mode):
    # ink-as-glyphs in both modes, like the reference (dark hair -> bright glyphs on dark)
    return dither(density("light"), CLASSIC)


# --- Variant 2: sketch strokes (edge direction -> / \ | - _) -------------------
FILL = " .:+%#"


def sketch(mode):
    W, H = COLS * SS, ROWS * SS
    g = grid(W, H, CLAHE + ["-blur", "0x1.2"])
    dens = density("light")  # strokes + ink fill in both modes
    lines = []
    for cy in range(ROWS):
        row = []
        for cx in range(COLS):
            vx = vy = 0.0
            for y in range(max(1, cy * SS), min(H - 1, cy * SS + SS)):
                for x in range(max(1, cx * SS), min(W - 1, cx * SS + SS)):
                    sx = (g[y-1][x+1] + 2*g[y][x+1] + g[y+1][x+1]
                          - g[y-1][x-1] - 2*g[y][x-1] - g[y+1][x-1])
                    sy = (g[y+1][x-1] + 2*g[y+1][x] + g[y+1][x+1]
                          - g[y-1][x-1] - 2*g[y-1][x] - g[y-1][x+1])
                    m = math.hypot(sx, sy)
                    if m:  # doubled-angle sum so opposite gradients reinforce
                        a = 2 * math.atan2(sy, sx)
                        vx += m * math.cos(a)
                        vy += m * math.sin(a)
            mag = math.hypot(vx, vy) / (SS * SS)
            dk = dens[cy][cx]
            if mag > 0.60:
                ang = (math.degrees(math.atan2(vy, vx) / 2) + 90) % 180
                ch = ("-" if ang < 22.5 or ang >= 157.5 else
                      "\\" if ang < 67.5 else "|" if ang < 112.5 else "/")
            else:
                ch = FILL[min(int(dk * len(FILL) * 0.999), len(FILL) - 1)]
            row.append(ch)
        lines.append("".join(row).rstrip())
    return lines


# --- Variant 3: shaded blocks ---------------------------------------------------
BLOCKS = " ·░▒▓█"


def shaded(mode):
    return dither(density(mode), BLOCKS, strength=0.45)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for name, fn in (("classic", classic), ("sketch", sketch), ("shaded", shaded)):
        for mode in ("dark", "light"):
            lines = fn(mode)
            (OUT / f"{name}_{mode}.txt").write_text("\n".join(lines) + "\n")
            print(f"== {name} {mode}")
            print("\n".join(lines))
