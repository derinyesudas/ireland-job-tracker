"""
Adds the employers the probe can actually read to the tracked list.

The probe answers "can this employer be read, and how". This takes that answer
and makes it permanent, so the work of finding a feed is paid once and the
tracker keeps collecting from it forever.

Nothing is taken on trust. Every candidate - whether the probe found it or it
was handed in by name - is called again here, and only lands in companies.json
if that call returns real jobs. A single result is not enough: a sitemap that
answers with one page is usually a blog post that happens to live under the
careers path, which is exactly how Howden's "Unlocking opportunities in climate
risk" nearly became a vacancy.

The candidate list is never written to disk in the clear. Manual additions come
in as an argument at run time and leave no trace in the repository.

  python scripts/adopt.py --dry-run
  python scripts/adopt.py
  python scripts/adopt.py --extra '[{"name":"X","ats":"workday","token":"a|wd3|b"}]'
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scripts.probe_platforms import probe, try_reader  # noqa: E402
import scraper.ats_extra as _ae  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
COMPANIES = DATA / "companies.json"
REGISTER = DATA / "ireland_register.json"

# A named board is its own evidence. When a reader talks to a real applicant
# tracking system, that system belongs to the employer and whatever it returns
# is that employer's vacancies - one job is a real job, and a company with one
# opening should be on the board.
#
# The guessing readers are different. They read whatever HTML a careers page
# happens to serve, so a single result is far more likely to be a blog post
# under the careers path than a vacancy: Howden's was "Unlocking opportunities
# in climate risk". Those still have to show three.
NAMED_BOARDS = {
    "ashby", "avature", "bamboohr", "cornerstone", "eightfold", "greenhouse",
    "hirehive", "icims", "jobvite", "lever", "occupop", "oraclecloud",
    "personio", "phenom", "pinpoint", "recruitee", "rippling", "smartrecruiters",
    "successfactors", "talentbrew", "taleo", "teamtailor", "workable", "workday",
}
GUESSWORK = {"joblinks", "jsonld", "sitemap", "apiprobe", "rssfeed"}


def enough(ats: str, found: int) -> bool:
    return found >= (3 if ats in GUESSWORK else 1)


# The sweep proves a feed cheaply, on five jobs. That number is far too small to
# decide by: PM Group came back "only 2 jobs" and was dropped, when the truth was
# that only two of the five links it was allowed to open happened to parse. So a
# candidate that survives the sweep is read again properly, and it is that second
# count that decides. Only the handful that pass pay for the full read.
FULL_READ = 45

CONF_TIER = {"documented": 3, "likely": 2, "unverified": 1}


@contextlib.contextmanager
def full_read():
    """Lift the probe's five-job ceiling for one call, then put it back."""
    was = (_ae.MAX_JOB_PAGES, _ae.MAX_SITEMAP_JOBS, _ae.MAX_CHILD_SITEMAPS)
    _ae.MAX_JOB_PAGES = _ae.MAX_SITEMAP_JOBS = FULL_READ
    _ae.MAX_CHILD_SITEMAPS = 6
    try:
        yield
    finally:
        (_ae.MAX_JOB_PAGES, _ae.MAX_SITEMAP_JOBS, _ae.MAX_CHILD_SITEMAPS) = was


def jobs_returned(note: str) -> int:
    """try_reader reports '21 jobs, e.g. ...' - read the count back out."""
    try:
        return int(note.split(" ", 1)[0])
    except (ValueError, IndexError):
        return 0


