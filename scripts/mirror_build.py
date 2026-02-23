#!/usr/bin/env python3
"""
Mirror v2 – public-only, raw mode
Deterministic crawler with manifest + sanity gates
"""

from __future__ import annotations
import argparse, hashlib, json, os, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode

import requests
from bs4 import BeautifulSoup

USER_AGENT = "FootbagMirrorV2/0.1 (public-only archival)"

# ------------------ policy ------------------

def load_policy(path: Path) -> dict:
    if not path.exists():
        raise RuntimeError(f"Policy not found: {path}")
    if path.suffix.lower() != ".json":
        raise RuntimeError("Policy must be JSON")
    return json.loads(path.read_text(encoding="utf-8"))

# ------------------ url normalization ------------------

UI_ONLY_QUERY_KEYS = {"mode", "really", "cachebuster", "cachebust"}

def normalize_url(url: str, policy: dict) -> str:
    p = urlparse(url.strip())
    scheme = "http"
    host = p.netloc.lower()
    if host == "footbag.org":
        host = "www.footbag.org"

    path = p.path or "/"
    qs = [(k.lower(), v) for k, v in parse_qsl(p.query)]
    qs = [(k, v) for k, v in qs if k not in UI_ONLY_QUERY_KEYS]

    whitelist = policy.get("query_whitelist", {}).get(path)
    if whitelist is not None:
        whitelist = {k.lower() for k in whitelist}
        qs = [(k, v) for k, v in qs if k in whitelist]

    qs.sort()
    query = urlencode(qs)

    return urlunparse((scheme, host, path, "", query, ""))

def in_scope(url: str, policy: dict) -> bool:
    p = urlparse(url)
    if p.netloc not in policy["allowed_hosts"]:
        return False
    return any(p.path.startswith(pref) for pref in policy["allowed_path_prefixes"])

# ------------------ storage ------------------

def url_to_relpath(url: str) -> str:
    p = urlparse(url)
    path = p.path.lstrip("/")
    if not path or "." not in Path(path).name:
        return path.rstrip("/") + "/index.html" if path else "index.html"
    return path

def safe_path(root: Path, rel: str) -> Path:
    p = (root / rel).resolve()
    if not str(p).startswith(str(root.resolve())):
        raise RuntimeError("Path traversal blocked")
    return p

# ------------------ html discovery ------------------

def discover_links(html: str, base: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = set()
    for tag, attr in [
        ("a", "href"), ("img", "src"), ("script", "src"),
        ("link", "href"), ("iframe", "src"), ("form", "action")
    ]:
        for el in soup.find_all(tag):
            v = el.get(attr)
            if not v or v.startswith(("mailto:", "javascript:", "#")):
                continue
            links.add(urljoin(base, v))
    return sorted(links)

# ------------------ crawl ------------------

def crawl(seeds, policy, mirror_root, out_dir, delay):
    manifest = out_dir / "mirror_manifest.jsonl"
    mirror_root = mirror_root / "www.footbag.org"
    mirror_root.mkdir(parents=True, exist_ok=True)

    visited = set()
    queue = []

    for s in seeds:
        u = normalize_url(s, policy)
        if in_scope(u, policy):
            queue.append((u, 0))

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    saved_files = saved_html = bytes_saved = 0

    while queue:
        url, depth = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "url": url,
            "depth": depth,
            "outcome": None
        }

        try:
            r = session.get(url, timeout=20)
            rec["status"] = r.status_code
            if r.status_code != 200:
                rec["outcome"] = "http_fail"
            else:
                rel = url_to_relpath(url)
                path = safe_path(mirror_root, rel)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(r.content)

                saved_files += 1
                bytes_saved += len(r.content)

                if "text/html" in r.headers.get("Content-Type", ""):
                    saved_html += 1
                    for link in discover_links(r.text, url):
                        n = normalize_url(link, policy)
                        if in_scope(n, policy) and n not in visited:
                            queue.append((n, depth + 1))

                rec["outcome"] = "saved"
                root_abs = mirror_root.parent.resolve()          # .../mirror_out
                path_abs = path.resolve()
                rec["path"] = str(path_abs.relative_to(root_abs))

        except Exception as e:
            rec["outcome"] = "error"
            rec["error"] = str(e)

        with manifest.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

        time.sleep(delay)

    sanity = out_dir / "mirror_sanity.txt"
    sanity.write_text(
        f"saved_files={saved_files}\n"
        f"saved_html={saved_html}\n"
        f"bytes_saved={bytes_saved}\n"
    )

    if saved_files == 0 or saved_html == 0:
        raise SystemExit("Sanity failed – mirror empty")

# ------------------ main ------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", required=True)
    ap.add_argument("--policy", required=True)
    ap.add_argument("--mirror-root", default="mirror_out")
    ap.add_argument("--out-dir", default="out")
    ap.add_argument("--delay", type=float, default=0.25)
    args = ap.parse_args()

    policy = load_policy(Path(args.policy))
    seeds = [l.strip() for l in Path(args.seeds).read_text().splitlines() if l.strip()]

    crawl(
        seeds=seeds,
        policy=policy,
        mirror_root=Path(args.mirror_root),
        out_dir=Path(args.out_dir),
        delay=args.delay,
    )

if __name__ == "__main__":
    main()
