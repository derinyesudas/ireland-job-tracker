"""
Decide which jobs are worth showing at all.

Three gates, in order:
  1. Is it in Ireland (or remote-from-Ireland)?
  2. Is it early-career, or at least not obviously senior?
  3. Is it a type of engagement Derin will actually take?

Anything failing gate 1 or 3 is dropped entirely. Gate 2 is soft - borderline
jobs stay in but the score pushes them down, because an occasional "1-2 years
preferred" role is still worth a look.
"""

from __future__ import annotations

import re

IRISH_PLACES = {
    "ireland", "republic of ireland", "eire", "éire",
    "dublin", "cork", "galway", "limerick", "waterford", "kilkenny",
    "sligo", "athlone", "drogheda", "dundalk", "wexford", "tralee",
    "letterkenny", "navan", "bray", "maynooth", "naas", "swords",
    "blanchardstown", "sandyford", "leopardstown", "citywest",
    "ballsbridge", "carlow", "cavan", "clonmel", "ennis", "kildare",
    "killarney", "mullingar", "portlaoise", "roscommon", "shannon",
    "tullamore", "westport", "wicklow", "leixlip", "clonskeagh",
    "grand canal", "docklands", "sandymount", "tallaght", "lucan",
    "dun laoghaire", "dún laoghaire", "santry", "clondalkin", "finglas",
    "little island", "mahon", "model farm road", "ballincollig",
}

# "Dublin" and "Limerick" also exist in the United States. If any of these
# appear alongside, it is not our Dublin.
NOT_IRELAND = {
    ", ca", ", oh", ", ga", ", pa", ", tx", ", nh", ", va", ", in,",
    "california", "ohio", "georgia", "pennsylvania", "texas",
    "new hampshire", "virginia", "united states", "usa", "u.s.",
    "canada", "australia", "new zealand", "india", "singapore",
    "philippines", "south africa", "united kingdom", "england",
    "scotland", "wales", "london", "manchester", "belfast",
}

# Used ONLY when judging a job that states no location at all. It must contain
# nothing short or ambiguous: the first version reused the US-state list, whose
# ", in," entry became "in" and matched the word "join", quietly binning every
# job whose ad said "join our team".
CLEARLY_ABROAD = {
    "united states", "united kingdom", "new zealand", "south africa",
    "california", "pennsylvania", "new hampshire", "philippines",
    "netherlands", "switzerland", "singapore", "australia", "germany",
    "portugal", "malaysia", "scotland", "romania", "belgium", "hungary",
    "canada", "england", "belfast", "london", "poland", "france", "spain",
    "india", "manila", "mumbai", "bengaluru", "bangalore", "warsaw",
    "amsterdam", "berlin", "madrid", "lisbon", "krakow", "budapest",
    # Added after the evaluation put three UK food-plant roles on an Irish
    # board: the slug carried the location, nothing was reading it.
    "wales", "yorkshire", "lancashire", "merseyside", "midlands", "essex",
    "kent", "surrey", "hampshire", "devon", "cornwall", "norfolk", "suffolk",
    "cumbria", "durham", "sussex", "wiltshire", "somerset", "cheshire",
}

REMOTE_OK = {
    "remote - ireland", "remote ireland", "ireland - remote",
    "remote (ireland)", "emea remote", "remote emea", "remote - emea",
    "europe remote", "remote europe", "remote - europe",
}

SENIOR_KILL = re.compile(
    r"\b(senior|principal|staff|lead|head of|director|vice president|"
    r"\bvp\b|chief|architect|manager)\b",
    re.I,
)

# A "manager" title is only a kill if it is not an entry-level scheme
GRAD_RESCUE = re.compile(
    r"\b(graduate|intern|internship|placement|trainee|apprentice|"
    r"entry[- ]level|junior|early careers?)\b",
    re.I,
)


# Read in the TITLE as well, because a careers site that publishes no location
# usually puts it in the job's address instead, and the sitemap reader turns
# that address into the title: "Junior Data Analyst Inplant Mexico City Mexico",
# "Hr Advisor 27797 En Us". Word boundaries, and no Midlands - Ireland has one.
TITLE_ABROAD = re.compile(
    r"\b(" + "|".join(sorted((re.escape(p) for p in CLEARLY_ABROAD if p != "midlands"),
                             key=len, reverse=True)) +
    r"|mexico|colombia|medell[ií]n|monterrey|bogot[aá]|cartagena|tegucigalpa|honduras|"
    r"brazil|argentina|chile|peru|costa\s+rica|guatemala|messico|isle\s+of\s+man|"
    r"jersey|guernsey|"
    r"en[\s-]us|en[\s-]gb)\b", re.I)

