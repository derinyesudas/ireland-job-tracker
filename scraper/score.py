"""
Compatibility scoring: how well does this job fit Derin, out of 100?

The score is deliberately transparent. Every job carries a breakdown showing
exactly which points it won and lost, so the number can be trusted rather than
taken on faith - and so the weights can be tuned by editing profile/derin.json
rather than by editing code.

Scale used on the site (recalibrated when the model was rebuilt around the CV -
the stricter scoring runs lower, so the old thresholds would have left the top
band permanently empty):
    70-100  Excellent - apply today
    58-69   Strong - worth a tailored CV
    45-57   Decent - apply if you have time
    32-44   Stretch - read it before spending effort
    0-31    Weak - probably skip
"""

from __future__ import annotations

import re

MAX_SCORE = 100

YEARS_RE = re.compile(
    r"(\d+)\s*(?:\+|\s*-\s*\d+)?\s*(?:\+)?\s*years?(?:\s+of)?\s+(?:relevant\s+|proven\s+|demonstrable\s+)?experience",
    re.I,
)


def _haystack(job: dict) -> str:
    return " ".join(
        [
            job.get("title", ""),
            job.get("description", ""),
            job.get("department", ""),
            job.get("employment_type", ""),
        ]
    ).lower()


# Short single words must match as WORDS, not as substrings. Without this,
# "rta" matches inside "important", "intern" matches inside "international",
# and a sales role starts looking like a graduate analyst post. This was a real
# bug caught on the first live run - the top three results were roles requiring
# fluent French, German and Hebrew.
_WORD_CACHE: dict[str, re.Pattern] = {}


def _matches(text: str, term: str) -> bool:
    t = term.lower().strip()
    if not t:
        return False
    # Multi-word phrases are unambiguous - plain containment is fine.
    if " " in t or "-" in t or "/" in t:
        return t in text
    pat = _WORD_CACHE.get(t)
    if pat is None:
        pat = re.compile(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])")
        _WORD_CACHE[t] = pat
    return bool(pat.search(text))


def _count_hits(text: str, terms: list[str]) -> list[str]:
    return [t for t in terms if _matches(text, t)]


# ---------------------------------------------------------------------------
# Languages Derin does not speak.
#
# A job that needs fluent French is no use to him whatever else it offers, and
# employers phrase that requirement a dozen different ways: "French Fluency",
# "fluent in German", "native Dutch speaker", "Spanish-speaking", "bilingual
# Italian". Listing every phrasing by hand is how the first version missed
# them. This builds the combinations instead.
# ---------------------------------------------------------------------------

OTHER_LANGUAGES = [
    "french", "german", "spanish", "italian", "dutch", "portuguese", "polish",
    "swedish", "danish", "norwegian", "finnish", "czech", "slovak", "hungarian",
    "romanian", "bulgarian", "greek", "turkish", "arabic", "hebrew", "russian",
    "ukrainian", "japanese", "korean", "mandarin", "cantonese", "chinese",
    "thai", "vietnamese", "indonesian", "flemish", "catalan", "croatian",
    "serbian", "slovenian", "lithuanian", "latvian", "estonian", "icelandic",
    "irish", "gaeilge", "welsh", "afrikaans", "farsi", "persian", "tagalog",
]

_LANG_ALT = "|".join(OTHER_LANGUAGES)
LANGUAGE_REQUIRED_RE = re.compile(
    # "French fluency", "French speaking", "French speaker", "French language"
    rf"(?<![a-z])({_LANG_ALT})\s*[-–]?\s*"
    rf"(fluency|fluent|speaking|speaker|speakers|native|bilingual|language\s+skills)"
    r"|"
    # "fluent in French", "native level German", "proficiency in Dutch"
    rf"(fluency|fluent|native|proficiency|proficient|bilingual)\s+"
    rf"(in\s+|level\s+|speaker\s+of\s+)?({_LANG_ALT})(?![a-z])",
    re.I,
)


# The forms above all name the requirement explicitly. Job TITLES do not: the
# commonest Irish shape is "Service Desk Analyst with Italian", which the
# evaluation caught scoring 71 - a role he cannot do sitting near the top of
# the board. These patterns are deliberately title-only: "with Italian" in the
# body of an ad can be innocuous, but in a title it is the whole point of the
# posting.
LANGUAGE_IN_TITLE_RE = re.compile(
    rf"(?:\bwith\s+|\bin\s+|[-–—]\s*|\(\s*)({_LANG_ALT})\b"
    rf"|\b({_LANG_ALT})\s*[-–—/]\s*(?:speaking|speaker|language)",
    re.I,
)


