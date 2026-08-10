#!/usr/bin/env python3
"""Download the current CI build of a manual, without hunting for a run artifact.

    fetch_build.py                     # every manual's current build -> downloads/
    fetch_build.py dm32                # just this one
    fetch_build.py --tag v1.2 --dir .  # a promoted release instead of `latest`
    fetch_build.py --list              # what the release currently holds

Each push to main republishes the builds under a rolling `latest` tag, so every
manual has one address that never changes:

    https://github.com/<owner>/<repo>/releases/download/latest/<product>.ready.idml

That URL is a plain HTTPS download — paste it in a browser, curl it, or point
InDesign's Open dialog at the file this script drops in `downloads/`. Nothing
here needs the `gh` CLI or a token; the repository is public.

The owner/repo is read from `git remote get-url origin`, so a fork or a rename
needs no edit. Standard library only, like the rest of the toolchain.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def repo_slug(explicit=None):
    if explicit:
        return explicit
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        raise SystemExit("could not read the git remote — pass --repo OWNER/REPO")
    m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", url)
    if not m:
        raise SystemExit(f"could not parse a repo out of {url!r} — pass --repo OWNER/REPO")
    return m.group(1)


def products():
    d = os.path.join(ROOT, "manuals")
    return sorted(n for n in os.listdir(d) if os.path.isdir(os.path.join(d, n))) \
        if os.path.isdir(d) else []


def release_assets(slug, tag):
    """Asset names on a release, via the public API (no token needed)."""
    url = f"https://api.github.com/repos/{slug}/releases/tags/{tag}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return [a["name"] for a in json.load(r).get("assets", [])]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise SystemExit(
                f"no release tagged {tag!r} in {slug}.\n"
                f"`latest` appears once the Build manual workflow has run on main; "
                f"until then, build locally:\n"
                f"  python3 toolchain/build_manual.py manuals/<product>/submissions/<file>.idml")
        raise SystemExit(f"GitHub API {e.code} for {url}")


def download(slug, tag, name, outdir):
    url = f"https://github.com/{slug}/releases/download/{tag}/{name}"
    dst = os.path.join(outdir, name)
    try:
        with urllib.request.urlopen(url, timeout=120) as r, open(dst, "wb") as f:
            n = 0
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                n += len(chunk)
    except urllib.error.HTTPError as e:
        print(f"  {name}: HTTP {e.code}", file=sys.stderr)
        return None
    print(f"  {name}  ({n:,} bytes)  -> {os.path.relpath(dst)}")
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("product", nargs="*", help="manual(s) to fetch (default: all)")
    ap.add_argument("--tag", default="latest", help="release tag (default: latest)")
    ap.add_argument("--dir", default=os.path.join(ROOT, "downloads"),
                    help="where to put the files (default: downloads/)")
    ap.add_argument("--repo", help="OWNER/REPO (default: from the git remote)")
    ap.add_argument("--list", action="store_true", help="list the release's assets and exit")
    ap.add_argument("--logs", action="store_true", help="also fetch the xref audit CSVs")
    args = ap.parse_args()

    slug = repo_slug(args.repo)
    assets = release_assets(slug, args.tag)
    if args.list:
        print(f"{slug} @ {args.tag}:")
        for a in assets:
            print(f"  {a}   https://github.com/{slug}/releases/download/{args.tag}/{a}")
        return 0

    wanted = args.product or products() or [a[:-len(".ready.idml")] for a in assets
                                            if a.endswith(".ready.idml")]
    names = []
    for p in wanted:
        if f"{p}.ready.idml" in assets:
            names.append(f"{p}.ready.idml")
            if args.logs and f"{p}.xref_log.csv" in assets:
                names.append(f"{p}.xref_log.csv")
        else:
            print(f"  {p}: no build on {args.tag} "
                  f"(assets: {', '.join(assets) or 'none'})", file=sys.stderr)
    if not names:
        return 1

    os.makedirs(args.dir, exist_ok=True)
    print(f"{slug} @ {args.tag} -> {os.path.relpath(args.dir)}")
    ok = [download(slug, args.tag, n, args.dir) for n in names]
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