# Northern Ireland is the United Kingdom. A Republic of Ireland work permit
# does not cover it, so "Northern Ireland, Ireland" is not an Irish job here.
NORTHERN_IRELAND = re.compile(
    r"\b(northern\s+ireland|county\s+(down|antrim|armagh|tyrone|fermanagh|"
    r"londonderry)|co\.?\s+(down|antrim|armagh|tyrone|fermanagh)|newry|"
    r"belfast|lisburn|londonderry|derry|craigavon|portadown|enniskillen|omagh|"
    r"coleraine|ballymena|bangor,?\s+co)\b", re.I)


def clearly_not_ireland(job: dict) -> bool:
    """The two cases the location check used to wave through. Pure, cheap, and
    safe to run over the whole board, not only this run's catch."""
    loc = (job.get("location") or "").lower().strip()
    title = (job.get("title") or "").lower()
    # Only when nowhere in the Republic is named too - a role advertised for
    # "Dublin, Ireland; Belfast, County Antrim" is still a Dublin job.
    if NORTHERN_IRELAND.search(f"{loc} {title}") and not any(
            p in loc for p in IRISH_PLACES if "ireland" not in p and p != "eire"):
        return True
    if not loc:
        return bool(TITLE_ABROAD.search(title))
    # A stated location abroad with nowhere Irish in it. "Administrative
    # Assistant - Ireland" based in Lisbon supports Ireland from Portugal.
    return bool(TITLE_ABROAD.search(loc)) and not any(p in loc for p in IRISH_PLACES)


def is_in_ireland(job: dict, employer_is_irish: bool = False) -> bool:
    loc = (job.get("location") or "").lower().strip()
    text = f"{loc} {(job.get('title') or '').lower()}"

    if clearly_not_ireland(job):
        return False

    if not loc:
        desc = (job.get("description") or "").lower()[:1500]
        if any(p in desc for p in ("ireland", "dublin", "cork")):
            return True
        # Some career sites publish no location at all on the job page. When
        # the employer itself came from the Irish register, silently dropping
        # those would lose real Dublin jobs - so give them the benefit of the
        # doubt. If the ad names somewhere clearly abroad, the check below
        # still catches it.
        if employer_is_irish:
            return not any(c in desc for c in CLEARLY_ABROAD)
        return False

    if any(r in loc for r in REMOTE_OK):
        return True

    hit = any(p in text for p in IRISH_PLACES)
    if not hit:
        return False

    # Guard against Dublin, California and friends
    if "ireland" not in loc and any(bad in loc for bad in NOT_IRELAND):
        return False

    return True


def is_acceptable_engagement(job: dict, profile: dict) -> bool:
    text = f"{job.get('title','')} {job.get('employment_type','')} {job.get('description','')[:2000]}".lower()
    return not any(term in text for term in profile["hard_exclusions"]["terms"])


def is_early_career(job: dict) -> bool:
    """Soft gate - True if it looks early-career or at least not clearly senior."""
    title = job.get("title") or ""
    if GRAD_RESCUE.search(title):
        return True
    if SENIOR_KILL.search(title):
        return False
    return True


def keep(job: dict, profile: dict, strict_early: bool = True,
         company_meta: dict | None = None) -> tuple[bool, str]:
    """Return (keep?, reason_if_dropped)."""
    company_meta = company_meta or {}
    # Everything in ireland_register.json was hand-researched as an employer
    # hiring in Ireland, so a missing location on one of their ads is a gap in
    # their careers page, not evidence the job is elsewhere.
    employer_is_irish = bool(company_meta.get("fit_rank") or company_meta.get("sector"))

    if not job.get("title") or not job.get("url"):
        return False, "incomplete record"
    if not is_in_ireland(job, employer_is_irish=employer_is_irish):
        return False, "not in Ireland"
    if not is_acceptable_engagement(job, profile):
        return False, "freelance/contract - not wanted"
    if strict_early and not is_early_career(job):
        return False, "senior role"
    return True, ""
