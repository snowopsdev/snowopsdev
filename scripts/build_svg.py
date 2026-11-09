#!/usr/bin/env python3
"""Render neofetch-style profile cards (card/svg/*.svg) from card/art/*.txt + live GitHub stats.

Stdlib only. Needs a token in GITHUB_TOKEN (or ACCESS_TOKEN) for the API calls.
Usage: python3 scripts/build_svg.py            # all variants, dark + light
       python3 scripts/build_svg.py --offline  # reuse card/stats.json, no API calls
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.request
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # repo root
USER = "snowopsdev"
JOINED = dt.date(2014, 1, 29)  # GitHub account created

# ---- Edit these freely: the left side is the key, the right side the value ----
HEADER = "aj@snowops"
SECTIONS = [
    [
        ("OS", "macOS, Omarchy Linux, iOS, Android"),
        ("Uptime", "{uptime}"),
        ("Host", "SnowOpsHQ (snowops.dev)"),
        ("Kernel", "10 yrs in search, now building tools"),
        ("IDE", "T3 Code, Orca, Cursor"),
    ],
    [
        ("Languages.Programming", "TypeScript, Rust, Python, C"),
        ("Languages.Computer", "HTML, CSS, SQL, Markdown"),
        ("Languages.Real", "English"),
    ],
    [
        # long comma-separated values wrap onto extra lines automatically
        ("Hobbies.Software", "Local LLMs, AI Coding/Building, Data Analysis"),
        ("Hobbies.Hardware", "GPU Benchmarking, Homelab, Retro Tech Revival, "
                             "Workstation Setup Iterations"),
    ],
    "- Contact",
    [
        ("Email", "aj@snowops.dev"),
        ("X", "@snowopsdev"),
        ("LinkedIn", "ajnieves"),
        ("Web", "snowops.dev"),
    ],
    "- GitHub Stats",
    "STATS",
]

# ---- Layout ----
CELL_W = 9.0         # px per character (enforced with textLength)
LINE_H = 20          # px per line
FONT = 15            # px
ART_X = 22
ART_FONT, ART_CELL_W, ART_LINE_H = 12, 7.2, 16   # art uses a finer grid than the panel
PANEL_X = 420
PANEL_COLS = 62
TOP = 32

THEMES = {
    # GitHub palette, like the reference README
    "classic": {
        "dark": dict(bg="#161b22", border="#30363d", text="#c9d1d9", art="#c9d1d9",
                     key="#ffa657", value="#a5d6ff", dots="#616e7f", add="#3fb950", rm="#f85149"),
        "light": dict(bg="#f6f8fa", border="#d0d7de", text="#24292f", art="#24292f",
                      key="#953800", value="#0a3069", dots="#c2cfde", add="#1a7f37", rm="#cf222e"),
    },
    # graphite on paper, to match the pencil-sketch avatar
    "sketch": {
        "dark": dict(bg="#1c1b19", border="#3a3834", text="#d8d2c4", art="#e9e3d5",
                     key="#e0b872", value="#b9c7a3", dots="#5b5850", add="#9fbf6f", rm="#d97862"),
        "light": dict(bg="#f4f0e6", border="#d9d2c0", text="#2b2a27", art="#34322d",
                      key="#8a5a12", value="#3d5a2a", dots="#c9c1ac", add="#4f7a1f", rm="#a8402c"),
    },
    # cold "snow" palette
    "shaded": {
        "dark": dict(bg="#0d1520", border="#1f2d3d", text="#d8e3ee", art="#9ccfe8",
                     key="#7fd4ff", value="#e8f1f8", dots="#3b4e63", add="#7ee0b5", rm="#ff8fa3"),
        "light": dict(bg="#f2f7fb", border="#cfdde9", text="#1b2a3a", art="#2b5d80",
                      key="#0b6aa2", value="#1b2a3a", dots="#b6c8d8", add="#13805a", rm="#c23a58"),
    },
}


# ------------------------------------------------------------------------------
# GitHub API
# ------------------------------------------------------------------------------
def token():
    t = os.environ.get("GITHUB_TOKEN") or os.environ.get("ACCESS_TOKEN")
    if not t:
        sys.exit("Set GITHUB_TOKEN (or ACCESS_TOKEN) to call the GitHub API.")
    return t


def api(path, data=None):
    req = urllib.request.Request(
        "https://api.github.com" + path,
        data=json.dumps(data).encode() if data else None,
        headers={"Authorization": f"Bearer {token()}",
                 "Accept": "application/vnd.github+json",
                 "User-Agent": f"{USER}-readme"})
    with urllib.request.urlopen(req) as r:
        body = r.read()
        return r.status, (json.loads(body) if body else None)


def fetch_stats():
    q = """query($login:String!){user(login:$login){
      followers{totalCount}
      repositoriesContributedTo(contributionTypes:[COMMIT,PULL_REQUEST,REPOSITORY]){totalCount}
      repositories(ownerAffiliations:OWNER, privacy:PUBLIC, first:100){
        totalCount nodes{name isFork stargazerCount}}}}"""
    _, res = api("/graphql", {"query": q, "variables": {"login": USER}})
    u = res["data"]["user"]
    repos = u["repositories"]["nodes"]
    stats = dict(repos=u["repositories"]["totalCount"],
                 contributed=u["repositoriesContributedTo"]["totalCount"],
                 stars=sum(r["stargazerCount"] for r in repos),
                 followers=u["followers"]["totalCount"],
                 commits=0, add=0, rm=0)
    # Commits: all-time commit contributions (what the contribution graph counts).
    years = range(JOINED.year, dt.date.today().year + 1)
    q = "{user(login:\"%s\"){%s}}" % (USER, " ".join(
        f'y{y}:contributionsCollection(from:"{y}-01-01T00:00:00Z",to:"{y}-12-31T23:59:59Z")'
        "{totalCommitContributions}" for y in years))
    _, res = api("/graphql", {"query": q})
    stats["commits"] = sum(v["totalCommitContributions"] for v in res["data"]["user"].values())
    # Lines of code across own (non-fork) public repos.
    for r in repos:
        if r["isFork"]:
            continue
        for _ in range(12):  # GitHub returns 202 while it computes the stats
            status, data = api(f"/repos/{USER}/{r['name']}/stats/contributors")
            if status == 200:
                break
            time.sleep(3)
        else:
            print(f"  ! stats not ready for {r['name']}, skipped", file=sys.stderr)
            continue
        for c in data or []:
            if (c.get("author") or {}).get("login", "").lower() == USER.lower():
                stats["add"] += sum(w["a"] for w in c["weeks"])
                stats["rm"] += sum(w["d"] for w in c["weeks"])
    return stats


def uptime(today=None):
    today = today or dt.date.today()
    y, m, d = today.year - JOINED.year, today.month - JOINED.month, today.day - JOINED.day
    if d < 0:
        m -= 1
        prev = (today.replace(day=1) - dt.timedelta(days=1))
        d += prev.day
    if m < 0:
        y, m = y - 1, m + 12
    s = lambda n, w: f"{n} {w}{'' if n == 1 else 's'}"
    out = f"{s(y, 'year')}, {s(m, 'month')}, {s(d, 'day')}"
    return out + (" 🎂" if (m, d) == (0, 0) else "")


# ------------------------------------------------------------------------------
# SVG rendering
# ------------------------------------------------------------------------------
def seg(text, cls=None):
    return (text, cls)


def kv(key, value, width=PANEL_COLS):
    """'. Key: ....... value' lines padded with dot leaders to a fixed width.

    A value too long for one line wraps at ', ' onto continuation lines
    ('. ............ rest'), each right-aligned like the first.
    """
    left = f". {key}:"
    room = width - len(left) - 3          # at least ' . ' between key and value
    chunks, cur = [], ""
    for part in value.split(", "):
        cand = f"{cur}, {part}" if cur else part
        if cur and len(cand) + 1 > room:  # +1 for the trailing comma
            chunks.append(cur + ",")
            cur, room = part, width - 5   # continuation: '. ' + ' . ' minimum
        else:
            cur = cand
    chunks.append(cur)

    lines = []
    for i, chunk in enumerate(chunks):
        if len(chunk) > (room if i == len(chunks) - 1 else width):
            chunk = chunk[: room - 1] + "…"
        if i == 0:
            gap = width - len(left) - len(chunk) - 2
            lines.append([seg(". ", "dots"), seg(key, "key"), seg(":", None),
                          seg(" " + "." * gap + " ", "dots"), seg(chunk, "value")])
        else:
            gap = width - 2 - len(chunk) - 1
            lines.append([seg(". ", "dots"), seg("." * gap + " ", "dots"),
                          seg(chunk, "value")])
    return lines


def rule(title, width=PANEL_COLS):
    return [seg(title, None), seg(" " + "—" * (width - len(title) - 1), "dots")]


def stats_lines(s, width=PANEL_COLS):
    f = lambda n: f"{n:,}"
    half = 34

    def pair(k1, v1_segs, k2, v2):
        v1_len = sum(len(t) for t, _ in v1_segs)
        left = f". {k1}:"
        gap1 = half - len(left) - v1_len - 2
        right = f"{k2}:"
        gap2 = width - half - 3 - len(right) - len(v2) - 2
        return ([seg(". ", "dots"), seg(k1, "key"), seg(":"), seg(" " + "." * gap1 + " ", "dots")]
                + v1_segs
                + [seg(" | "), seg(k2, "key"), seg(":"), seg(" " + "." * gap2 + " ", "dots"),
                   seg(v2, "value")])

    loc = s["add"] - s["rm"]
    loc_tail = [seg(f(loc), "value"), seg(" ( "), seg(f(s["add"]) + "++", "add"),
                seg(", "), seg(f(s["rm"]) + "--", "rm"), seg(" )")]
    tail_len = sum(len(t) for t, _ in loc_tail)
    label = "Lines of Code"  # "Lines of Code on GitHub" doesn't fit 62 columns
    left = f". {label}:"
    return [
        pair("Repos", [seg(f(s["repos"]), "value"), seg(" {"), seg("Contributed", "key"),
                       seg(": "), seg(f(s["contributed"]), "value"), seg("}")],
             "Stars", f(s["stars"])),
        pair("Commits", [seg(f(s["commits"]), "value")], "Followers", f(s["followers"])),
        [seg(". ", "dots"), seg(label, "key"), seg(":"),
         seg(" " + "." * (width - len(left) - tail_len - 2) + " ", "dots")] + loc_tail,
    ]


def panel_lines(stats):
    lines = [[seg(HEADER, "header"), seg(" " + "—" * (PANEL_COLS - len(HEADER) - 1), "dots")]]
    after_rule = False
    for block in SECTIONS:
        if block == "STATS":
            lines += stats_lines(stats)
        elif isinstance(block, str):
            lines.append([])
            lines.append(rule(block))
            after_rule = True
        else:
            if len(lines) > 1 and not after_rule:
                lines.append([])          # blank between blocks, not right after a rule
            after_rule = False
            for k, v in block:
                lines += kv(k, v.format(uptime=uptime()))
    return lines


def render(variant, mode, stats):
    c = THEMES[variant][mode]
    art = (ROOT / "card" / "art" / f"{variant}_{mode}.txt").read_text().rstrip("\n").split("\n")
    art_cols = max(len(l) for l in art)
    panel = panel_lines(stats)
    body_h = max(len(art) * ART_LINE_H, len(panel) * LINE_H)
    width = PANEL_X + PANEL_COLS * CELL_W + 22
    height = body_h + 2 * (TOP - LINE_H) + 22

    out = [f'<?xml version="1.0" encoding="UTF-8"?>',
           f'<svg xmlns="http://www.w3.org/2000/svg" font-family="ConsolasFallback,Consolas,Menlo,'
           f'\'DejaVu Sans Mono\',monospace" width="{width:.0f}px" height="{height}px" '
           f'font-size="{FONT}px">',
           f'<title>{escape(HEADER)}</title>',
           "<style>",
           "@font-face{src:local('Consolas'),local('Consolas Bold');font-family:'ConsolasFallback';"
           "font-display:swap;size-adjust:109%}",
           f".key{{fill:{c['key']}}}.value{{fill:{c['value']}}}.dots{{fill:{c['dots']}}}"
           f".add{{fill:{c['add']}}}.rm{{fill:{c['rm']}}}.header{{fill:{c['text']};font-weight:bold}}"
           f"text,tspan{{white-space:pre}}",
           "</style>",
           f'<rect width="{width:.0f}px" height="{height}px" fill="{c["bg"]}" rx="15" '
           f'stroke="{c["border"]}" stroke-width="1"/>',
           f'<g fill="{c["art"]}" font-size="{ART_FONT}px" xml:space="preserve">']
    art_top = TOP - LINE_H + ART_LINE_H + (body_h - len(art) * ART_LINE_H) // 2
    for i, line in enumerate(art):
        y = art_top + i * ART_LINE_H
        out.append(f'<text x="{ART_X}" y="{y}" textLength="{art_cols * ART_CELL_W:.1f}" '
                   f'lengthAdjust="spacingAndGlyphs">{escape(line.ljust(art_cols))}</text>')
    out.append(f'</g><g fill="{c["text"]}" xml:space="preserve">')
    for i, segs in enumerate(panel):
        if not segs:
            continue
        n = sum(len(t) for t, _ in segs)
        y = TOP + (body_h - len(panel) * LINE_H) // 2 + i * LINE_H
        body = "".join(f'<tspan class="{cls}">{escape(t)}</tspan>' if cls else escape(t)
                       for t, cls in segs)
        out.append(f'<text x="{PANEL_X}" y="{y}" textLength="{n * CELL_W:.0f}" '
                   f'lengthAdjust="spacingAndGlyphs">{body}</text>')
    out.append("</g></svg>")
    return "\n".join(out) + "\n"


def main():
    cache = ROOT / "card" / "stats.json"
    if "--offline" in sys.argv:
        stats = json.loads(cache.read_text())
    else:
        stats = fetch_stats()
        cache.parent.mkdir(exist_ok=True)
        cache.write_text(json.dumps(stats, indent=2) + "\n")
    print(stats)
    (ROOT / "card" / "svg").mkdir(exist_ok=True)
    for variant in THEMES:
        for mode in ("dark", "light"):
            p = ROOT / "card" / "svg" / f"{variant}_{mode}.svg"
            p.write_text(render(variant, mode, stats))
            print("wrote", p.relative_to(ROOT))


if __name__ == "__main__":
    main()
