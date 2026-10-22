#!/usr/bin/env python3
"""Refresh the exhibition labels in README.md from live GitHub data.

Fills two kinds of markers, leaving everything else untouched:

  <!--revised:REPO-->...<!--/revised-->  last commit date on the default branch,
                                         plus the latest release tag if there is one
  <!--new:REPO-->...<!--/new-->          "NEW ACQUISITION" on the most recently
                                         created repo among those exhibited

Usage: refresh_labels.py README.md   (reads GH_TOKEN or GITHUB_TOKEN if set)
Set LABEL_STYLE=relative for "3 days ago" instead of "Oct 20". Note that relative
labels change daily, so the workflow will commit daily.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

OWNER = "snowopsdev"
API = "https://api.github.com"
REVISED = re.compile(r"(<!--revised:([\w.-]+)-->)(.*?)(<!--/revised-->)", re.S)
NEW = re.compile(r"(<!--new:([\w.-]+)-->)(.*?)(<!--/new-->)", re.S)
NEW_TEXT = " &nbsp;·&nbsp; NEW ACQUISITION"


def get(path):
    req = urllib.request.Request(API + path, headers={"Accept": "application/vnd.github+json"})
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def when(dt, now):
    if os.environ.get("LABEL_STYLE") == "relative":
        days = (now.date() - dt.date()).days
        if days <= 0:
            return "today"
        if days == 1:
            return "yesterday"
        if days < 14:
            return f"{days} days ago"
        if days < 60:
            return f"{days // 7} weeks ago"
        return f"{days // 30} months ago"
    return dt.strftime("%b %-d") if dt.year == now.year else dt.strftime("%b %-d, %Y")


def main(path):
    text = open(path, encoding="utf-8").read()
    now = datetime.now(timezone.utc)
    repos = sorted({m.group(2) for m in REVISED.finditer(text)} | {m.group(2) for m in NEW.finditer(text)})

    info = {}
    for name in repos:
        repo = get(f"/repos/{OWNER}/{name}")
        if repo is None:
            print(f"skip {name}: not found", file=sys.stderr)
            continue
        commits = get(f"/repos/{OWNER}/{name}/commits?per_page=1") or []
        release = get(f"/repos/{OWNER}/{name}/releases/latest")
        last = parse(commits[0]["commit"]["committer"]["date"]) if commits else parse(repo["pushed_at"])
        label = "Last revised " + when(last, now)
        if release and release.get("tag_name"):
            label += " &nbsp;·&nbsp; " + release["tag_name"]
        info[name] = {"label": label, "created": parse(repo["created_at"])}

    newest = max(info, key=lambda n: info[n]["created"]) if info else None

    def fill_revised(m):
        name = m.group(2)
        body = info[name]["label"] if name in info else m.group(3)
        return m.group(1) + body + m.group(4)

    def fill_new(m):
        return m.group(1) + (NEW_TEXT if m.group(2) == newest else "") + m.group(4)

    updated = NEW.sub(fill_new, REVISED.sub(fill_revised, text))
    if updated != text:
        open(path, "w", encoding="utf-8").write(updated)
        print("labels updated")
    else:
        print("labels already current")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "README.md")
