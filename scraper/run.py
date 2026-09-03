"""
The pipeline. Run with:  python -m scraper.run

Scanning strategy
-----------------
Hitting every company every 15 minutes would be both slow and rude. Instead:

  * PRIORITY companies (the big Dublin graduate employers and the heaviest
    work-permit sponsors) are checked on EVERY run - so genuinely new jobs at
    the places that matter show up within about 15 minutes.

  * Everyone else is split into shards. Each run takes one shard, so the whole
    register is swept roughly every few hours and completely every day.

Pass --full to force a complete sweep of every company in one go.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper import filters, normalise, score  # noqa: E402
from scraper.ats_clients import FETCHERS, FetchError  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE_DATA = ROOT / "site" / "data"

COMPANIES_FILE = DATA / "companies.json"
PROFILE_FILE = ROOT / "profile" / "derin.json"
JOBS_FILE = DATA / "jobs.json"
STATS_FILE = DATA / "stats.json"
HEALTH_FILE = DATA / "feed_health.json"

MAX_AGE_DAYS = 45

# Below this, a job is not a near miss - it is a different career.
#
# The rebuilt scoring caps anything whose title matches nothing on the CV, so
# the bottom of the board fills with software engineers, product designers and
# account executives that scored a point or two for being in Dublin at a
# sponsoring employer. Derin asked for the zeroes gone; the 1-9 band is the
# same thing wearing a different number, so the floor sits at 10. Nothing that
# scores in double figures is ever dropped, so every borderline case survives.
MIN_SCORE = 10
SHARD_COUNT = 8
WORKERS = {
    "greenhouse": 12,
    "lever": 12,
    "ashby": 5,
    "workable": 8,
    "smartrecruiters": 8,
    "recruitee": 8,
    "personio": 8,
    "workday": 4,
    "oraclecloud": 6,
    "pinpoint": 8,
    "successfactors": 5,
    "jsonld": 6,
    # joblinks opens many pages per company, so keep its own fan-out modest.
    "joblinks": 3,
    "sitemap": 3,
    "rssfeed": 6,
    "apiprobe": 5,
}
DEFAULT_WORKERS = 8


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def pick_shard(companies: list[dict], full: bool, health: dict | None = None) -> list[dict]:
    if full:
        return companies

    health = health or {}
    slot = int(time.time() // 900)

    live = [c for c in companies if not is_quarantined(c.get("name", ""), health, slot)]
    priority = [c for c in live if c.get("priority")]
    rest = [c for c in live if not c.get("priority")]

    # Rotate the shard by a 15-minute slot number so consecutive runs move on.
    shard = [c for i, c in enumerate(rest) if i % SHARD_COUNT == slot % SHARD_COUNT]
    return priority + shard


def fetch_company(company: dict) -> tuple[dict, list[dict], str]:
    """Fetch and normalise one company's board. Never raises."""
    ats = company.get("ats", "")
    token = company.get("token", "")
    name = company.get("name", token)

    fetcher = FETCHERS.get(ats)
    normaliser = normalise.NORMALISERS.get(ats)
    if not fetcher or not normaliser:
        return company, [], f"unknown ats '{ats}'"

    try:
        raw_jobs = fetcher(token)
    except FetchError as exc:
        return company, [], str(exc)
    except Exception as exc:  # noqa: BLE001
        return company, [], f"unexpected: {exc}"

    out = []
    for raw in raw_jobs:
        try:
            out.append(normaliser(raw, name))
        except Exception:  # noqa: BLE001 - one bad record must not kill the run
            continue
    return company, out, ""


# How many runs in a row a feed may fail before it stops being called every
# time. Six is about ninety minutes of trying - long enough to ride out a site
# being briefly down, short enough that a genuinely dead board is not hammered
# every quarter of an hour for weeks. Half a dozen of the register's feeds are
# permanent 404s: the company moved or closed its board, and no amount of
# retrying will bring it back. They are not dropped, only demoted - a
# quarantined feed is still retried hourly, and one success clears it.
QUARANTINE_AFTER = 6
QUARANTINE_RETRY_EVERY = 4          # runs, so roughly hourly


def load_health() -> dict:
    return load_json(HEALTH_FILE, {})


def is_quarantined(name: str, health: dict, slot: int) -> bool:
    fails = (health.get(name) or {}).get("fails", 0)
    if fails < QUARANTINE_AFTER:
        return False
    return slot % QUARANTINE_RETRY_EVERY != 0


def _is_a_real_posting(job: dict) -> bool:
    """
    Is this row an actual vacancy, or the shell of a page that needed JavaScript?

    A site that renders its jobs in the browser still returns HTML, and its
    <title> is the same string on every job - "JavaScript is disabled", "Job
    Details", the company name. Reading the title out of the URL slug rescues
    most of those at the point of fetching; anything that arrives here still
    carrying boilerplate could not be rescued and is not a job.
    """
    title = (job.get("title") or "").strip()
    if len(title) < 4:
        return False
    try:
        from scraper.ats_extra import _looks_like_a_title
    except ImportError:  # pragma: no cover
        return True
    return _looks_like_a_title(title)


