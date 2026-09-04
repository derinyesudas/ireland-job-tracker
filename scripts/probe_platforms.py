"""
Works out how an employer that never resolved actually serves its jobs.

Two things are tried for every employer, because the last sweep showed the
failures are not all the same problem:

  1. A different URL on the same site. Citi is the worked example: the register
     pointed at a landing page, its search page carries the jobs in the HTML,
     and the existing joblinks reader handles it once aimed correctly. No new
     code, just a better address.

  2. The platform behind the branding. A careers page often names its platform
     without spelling out the tenant, so the platform and the tenant are looked
     for separately, and an employer that names one without the other is
     reported as such rather than silently skipped.

Nothing is reported as working unless a reader actually returned a posting.

    python scripts/probe_platforms.py
    python scripts/probe_platforms.py --only Citi
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.ats_clients import FETCHERS, FetchError, BROWSER_HEADERS  # noqa: E402
from scraper.ats_extra import _job_candidate_links  # noqa: E402

import time  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

# The shared fetcher already sends a Chrome user agent, so the 403s in the last
# sweep were not a missing UA. What it does not send is the rest of what a real
# navigation carries, and it never retries a page fetch, so a single DNS blip
# reads as a dead site. Both are fixed here rather than in the shared client,
# because the live scraper is working and is not what we are debugging.
NAV_HEADERS = {
    **BROWSER_HEADERS,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}
PAGE_TIMEOUT = 25
PAGE_TRIES = 3

# A hostname that does not resolve does not resolve on any path, so the retry
# added for flaky DNS must not be paid fourteen times over for one dead host.
# v4 did exactly that, which is why it ran for the best part of an hour.
DEAD_HOST_RE = re.compile(
    r"name or service not known|temporary failure in name resolution|"
    r"nodename nor servname|getaddrinfo|connection refused|"
    r"certificate verify failed|handshake", re.I)


class HostIsDead(FetchError):
    """The host itself is unreachable - stop trying paths on it."""


def fetch(url: str, limit: int = 3_000_000) -> str:
    """Page fetch that looks like a navigation and survives a transient blip."""
    last = None
    for attempt in range(PAGE_TRIES):
        try:
            req = urllib.request.Request(url, headers=NAV_HEADERS)
            with urllib.request.urlopen(req, timeout=PAGE_TIMEOUT) as resp:
                return resp.read(limit).decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 404, 410):
                raise FetchError(f"HTTP {exc.code}") from exc   # settled, not flaky
            last = exc
        except Exception as exc:  # noqa: BLE001
            last = exc
        if DEAD_HOST_RE.search(str(last)):
            raise HostIsDead(str(last))          # no point sleeping on this one
        if attempt < PAGE_TRIES - 1:
            time.sleep(1.5 * (attempt + 1))
    raise FetchError(str(last))

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# Where a careers site tends to keep its actual list, when the address in the
# register turns out to be a landing page.
URL_PATHS = ["/search-jobs", "/jobs", "/search", "/job-search", "/vacancies",
             "/careers/search", "/en/search-jobs", "/opportunities", "/all-jobs"]

# A link that looks like an individual posting rather than navigation.
JOB_LINK = re.compile(r'href=["\']([^"\']*(?:/job/|/jobs/|/job-|jobid=|/vacancy/|/position/)[^"\']*)', re.I)

# An anchor that looks like the way in to the list, so the site's own
# navigation is followed rather than only guessing at paths.
LIST_LINK = re.compile(
    r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>((?:(?!</a>).){0,120})</a>', re.I | re.S)
LIST_WORDS = re.compile(
    r'(search\s*(?:our\s*)?(?:jobs|roles|openings)|view\s*all\s*(?:jobs|roles)|'
    r'all\s*(?:jobs|vacancies|openings)|current\s*(?:vacancies|openings|opportunities)|'
    r'job\s*search|browse\s*jobs|open\s*(?:roles|positions))', re.I)

PLATFORM_DOMAINS = {
    "myworkdayjobs.com": "workday", "icims.com": "icims", "avature.net": "avature",
    "eightfold.ai": "eightfold", "successfactors": "successfactors",
    "jobs2web.com": "successfactors", "smartrecruiters.com": "smartrecruiters",
    "taleo.net": "taleo", "oraclecloud.com": "oraclecloud", "csod.com": "cornerstone",
    "greenhouse.io": "greenhouse", "lever.co": "lever", "workable.com": "workable",
    "ashbyhq.com": "ashby", "recruitee.com": "recruitee", "jobs.personio.de": "personio",
    "phenompeople.com": "phenom", "talentbrew.com": "talentbrew",
    "candidatemanager.net": "candidatemanager", "talent-community.com": "talentcommunity",
    "occupop.com": "occupop", "hirehive.com": "hirehive", "pinpointhq.com": "pinpoint",
}

TOKEN_PATTERNS = {
    "workday":        [r"([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:wday/cxs/[\w-]+/)?([\w-]+)",
                       r"([\w-]+)\.(wd\d+)\.myworkdayjobs\.com"],
    "icims":          [r"(?:careers-)?([\w-]+)\.icims\.com"],
    "avature":        [r"([\w-]+)\.avature\.net"],
    "eightfold":      [r"([\w-]+)\.eightfold\.ai"],
    "successfactors": [r"career\d*\.successfactors\.(?:eu|com)/[^\"'\s]*company=([\w-]+)",
                       r"[?&]company=([\w-]+)", r"([\w-]+)\.jobs2web\.com"],
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

# Readers that take a careers URL rather than a tenant, in the order worth trying.
GENERIC = ["joblinks", "jsonld", "sitemap", "apiprobe"]

MIN_JOB_LINKS = 3          # fewer than this and the page is navigation, not a list
CLEAR_LIST = 8             # this many and it is plainly the list, stop looking
MAX_FETCHES = 14           # per employer, so one big site cannot eat the run


def variants(url: str) -> list[str]:
    """The registered address first, then the usual places a list hides."""
    p = urlparse(url)
    root = f"{p.scheme}://{p.netloc}"
    out = [url]
    for path in URL_PATHS:
        cand = root + path
        if cand.rstrip("/") != url.rstrip("/"):
            out.append(cand)
    return out


def look(url: str) -> dict:
    """One cheap fetch: how many postings does this page link to, and does it
    name a platform?"""
    try:
        page = fetch(url)
    except FetchError as exc:
        return {"url": url, "ok": False, "note": str(exc)[:100], "links": 0,
                "dead_host": isinstance(exc, HostIsDead),
                "samples": [], "platforms": [], "follow": []}
    links = {urljoin(url, h) for h in JOB_LINK.findall(page)}
    plats = []
    low = page.lower()
    for domain, platform in PLATFORM_DOMAINS.items():
        if domain in low and platform not in plats:
            plats.append(platform)
    follow = []
    for href, text in LIST_LINK.findall(page):
        if not LIST_WORDS.search(re.sub(r"<[^>]+>", " ", text)):
            continue
        cand = urljoin(url, href.strip())
        if urlparse(cand).netloc == urlparse(url).netloc and cand not in follow:
            follow.append(cand)
    return {"url": url, "ok": True, "note": "", "links": len(links),
            "samples": sorted(links)[:3], "platforms": plats, "page": page,
            "follow": follow[:4]}


def tokens_from(page: str, host: str, platforms: list[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []

    def add(reader, token):
        if token and reader in FETCHERS and (reader, token) not in out:
            out.append((reader, token))

    for platform in platforms:
        if platform not in TOKEN_PATTERNS:
            continue
        for pattern in TOKEN_PATTERNS[platform]:
            for m in re.finditer(pattern, page, re.I):
                if platform == "workday":
                    g = m.groups()
                    add("workday", "|".join(g) if len(g) == 3 else f"{g[0]}|{g[1]}|External")
                else:
                    add(platform, m.group(1))
            if out:
                break
    return out


def try_reader(reader: str, token: str) -> tuple[bool, str]:
    fn = FETCHERS.get(reader)
    if not fn:
        return False, "no such reader"
    try:
        jobs = fn(token)
    except FetchError as exc:
        return False, str(exc)[:90]
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:70]}"
    if not jobs:
        return False, "answered, no jobs"
    return True, f"{len(jobs)} jobs, e.g. {(jobs[0].get('title') or '?')[:44]}"


def probe(name: str, url: str) -> dict:
    r = {"name": name, "url": url, "working": [], "tried": [],
         "platforms": [], "best_url": "", "note": ""}

    first = look(url)
    seen = {url.rstrip("/")}
    looks = [first]
    # the site's own way in, before any guessing
    queue = list(first.get("follow", [])) + [v for v in variants(url)[1:]]
    best = first["links"] if first["ok"] else 0
    dead_hosts = {urlparse(url).netloc} if first.get("dead_host") else set()
    for u in queue:
        if u.rstrip("/") in seen or best >= CLEAR_LIST or len(looks) >= MAX_FETCHES:
            continue                      # list page in hand, or budget spent
        if urlparse(u).netloc in dead_hosts:
            continue                      # this host is already proven gone
        seen.add(u.rstrip("/"))
        l = look(u)
        if l.get("dead_host"):
            dead_hosts.add(urlparse(u).netloc)
        looks.append(l)
        best = max(best, l["links"])
        if l["links"]:                    # only worth going deeper from a live trail
            queue.extend(x for x in l.get("follow", []) if x.rstrip("/") not in seen)

    alive = [l for l in looks if l["ok"]]
    if not alive:
        r["note"] = first["note"] or "could not open anything"
        return r

    for l in alive:
        for p in l["platforms"]:
            if p not in r["platforms"]:
                r["platforms"].append(p)

    # the page that links to the most postings is the one worth reading
    alive.sort(key=lambda l: -l["links"])
    best = alive[0]
    r["best_url"] = best["url"]
    r["links"] = best["links"]
    r["samples"] = best.get("samples", [])
    # The whole point of this pass: how many of those links does the reader's
    # own filter actually keep? If mine sees 39 and the reader keeps 0, the bug
    # is the filter, not the site.
    try:
        r["reader_links"] = len(_job_candidate_links(best["url"], best.get("page", "")))
    except Exception as exc:  # noqa: BLE001
        r["reader_links"] = -1
        r["note"] = f"link filter raised {type(exc).__name__}"

    def attempt(reader, token):
        ok, why = try_reader(reader, token)
        r["tried"].append({"reader": reader, "token": token[:70], "ok": ok, "note": why})
        if ok:
            r["working"].append({"ats": reader, "token": token, "note": why})
        return ok

    # 1. a page that already lists postings - no new code needed
    for l in alive[:2]:
        if l["links"] >= MIN_JOB_LINKS:
            for reader in GENERIC:
                if attempt(reader, l["url"]):
                    return r

    # 1b. the register sometimes already gives the tenant, and the page fetch
    #     failing (Perrigo's 500, QBE's 404) hid that the API is fine.
    m = re.search(r"([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[\w-]+/)?([\w-]+)", url, re.I)
    if m and attempt("workday", "|".join(m.groups())):
        return r

    # 2. the platform behind the branding
    host = urlparse(url).netloc
    for l in alive[:2]:
        for reader, token in tokens_from(l.get("page", ""), host, l["platforms"]):
            if attempt(reader, token):
                return r
        for p in l["platforms"]:
            if p in ("phenom", "talentbrew") and attempt(p, host):
                return r

    # 3. last resort on the richest page
    if not r["tried"]:
        for reader in ("jsonld", "sitemap"):
            if attempt(reader, alive[0]["url"]):
                return r
    return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    register = json.loads((DATA / "ireland_register.json").read_text())
    tracked = {(c.get("company") or c.get("name") or "").lower()
               for c in json.loads((DATA / "companies.json").read_text())}

    todo = []
    for row in register:
        nm = row.get("company") or row.get("name") or ""
        if nm.lower() in tracked or (args.only and args.only.lower() not in nm.lower()):
            continue
        if row.get("careers_url"):
            todo.append((nm, row["careers_url"]))

    print(f"probing {len(todo)} employers\n", flush=True)
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for f in as_completed({pool.submit(probe, n, u): n for n, u in todo}):
            r = f.result()
            results.append(r)
            if r["working"]:
                tag = f"HIT  {r['working'][0]['ats']}"
            elif r["tried"]:
                tag = f"     {len(r['tried'])} tried, none worked"
            elif r["platforms"]:
                tag = f"SEEN {', '.join(r['platforms'])}, tenant not in the page"
            elif r["note"]:
                tag = f"     {r['note'][:44]}"
            else:
                tag = f"     nothing to go on ({r.get('links',0)} job links)"
            print(f"{r['name'][:38]:<38} {tag}", flush=True)

    results.sort(key=lambda r: (not r["working"], r["name"]))
    (DATA / "probe_results.json").write_text(json.dumps(results, indent=1))

    hits = [r for r in results if r["working"]]
    print(f"\n{'='*72}\n  {len(hits)} of {len(results)} employers now return real jobs\n{'='*72}")
    for r in hits:
        w = r["working"][0]
        print(f"  {r['name'][:34]:<34} {w['ats']:<12} {w['token'][:44]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
