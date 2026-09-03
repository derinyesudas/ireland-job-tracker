"""
Reconnaissance for the career sites that run on their own software.

About a third of the employers in the register don't use a recruitment platform
we can read generically - Teleperformance, Flutter, Aviva, Zurich, AXA, Bank of
Ireland and friends all built their own. Each of those needs a scraper written
by hand, and writing one means first knowing what the page is actually doing.

This does that legwork. For each site it reports:

  * whether the page publishes Google-for-Jobs structured data (if so, no
    custom scraper is needed at all - the generic reader handles it)
  * every API-looking URL the page's own JavaScript refers to, which is
    almost always where the job list really comes from
  * any embedded recruitment platform hiding behind the branding
  * iframes, RSS links, and sitemap entries that mention jobs
  * a guess at the framework, which narrows where the data lives

Run it in CI, read the report, then write each scraper against real evidence
instead of guesswork.

    python scripts/inspect_sites.py --proprietary-only
    python scripts/inspect_sites.py --only "Teleperformance"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scraper.ats_clients import BROWSER_HEADERS  # noqa: E402

DATA = ROOT / "data"
REGISTER = DATA / "ireland_register.json"
OUT = DATA / "site_inspection.json"

TIMEOUT = 25

KNOWN_PLATFORMS = [
    "greenhouse.io", "lever.co", "ashbyhq.com", "workable.com",
    "smartrecruiters.com", "recruitee.com", "personio.de",
    "myworkdayjobs.com", "oraclecloud.com", "successfactors",
    "pinpointhq.com", "icims.com", "taleo.net", "brassring.com",
    "avature.net", "jobvite.com", "teamtailor.com", "phenompeople.com",
    "eightfold.ai", "smashfly.com", "candidatemanager.net",
    "talent-community.com", "jobs2web.com", "cornerstoneondemand",
]

# URLs in the page source that smell like a job-list endpoint
API_HINT = re.compile(
    r'["\'](?P<u>(?:https?:)?//[^"\'\s<>]{6,220}?|/[^"\'\s<>]{4,200}?)["\']',
)
API_WORDS = re.compile(
    r"(job|vacan|career|opening|position|requisition|search|posting|opportunit)",
    re.I,
)
API_SHAPE = re.compile(r"(/api/|/rest/|\.json|/graphql|/services/|/v\d+/|/search)", re.I)

JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I
)
IFRAME_RE = re.compile(r'<iframe[^>]+src=["\']([^"\']+)["\']', re.I)
RSS_RE = re.compile(
    r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]+href=["\']([^"\']+)["\']',
    re.I,
)

FRAMEWORKS = {
    "Next.js": ["__NEXT_DATA__", "/_next/"],
    "Nuxt": ["__NUXT__", "/_nuxt/"],
    "React": ["react-dom", "data-reactroot", "__REACT"],
    "Angular": ["ng-version", "angular"],
    "Vue": ["__VUE__", "data-v-"],
    "WordPress": ["/wp-content/", "/wp-json/"],
    "Drupal": ["/sites/default/files", "Drupal.settings"],
    "Sitecore": ["/sitecore/", "sc_site"],
    "Adobe AEM": ["/etc.clientlibs/", "/content/dam/"],
}


def fetch(url: str) -> tuple[str, str, int]:
    req = urllib.request.Request(
        url,
        headers={**BROWSER_HEADERS, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.geturl(), resp.read(4_000_000).decode("utf-8", errors="replace"), resp.status


def has_jobposting_jsonld(html_text: str) -> int:
    """How many JobPosting blocks the page publishes. Non-zero means no custom work needed."""
    count = 0
    for block in JSONLD_RE.findall(html_text):
        if re.search(r'"@type"\s*:\s*"?\[?\s*"?JobPosting', block, re.I):
            count += len(re.findall(r'"@type"\s*:\s*"?\[?\s*"?JobPosting', block, re.I))
    return count


def candidate_endpoints(final_url: str, html_text: str) -> list[str]:
    base = f"{urlparse(final_url).scheme}://{urlparse(final_url).netloc}"
    found: dict[str, None] = {}
    for m in API_HINT.finditer(html_text):
        u = m.group("u")
        if not u or u.startswith("//fonts") or len(u) > 220:
            continue
        if not (API_WORDS.search(u) and API_SHAPE.search(u)):
            continue
        if re.search(r"\.(css|png|jpe?g|svg|gif|woff2?|ico|mp4)(\?|$)", u, re.I):
            continue
        full = urljoin(base, u.replace("//", "https://", 1) if u.startswith("//") else u)
        found.setdefault(full, None)
    return list(found)[:25]


def inspect_one(entry: dict) -> dict:
    name, url = entry["name"], entry.get("careers_url", "")
    out = {
        "name": name,
        "url": url,
        "fit_rank": entry.get("fit_rank", 0),
        "ats_hint": entry.get("ats_hint", ""),
        "ok": False,
        "verdict": "",
    }
    if not url:
        out["verdict"] = "no URL"
        return out

    try:
        final_url, html_text, status = fetch(url)
    except urllib.error.HTTPError as exc:
        out["verdict"] = f"HTTP {exc.code}"
        return out
    except Exception as exc:  # noqa: BLE001
        out["verdict"] = f"{type(exc).__name__}"
        return out

    out["ok"] = True
    out["final_url"] = final_url
    out["status"] = status
    out["page_bytes"] = len(html_text)

    jsonld = has_jobposting_jsonld(html_text)
    out["jsonld_jobpostings"] = jsonld

    platforms = sorted({p for p in KNOWN_PLATFORMS if p in html_text or p in final_url})
    out["platforms_referenced"] = platforms

    out["endpoints"] = candidate_endpoints(final_url, html_text)
    out["iframes"] = [
        urljoin(final_url, s) for s in IFRAME_RE.findall(html_text)[:8]
        if API_WORDS.search(s) or any(p in s for p in KNOWN_PLATFORMS)
    ]
    out["feeds"] = [urljoin(final_url, s) for s in RSS_RE.findall(html_text)[:5]]
    out["framework"] = [
        fw for fw, marks in FRAMEWORKS.items() if any(m in html_text for m in marks)
    ]
    out["has_next_data"] = "__NEXT_DATA__" in html_text

    # The headline: what should be done about this site
    if jsonld:
        out["verdict"] = f"SOLVED — publishes {jsonld} JobPosting blocks, generic reader handles it"
    elif platforms:
        out["verdict"] = f"PLATFORM BEHIND BRANDING — {', '.join(platforms[:3])}"
    elif out["endpoints"]:
        out["verdict"] = f"CUSTOM — {len(out['endpoints'])} candidate endpoints to try"
    elif out["feeds"]:
        out["verdict"] = "CUSTOM — has an RSS/Atom feed worth reading"
    elif out["has_next_data"]:
        out["verdict"] = "CUSTOM — Next.js, jobs likely inside __NEXT_DATA__"
    else:
        out["verdict"] = "HARD — nothing obvious in the HTML, probably renders client-side"
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="only companies whose name contains this")
    ap.add_argument("--proprietary-only", action="store_true",
                    help="skip companies already on a platform we read generically")
    ap.add_argument("--min-fit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=5)
    args = ap.parse_args()

    register = json.loads(REGISTER.read_text(encoding="utf-8"))

    generic = {"Workday", "Greenhouse", "Lever", "Workable", "Pinpoint",
               "SAP SuccessFactors", "Oracle Cloud Recruiting"}
    if args.proprietary_only:
        register = [e for e in register if e.get("ats_hint") not in generic]
    if args.only:
        register = [e for e in register if args.only.lower() in e["name"].lower()]
    register = [e for e in register if e.get("fit_rank", 0) >= args.min_fit]
    register.sort(key=lambda e: -e.get("fit_rank", 0))

    print(f"inspecting {len(register)} career sites\n")

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(inspect_one, e) for e in register]
        for i, fut in enumerate(as_completed(futures), 1):
            r = fut.result()
            results.append(r)
            print(f"  [{i:>3}] {r['name'][:38]:<38} {r['verdict'][:70]}")

    results.sort(key=lambda r: -r.get("fit_rank", 0))
    OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")

    from collections import Counter
    kinds = Counter(r["verdict"].split("—")[0].strip() for r in results)
    print(f"\n{'='*66}")
    for k, v in kinds.most_common():
        print(f"  {v:>4}  {k}")
    print(f"\nwritten to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