def dedupe_key(job: dict) -> tuple:
    """One employer advertising one title in one place is one job."""
    title = re.sub(r"[^a-z0-9]+", " ", (job.get("title") or "").lower()).strip()
    place = re.sub(r"[^a-z0-9]+", " ", (job.get("location") or "").lower()).strip()
    return (job.get("company", ""), title, place)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="scan every company")
    ap.add_argument("--loose", action="store_true", help="keep senior roles too")
    args = ap.parse_args()

    companies = load_json(COMPANIES_FILE, [])
    profile = load_json(PROFILE_FILE, None)
    if not companies:
        print("ERROR: data/companies.json is empty. Run scripts/build_companies.py first.")
        return 1
    if not profile:
        print("ERROR: profile/derin.json missing.")
        return 1

    health = load_health()
    targets = pick_shard(companies, args.full, health)
    by_ats: dict[str, list[dict]] = {}
    for c in targets:
        by_ats.setdefault(c.get("ats", "?"), []).append(c)

    print(f"[{now_iso()}] scanning {len(targets)} of {len(companies)} companies")

    all_jobs: list[dict] = []
    errors: list[dict] = []
    scanned = 0

    for ats, group in by_ats.items():
        workers = WORKERS.get(ats, DEFAULT_WORKERS)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(fetch_company, c): c for c in group}
            for fut in as_completed(futures):
                company, jobs, err = fut.result()
                scanned += 1
                name = company.get("name", "")
                entry = health.setdefault(name, {"fails": 0, "last_ok": ""})
                if err:
                    errors.append({"company": name, "ats": ats, "error": err})
                    entry["fails"] = entry.get("fails", 0) + 1
                    entry["last_error"] = err[:120]
                else:
                    all_jobs.extend(jobs)
                    entry["fails"] = 0
                    entry["last_ok"] = now_iso()
                    entry.pop("last_error", None)

    print(f"  fetched {len(all_jobs)} raw postings, {len(errors)} boards failed")

    # ------------------------------------------------------- filter and score
    meta_by_company = {c["name"]: c for c in companies}
    kept: list[dict] = []
    drop_reasons: dict[str, int] = {}

    for job in all_jobs:
        meta = meta_by_company.get(job["company"], {})
        ok, reason = filters.keep(job, profile, strict_early=not args.loose,
                                  company_meta=meta)
        if not ok:
            drop_reasons[reason] = drop_reasons.get(reason, 0) + 1
            continue
        result = score.score_job(job, profile, meta)
        job.update(result)
        job["sponsor_tier"] = meta.get("sponsor_tier", 0)
        job["permits"] = meta.get("permits", 0)
        job["company_site"] = meta.get("website", "")
        kept.append(job)

    # -------------------------------------------------------- drop the no-hopers
    below = [j for j in kept if j.get("score", 0) < MIN_SCORE]
    if below:
        kept = [j for j in kept if j.get("score", 0) >= MIN_SCORE]
        print(f"  dropped {len(below)} jobs scoring under {MIN_SCORE} - wrong field, not near misses")

    # ------------------------------------------------------------- deduplicate
    #
    # The generic readers open one page per job link, and a site that lists the
    # same vacancy under several URLs - or that needs JavaScript, so every job
    # page returns the same shell - produces one row per URL. The first live
    # board carried 415 such rows out of 1,212: forty-five SSE jobs all called
    # "JavaScript is disabled". Reading titles out of the URL slug fixed most
    # of it at the source; this collapses whatever still slips through.
    #
    # Two postings are the same job if the same employer is advertising the
    # same title in the same place. The one kept is the best-scoring, which is
    # the one whose page gave up the most information.
    best: dict[tuple, dict] = {}
    for job in kept:
        key = dedupe_key(job)
        prev = best.get(key)
        if prev is None or job.get("score", 0) > prev.get("score", 0):
            best[key] = job
    if len(best) < len(kept):
        print(f"  collapsed {len(kept) - len(best)} duplicate postings")
    kept = list(best.values())

    print(f"  {len(kept)} jobs relevant to you after filtering")
    for reason, count in sorted(drop_reasons.items(), key=lambda x: -x[1]):
        print(f"    dropped {count:>5}  {reason}")

    # -------------------------------------------------------- merge with disk
    existing = {j["id"]: j for j in load_json(JOBS_FILE, [])}
    seen_now = set()
    new_count = 0

    for job in kept:
        seen_now.add(job["id"])
        prev = existing.get(job["id"])
        if prev:
            job["first_seen"] = prev.get("first_seen", now_iso())
            job["is_new"] = prev.get("is_new", False)
        else:
            job["first_seen"] = now_iso()
            job["is_new"] = True
            new_count += 1
        job["last_seen"] = now_iso()
        existing[job["id"]] = job

    # Age out anything we have not seen in a while.
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    fresh: list[dict] = []
    for job in existing.values():
        try:
            last = datetime.fromisoformat(job.get("last_seen", ""))
        except ValueError:
            last = datetime.now(timezone.utc)
        if last >= cutoff:
            # "New" badge lasts 24 hours
            try:
                first = datetime.fromisoformat(job.get("first_seen", ""))
                job["is_new"] = (datetime.now(timezone.utc) - first) < timedelta(hours=24)
            except ValueError:
                job["is_new"] = False
            fresh.append(job)

    # Re-score EVERY job on the board, not just the ones fetched this run.
    #
    # Because scanning is sharded, most jobs are not re-fetched on a given run.
    # The first version only scored what it had just fetched, so after a change
    # to the scoring model the board was a mix of new and stale numbers - the
    # foreign-language roles that should have dropped to zero were still sitting
    # near the top with their old scores. Scoring is pure local computation with
    # no network cost, so there is no reason not to redo all of it every time.
    # It also means any edit to profile/derin.json takes effect immediately
    # across the whole board rather than trickling in over a day.
    rescored = 0
    for job in fresh:
        meta = meta_by_company.get(job.get("company", ""), {})
        before = job.get("score")
        job.update(score.score_job(job, profile, meta))
        job["sponsor_tier"] = meta.get("sponsor_tier", 0)
        job["permits"] = meta.get("permits", 0)
        if before != job["score"]:
            rescored += 1
    if rescored:
        print(f"  re-scored {rescored} existing jobs against the current profile")

    # Clean the WHOLE board, not just what was fetched this run.
    #
    # Same lesson as the re-scoring above. Jobs live on the board for 45 days,
    # so a fix that only applies to freshly-fetched postings leaves the old bad
    # rows sitting there for six weeks. When the duplicate fix first shipped,
    # the board still carried 429 duplicates and 144 rows titled "JavaScript is
    # disabled" the next morning - all of them already on disk, none of them
    # re-fetched. Both passes are pure local computation, so both run over
    # everything, every time.
    before_clean = len(fresh)
    fresh = [j for j in fresh if _is_a_real_posting(j)]
    junked = before_clean - len(fresh)

    # The floor applies to the whole board, not only to this run's catch -
    # otherwise jobs that scored above it under the old model would sit there
    # for the full 45-day retention.
    before_floor = len(fresh)
    fresh = [j for j in fresh if j.get("score", 0) >= MIN_SCORE]
    floored = before_floor - len(fresh)
    if floored:
        print(f"  removed {floored} existing jobs now scoring under {MIN_SCORE}")

    board: dict[tuple, dict] = {}
    for job in fresh:
        key = dedupe_key(job)
        prev = board.get(key)
        if prev is None or job.get("score", 0) > prev.get("score", 0):
            board[key] = job
    collapsed = len(fresh) - len(board)
    fresh = list(board.values())
    if junked or collapsed:
        print(f"  cleaned the board: dropped {junked} unreadable, "
              f"collapsed {collapsed} duplicates")

    fresh.sort(key=lambda j: (-j.get("score", 0), j.get("first_seen", "")), reverse=False)
    fresh.sort(key=lambda j: -j.get("score", 0))

    DATA.mkdir(exist_ok=True)
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    JOBS_FILE.write_text(json.dumps(fresh, indent=1, ensure_ascii=False), encoding="utf-8")
    (SITE_DATA / "jobs.json").write_text(
        json.dumps(fresh, separators=(",", ":"), ensure_ascii=False), encoding="utf-8"
    )

    stats = {
        "last_run": now_iso(),
        "companies_total": len(companies),
        "companies_scanned": scanned,
        "boards_failed": len(errors),
        "raw_postings": len(all_jobs),
        "relevant_jobs": len(fresh),
        "min_score": MIN_SCORE,
        "new_this_run": new_count,
        "by_band": {},
        "top_errors": errors[:25],
    }
    for job in fresh:
        b = job.get("band", "weak")
        stats["by_band"][b] = stats["by_band"].get(b, 0) + 1

    quarantined = sorted(n for n, h in health.items() if h.get("fails", 0) >= QUARANTINE_AFTER)
    stats["quarantined_feeds"] = quarantined
    HEALTH_FILE.write_text(json.dumps(health, indent=1, ensure_ascii=False), encoding="utf-8")
    if quarantined:
        print(f"  {len(quarantined)} feeds quarantined (retried hourly, not every run): "
              f"{', '.join(quarantined[:5])}{' ...' if len(quarantined) > 5 else ''}")

    STATS_FILE.write_text(json.dumps(stats, indent=1), encoding="utf-8")
    (SITE_DATA / "stats.json").write_text(json.dumps(stats, separators=(",", ":")), encoding="utf-8")

    print(f"  {new_count} brand new | {len(fresh)} live on the site")
    print(f"  bands: {stats['by_band']}")

    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(f"### Scrape at {now_iso()}\n\n")
            fh.write(f"- Companies scanned: **{scanned}**\n")
            fh.write(f"- New jobs found: **{new_count}**\n")
            fh.write(f"- Total live jobs: **{len(fresh)}**\n")
            fh.write(f"- Bands: `{stats['by_band']}`\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