# "Payroll Associate 2027", "Audit Associate Galway 2027" - professional
# services firms name the intake year in the title. That is an early-careers
# signal as clear as the word "graduate".
INTAKE_YEAR_RE = re.compile(r"(?<!\d)(202[5-9]|203[0-9])(?!\d)")


SENIORITY_MARKER_RE = re.compile(
    r"(?<![a-z])(senior|snr|lead|leader|principal|head\s+of|director|manager|"
    r"managing|supervisor|expert|chief|vp\b|svp\b|evp\b|avp\b|vice\s+president|"
    r"staff\s|architect|partner|controller|product\s+owner|"
    r"\bii\b|\biii\b|\biv\b)",
    re.I,
)


def _has_seniority_marker(title: str) -> bool:
    return bool(SENIORITY_MARKER_RE.search(title or ""))


def _requires_other_language(job: dict) -> str:
    """Return the offending phrase, or '' if none. Title is weighted heavily."""
    title = job.get("title", "") or ""
    m = LANGUAGE_REQUIRED_RE.search(title) or LANGUAGE_IN_TITLE_RE.search(title)
    if m:
        return m.group(0).strip()
    body = (job.get("description", "") or "")[:4000]
    m = LANGUAGE_REQUIRED_RE.search(body)
    return m.group(0).strip() if m else ""


