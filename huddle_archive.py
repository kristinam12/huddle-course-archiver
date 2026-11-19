#!/usr/bin/env python3
"""Archive a Huddle e-learning course: lesson text, attachments (PDFs etc.) and Vimeo videos.

Usage:
  export HUDDLE_COOKIE (see instructions), then:
  python3 huddle_archive.py --dry-run --module introductie-copy   # list only, one module
  python3 huddle_archive.py --module introductie-copy             # real run, one module
  python3 huddle_archive.py                                       # everything

Safe to rerun: existing files are skipped, so an interrupted run just continues.
"""
import argparse
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# --- Course settings ---------------------------------------------------------
# These point at one specific course: "PCOS Balans Formule 2025" on the PCOS
# platform. To archive a different course, change both values:
#   SITE   = the platform's base URL (from your browser's address bar)
#   COURSE = the course slug, i.e. the part after /resources/ in the course URL
SITE = "https://pcosplatform.thehuddle.nl"
COURSE = "pcos-balans-formule-2025"
SITE = "https://pcosplatform.thehuddle.nl"
COURSE = "pcos-balans-formule-2025"
API = f"{SITE}/api/v4/e-learning/courses/{COURSE}"
COOKIE = os.environ.get("HUDDLE_COOKIE")
DELAY = 0.5  # seconds between API calls, to be polite to the platform
UA = "Mozilla/5.0 (X11; Linux x86_64)"


def api_get(path):
    """GET a course API endpoint with the session cookie and return parsed JSON."""
    req = urllib.request.Request(
        f"{API}{path}",
        headers={"Cookie": COOKIE, "Accept": "application/json", "User-Agent": UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 419):
            sys.exit(f"Auth failed ({e.code}) on {path}. Cookie probably expired: export a fresh HUDDLE_COOKIE and rerun.")
        raise
    time.sleep(DELAY)
    return data


def safe(name, maxlen=80):
    """Make a string safe to use as a file or folder name."""
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", name or "")
    name = re.sub(r"\s+", " ", name).strip().rstrip(".")
    return name[:maxlen].strip() or "untitled"


def download(url, dest, dry):
    """Download a file from the CDN (no cookie sent: it's a different domain)."""
    if dest.exists():
        print(f"    = exists: {dest.name}")
        return
    print(f"    ↓ {dest.name}")
    if dry:
        return
    tmp = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.rename(dest)


def download_vimeo(vid, name, folder, referer, archive, dry):
    """Download one Vimeo video with yt-dlp, pretending to come from the lesson page."""
    print(f"    ▶ vimeo {vid}: {name}")
    if dry:
        return True
    cmd = [
        "yt-dlp",
        "--referer", referer,
        "--download-archive", str(archive),
        "--merge-output-format", "mp4",
        "--no-progress",
        "-o", str(folder / f"{safe(name)} [{vid}].%(ext)s"),
        f"https://player.vimeo.com/video/{vid}",
    ]
    return subprocess.run(cmd).returncode == 0


def save_html(lesson, dest):
    """Save the lesson text as a standalone HTML page."""
    title = html.escape(lesson.get("name") or "")
    dest.write_text(
        f'<!doctype html>\n<html><head><meta charset="utf-8"><title>{title}</title></head>\n'
        f"<body>\n<h1>{title}</h1>\n{lesson.get('content') or ''}\n</body></html>\n",
        encoding="utf-8",
    )


def process_lesson(mod, les, ldir, archive, dry, problems):
    lpath = f"/modules/{mod['slug']}/lessons/{les['slug']}"
    referer = f"{SITE}/resources/{COURSE}/{mod['slug']}/{les['slug']}"

    resp = api_get(lpath)
    lesson, links = resp["data"], resp.get("links") or {}

    if not dry:
        ldir.mkdir(parents=True, exist_ok=True)
        (ldir / "lesson.json").write_text(json.dumps(resp, indent=2, ensure_ascii=False), encoding="utf-8")
        if lesson.get("content"):
            save_html(lesson, ldir / "content.html")

    # Attachments (PDFs, spreadsheets, ...)
    if "attachments" in links or lesson.get("attachment_count"):
        for att in api_get(f"{lpath}/attachments?per_page=500")["data"]:
            try:
                download(att["url"], ldir / safe(att["name"], 150), dry)
            except Exception as e:
                problems.append(f"{ldir}: attachment '{att.get('name')}' failed: {e}")

    # Videos: from the videos endpoint, plus any Vimeo embeds inside the lesson text
    vimeo = {}
    if "videos" in links or les["content_kind"] == "video":
        for v in api_get(f"{lpath}/videos?per_page=500")["data"]:
            src = v.get("source") or {}
            if src.get("host") == "vimeo" and src.get("content_id"):
                vimeo[str(src["content_id"])] = v.get("name") or les["name"]
            elif src.get("host") == "vimeo" and (m := re.search(r"player\.vimeo\.com/video/(\d+)", src.get("content") or "")):
                # Video added as a raw iframe embed: the ID is inside the HTML, not in content_id
                vimeo[m.group(1)] = v.get("name") or les["name"]
            else:
                problems.append(f"{ldir}: non-Vimeo video, check manually: {json.dumps(src)}")
    for vid in re.findall(r"player\.vimeo\.com/video/(\d+)", lesson.get("content") or ""):
        vimeo.setdefault(vid, les["name"])
    for vid, name in vimeo.items():
        if not download_vimeo(vid, name, ldir, referer, archive, dry):
            problems.append(f"{ldir}: yt-dlp failed for Vimeo {vid}")

    # Anything we don't handle yet (e.g. audio lessons) gets reported, not silently skipped
    extra = set(links) - {"attachments", "videos"}
    if extra or les["content_kind"] not in ("text", "video"):
        problems.append(f"{ldir}: unhandled content_kind={les['content_kind']} links={sorted(extra)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="course", help="output folder (default: course)")
    ap.add_argument("--module", help="only process this module slug, e.g. introductie-copy")
    ap.add_argument("--dry-run", action="store_true", help="call the API and list everything, download nothing")
    args = ap.parse_args()

    if not COOKIE:
        sys.exit("HUDDLE_COOKIE is not set. Run: read -rs HUDDLE_COOKIE && export HUDDLE_COOKIE")

    out = Path(args.out)
    archive = out / "yt-dlp-archive.txt"
    catalog = api_get("/catalog?include=image")["data"]
    if not args.dry_run:
        out.mkdir(parents=True, exist_ok=True)
        (out / "catalog.json").write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8")

    problems = []
    modules = sorted(catalog["modules"], key=lambda m: m["index"])
    for mi, mod in enumerate(modules, 1):
        if args.module and mod["slug"] != args.module:
            continue
        mdir = out / f"{mi:02d} - {safe(mod['name'])}"
        print(f"\n== {mdir.name}  ({mod['slug']})")
        for li, les in enumerate(sorted(mod["lessons"], key=lambda l: l["index"]), 1):
            ldir = mdir / f"{li:02d} - {safe(les['name'])}"
            print(f"  -- {ldir.name} [{les['content_kind']}]")
            try:
                process_lesson(mod, les, ldir, archive, args.dry_run, problems)
            except Exception as e:
                problems.append(f"{ldir}: failed: {e}")

    print(f"\nDone. {len(problems)} item(s) need attention.")
    for p in problems:
        print(f"  ! {p}")
    if problems and not args.dry_run:
        (out / "problems.txt").write_text("\n".join(problems) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
