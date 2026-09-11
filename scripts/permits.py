"""
Which of the tracked employers have actually sponsored someone.

Every job board guesses at this from words in the ad. Ireland publishes the
answer: the Department of Enterprise lists, by name, every company issued an
employment permit, refreshed monthly. Joining that list to the tracked
companies turns "likely sponsor" into "sponsored 14 people this year", which is
the difference between a hint and a fact.

The workbook's exact shape could not be confirmed before writing this - the
file is not reachable from where this was built - so nothing here assumes a
column layout. It finds the header row, works out which column holds company
names and which holds a count, prints what it decided, and refuses to write
anything if it cannot tell. The first run therefore reports the truth about the
file rather than acting on a guess about it.

    python scripts/permits.py --dry-run
    python scripts/permits.py
"""

from __future__ import annotations

import argparse
import io
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
COMPANIES = DATA / "companies.json"

YEARS = [2026, 2025]
URL_SHAPES = [
    "https://enterprise.gov.ie/en/publications/publication-files/"
    "employment-permits-issued-to-companies-{y}.xlsx",
    "https://enterprise.gov.ie/en/publications/publication-files/"
    "permits-issued-to-companies-{y}.xlsx",
]
LANDING = "https://enterprise.gov.ie/en/publications/employment-permit-statistics-{y}.html"

UA = {"User-Agent": "Mozilla/5.0 (compatible; ireland-job-tracker/1.0)"}

# A legal entity is not a brand. "GOOGLE IRELAND LIMITED" and "Google Ireland"
# are the same employer, and matching them means dropping the scaffolding both
# sides put around the name.
SUFFIX = re.compile(
    r"\b(limited|ltd|plc|dac|ulc|uc|teoranta|teo|unlimited company|holdings?|"
    r"group|international|ireland|eire|company|services|solutions|"
    r"technologies|technology|global|europe|emea|operations|management|"
    r"consulting|partners|associates|inc|corp|corporation|llc|llp|gmbh|bv|sa|"
    r"the)\b", re.I)
NOISE = re.compile(r"[^a-z0-9]+")


def key(name: str) -> str:
    n = SUFFIX.sub(" ", (name or "").lower())
    return NOISE.sub("", n)


def fetch(url: str) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
        # An HTML error page is a few KB; the real workbook is hundreds.
        if len(body) < 50_000 or not body.startswith(b"PK"):
            print(f"  {url.rsplit('/',1)[-1]}: not a workbook ({len(body)} bytes)")
            return None
        print(f"  got {url.rsplit('/',1)[-1]} ({len(body)//1024} KB)")
        return body
    except Exception as exc:  # noqa: BLE001
        print(f"  {url.rsplit('/',1)[-1]}: {type(exc).__name__} {str(exc)[:60]}")
        return None


def find_workbook() -> tuple[bytes, int] | tuple[None, None]:
    """Both known URL shapes, for both years, then the page they live on."""
    for y in YEARS:
        for shape in URL_SHAPES:
            if (body := fetch(shape.format(y=y))):
                return body, y
    for y in YEARS:
        try:
            req = urllib.request.Request(LANDING.format(y=y), headers=UA)
            with urllib.request.urlopen(req, timeout=45) as r:
                page = r.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            continue
        for href in re.findall(r'href="([^"]+\.xlsx)"', page, re.I):
            if "compan" not in href.lower():
                continue
            url = href if href.startswith("http") else "https://enterprise.gov.ie" + href
            if (body := fetch(url)):
                return body, y
    return None, None


def read_counts(body: bytes) -> dict[str, int]:
    """Company -> permits, working out the layout rather than assuming one."""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(body), read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = [[c for c in row] for row in ws.iter_rows(max_row=400, values_only=True)]
    print(f"  sheet {wb.sheetnames[0]!r}, {ws.max_row} rows x {ws.max_column} cols")
    for i, r in enumerate(rows[:6]):
        print(f"    row {i}: {[str(c)[:26] for c in r[:7]]}")

    # The header is the first row where some cell reads like a company column.
    head_at, name_col, count_col = None, None, None
    for i, r in enumerate(rows[:30]):
        for j, cell in enumerate(r):
            if cell and re.search(r"company|employer|organisation|name",
                                  str(cell), re.I):
                head_at, name_col = i, j
                break
        if head_at is not None:
            # "County" contains "count". Matching on a bare substring picked
            # the county column over the totals and gave every employer one
            # permit - the same mistake the Internship badge was making. Whole
            # words only, and the most explicit header wins rather than the
            # leftmost one.
            RANK = [r"\btotal\b", r"\bytd\b", r"\bpermits?\s+issued\b",
                    r"\bissued\b", r"\bpermits?\b", r"\bcount\b"]
            for pattern in RANK:
                for j, cell in enumerate(r):
                    if cell and re.search(pattern, str(cell), re.I):
                        count_col = j
                        break
                if count_col is not None:
                    break
            break

    if head_at is None:
        # No usable header. Fall back to the column carrying the most distinct
        # text, which on a company listing is the company column.
        body_rows = [r for r in rows if any(r)]
        if not body_rows:
            return {}
        width = max(len(r) for r in body_rows)
        best, seen = 0, -1
        for j in range(width):
            vals = {str(r[j]).strip() for r in body_rows
                    if j < len(r) and isinstance(r[j], str) and r[j].strip()}
            if len(vals) > seen:
                best, seen = j, len(vals)
        head_at, name_col = -1, best
        print(f"  no header found; using column {best} ({seen} distinct names)")

    print(f"  header row {head_at}, names in column {name_col}, "
          f"count in column {count_col if count_col is not None else 'none - will count rows'}")

    out: dict[str, int] = {}
    for row in ws.iter_rows(min_row=head_at + 2, values_only=True):
        if name_col >= len(row):
            continue
        name = row[name_col]
        if not isinstance(name, str) or not name.strip():
            continue
        n = 0
        if count_col is not None and count_col < len(row):
            v = row[count_col]
            if isinstance(v, (int, float)):
                n = int(v)
        k = key(name)
        if k:
            out[k] = out.get(k, 0) + max(n, 1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("looking for the permit register")
    body, year = find_workbook()
    if not body:
        print("\ncould not reach the register - nothing written")
        return 0

    counts = read_counts(body)
    print(f"\n  {len(counts)} employers in the {year} register")
    if len(counts) < 200:
        print("  that is far fewer than expected - refusing to act on it")
        return 0

    companies = json.loads(COMPANIES.read_text(encoding="utf-8"))
    hits, total = 0, 0
    for c in companies:
        k = key(c.get("name", ""))
        n = counts.get(k)
        if n is None:
            # A tracked name is often the parent of the registered entity, or
            # the other way round, so try containment before giving up.
            for rk, rn in counts.items():
                if len(k) >= 6 and (k in rk or rk in k):
                    n = rn
                    break
        if n:
            c["permits"] = n
            c["sponsor_tier"] = 3
            c["sponsor_confidence"] = "documented"
            hits += 1
            total += n

    print(f"  {hits} of {len(companies)} tracked employers appear in it, "
          f"{total} permits between them")
    top = sorted((c for c in companies if c.get("permits")),
                 key=lambda c: -c["permits"])[:12]
    for c in top:
        print(f"    {c['name'][:34]:<34} {c['permits']:>4}")

    if args.dry_run:
        print("\n  dry run - nothing written")
        return 0
    if not hits:
        print("\n  no matches - nothing written")
        return 0
    COMPANIES.write_text(json.dumps(companies, indent=1, ensure_ascii=False),
                         encoding="utf-8")
    print(f"\n  wrote permit counts for {hits} employers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