def score_job(job: dict, profile: dict, company_meta: dict | None = None) -> dict:
    """Return {'score': int, 'band': str, 'breakdown': [...]}"""
    company_meta = company_meta or {}
    text = _haystack(job)
    title = (job.get("title") or "").lower()
    location = (job.get("location") or "").lower()

    points = 0
    breakdown: list[dict] = []

    def add(label: str, pts: int, note: str = "") -> None:
        nonlocal points
        points += pts
        breakdown.append({"label": label, "points": pts, "note": note})

    # ---------------------------------------------------------------- 1. role
    fams = profile["target_role_families"]
    evidence = profile.get("evidence", {})
    grad_hits = _count_hits(text, profile["graduate_programme_terms"])
    role_note = ""

    # Is this advert an entry route in its own right? Used both to credit the
    # level and to decide whether the no-match ceiling should apply at all.
    STRONG_ENTRY = ("graduate programme", "graduate program", "graduate scheme",
                    "graduate trainee", "internship", "intern", "trainee programme",
                    "placement", "apprentice", "early careers", "entry level",
                    "entry-level", "summer internship", "analyst programme",
                    "analyst program", "rotational programme", "development programme")
    is_entry_route = (any(h in STRONG_ENTRY for h in grad_hits)
                      or bool(INTAKE_YEAR_RE.search(title))) and not _has_seniority_marker(title)

    # Role families are matched against the TITLE and nothing else.
    #
    # The previous version fell back to scanning the whole advert and awarded
    # eight points when any target word appeared anywhere in it. That is what
    # made the board feel loose: "reporting" and "operations" turn up in the
    # boilerplate of almost every job ever posted, so a warehouse role could
    # collect role points for describing its own shift reporting. A job is what
    # its title says it is, so that fallback is gone.
    role_family = ""
    role_weight = 0
    for fam_name, fam in fams.items():
        hits = _count_hits(title, fam["terms"])
        if not hits:
            continue
        weight = fam["weight"]
        note = f"'{hits[0]}' — {evidence.get(fam['evidence'], '')}"
        # Some families are only open to him through an entry route. A finance
        # degree with no finance experience qualifies him for a graduate
        # scheme, not for the same title at experienced level.
        if fam.get("requires_early_career") and not grad_hits:
            weight = weight // 2
            note += " (halved: open to you through graduate routes, and this ad names none)"
        if weight > role_weight:
            role_family, role_weight, role_note = fam_name, weight, note
    if role_family:
        add("Role fit", role_weight, role_note)
    else:
        add("Role fit", 0,
            "This job title is not one your CV qualifies you for — capped accordingly")

    # ------------------------------------------------------- 2. early careers
    if grad_hits:
        pts = 20 if any(
            h in ("graduate programme", "graduate program", "graduate scheme",
                  "internship", "intern", "entry level", "entry-level", "junior")
            for h in grad_hits
        ) else 12
        add("Early careers", pts, f"Flagged as {grad_hits[0]}")
    elif (yr := INTAKE_YEAR_RE.search(title)) and not _has_seniority_marker(title):
        add("Early careers", 16,
            f"Titled for the {yr.group(0)} intake — a graduate entry route")
    elif role_family and not _has_seniority_marker(title):
        # No graduate wording - but plenty of genuinely entry-level operations
        # roles never use any. "Claims Handler", "Customer Care Advisor",
        # "Policy Administrator" are exactly his TCS background and exactly his
        # level, and the evaluation found them scoring in the thirties while
        # the labeller rated them a strong fit. Where the TITLE is already one
        # of his target roles and carries no seniority marker, the absence of
        # graduate wording is not evidence that the role is senior.
        add("Early careers", 9,
            "No graduate wording, but an entry-level title with no seniority markers")
    else:
        add("Early careers", 0, "No graduate/junior/internship signal")

    # -------------------------------------------------------------- 3. tools
    #
    # Only the tools on his CV count, and they count by how solid the evidence
    # is: Excel and Power BI he has certified and built with, R and Python he
    # has used on coursework. The operational vocabulary he picked up at TCS -
    # KPIs, SLAs, data accuracy - is real but appears in nearly every advert
    # written, so it is capped at a handful of points and can never carry a job
    # on its own. That cap is the difference between "this job wants what I can
    # do" and "this advert happens to contain words from my CV".
    tools = profile["tools_he_has"]
    core = _count_hits(text, tools["core"])
    taught = _count_hits(text, tools["taught"])
    certified = _count_hits(text, tools["certified"])
    tool_pts = min(18, len(core) * 5 + len(taught) * 3 + len(certified) * 1)
    if tool_pts:
        shown = ", ".join(sorted(set(core + taught))[:4]) or ", ".join(sorted(set(certified))[:3])
        add("Tools you have", tool_pts, f"Wants {shown} — all on your CV")
    else:
        add("Tools you have", 0, "Names none of the tools you actually use")

    ops = profile["operational_vocabulary"]
    ops_hits = _count_hits(text, ops["terms"])
    if ops_hits:
        add("How you already work", min(ops["cap"], len(ops_hits)),
            f"Mentions {', '.join(sorted(set(ops_hits))[:3])} — the way you worked at TCS")

    # -------------------------------------------------------------- 4. domain
    #
    # The domain has to be the job's own field, not a word that drifted into a
    # long advert. Title first, then the employer's sector as recorded in the
    # register. A logistics role that mentions insurance once is not an
    # insurance job, and the old version gave it the full ten points for saying
    # the word.
    dom = profile["domain_bonus"]
    sector = (company_meta.get("sector") or "").lower()
    dom_in_title = _count_hits(title, dom["terms"])
    dom_in_sector = _count_hits(sector, dom["terms"])
    if dom_in_title:
        add("Industry fit", dom["bonus"],
            f"{dom_in_title[0].title()} is in the job title — your TCS year was insurance operations")
    elif dom_in_sector:
        add("Industry fit", dom["bonus"] - 2,
            f"{company_meta.get('sector','')} employer — the sector your experience is in")
    else:
        # A domain mentioned repeatedly in the body is weak evidence, not none.
        body_hits = _count_hits(text, dom["terms"])
        repeated = [t for t in body_hits if text.count(t) >= 3]
        if repeated:
            add("Industry fit", 4, f"Advert is built around {repeated[0]}")
        else:
            add("Industry fit", 0, "Not in insurance, finance or operations")

    # ------------------------------------------------------------- 5. location
    loc_pts = 0
    loc_note = "Location unclear"
    for key, val in profile["locations"].items():
        if key in location or key in text:
            if val > loc_pts:
                loc_pts, loc_note = val, f"{key.title()}"
    add("Location", loc_pts, loc_note)

    # ---------------------------------------------------------- 6. sponsorship
    # Two independent sources of evidence, and they are not equally strong.
    # A permit count is a government record of permits actually granted.
    # A confidence level is Derin's own desk research. The note says which,
    # so the number can always be traced back to what it rests on.
    permits = company_meta.get("permits", 0)
    confidence = company_meta.get("sponsor_confidence", "")

    if permits >= 25:
        add("Sponsorship", 10, f"Issued {permits} employment permits this year — very active sponsor")
    elif permits >= 5:
        add("Sponsorship", 8, f"Issued {permits} employment permits this year")
    elif permits >= 1:
        add("Sponsorship", 6, f"Issued {permits} employment permit(s) this year")
    elif confidence == "documented":
        add("Sponsorship", 7, "Documented sponsor in your employer research")
    elif confidence == "likely":
        add("Sponsorship", 4, "Likely sponsor — flagged in your research, not yet in the permit register")
    elif confidence == "unverified":
        add("Sponsorship", 1, "Sponsorship not established either way")
    else:
        add("Sponsorship", 0, "Not on this year's employment permit register")

    # ------------------------------------------------- 6b. researched routes
    # Where the register recorded the specific way in at a company ("Graduate
    # programme", "Administrator Intern"), reward a job that matches it.
    routes = (company_meta.get("entry_routes") or "").lower()
    if routes:
        route_terms = [
            t.strip() for t in re.split(r"[,;/]", routes)
            if 3 < len(t.strip()) < 40
        ]
        matched = [t for t in route_terms if t in text]
        if matched:
            add("Known entry route", 6,
                f"Matches an entry route you identified at this employer: {matched[0]}")

    # ------------------------------------------------------------- 7. bonuses
    lang = profile["language_gated_bonus"]
    lang_hits = _count_hits(text, lang["terms"])
    if lang_hits:
        add("Language edge", lang["bonus"], f"Mentions {lang_hits[0]} - your Hindi/Malayalam is a real advantage here")

    shift = profile["shift_work_bonus"]
    if _count_hits(text, shift["terms"]):
        add("Shift work", shift["bonus"], "Shift pattern - you already did a year of permanent nights")

    # ----------------------------------------------------------- 8. penalties
    blocked = profile["skills_he_does_not_have"]
    hard = _count_hits(text, blocked["hard_block"])
    if hard:
        add("Needs skills you don't have", -20,
            f"Requires {hard[0]} — you have never done this and must not claim it")
    soft = _count_hits(text, blocked["soft_block"])
    if soft:
        # SQL is the one that matters. It is on a great many analyst adverts,
        # he does not have it, and he has been explicit that it must never be
        # claimed - so an advert built on it is a worse fit than the title
        # alone suggests, and should say so plainly on the card.
        pen = -8 if len(soft) == 1 else -15
        add("Technical gap", pen,
            f"Wants {', '.join(sorted(set(soft))[:3])} — not on your CV")

    dq_phrase = _requires_other_language(job)
    if dq_phrase:
        add(
            "Language you don't speak",
            -profile["languages_that_disqualify"]["penalty"],
            f"Requires {dq_phrase} — you don't speak it, so this is a dead end",
        )

    sen = profile["seniority_penalties"]["senior_titles"]
    sen_hits = _count_hits(title, sen["terms"])
    if sen_hits:
        add("Too senior", -sen["penalty"], f"Title contains '{sen_hits[0].strip()}'")

    years_found = [int(m) for m in YEARS_RE.findall(job.get("description", ""))]
    if years_found:
        yrs = max(years_found)
        table = profile["seniority_penalties"]["experience_years"]
        if yrs <= 1:
            pen = table["0-1"]
        elif yrs == 2:
            pen = table["2"]
        elif yrs == 3:
            pen = table["3"]
        elif yrs == 4:
            pen = table["4"]
        else:
            pen = table["5+"]
        if pen:
            add("Experience required", -pen, f"Asks for {yrs}+ years")

    # A job whose title matches nothing on his CV is capped, however many
    # familiar words its advert contains. Without this the loose components -
    # location, sponsorship, a domain word - can push a role he is not
    # qualified for into the fifties purely on context. The cap keeps those
    # jobs visible and honest about what they are.
    ceiling = MAX_SCORE
    if not role_family and not is_entry_route:
        ceiling = profile.get("no_title_match_ceiling", 35)
        if points > ceiling:
            breakdown.append({
                "label": "Capped",
                "points": ceiling - points,
                "note": f"Held at {ceiling}: nothing in this title matches your background",
            })
            points = ceiling

    final = max(0, min(MAX_SCORE, points))

    # Bands recalibrated when the scoring was rebuilt around the CV.
    #
    # The old thresholds (85 / 70 / 55 / 40) were set against a looser model
    # that handed out points for any familiar word, so scores ran high. Under
    # the stricter model a job has to actually match his background to climb,
    # and the very top of a real board sits around 80 - so on the old scale
    # "excellent" would have been permanently empty and the labels would have
    # meant nothing. These thresholds are set from the live distribution: about
    # 1% of the board is excellent, 6% strong or better, 8% decent or better.
    if final >= 70:
        band = "excellent"
    elif final >= 58:
        band = "strong"
    elif final >= 45:
        band = "decent"
    elif final >= 32:
        band = "stretch"
    else:
        band = "weak"

    return {"score": final, "band": band, "breakdown": breakdown}
