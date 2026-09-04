"""
Works out how the branded careers sites actually serve their jobs.

The resolver already spots that a page is "a platform behind branding" - it
sees myworkdayjobs.com or icims.com referenced in the markup - but it stops
there, because knowing the platform is not the same as knowing the tenant. This
finds the tenant: it opens each careers page, pulls every platform URL out of
the HTML and the scripts it loads, works the token out of those URLs, and then
CALLS the feed to see whether jobs actually come back.

Nothing is reported as working unless a real posting was returned.

    python scripts/probe_platforms.py                 # every unresolved employer
    python scripts/probe_platforms.py --only Citi     # just one
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.ats_clients import FETCHERS, FetchError, _get_html  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# How a platform's own URLs give away the tenant. Each entry is the host
# fragment to look for, and how to turn a matching URL into a reader token.
SIGNATURES = [
    ("workday",         r"https?://([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:wday/cxs/[\w-]+/)?([\w-]+)",
                        lambda m: f"{m.group(1)}|{m.group(2)}|{m.group(3)}"),
    ("icims",           r"https?://(?:careers-)?([\w-]+)\.icims\.com",              lambda m: m.group(1)),
    ("avature",         r"https?://([\w-]+)\.avature\.net",                          lambda m: m.group(1)),
    ("eightfold",       r"https?://([\w-]+)\.eightfold\.ai",                         lambda m: m.group(1)),
    ("successfactors",  r"https?://career(\d*)\.successfactors\.(?:eu|com)/[^\"'\s]*company=([\w-]+)",
                        lambda m: m.group(2)),
    ("successfactors",  r"https?://([\w-]+)\.jobs2web\.com",                         lambda m: m.group(1)),
    ("smartrecruiters", r"https?://(?:api|www|jobs)\.smartrecruiters\.com/(?:v1/companies/)?([\w-]+)",
                        lambda m: m.group(1)),
    ("taleo",           r"https?://([\w-]+)\.taleo\.net",                            lambda m: m.group(1)),
    ("oraclecloud",     r"https?://([\w-]+\.oraclecloud\.com)",                       lambda m: m.group(1)),
    ("cornerstone",     r"https?://([\w-]+)\.csod\.com",                              lambda m: m.group(1)),
    ("greenhouse",      r"boards\.greenhouse\.io/([\w-]+)",                           lambda m: m.group(1)),
    ("lever",           r"jobs\.lever\.co/([\w-]+)",                                  lambda m: m.group(1)),
    ("phenom",          r"cdn-prod-static\.phenompeople\.com",                        lambda m: None),
    ("talentbrew",      r"tbcdn\.talentbrew\.com",                                    lambda m: None),
]

SCRIPT_SRC = re.compile(r'<script[^>]+src=["\']([^"\']+)', re.I)
MAX_SCRIPTS = 6


def page_and_scripts(url: str) -> str:
    """The page, plus the scripts it loads. A branded site usually hides its
    platform in a bundle rather than in the HTML itself."""
    blob = _get_html(url)
    out = [blob]
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    for src in SCRIPT_SRC.findall(blob)[:MAX_SCRIPTS]:
        full = src if src.startswith("http") else (base + src if src.startswith("/") else None)
        if not full:
            continue
        try:
            out.append(_get_html(full, limit=400_000))
        except FetchError:
            pass
    return "\n".join(out)


def candidates(name: str, url: str) -> list[tuple[str, str]]:
    """Every (reader, token) worth trying for this employer."""
    found: list[tuple[str, str]] = []
    try:
        blob = page_and_scripts(url)
    except FetchError as exc:
        return [("__error__", str(exc)[:120])]

    host = urlparse(url).netloc
    for reader, pattern, to_token in SIGNATURES:
        for m in re.finditer(pattern, blob, re.I):
            tok = to_token(m)
            if tok is None:            # host-only tell, so the careers host IS the token
                tok = host
            if (reader, tok) not in found:
                found.append((reader, tok))

    # phenom keys on a domain that is usually, but not always, the host minus
    # its careers label - so try both, and the employer's own domain too.
    if any(r == "phenom" for r, _ in found):
        bare = re.sub(r"^(careers|jobs|www)\.", "", host)
        for extra in (f"{host}|{bare}", host):
            if ("phenom", extra) not in found:
                found.append(("phenom", extra))
    return found


def try_feed(reader: str, token: str) -> tuple[bool, str]:
    fn = FETCHERS.get(reader)
    if not fn:
        return False, f"no reader called {reader}"
    try:
        jobs = fn(token)
    except FetchError as exc:
        return False, str(exc)[:110]
    except Exception as exc:                       # a reader bug must not stop the sweep
        return False, f"{type(exc).__name__}: {str(exc)[:90]}"
    if not jobs:
        return False, "feed answered but returned no jobs"
    t = (jobs[0].get("title") or "?")[:52]
    return True, f"{len(jobs)} jobs, first: {t}"


def probe(name: str, url: str) -> dict:
    result = {"name": name, "url": url, "tried": [], "working": []}
    for reader, token in candidates(name, url):
        if reader == "__error__":
            result["tried"].append({"reader": "-", "token": "-", "ok": False, "note": token})
            continue
        ok, note = try_feed(reader, token)
        result["tried"].append({"reader": reader, "token": token, "ok": ok, "note": note})
        if ok:
            result["working"].append({"ats": reader, "token": token, "note": note})
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="only employers whose name contains this")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    register = json.loads((DATA / "ireland_register.json").read_text())
    tracked = {(c.get("company") or c.get("name") or "").lower()
               for c in json.loads((DATA / "companies.json").read_text())}

    todo = []
    for r in register:
        nm = r.get("company") or r.get("name") or ""
        if nm.lower() in tracked:
            continue
        if args.only and args.only.lower() not in nm.lower():
            continue
        u = r.get("careers_url")
        if u:
            todo.append((nm, u))

    print(f"probing {len(todo)} employers that are not yet tracked\n", flush=True)
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(probe, n, u): n for n, u in todo}
        for f in as_completed(futures):
            r = f.result()
            results.append(r)
            mark = "HIT " if r["working"] else "    "
            print(f"{mark}{r['name'][:44]:<44} {len(r['tried'])} tried", flush=True)

    results.sort(key=lambda r: (not r["working"], r["name"]))
    (DATA / "probe_results.json").write_text(json.dumps(results, indent=1))

    hits = [r for r in results if r["working"]]
    print(f"\n{'='*70}\n{len(hits)} of {len(results)} employers now have a working feed\n{'='*70}")
    for r in hits:
        w = r["working"][0]
        print(f"  {r['name'][:40]:<40} {w['ats']:<16} {w['token'][:40]}")
        print(f"  {'':<40} {w['note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
