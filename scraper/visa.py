"""
What a job ad says about sponsorship, and whether its pay clears the permit bar.

Three states, not two. Most Irish ads say nothing at all about sponsorship, and
silence is not a refusal - treating it as one would hide most of the board. So
an ad is only marked as refusing when it says so, only marked as offering when
it says so, and left alone otherwise.

"Must have the right to work in Ireland" is deliberately NOT a refusal. Anyone
on Stamp 1G, 4, 5 or 6 already has that right, so the phrase excludes nobody
holding one - and a graduate on 1G reading it as a closed door would skip jobs
that are open to them.
"""

from __future__ import annotations

import re

# From 1 March 2026. Critical Skills is the route a master's graduate in an
# eligible occupation takes; General is the fallback and a materially worse
# one, so knowing which a salary reaches changes whether a role is worth the
# fifteen-minute application form.
CSEP_THRESHOLD = 40904
CSEP_RECENT_GRAD = 36848      # qualification obtained in the previous 12 months
GEP_THRESHOLD = 36605

_REFUSES = [
    r"no\s+sponsorship\s+(?:is\s+)?available",
    r"sponsorship\s+is\s+not\s+available",
    r"not\s+(?:be\s+)?(?:in\s+a\s+position\s+to\s+)?(?:offer|provide)\s+"
    r"(?:visa\s+)?sponsorship",
    r"(?:unable|not\s+able)\s+to\s+(?:offer|provide|support)\s+"
    r"(?:visa\s+)?sponsorship",
    r"requiring\s+(?:employment\s+)?sponsorship\s+or\s+a\s+work\s+permit\s+"
    r"are\s+not\s+eligible",
    r"unable\s+to\s+consider\s+candidates\s+who\s+do\s+not\s+have\s+full\s+"
    r"authoris\w+\s+to\s+work",
    r"available\s+for\s+work\s+visa\s+sponsorship\s*:?\s*no\b",
    r"work\s+permits?,?\s+visas?\s+or\s+sponsorships?\s+already\s+in\s+place",
    r"must\s+currently\s+reside\s+in\s+ireland",
    r"we\s+do\s+not\s+sponsor",
]
_OFFERS = [
    r"available\s+for\s+work\s+visa\s+sponsorship\s*:?\s*yes\b",
    r"(?:visa\s+)?sponsorship\s+(?:is\s+|may\s+be\s+)?available",
    r"(?:we\s+)?(?:do\s+|can\s+)?sponsor\s+visas",
    r"critical\s+skills\s+employment\s+permit",
    r"we\s+(?:offer|provide)\s+(?:visa\s+)?sponsorship",
    r"relocation\s+(?:package|support|assistance)\s+(?:is\s+)?(?:available|offered)",
]

REFUSES_RE = re.compile("|".join(_REFUSES), re.I)
OFFERS_RE = re.compile("|".join(_OFFERS), re.I)

# Salary in an Irish ad: "€45,000", "€45k", "45,000 - 55,000", "€21.50 per hour".
_MONEY = re.compile(
    r"(?:€|eur\s?)\s?(\d{1,3}(?:,\d{3})+|\d{2,3}(?:\.\d+)?\s?k\b|\d{4,6})",
    re.I)
_HOURLY = re.compile(r"(?:€|eur\s?)\s?(\d{1,3}(?:\.\d{1,2})?)\s*(?:per\s+hour|p\.?h\b|/\s?hr|an\s+hour)", re.I)


def _to_number(raw: str) -> int | None:
    raw = raw.strip().lower().replace(",", "")
    try:
        if raw.endswith("k"):
            return int(float(raw[:-1].strip()) * 1000)
        return int(float(raw))
    except ValueError:
        return None


def salary(text: str) -> int | None:
    """The top annual figure the ad advertises, or None if it advertises none.

    The top of a range is used because that is the number a permit is judged
    against, and an ad quoting 35,000-45,000 can clear a threshold its floor
    does not.
    """
    if not text:
        return None
    found = [n for m in _MONEY.findall(text[:6000])
             if (n := _to_number(m)) and 15000 <= n <= 400000]
    if found:
        return max(found)
    # An hourly rate is still a salary; a 39-hour week is the Irish norm.
    hourly = [n for m in _HOURLY.findall(text[:6000])
              if (n := _to_number(m)) and 10 <= n <= 200]
    if hourly:
        return int(max(hourly) * 39 * 52)
    return None


def assess(text: str) -> dict:
    """Everything the ad itself tells us about whether he could take the job."""
    text = text or ""
    out: dict = {"sponsorship": None, "salary_eur": None, "permit_route": None}

    if REFUSES_RE.search(text):
        out["sponsorship"] = "refuses"
    elif OFFERS_RE.search(text):
        out["sponsorship"] = "offers"

    pay = salary(text)
    if pay:
        out["salary_eur"] = pay
        if pay >= CSEP_THRESHOLD:
            out["permit_route"] = "critical_skills"
        elif pay >= GEP_THRESHOLD:
            out["permit_route"] = "general"
        else:
            out["permit_route"] = "below_threshold"
    return out