def record(name: str, ats: str, token: str, url: str, found: int,
           meta: dict) -> dict:
    """The same shape the careers-site resolver writes, so a company adopted
    here is indistinguishable from one resolved there."""
    return {
        "name": name,
        "ats": ats,
        "token": token,
        "website": url,
        "permits": 0,
        "sponsor_tier": CONF_TIER.get(meta.get("sponsor_confidence", ""), 1),
        "sponsor_confidence": meta.get("sponsor_confidence", "unverified"),
        "priority": meta.get("fit_rank", 0) >= 80,
        "fit_rank": meta.get("fit_rank", 0),
        "sector": meta.get("sector", ""),
        "entry_routes": meta.get("entry_routes", ""),
        "research_note": meta.get("research_note", ""),
        "jobs_at_discovery": found,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="limit the sweep to matching names")
    ap.add_argument("--extra", default="",
                    help='JSON list of {name, ats, token} to verify and adopt')
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--dry-run", action="store_true",
                    help="say what would be adopted, write nothing")
    args = ap.parse_args()

    register = json.loads(REGISTER.read_text(encoding="utf-8"))
    by_meta = {e["name"]: e for e in register}
    existing = json.loads(COMPANIES.read_text(encoding="utf-8")) if COMPANIES.exists() else []
    by_key = {(c.get("ats"), c.get("token")): c for c in existing}
    tracked_names = {c.get("name", "").lower() for c in existing}
    before = len(by_key)

    adopted: list[tuple[str, str, str, int]] = []
    rejected: list[tuple[str, str]] = []

    # 1. anything handed in by name, verified before it is believed
    for e in json.loads(args.extra) if args.extra.strip() else []:
        with full_read():
            ok, note = try_reader(e["ats"], e["token"])
        found = jobs_returned(note) if ok else 0
        if not ok or not enough(e["ats"], found):
            rejected.append((e["name"], note if not ok else f"only {found} jobs"))
            continue
        key = (e["ats"], e["token"])
        r = record(e["name"], e["ats"], e["token"], e.get("url", ""), found,
                   by_meta.get(e["name"], {}))
        by_key[key] = {**by_key.get(key, {}), **r}
        adopted.append((e["name"], e["ats"], e["token"], found))

    # 2. the register sweep
    from concurrent.futures import ThreadPoolExecutor, as_completed
    todo = [(row.get("company") or row.get("name") or "", row["careers_url"])
            for row in register
            if row.get("careers_url")
            and (row.get("company") or row.get("name") or "").lower() not in tracked_names
            and (not args.only or args.only.lower() in
                 (row.get("company") or row.get("name") or "").lower())]

    print(f"checking {len(todo)} untracked employers\n", flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for fut in as_completed({pool.submit(probe, n, u): n for n, u in todo}):
            r = fut.result()
            if not r["working"]:
                continue
            w = r["working"][0]
            with full_read():
                ok, note = try_reader(w["ats"], w["token"])
            found = jobs_returned(note) if ok else 0
            if not ok or not enough(w["ats"], found):
                rejected.append((r["name"],
                                 note if not ok else f"only {found} job(s) - not evidence"))
                continue
            key = (w["ats"], w["token"])
            if key in by_key:
                # Two employers, one feed. Irish Life Group and Irish Life
                # Health are the same 21 jobs at the same address, and the
                # board should carry that once.
                rejected.append((r["name"], f"same feed as {by_key[key]['name']}"))
                continue
            by_key[key] = record(r["name"], w["ats"], w["token"],
                                 r.get("best_url", r["url"]), found,
                                 by_meta.get(r["name"], {}))
            adopted.append((r["name"], w["ats"], w["token"], found))
            print(f"  ADOPT  {r['name'][:38]:<38} {w['ats']:<12} {found} jobs", flush=True)

    print(f"\n{'='*72}")
    for n, a, t, f in sorted(adopted, key=lambda x: -x[3]):
        print(f"  {n[:34]:<34} {a:<14} {t[:40]:<40} {f} jobs")
    if rejected:
        print("\n  not adopted:")
        for n, why in sorted(rejected):
            print(f"  {n[:34]:<34} {why[:60]}")
    print(f"{'='*72}")
    print(f"  {before} tracked before, {len(by_key)} after "
          f"(+{len(by_key) - before})")

    if args.dry_run:
        print("\n  dry run - nothing written")
        return 0
    if len(by_key) == before:
        print("\n  nothing new to write")
        return 0

    merged = sorted(by_key.values(), key=lambda c: (-c.get("fit_rank", 0), c["name"]))
    COMPANIES.write_text(json.dumps(merged, indent=1, ensure_ascii=False),
                         encoding="utf-8")
    print(f"\n  companies.json now holds {len(merged)} feeds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
