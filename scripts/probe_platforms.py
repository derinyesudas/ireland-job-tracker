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
# Every platform domain worth noticing, and how to turn a URL on that domain
# into a reader token. The domain match is deliberately loose - a branded page
# may name its platform in a link, a preconnect hint, a security header or a
# blob of config, and only some of those carry the tenant. So the domain and
# the token are found separately: seeing the domain tells us which platform,
# and the token pattern is then tried against everything on the page.
PLATFORM_DOMAINS = {
    "myworkdayjobs.com":  "workday",
    "icims.com":          "icims",
    "avature.net":        "avature",
    "eightfold.ai":       "eightfold",
    "successfactors.eu":  "successfactors",
    "successfactors.com": "successfactors",
    "jobs2web.com":       "successfactors",
    "smartrecruiters.com": "smartrecruiters",
    "taleo.net":          "taleo",
    "oraclecloud.com":    "oraclecloud",
    "csod.com":           "cornerstone",
    "greenhouse.io":      "greenhouse",
    "lever.co":           "lever",
    "workable.com":       "workable",
    "ashbyhq.com":        "ashby",
    "recruitee.com":      "recruitee",
    "personio.de":        "personio",
    "phenompeople.com":   "phenom",
    "talentbrew.com":     "talentbrew",
    "candidatemanager.net": "candidatemanager",
    "talent-community.com": "talentcommunity",
    "occupop.com":        "occupop",
    "hirehive.com":       "hirehive",
    "pinpointhq.com":     "pinpoint",
}

# How to lift the tenant out, once we know which platform we are looking at.
# No scheme required: these run against the whole page, not just hrefs.
TOKEN_PATTERNS = {
    "workday":        [r"([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:wday/cxs/[\w-]+/)?([\w-]+)",
                       r"([\w-]+)\.(wd\d+)\.myworkdayjobs\.com"],
    "icims":          [r"(?:careers-)?([\w-]+)\.icims\.com"],
    "avature":        [r"([\w-]+)\.avature\.net"],
    "eightfold":      [r"([\w-]+)\.eightfold\.ai"],
    "successfactors": [r"career\d*\.successfactors\.(?:eu|com)/[^\"'\s]*company=([\w-]+)",
                       r"[?&]company=([\w-]+)",
                       r"([\w-]+)\.jobs2web\.com"],
    "smartrecruiters":[r"smartrecruiters\.com/(?:v1/companies/)?([\w-]+)"],
    "taleo":          [r"([\w-]+)\.taleo\.net"],
    "oraclecloud":    [r"([\w-]+\.oraclecloud\.com)"],
    "cornerstone":    [r"([\w-]+)\.csod\.com"],
    "greenhouse":     [r"greenhouse\.io/(?:embed/job_board\?for=)?([\w-]+)"],
    "lever":          [r"lever\.co/([\w-]+)"],
    "workable":       [r"workable\.com/(?:api/accounts/)?([\w-]+)"],
    "ashby":          [r"ashbyhq\.com/([\w-]+)"],
    "recruitee":      [r"([\w-]+)\.recruitee\.com"],
    "personio":       [r"([\w-]+)\.jobs\.personio\.de"],
    "occupop":        [r"([\w-]+)\.occupop\.com"],
    "hirehive":       [r"([\w-]+)\.hirehive\.com"],
    "pinpoint":       [r"([\w-]+)\.pinpointhq\.com"],
}

# Platforms where the careers host itself is the token, so nothing needs lifting.
HOST_IS_TOKEN = {"phenom", "talentbrew", "candidatemanager", "talentcommunity"}

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


def candidates(name: str, url: str) -> tuple[list[tuple[str, str]], list[str], str]:
    """Returns (things worth trying, platforms merely seen, note).

    Reporting what was seen but not usable is the point: a page that names
    myworkdayjobs.com without ever spelling out its tenant is a different
    problem from a page that names nothing at all, and only the first is worth
    another go.
    """
    try:
        blob = page_and_scripts(url)
    except FetchError as exc:
        return [], [], str(exc)[:120]

    host = urlparse(url).netloc
    seen: list[str] = []
    for domain, platform in PLATFORM_DOMAINS.items():
        if domain in blob.lower() and platform not in seen:
            seen.append(platform)

    found: list[tuple[str, str]] = []

    def add(reader: str, token: str) -> None:
        if token and (reader, token) not in found:
            found.append((reader, token))

    for platform in seen:
        if platform in HOST_IS_TOKEN:
            add(platform if platform in FETCHERS else "jsonld", 
                host if platform in FETCHERS else url)
            if platform == "phenom":
                bare = re.sub(r"^(careers|jobs|www)\.", "", host)
                add("phenom", f"{host}|{bare}")
            continue
        for pattern in TOKEN_PATTERNS.get(platform, []):
            for m in re.finditer(pattern, blob, re.I):
                if platform == "workday":
                    g = m.groups()
                    add("workday", "|".join(g) if len(g) == 3 else f"{g[0]}|{g[1]}|External")
                else:
                    add(platform, m.group(1))
            if found:
                break

    return found, seen, ""


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
    tried, seen, note = candidates(name, url)
    result = {"name": name, "url": url, "seen": seen, "note": note,
              "tried": [], "working": []}
    for reader, token in tried:
        ok, why = try_feed(reader, token)
        result["tried"].append({"reader": reader, "token": token, "ok": ok, "note": why})
        if ok:
            result["working"].append({"ats": reader, "token": token, "note": why})
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
            if r["working"]:
                mark, detail = "HIT ", r["working"][0]["ats"]
            elif r["tried"]:
                mark, detail = "    ", f"{len(r['tried'])} tried, none worked"
            elif r["seen"]:
                mark, detail = "SEEN", f"{', '.join(r['seen'])} but no tenant in the page"
            elif r["note"]:
                mark, detail = "    ", r["note"][:48]
            else:
                mark, detail = "    ", "no platform named anywhere"
            print(f"{mark}{r['name'][:40]:<40} {detail}", flush=True)

    results.sort(key=lambda r: (not r["working"], r["name"]))
    (DATA / "probe_results.json").write_text(json.dumps(results, indent=1))

    hits    = [r for r in results if r["working"]]
    tokenless = [r for r in results if not r["working"] and not r["tried"] and r["seen"]]
    tried_no  = [r for r in results if not r["working"] and r["tried"]]
    silent    = [r for r in results if not r["working"] and not r["tried"] and not r["seen"] and not r["note"]]
    errored   = [r for r in results if r["note"]]
    print(f"\n{'='*70}")
    print(f"  {len(hits):>3} now have a working feed")
    print(f"  {len(tokenless):>3} name a platform but never spell out the tenant")
    print(f"  {len(tried_no):>3} gave a tenant, but the feed came back empty")
    print(f"  {len(silent):>3} name no platform at all")
    print(f"  {len(errored):>3} could not be opened")
    print("="*70)
    if tokenless:
        print("\n  platform named, tenant hidden:")
        for r in tokenless:
            print(f"    {r['name'][:44]:<44} {', '.join(r['seen'])}")
    for r in hits:
        w = r["working"][0]
        print(f"  {r['name'][:40]:<40} {w['ats']:<16} {w['token'][:40]}")
        print(f"  {'':<40} {w['note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
