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
import re
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
# Hand-picked employers to add, kept in the clear so the list can be
# reviewed in the repository. Only names and public careers addresses -
# nothing about the person doing the searching.
CANDIDATES = DATA / "candidates.json"

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


_NAME_NOISE = {"the", "and", "of", "group", "ireland", "irish", "plc", "ltd", "limited",
               "dac", "se", "sa", "nv", "clg", "company", "inc", "llc", "eu", "europe",
               "european", "international", "holdings", "dublin"}


def _name_words(name: str) -> set[str]:
    return {w for w in re.findall(r"[\w&]+", name.lower())
            if w not in _NAME_NOISE and len(w) > 1}


def already_tracked(name: str, existing: list[dict]) -> str | None:
    """The tracked employer this name already refers to, if any. Every
    distinctive word must appear: "Citi" is "Citi Ireland", but "Bank of
    America" is not "Bank of Ireland". A bracketed aside is ignored."""
    want = _name_words(name.split("(")[0])
    if not want:
        return None
    for c in existing:
        have = _name_words(c.get("name", ""))
        # ...and they must make up at least half of the tracked name, or
        # "Brown & Brown" would be Brown Brothers Harriman.
        if want <= have and len(want) * 2 >= len(have):
            return c.get("name")
    return None


def irish_jobs(ats: str, token: str, name: str) -> int:
    """How many of a feed's jobs are in Ireland - the only count that matters
    when deciding between two feeds for one employer. -1 if it will not read."""
    from scraper.ats_clients import FETCHERS
    from scraper import filters, normalise
    fn = FETCHERS.get(ats)
    if not fn:
        return -1
    try:
        with full_read():
            raw = fn(token) or []
    except Exception:  # noqa: BLE001
        return -1
    norm = normalise.NORMALISERS.get(ats)
    n = 0
    for r in raw:
        try:
            job = norm(r, name) if norm else r
        except Exception:  # noqa: BLE001
            continue
        if filters.is_in_ireland(job, employer_is_irish=True):
            n += 1
    return n


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
    ap.add_argument("--drop", default="",
                    help="remove tracked employers by name (comma separated) "
                         "and do nothing else")
    args = ap.parse_args()

    # Removing a feed has to be as easy as adding one. IDA Ireland was adopted
    # on four sitemap results that turned out to be its own landing pages -
    # "making-a-difference", "wellbeing", "diversity-inclusion" - because a long
    # slug is not the same thing as a vacancy. Nothing that gets onto the board
    # by mistake should need a person to hand-edit an encrypted file.
    if args.drop.strip():
        wanted = {n.strip().lower() for n in args.drop.split(",") if n.strip()}
        current = json.loads(COMPANIES.read_text(encoding="utf-8"))
        keep = [c for c in current if c.get("name", "").lower() not in wanted]
        gone = [c["name"] for c in current if c.get("name", "").lower() in wanted]
        print(f"dropping {len(gone)}: {', '.join(gone) or 'nothing matched'}")
        for miss in wanted - {g.lower() for g in gone}:
            print(f"  not tracked: {miss}")
        if gone and not args.dry_run:
            COMPANIES.write_text(json.dumps(keep, indent=1, ensure_ascii=False),
                                 encoding="utf-8")
            print(f"companies.json now holds {len(keep)} feeds")
        return 0

    register = json.loads(REGISTER.read_text(encoding="utf-8"))
    by_meta = {e["name"]: e for e in register}
    existing = json.loads(COMPANIES.read_text(encoding="utf-8")) if COMPANIES.exists() else []
    by_key = {(c.get("ats"), c.get("token")): c for c in existing}
    tracked_names = {c.get("name", "").lower() for c in existing}
    before = len(by_key)

    adopted: list[tuple[str, str, str, int]] = []
    rejected: list[tuple[str, str]] = []

    # 1. anything handed in by name, verified before it is believed.
    #
    # Two shapes are accepted, and an entry may carry both. {name, ats, token}
    # says exactly which feed to read. {name, url} says only where the careers
    # page is, and the probe is asked to find the feed behind it. When both are
    # given the named feed is tried first and the page is the fallback, so one
    # wrong guess about a tenant does not lose the employer.
    def adopt_one(e: dict) -> str | None:
        """Verify and record one feed. None on success, else the reason."""
        key = (e["ats"], e["token"])
        if key in by_key:
            return f"same feed as {by_key[key]['name']}"
        with full_read():
            ok, note = try_reader(e["ats"], e["token"])
        found = jobs_returned(note) if ok else 0
        if not ok or not enough(e["ats"], found):
            return note if not ok else f"only {found} jobs"
        r = record(e["name"], e["ats"], e["token"], e.get("url", ""), found,
                   by_meta.get(e["name"], {}))
        # A named addition replaces whatever feed that company had, rather than
        # sitting beside it. Davy is the case: the address in the register now
        # 404s, so the company was tracked and silently returning nothing while
        # its real board carried twenty-three Dublin jobs. Adding the working
        # feed without removing the dead one leaves the company on the list
        # twice, one of them broken.
        for k in [k for k, c in by_key.items()
                  if c.get("name", "").lower() == e["name"].lower() and k != key]:
            print(f"  replacing {e['name']}'s old feed {k[0]}/{k[1][:40]}")
            del by_key[k]
        by_key[key] = {**by_key.get(key, {}), **r}
        adopted.append((e["name"], e["ats"], e["token"], found))
        print(f"  ADOPT  {e['name'][:38]:<38} {e['ats']:<14} {found} jobs", flush=True)
        return None

    handed = json.loads(args.extra) if args.extra.strip() else []
    upgrades: list[tuple[dict, str]] = []
    if CANDIDATES.exists():
        for e in json.loads(CANDIDATES.read_text(encoding="utf-8")):
            # {"name": X, "drop": true} takes a feed off the board. Goodbody is
            # the case: its probe landed on AIB's whole job search, so AIB's
            # vacancies were turning up under Goodbody's name.
            if e.get("drop"):
                gone = [k for k, c in by_key.items()
                        if c.get("name", "").lower() == e["name"].lower()]
                for k in gone:
                    del by_key[k]
                print(f"  DROP   {e['name'][:38]:<38} {len(gone)} feed(s) removed")
                continue
            hit = already_tracked(e.get("name", ""), existing)
            if hit and e.get("fix"):
                # {"fix": true} asks for the tracked feed to be checked against
                # this one - for employers that are tracked but never show a
                # job. Without it, a tracked employer is simply left alone.
                upgrades.append((e, hit))
            elif hit:
                rejected.append((e["name"], f"already tracked as {hit}"))
            else:
                handed.append(e)

    to_probe: list[dict] = []
    for e in handed:
        if e.get("ats") and e.get("token"):
            why = adopt_one(e)
            if why is None:
                continue
            if e.get("url"):
                to_probe.append({**{k: v for k, v in e.items()
                                    if k not in ("ats", "token")}, "_first": why})
            else:
                rejected.append((e["name"], why))
        elif e.get("url"):
            to_probe.append(e)
        else:
            rejected.append((e.get("name", "?"), "no ats/token and no url"))

    # The probing is the slow part and every candidate is independent, so the
    # ones that need it are all probed at once before anything is verified.
    if to_probe:
        from concurrent.futures import ThreadPoolExecutor as _TPE
        print(f"\nfinding the feed behind {len(to_probe)} careers pages\n", flush=True)
        with _TPE(max_workers=args.workers) as pool:
            probed = list(pool.map(lambda e: probe(e["name"], e["url"]), to_probe))
        for e, r in zip(to_probe, probed):
            if not r["working"]:
                rejected.append((e["name"], e.get("_first") or r.get("note")
                                 or "no readable feed found"))
                continue
            w = r["working"][0]
            why = adopt_one({**e, "ats": w["ats"], "token": w["token"],
                             "url": r.get("best_url") or e["url"]})
            if why:
                rejected.append((e["name"], why))

    # 1b. employers already on the board. The candidate list is a wish list,
    # and a working feed is never swapped for a guess - but a tracked feed that
    # finds no Irish jobs while the candidate finds some is a dead feed, and is
    # replaced. The tracked name and its permit record are kept.
    for e, hit in upgrades:
        old_keys = [k for k, c in by_key.items() if c.get("name") == hit]
        old_n = max((irish_jobs(k[0], k[1], hit) for k in old_keys), default=-1)
        cand = None
        if e.get("ats") and e.get("token"):
            cand = (e["ats"], e["token"], e.get("url", ""))
        if (cand is None or irish_jobs(cand[0], cand[1], hit) <= 0) and e.get("url"):
            r = probe(e["name"], e["url"])
            if r["working"]:
                w = r["working"][0]
                cand = (w["ats"], w["token"], r.get("best_url") or e["url"])
        new_n = irish_jobs(cand[0], cand[1], hit) if cand else -1
        if cand and new_n > max(old_n, 0) and (cand[0], cand[1]) not in by_key:
            keep = by_key[old_keys[0]] if old_keys else {}
            for k in old_keys:
                del by_key[k]
            by_key[(cand[0], cand[1])] = {
                **keep, **record(hit, cand[0], cand[1], cand[2], new_n, by_meta.get(hit, {})),
                **{f: keep[f] for f in ("permits", "sponsor_tier", "sponsor_confidence",
                                        "priority", "fit_rank", "sector", "entry_routes",
                                        "research_note") if f in keep},
            }
            adopted.append((f"{hit} (fixed)", cand[0], cand[1], new_n))
            print(f"  FIXED  {hit[:38]:<38} {max(old_n, 0)} -> {new_n} Irish jobs", flush=True)
        else:
            rejected.append((e["name"], f"already tracked as {hit} "
                                        f"({max(old_n, 0)} Irish jobs; candidate {max(new_n, 0)})"))

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
    # Count is the wrong test. Replacing a company's dead feed with a working
    # one leaves the total unchanged, and this guard then threw the repair away.
    if not adopted:
        print("\n  nothing new to write")
        return 0

    merged = sorted(by_key.values(), key=lambda c: (-c.get("fit_rank", 0), c["name"]))
    COMPANIES.write_text(json.dumps(merged, indent=1, ensure_ascii=False),
                         encoding="utf-8")
    print(f"\n  companies.json now holds {len(merged)} feeds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
