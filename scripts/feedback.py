"""
Logs what Derin hid and applied to, sent from the site as a GitHub issue.

    ISSUE_BODY='```json [...] ```' python scripts/feedback.py

Writes data/feedback.json (the log the scraper reads to skip jobs she already
rejected) and data/feedback_report.md (which title words she rejects but never
applies to - suggestions for a human to turn into rules, never applied blindly).
"""
import json, os, re, sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
LOG, REPORT = DATA / "feedback.json", DATA / "feedback_report.md"
STOP = {"the", "and", "for", "with", "ireland", "dublin", "cork", "limited", "group", "job", "a", "of", "in", "to", "at", "-", "&"}


def parse(body: str) -> list[dict]:
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", body or "", re.S)
    items = json.loads(m.group(1)) if m else []
    out = []
    for i in items[:50]:
        if isinstance(i, dict) and i.get("kind") in ("hidden", "applied") and i.get("title"):
            out.append({k: str(i.get(k) or "")[:160] for k in ("kind", "id", "title", "company", "reason")})
    return out


def words(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", title.lower()) if w not in STOP}


def report(log: list[dict]) -> str:
    hid = [e for e in log if e["kind"] == "hidden"]
    app = [e for e in log if e["kind"] == "applied"]
    applied_words = set().union(*(words(e["title"]) for e in app)) if app else set()
    cnt = Counter(w for e in hid for w in words(e["title"]))
    sugg = [f"`{w}` ({n}x)" for w, n in cnt.most_common(30) if n >= 2 and w not in applied_words]
    reasons = Counter(e["reason"] or "no reason" for e in hid)
    return (f"# Feedback report\n\nHidden: {len(hid)}, applied: {len(app)}\n\n"
            f"Reasons: {dict(reasons)}\n\n"
            f"Title words hidden 2+ times and never applied to (candidate filter rules):\n"
            f"{', '.join(sugg) or 'none yet'}\n")


def main() -> int:
    new = parse(os.environ.get("ISSUE_BODY", ""))
    if not new:
        print("no usable feedback in the issue"); return 1
    log = json.loads(LOG.read_text(encoding="utf-8")) if LOG.exists() else []
    seen = {(e["kind"], e["id"]) for e in log}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    log += [dict(e, at=now) for e in new if (e["kind"], e["id"]) not in seen]
    LOG.write_text(json.dumps(log, indent=1, ensure_ascii=False), encoding="utf-8")
    REPORT.write_text(report(log), encoding="utf-8")
    print(f"logged {len(log)} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
