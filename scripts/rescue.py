"""
One pass at the feeds the scraper has given up on.

A feed is quarantined after six consecutive failures. That is not a state to be
cleared by hand - one success clears it on its own - so this does not touch the
quarantine. It looks for a reader and token that actually work, writes those
into the tracked list, and lets the next scrape do the rest.

Three attempts per company, cheapest first, stopping at the first that returns
real jobs:

  1. The stored feed again. Six failures can still be six bad minutes.
  2. The company name as a board token, across the platforms whose tokens are
     guessable. Most of these employers are Irish tech firms on Greenhouse or
     Lever, and a board token drifts when a company renames or migrates.
  3. The full careers-page probe, which follows the site's own links and reads
     whichever page carries the most postings.

Run once. Whatever answers is kept, whatever does not is left alone.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scripts.probe_platforms import probe, try_reader  # noqa: E402
from scripts.build_companies import slug_variants  # noqa: E402
from scripts.adopt import full_read, jobs_returned, enough  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
COMPANIES = DATA / "companies.json"
REGISTER = DATA / "ireland_register.json"
HEALTH = DATA / "feed_health.json"
STATS = DATA / "stats.json"

# Platforms whose token can be guessed from a company name. Workday and Oracle
# need a tenant only the careers page reveals, so they arrive via the probe.
GUESSABLE = ["greenhouse", "lever", "workable", "smartrecruiters", "ashby",
             "recruitee", "pinpoint", "personio", "teamtailor", "occupop",
             "hirehive", "rippling", "bamboohr", "jobvite"]
MAX_SLUGS = 4          # best guesses only - this is one pass, not a search


def attempt(ats: str, token: str) -> tuple[bool, int, str]:
    with full_read():
        ok, note = try_reader(ats, token)
    found = jobs_returned(note) if ok else 0
    return (ok and enough(ats, found)), found, note


def rescue(name: str, entry: dict, careers_url: str) -> dict:
    r = {"name": name, "fixed": None, "tried": 0, "note": ""}

    def record(ats, token, why, found):
        r["fixed"] = {"ats": ats, "token": token, "jobs": found, "how": why}

    # 1. the stored feed, one more time
    ats, token = entry.get("ats", ""), entry.get("token", "")
    if ats and token:
        r["tried"] += 1
        ok, found, note = attempt(ats, token)
        r["note"] = note
        if ok:
            record(ats, token, "recovered on its own", found)
            return r

    # 2. the name as a board token
    for slug in slug_variants(name)[:MAX_SLUGS]:
        for platform in GUESSABLE:
            if platform == ats and slug == token:
                continue                       # already tried above
            r["tried"] += 1
            ok, found, _ = attempt(platform, slug)
            if ok:
                record(platform, slug, "found on a guessable board", found)
                return r

    # 3. the careers page itself
    if careers_url:
        p = probe(name, careers_url)
        r["tried"] += len(p.get("tried", []))
        if p["working"]:
            w = p["working"][0]
            ok, found, _ = attempt(w["ats"], w["token"])
            if ok:
                record(w["ats"], w["token"], "read off the careers page", found)
                return r
        elif not r["note"]:
            r["note"] = p.get("note", "nothing readable")
    return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    companies = json.loads(COMPANIES.read_text(encoding="utf-8"))
    by_name = {c.get("name", ""): c for c in companies}
    health = json.loads(HEALTH.read_text(encoding="utf-8")) if HEALTH.exists() else {}
    stats = json.loads(STATS.read_text(encoding="utf-8")) if STATS.exists() else {}

    # Whatever the last run called quarantined, plus anything the health file
    # says has failed its way there since.
    names = set(stats.get("quarantined_feeds", []))
    names |= {n for n, h in health.items() if (h.get("fails") or 0) >= 6}
    names = sorted(n for n in names if n in by_name)

    urls = {}
    if REGISTER.exists():
        for e in json.loads(REGISTER.read_text(encoding="utf-8")):
            nm = e.get("company") or e.get("name") or ""
            if e.get("careers_url"):
                urls[nm] = e["careers_url"]

    print(f"one pass at {len(names)} quarantined feeds\n", flush=True)
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(rescue, n, by_name[n],
                            urls.get(n) or by_name[n].get("website", "")): n
                for n in names}
        for f in as_completed(futs):
            r = f.result()
            results.append(r)
            if r["fixed"]:
                x = r["fixed"]
                print(f"  FIXED  {r['name'][:30]:<30} {x['ats']:<14} "
                      f"{x['token'][:34]:<34} {x['jobs']} jobs", flush=True)
            else:
                print(f"         {r['name'][:30]:<30} {r['note'][:52]}", flush=True)

    fixed = [r for r in results if r["fixed"]]
    print(f"\n{'='*74}\n  {len(fixed)} of {len(results)} recovered\n{'='*74}")
    for r in sorted(fixed, key=lambda x: -x["fixed"]["jobs"]):
        x = r["fixed"]
        print(f"  {r['name'][:28]:<28} {x['ats']:<14} {x['jobs']:>3} jobs   {x['how']}")
    if len(fixed) < len(results):
        print("\n  left alone:")
        for r in sorted(results, key=lambda x: x["name"]):
            if not r["fixed"]:
                print(f"  {r['name'][:28]:<28} {r['note'][:56]}")

    if args.dry_run or not fixed:
        print("\n  nothing written" if not fixed else "\n  dry run - nothing written")
        return 0

    for r in fixed:
        e = by_name[r["name"]]
        e["ats"], e["token"] = r["fixed"]["ats"], r["fixed"]["token"]
        e["jobs_at_discovery"] = r["fixed"]["jobs"]
        # One success clears quarantine anyway; zeroing the counter just means
        # the next scrape calls these in the normal rotation instead of hourly.
        if r["name"] in health:
            health[r["name"]]["fails"] = 0

    COMPANIES.write_text(json.dumps(companies, indent=1, ensure_ascii=False),
                         encoding="utf-8")
    HEALTH.write_text(json.dumps(health, indent=1, ensure_ascii=False),
                      encoding="utf-8")
    print(f"\n  wrote {len(fixed)} repaired feeds back into the tracked list")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
