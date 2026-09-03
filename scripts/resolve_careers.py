"""
Turn a careers-page URL into a working job feed, one company at a time.

This is the piece that does the manual integration work systematically. For
each company in data/ireland_register.json it:

  1. Opens the careers URL and follows any redirects.
  2. Works out which recruitment platform is behind it - from the final URL,
     and failing that from telltale signs in the page itself (an embedded
     Greenhouse board, a Workday fetch, an Oracle site number, and so on).
  3. Builds the exact API token for that platform.
  4. CALLS the feed for real and counts the jobs that come back.
  5. Records the outcome, honestly: resolved, or unresolved with the reason.

Nothing is written to the tracker on a guess. A company only enters
data/companies.json once step 4 has actually returned jobs.

Must run somewhere with open network access - in practice GitHub Actions.

    python scripts/resolve_careers.py               # everything
    python scripts/resolve_careers.py --only "Irish Life"
    python scripts/resolve_careers.py --limit 40
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scraper.ats_clients import FETCHERS, BROWSER_HEADERS, FetchError  # noqa: E402

DATA = ROOT / "data"
REGISTER = DATA / "ireland_register.json"
COMPANIES = DATA / "companies.json"
REPORT = DATA / "resolution_report.json"

PAGE_TIMEOUT = 15
MAX_PAGE = 3_000_000


# ------------------------------------------------------------------ fetching

def _fetch_once(url: str) -> tuple[str, str]:
    req = urllib.request.Request(
        url,
        headers={**BROWSER_HEADERS, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
    )
    with urllib.request.urlopen(req, timeout=PAGE_TIMEOUT) as resp:
        raw = resp.read(MAX_PAGE)
        return resp.geturl(), raw.decode("utf-8", errors="replace")


COMMON_CAREERS_PATHS = [
    "/careers", "/careers/", "/jobs", "/jobs/", "/en/careers", "/careers/jobs",
    "/about/careers", "/about-us/careers", "/company/careers", "/join-us",
    "/en-ie/careers", "/ie/careers", "/careers/vacancies", "/vacancies",
]


def _url_variants(url: str) -> list[str]:
    """
    Sensible alternatives when a careers URL no longer works.

    Fifteen of the register's URLs return 404 and twenty-one fail to connect
    at all - companies reorganise their sites constantly. Rather than writing
    those employers off, try the obvious places their careers page moved to.
    """
    p = urlparse(url)
    if not p.netloc:
        return []
    host = p.netloc
    alt_host = host[4:] if host.startswith("www.") else "www." + host
    out: list[str] = []

    def push(u: str) -> None:
        if u and u not in out and u != url:
            out.append(u)

    # Same path on the other spelling of the host.
    push(f"{p.scheme}://{alt_host}{p.path}")

    # Walk the path back one segment at a time - a dead deep link often has a
    # living parent.
    segments = [seg for seg in p.path.split("/") if seg]
    for cut in range(len(segments) - 1, 0, -1):
        push(f"{p.scheme}://{host}/{'/'.join(segments[:cut])}/")

    # Then the usual places a careers page lives.
    for path in COMMON_CAREERS_PATHS:
        push(f"{p.scheme}://{host}{path}")
    for path in COMMON_CAREERS_PATHS[:6]:
        push(f"{p.scheme}://{alt_host}{path}")

    return out[:12]


def fetch_page(url: str) -> tuple[str, str]:
    """Return (final_url, html), trying alternatives if the given URL is dead."""
    try:
        return _fetch_once(url)
    except urllib.error.HTTPError as exc:
        if exc.code not in (404, 403, 410, 500, 503):
            raise
        first_error: Exception = exc
    except Exception as exc:  # noqa: BLE001
        first_error = exc

    for alt in _url_variants(url):
        try:
            final_url, html_text = _fetch_once(alt)
        except Exception:  # noqa: BLE001
            continue
        # Only accept a page that actually looks like it lists jobs.
        low = html_text.lower()
        if any(w in low for w in ("job", "vacanc", "career", "opportunit")):
            return final_url, html_text

    raise first_error


# ----------------------------------------------------------------- detection
# Each entry: (compiled pattern, platform, function building the token)

def _wd_token(m: re.Match) -> str:
    return f"{m.group('tenant')}|{m.group('wd')}|{m.group('site')}"


URL_PATTERNS = [
    # The API form must be tried FIRST. A branded careers page often calls
    # .../wday/cxs/<tenant>/<site>/jobs from its JavaScript, and the general
    # pattern below would otherwise read "cxs" as the site name.
    (re.compile(r"https?://(?P<tenant>[\w-]+)\.wd(?P<wd>\d+)\.myworkdayjobs\.com/wday/cxs/[\w-]+/(?P<site>[\w-]+)/jobs", re.I),
     "workday", _wd_token),
    # The human-facing form, optionally carrying a locale segment
    # (/en-US/SiteName). "wday" is excluded so it cannot match the API path.
    (re.compile(r"https?://(?P<tenant>[\w-]+)\.wd(?P<wd>\d+)\.myworkdayjobs\.com/(?!wday/)(?:[a-z]{2}-[A-Z]{2}/)?(?P<site>[\w-]+)", re.I),
     "workday", _wd_token),
    (re.compile(r"https?://(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_board\?for=)?(?P<t>[\w-]+)", re.I),
     "greenhouse", lambda m: m.group("t")),
    (re.compile(r"boards\.greenhouse\.io/embed/job_board\?for=(?P<t>[\w-]+)", re.I),
     "greenhouse", lambda m: m.group("t")),
    (re.compile(r"https?://jobs\.lever\.co/(?P<t>[\w-]+)", re.I),
     "lever", lambda m: m.group("t")),
    (re.compile(r"https?://jobs\.ashbyhq\.com/(?P<t>[\w.-]+)", re.I),
     "ashby", lambda m: m.group("t")),
    (re.compile(r"https?://(?:apply|www)\.workable\.com/(?P<t>[\w-]+)", re.I),
     "workable", lambda m: m.group("t")),
    (re.compile(r"https?://jobs\.smartrecruiters\.com/(?P<t>[\w-]+)", re.I),
     "smartrecruiters", lambda m: m.group("t")),
    (re.compile(r"https?://(?P<t>[\w-]+)\.recruitee\.com", re.I),
     "recruitee", lambda m: m.group("t")),
    (re.compile(r"https?://(?P<t>[\w-]+)\.jobs\.personio\.(?:de|com)", re.I),
     "personio", lambda m: m.group("t")),
    (re.compile(r"https?://(?P<t>[\w-]+)\.pinpointhq\.com", re.I),
     "pinpoint", lambda m: m.group("t")),

    # The enterprise suites the large Irish employers actually run on. These
    # were added after the first full resolution run: the eight mainstream
    # platforms above covered the scale-ups but almost none of the insurers,
    # banks and professional-services firms, which is where the graduate
    # programmes are.
    (re.compile(r"https?://(?P<h>[\w.-]+\.icims\.com)", re.I),
     "icims", lambda m: m.group("h")),
    (re.compile(r"https?://(?P<h>[\w.-]+\.taleo\.net)", re.I),
     "taleo", lambda m: m.group("h")),
    (re.compile(r"https?://(?P<h>[\w.-]+\.avature\.net)", re.I),
     "avature", lambda m: m.group("h")),
    (re.compile(r"https?://(?P<h>[\w.-]+\.csod\.com)", re.I),
     "cornerstone", lambda m: m.group("h")),
    (re.compile(r"https?://(?P<h>[\w-]+\.teamtailor\.com)", re.I),
     "teamtailor", lambda m: m.group("h")),
    (re.compile(r"https?://(?:app|www)\.occupop\.com/(?:careers|jobs)/(?P<t>[\w-]+)", re.I),
     "occupop", lambda m: m.group("t")),
    (re.compile(r"https?://(?P<h>[\w-]+\.hirehive\.com)", re.I),
     "hirehive", lambda m: m.group("h")),
    (re.compile(r"https?://(?P<t>[\w-]+)\.eightfold\.ai", re.I),
     "eightfold", lambda m: m.group("t")),
    (re.compile(r"https?://jobs\.jobvite\.com/(?P<t>[\w-]+)", re.I),
     "jobvite", lambda m: m.group("t")),
    (re.compile(r"https?://(?P<t>[\w-]+)\.bamboohr\.com", re.I),
     "bamboohr", lambda m: m.group("t")),
    (re.compile(r"https?://ats\.rippling\.com/(?P<t>[\w-]+)", re.I),
     "rippling", lambda m: m.group("t")),
]

ORACLE_HOST_RE = re.compile(r"https?://(?P<host>[\w.-]*\.fa\.[\w.-]*oraclecloud\.com)", re.I)
ORACLE_SITE_RE = re.compile(r"(?:siteNumber[=:]\s*[\"']?|/sites/)(?P<site>CX_?[\w-]+)", re.I)
SF_HOST_RE = re.compile(r"https?://(?P<host>[\w.-]*successfactors\.(?:eu|com))", re.I)
SF_COMPANY_RE = re.compile(r"[?&]company=(?P<c>[\w-]+)", re.I)


SCRIPT_SRC_RE = re.compile(r'<script[^>]+src=["\']([^"\']+)["\']', re.I)
IFRAME_SRC_RE = re.compile(r'<iframe[^>]+src=["\']([^"\']+)["\']', re.I)
# A careers page's own bundle is the interesting one; the analytics and
# consent-banner scripts every site loads are not worth opening.
BORING_SCRIPT_RE = re.compile(
    r"(google|gtag|gtm|analytics|facebook|hotjar|cookie|consent|onetrust|"
    r"jquery|polyfill|recaptcha|cloudflare|newrelic|sentry|tiktok|linkedin\.com|"
    r"doubleclick|adobe|munchkin|hubspot)", re.I
)
MAX_EXTRA_DOCS = 8


def _linked_documents(final_url: str, html_text: str) -> str:
    """
    The page's own JavaScript and iframes, concatenated.

    A branded careers page very often contains no sign of its platform in the
    HTML at all - it loads a bundle that calls the ATS, or drops the whole
    board into an iframe. Seventy-one employers failed the first resolution
    run with "no readable job feed" for exactly this reason. Opening the few
    scripts that are plausibly the site's own, plus any iframes, is cheap and
    turns a lot of those into a clean platform match.
    """
    from urllib.parse import urljoin

    urls: list[str] = []
    for m in IFRAME_SRC_RE.finditer(html_text):
        urls.append(urljoin(final_url, m.group(1)))
    for m in SCRIPT_SRC_RE.finditer(html_text):
        src = m.group(1)
        if BORING_SCRIPT_RE.search(src):
            continue
        urls.append(urljoin(final_url, src))

    chunks: list[str] = []
    for u in urls[:MAX_EXTRA_DOCS]:
        try:
            _, body = _fetch_once(u)
        except Exception:  # noqa: BLE001
            continue
        chunks.append(body[:400_000])
    return "\n".join(chunks)


# The register records what platform each employer was believed to use. That
# hint is not trusted on its own - nothing enters the tracker unverified - but
# it is worth ordering the candidates by, so the likely platform is called
# first and an unlucky generic match cannot claim the company before it.
HINT_PLATFORMS = {
    "workday": "workday",
    "successfactors": "successfactors",
    "sap successfactors": "successfactors",
    "greenhouse": "greenhouse",
    "lever": "lever",
    "ashby": "ashby",
    "workable": "workable",
    "smartrecruiters": "smartrecruiters",
    "recruitee": "recruitee",
    "personio": "personio",
    "oracle": "oraclecloud",
    "taleo": "taleo",
    "icims": "icims",
    "avature": "avature",
    "cornerstone": "cornerstone",
    "csod": "cornerstone",
    "teamtailor": "teamtailor",
    "occupop": "occupop",
    "hirehive": "hirehive",
    "eightfold": "eightfold",
    "jobvite": "jobvite",
    "bamboohr": "bamboohr",
    "pinpoint": "pinpoint",
}


def hinted_platform(entry: dict) -> str:
    hint = (entry.get("ats_hint") or "").lower()
    for needle, platform in HINT_PLATFORMS.items():
        if needle in hint:
            return platform
    return ""


# A corporate careers page is very often pure marketing, with the actual job
# board one click away behind "Search our jobs" or "Current vacancies". That
# is the single commonest reason a page opens fine and yields nothing.
SEARCH_LINK_RE = re.compile(
    r'<a\b[^>]*\bhref=["\']([^"\'#][^"\']*)["\'][^>]*>(?P<label>(?:(?!</a>).){0,160})</a>',
    re.I | re.S,
)
SEARCH_WORDS_RE = re.compile(
    r"(search\s+(?:our\s+)?(?:jobs|roles|vacan|opportunit)|view\s+(?:all\s+)?(?:jobs|roles|vacan|"
    r"opening|opportunit)|current\s+(?:jobs|roles|vacan|opening)|browse\s+(?:jobs|roles)|"
    r"all\s+(?:jobs|vacancies|openings)|job\s+search|see\s+(?:all\s+)?(?:jobs|openings)|"
    r"live\s+roles|open\s+(?:roles|positions)|explore\s+(?:jobs|opportunit)|apply\s+now|"
    r"graduate\s+programme|early\s+careers)",
    re.I,
)
MAX_HOPS = 4


def _search_links(final_url: str, html_text: str) -> list[str]:
    """Links on a careers landing page that lead to the actual job list."""
    from urllib.parse import urljoin, urlparse as _up

    out: list[str] = []
    for m in SEARCH_LINK_RE.finditer(html_text):
        href = m.group(1)
        label = re.sub(r"<[^>]+>", " ", m.group("label"))
        if not SEARCH_WORDS_RE.search(label) and not SEARCH_WORDS_RE.search(href):
            continue
        target = urljoin(final_url, href)
        if not target.startswith("http") or target.rstrip("/") == final_url.rstrip("/"):
            continue
        if _up(target).scheme not in ("http", "https"):
            continue
        if target not in out:
            out.append(target)
    return out[:MAX_HOPS]


def detect(final_url: str, html_text: str) -> list[tuple[str, str]]:
    """
    Return candidate (platform, token) pairs, most likely first.
    Looks at the final URL first, then inside the page - a branded careers
    site very often embeds or calls the real platform.
    """
    candidates: list[tuple[str, str]] = []

    def add(platform: str, token: str) -> None:
        if token and (platform, token) not in candidates:
            candidates.append((platform, token))

    for haystack in (final_url, html_text):
        for pattern, platform, build in URL_PATTERNS:
            for m in pattern.finditer(haystack):
                try:
                    add(platform, build(m))
                except (IndexError, AttributeError):
                    continue
        # Oracle needs a host and a site number, which may be in different places
        host_m = ORACLE_HOST_RE.search(haystack)
        if host_m:
            site_m = ORACLE_SITE_RE.search(html_text) or ORACLE_SITE_RE.search(final_url)
            if site_m:
                add("oraclecloud", f"{host_m.group('host')}|{site_m.group('site')}")
        sf_m = SF_HOST_RE.search(haystack)
        if sf_m:
            co_m = SF_COMPANY_RE.search(haystack)
            if co_m:
                add("successfactors", f"{sf_m.group('host')}|{co_m.group('c')}")

    # Two last resorts, in order of cost. First: structured data published on
    # the careers page itself. Then: open the individual job pages linked from
    # it and read the structured data off those - slower, but it is what gets
    # the employers who built their own careers software.
    add("jsonld", final_url)
    # The site's own job endpoint, if its JavaScript names one.
    add("apiprobe", final_url)
    add("joblinks", final_url)
    add("rssfeed", final_url)
    # And if even that finds nothing, the site probably builds its list in the
    # browser. Its sitemap will still list the jobs, because Google needs them.
    add("sitemap", final_url)
    return candidates


# ---------------------------------------------------------------- resolution

def resolve_one(entry: dict) -> dict:
    """Resolve and VERIFY one company. Never raises."""
    name = entry["name"]
    url = entry.get("careers_url", "")
    result = {
        "name": name,
        "careers_url": url,
        "status": "unresolved",
        "reason": "",
        "ats": "",
        "token": "",
        "jobs_found": 0,
        "tried": [],
    }

    if not url:
        result["reason"] = "no careers URL in the register"
        return result

    try:
        final_url, html_text = fetch_page(url)
    except urllib.error.HTTPError as exc:
        result["reason"] = f"careers page returned HTTP {exc.code}"
        return result
    except Exception as exc:  # noqa: BLE001
        result["reason"] = f"could not open careers page: {type(exc).__name__}"
        return result

    result["final_url"] = final_url
    candidates = detect(final_url, html_text)
    generic = {"jsonld", "apiprobe", "joblinks", "rssfeed", "sitemap"}

    # If nothing but the generic fallbacks turned up, look inside the page's
    # own scripts and iframes before giving up on a real platform match.
    if all(p in generic for p, _ in candidates):
        extra = _linked_documents(final_url, html_text)
        if extra:
            deeper = detect(final_url, extra)
            specific = [c for c in deeper if c[0] not in generic]
            if specific:
                result["found_in_scripts"] = True
                candidates = specific + candidates

    # Still nothing specific? Follow the "search our jobs" link and try again
    # on the page it leads to.
    if all(p in generic for p, _ in candidates):
        for hop in _search_links(final_url, html_text):
            try:
                hop_url, hop_html = _fetch_once(hop)
            except Exception:  # noqa: BLE001
                continue
            hopped = detect(hop_url, hop_html)
            specific = [c for c in hopped if c[0] not in generic]
            if not specific:
                extra = _linked_documents(hop_url, hop_html)
                if extra:
                    specific = [c for c in detect(hop_url, extra) if c[0] not in generic]
            if specific:
                result["followed_link"] = hop
                candidates = specific + candidates
                break
            # Even without a platform match the deeper page is a better target
            # for the generic readers than the marketing page was.
            candidates = [(p, hop_url if t == final_url else t) for p, t in candidates]
            result["followed_link"] = hop
            break

    # Try the platform the register expected first, when it is on the list.
    hint = hinted_platform(entry)
    if hint:
        candidates.sort(key=lambda c: 0 if c[0] == hint else 1)

    for platform, token in candidates[:18]:
        fetcher = FETCHERS.get(platform)
        if not fetcher:
            continue
        result["tried"].append(f"{platform}:{token[:60]}")
        try:
            jobs = fetcher(token)
        except (FetchError, Exception):  # noqa: BLE001
            continue
        if jobs:
            result.update(
                status="resolved", ats=platform, token=token, jobs_found=len(jobs), reason=""
            )
            return result

    result["reason"] = (
        "page opened but no readable job feed behind it"
        if candidates else "no recognisable platform"
    )
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="resolve only companies whose name contains this")
    ap.add_argument("--limit", type=int, help="stop after this many companies")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--retry-failed", action="store_true",
                    help="only retry the ones that failed last time")
    ap.add_argument("--cap", type=int, default=0,
                    help="stop once companies.json holds this many feeds")
    ap.add_argument("--unresolved-only", action="store_true",
                    help="skip companies that already have a working feed")
    args = ap.parse_args()

    register = json.loads(REGISTER.read_text(encoding="utf-8"))

    # Work the best prospects first.
    #
    # There is no value in tracking every employer in the register: a company
    # only earns its place if it is likely to hire someone who needs a permit
    # AND likely to post the kind of role worth applying for. So the queue is
    # ordered by the register's own two judgements - how confident the
    # sponsorship evidence is, then how well the employer fits - and with
    # --cap the run stops as soon as the tracker is full enough. The employers
    # that never resolve are the long tail: obscure, rarely hiring, or hidden
    # behind a bot wall. Chasing them costs far more than they return.
    CONF_WEIGHT = {"documented": 3, "confirmed": 3, "likely": 2,
                   "possible": 1, "unverified": 1}

    def prospect_value(entry: dict) -> int:
        conf = (entry.get("sponsor_confidence") or "").lower()
        return CONF_WEIGHT.get(conf, 1) * 12 + int(entry.get("fit_rank") or 0)

    already: set[str] = set()
    if COMPANIES.exists():
        already = {c.get("name") for c in json.loads(COMPANIES.read_text(encoding="utf-8"))}
    if args.unresolved_only:
        # A company that resolved once is not resolved forever. Boards move,
        # tokens go stale, and the last scrape run recorded twenty-one feeds
        # returning 404 or 403 - those companies are in the tracker but
        # silently contributing nothing, which is worse than being absent.
        # So "already done" means "has a feed that still worked last run".
        broken: set[str] = set()
        stats_file = DATA / "stats.json"
        if stats_file.exists():
            try:
                stats = json.loads(stats_file.read_text(encoding="utf-8"))
                broken = {e.get("company") for e in stats.get("top_errors", [])
                          if e.get("company")}
            except (json.JSONDecodeError, OSError):
                pass
        skip = already - broken
        register = [e for e in register if e["name"] not in skip]
        print(f"{len(skip)} companies have a feed that still works; "
              f"{len(broken & already)} are broken and will be re-resolved; "
              f"{len(register)} to try in total")

    register.sort(key=prospect_value, reverse=True)

    if args.retry_failed and REPORT.exists():
        prev = json.loads(REPORT.read_text(encoding="utf-8"))
        failed = {r["name"] for r in prev.get("results", []) if r["status"] != "resolved"}
        register = [e for e in register if e["name"] in failed]
        print(f"retrying {len(register)} previously unresolved companies")

    if args.only:
        needle = args.only.lower()
        register = [e for e in register if needle in e["name"].lower()]
    if args.limit:
        register = register[: args.limit]

    print(f"resolving {len(register)} companies\n")

    results: list[dict] = []
    live_count = len(already)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(resolve_one, e): e for e in register}
        done = 0
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            done += 1
            if r["status"] == "resolved" and r["name"] not in already:
                live_count += 1
            if args.cap and live_count >= args.cap:
                print(f"\n  reached the {args.cap}-company cap - stopping here")
                for other in futures:
                    other.cancel()
                _write_outputs(results, partial=False)
                return 0
            if r["status"] == "resolved":
                print(f"  [{done:>3}/{len(register)}] OK   {r['name'][:38]:<38} "
                      f"{r['ats']}  ({r['jobs_found']} jobs)", flush=True)
            else:
                print(f"  [{done:>3}/{len(register)}] --   {r['name'][:38]:<38} "
                      f"{r['reason'][:44]}", flush=True)

            # Save every 20 companies. Opening hundreds of careers sites and
            # following their job links is slow enough to risk hitting the
            # workflow timeout, and losing a 90-minute run because the last
            # company hung would be maddening. Partial progress is still
            # progress, so it goes to disk as it is earned.
            if done % 20 == 0:
                _write_outputs(results, partial=True)
                print(f"       ...checkpointed {done} companies", flush=True)

    _write_outputs(results, partial=False)
    return 0


def _write_outputs(results: list[dict], partial: bool) -> int:
    resolved = [r for r in results if r["status"] == "resolved"]
    by_meta = {e["name"]: e for e in json.loads(REGISTER.read_text(encoding="utf-8"))}

    # Merge into companies.json, keeping anything already there.
    existing = []
    if COMPANIES.exists():
        existing = json.loads(COMPANIES.read_text(encoding="utf-8"))
    by_key = {(c.get("ats"), c.get("token")): c for c in existing}

    CONF_TIER = {"documented": 3, "likely": 2, "unverified": 1}

    for r in resolved:
        meta = by_meta.get(r["name"], {})
        record = {
            "name": r["name"],
            "ats": r["ats"],
            "token": r["token"],
            "website": r["careers_url"],
            "permits": 0,
            "sponsor_tier": CONF_TIER.get(meta.get("sponsor_confidence", ""), 1),
            "sponsor_confidence": meta.get("sponsor_confidence", "unverified"),
            "priority": meta.get("fit_rank", 0) >= 80,
            "fit_rank": meta.get("fit_rank", 0),
            "sector": meta.get("sector", ""),
            "entry_routes": meta.get("entry_routes", ""),
            "research_note": meta.get("research_note", ""),
            "jobs_at_discovery": r["jobs_found"],
        }
        key = (r["ats"], r["token"])
        if key in by_key:
            by_key[key].update(record)
        else:
            by_key[key] = record

    merged = sorted(by_key.values(), key=lambda c: (-c.get("fit_rank", 0), c["name"]))
    COMPANIES.write_text(json.dumps(merged, indent=1, ensure_ascii=False), encoding="utf-8")

    from collections import Counter
    report = {
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "attempted": len(results),
        "resolved": len(resolved),
        "unresolved": len(results) - len(resolved),
        "by_platform": dict(Counter(r["ats"] for r in resolved)),
        "failure_reasons": dict(Counter(r["reason"] for r in results if r["status"] != "resolved")),
        "results": sorted(results, key=lambda r: (r["status"] != "resolved", r["name"])),
    }
    REPORT.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")

    if partial:
        return 0

    print(f"\n{'='*66}")
    print(f"resolved   {len(resolved)} / {len(results)}")
    print(f"platforms  {report['by_platform']}")
    print(f"companies.json now holds {len(merged)} feeds")
    print("\nwhy the rest failed:")
    for reason, n in sorted(report["failure_reasons"].items(), key=lambda x: -x[1]):
        print(f"  {n:>4}  {reason}")
    print(f"\nfull per-company detail in {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
