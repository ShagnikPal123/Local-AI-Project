"""Make a beta release for testers — and, only when asked, publish it on GitHub (Request G2).

    .venv/Scripts/python.exe release_beta.py                 # test, build, checksum → dist/beta/  (nothing leaves this PC)
    .venv/Scripts/python.exe release_beta.py --notes "…"      # same, with release notes
    .venv/Scripts/python.exe release_beta.py --publish        # also create the GitHub pre-release beta-<version>

Publishing needs the commits pushed first and a GitHub token with "contents: write"
for the repository, in the GITHUB_TOKEN environment variable (never in a file).
Testers' Nyx picks the release up from Settings → Updates (beta channel).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import build_release
from beta_channel import DEFAULT_REPO, config

PROJECT = Path(__file__).resolve().parent
OUT = PROJECT / "dist" / "beta"


def run(cmd, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=PROJECT, text=True, capture_output=True, **kw)


def next_version() -> str:
    today = dt.date.today().strftime("%Y.%m.%d")
    current = (PROJECT / "VERSION").read_text(encoding="utf-8").strip() if (PROJECT / "VERSION").exists() else ""
    if current.startswith(today):
        parts = current.split(".")
        return f"{today}.{int(parts[3]) + 1 if len(parts) > 3 and parts[3].isdigit() else 2}"
    return f"{today}.1"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--notes", default="", help="What changed, in words testers understand")
    parser.add_argument("--skip-tests", action="store_true", help="Only for an emergency fix; the release notes will say so")
    parser.add_argument("--publish", action="store_true", help="Create the GitHub pre-release (outward-facing)")
    args = parser.parse_args()

    if not args.skip_tests:
        print("Running the test suite…")
        tests = run([sys.executable, "-m", "pytest", "-q"])
        tail = (tests.stdout or "").strip().splitlines()[-1:] or ["no output"]
        if tests.returncode != 0:
            print(tests.stdout[-3000:])
            print("Tests failed — no release was made.")
            return 1
        print("  " + tail[0])

    dist_index = PROJECT / "frontend" / "nyx-pulse" / "dist" / "app" / "index.html"
    src = PROJECT / "frontend" / "nyx-pulse" / "src"
    newest_src = max((p.stat().st_mtime for p in src.rglob("*") if p.is_file()), default=0)
    if not dist_index.exists() or dist_index.stat().st_mtime < newest_src:
        print("The web UI is older than its source. Run `npm run build` in frontend/nyx-pulse, then try again.")
        return 1

    version = next_version()
    (PROJECT / "VERSION").write_text(version, encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    archive = build_release.build(OUT / f"NyxIchos-beta-{version}.zip")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    commit = run(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()
    manifest = {"version": version, "channel": "beta", "sha256": digest, "size": archive.stat().st_size, "asset": archive.name,
                "commit": commit, "notes": args.notes + (" (tests skipped)" if args.skip_tests else ""), "built_at": dt.datetime.now().isoformat()}
    (OUT / "release.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Built beta {version}: {archive.name} ({archive.stat().st_size / 1_048_576:.1f} MB), sha256 {digest[:16]}…")

    if not args.publish:
        print("Not published. Review the zip, push your commits, then run again with --publish.")
        return 0

    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        print("Set GITHUB_TOKEN (a token with contents: write) in this terminal, then run with --publish again.")
        return 1
    status = run(["git", "status", "-sb"]).stdout.splitlines()[:1]
    if status and "ahead" in status[0]:
        print("Your branch has commits GitHub doesn't have yet. Push first, so testers get the code this release describes.")
        return 1
    import requests

    repo = config().get("repo") or DEFAULT_REPO
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    created = requests.post(f"https://api.github.com/repos/{repo}/releases", headers=headers, timeout=30, json={
        "tag_name": f"beta-{version}", "target_commitish": run(["git", "rev-parse", "HEAD"]).stdout.strip(),
        "name": f"Nyx Ichos beta {version}", "body": args.notes or "Beta update.", "prerelease": True})
    if created.status_code >= 300:
        print(f"GitHub refused the release ({created.status_code}): {created.text[:300]}")
        return 1
    upload = created.json()["upload_url"].split("{")[0]
    for path, kind in ((archive, "application/zip"), (OUT / "release.json", "application/json")):
        response = requests.post(f"{upload}?name={path.name}", headers={**headers, "Content-Type": kind}, data=path.read_bytes(), timeout=600)
        if response.status_code >= 300:
            print(f"Uploading {path.name} failed ({response.status_code}): {response.text[:200]}")
            return 1
    print(f"Published beta-{version}: {created.json().get('html_url')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
