"""
Decide whether Derin could actually apply for a job, by reading the advert.

Four questions, asked of the title and the description:

  1. Is this a discipline she has a background in?   -> field
  2. Does it demand a credential she does not hold?  -> qualification
  3. Does it demand more years than she has?         -> experience
  4. Does it demand a language she does not speak?   -> language

Anything that fails is NOT deleted. It is marked blocked, with the exact
sentence that blocked it, so a wrong rule is visible instead of silent.

Two lessons are baked in here. Match whole words, never fragments - "intern"
lives inside "international" and "count" inside "County", and both cost a day.
And a credential named in an advert is only a barrier when the advert says it
is required; when the advert says it will pay for it, that is the opposite of
a barrier and the job scores higher, not lower.
"""

from __future__ import annotations
import re

# ---------------------------------------------------------------- disciplines

IN_FIELD = re.compile(r"""\b(
    analyst|analytics|analysis|
    data\s+analyst|business\s+intelligence|\bbi\b|\bmi\b|reporting|report\s+developer|
    finance|financial|accounts?|accountant|accounting|accountancy|payroll|treasury|
    pension[s]?|retirement|annuit\w+|insurance|claims?|underwrit\w+|policy\s+admin\w*|
    bank|banking|investment\s+(operations|administration|support)|fund\s+(admin\w+|account\w+)|
    custody|transfer\s+agency|
    compliance|risk|regulatory|\baml\b|\bkyc\b|audit|assurance|fraud|financial\s+crime|
    data\s+(migration|quality|governance|steward\w*|management)|business\s+analy\w+|
    defined\s+benefit|defined\s+contribution|\bdb\b\s+pension|
    operations|back\s+office|middle\s+office|administrat\w+|coordinator|
    customer\s+(service|support|care|operations|experience)|client\s+(service|support|onboarding)|
    service\s+desk|helpdesk|contact\s+centre|call\s+centre|
    sales\s+support|inside\s+sales|account\s+management|
    procurement|purchasing|supply\s+chain|planner|planning|
    business\s+support|project\s+(support|coordinator|administrator)|\bpmo\b|
    graduate\s+programme|graduate\s+program|rotational\s+programme
)\b""", re.I | re.X)

OUT_OF_FIELD = {
    "engineering": r"\b(engineer|engineering|mechanical|electrical|electronic|automation|"
                   r"instrumentation|metrology|validation\s+technician|manufacturing\s+technician|"
                   r"process\s+technician|maintenance\s+technician|civil|structural|quantity\s+surveyor|"
                   r"cnc|tooling|firmware|hardware)\b",
    "software development": r"\b(software\s+(developer|engineer)|developer|programmer|devops|\bsre\b|"
                            r"full[\s-]stack|back[\s-]end|front[\s-]end|data\s+engineer|"
                            r"platform\s+engineer|cloud\s+(engineer|architect)|solutions?\s+architect|"
                            r"cyber\s*security|penetration\s+test|qa\s+engineer|test\s+engineer|"
                            r"machine\s+learning\s+engineer)\b",
    "actuarial": r"\b(actuar\w+)\b",
    "clinical or healthcare": r"\b(nurse|nursing|midwif\w+|clinical|physiotherap\w+|radiograph\w+|"
                              r"pharmacist|pharmacy\s+technician|dentist|dental|occupational\s+therap\w+|"
                              r"speech\s+and\s+language|healthcare\s+assistant|care\s+assistant|"
                              r"phlebotom\w+|sonograph\w+|paramedic)\b",
    "laboratory science": r"\b(laborator\w+|\blab\s+(analyst|technician|scientist)|scientist|chemist|"
                          r"microbiolog\w+|biolog\w+|toxicolog\w+|formulation)\b",
    "legal": r"\b(solicitor|barrister|legal\s+counsel|paralegal|legal\s+advis\w+|law\s+clerk|"
             r"company\s+secretar\w+\s+lawyer)\b",
    "teaching or academia": r"\b(lecturer|professor|teacher|tutor|postdoc\w*|phd\s+researcher|"
                            r"research\s+fellow)\b",
    "skilled trades or production": r"\b(electrician|plumber|welder|fitter|machinist|carpenter|"
                                    r"forklift|\bhgv\b|\blgv\b|driver|warehouse\s+operative|"
                                    r"general\s+operative|production\s+operative|butcher|baker|"
                                    r"warehouse\s+associate|production\s+associate|"
                                    r"manufacturing\s+associate|bioprocess|"
                                    r"chef|kitchen\s+porter|cleaner|security\s+officer|groundsk\w+)\b",
    "marketing or creative": r"\b(marketing|brand\s+manager|content\s+(writer|creator|marketer)|"
                             r"social\s+media|\bseo\b|copywriter|graphic\s+design\w*|"
                             r"\bux\b|\bui\b\s+design\w*|videograph\w+|public\s+relations)\b",
}

# Titles that look out-of-field but are hers. Checked first, wins outright.
RESCUE = re.compile(
    r"\b(business\s+intelligence\s+(developer|analyst)|bi\s+developer|report\s+developer|"
    r"reporting\s+(analyst|developer)|data\s+analyst|business\s+analyst|systems?\s+analyst|"
    r"sales\s+support|customer\s+(service|support)|client\s+service)\b", re.I)

# ------------------------------------------------------------- qualifications

CREDENTIALS = {
    "QFA":  r"\bQFA\b|qualified\s+financial\s+advi[sz]er",
    "APA":  r"\bAPA\b|accredited\s+product\s+advi[sz]er",
    "IIPM": r"\bIIPM\b",
    "ACA / ACCA / CIMA / CPA": r"\bACA\b|\bACCA\b|\bCIMA\b|\bCPA\b|chartered\s+accountant",
    "CFA":  r"\bCFA\b",
    "FRM":  r"\bFRM\b",
    "actuarial exams": r"actuarial\s+(exam|qualif)|\bIFoA\b|institute\s+and\s+faculty\s+of\s+actuaries",
    "NMBI nursing registration": r"\bNMBI\b|an\s+bord\s+altranais|registered\s+nurse",
    "CORU registration": r"\bCORU\b",
    "Chartered Engineer": r"chartered\s+engineer|engineers\s+ireland",
    "legal qualification": r"qualified\s+solicitor|admitted\s+to\s+the\s+roll|law\s+society\s+of\s+ireland",
    "Teaching Council registration": r"teaching\s+council",
    "CII / LIA insurance qualification": r"\bCII\b|\bLIA\b|certified\s+insurance\s+practitioner",
}
REQUIRED = re.compile(r"\b(must\s+(hold|have|be|possess)|required|requirement|essential|"
                      r"mandatory|minimum\s+of|you\s+will\s+(hold|have|be)|qualified\s+in|"
                      r"fully\s+qualified|holds?\s+a)\b", re.I)
OFFERED  = re.compile(r"\b(desirable|preferred|advantage|beneficial|nice\s+to\s+have|"
                      r"working\s+towards|support(ed)?\s+(you\s+)?(to|in|through)|we\s+will\s+support|"
                      r"fully\s+supported|financial\s+support|study\s+support|funded|"
                      r"opportunit\w+\s+to|you\s+will\s+(complete|gain|pursue)|"
                      r"or\s+equivalent|or\s+working\s+towards)\b", re.I)

# ------------------------------------------------------------------ the rest

DEGREE_BLOCK = re.compile(
    r"degree\s+in\s+[^.;]{0,60}?\b(engineering|computer\s+science|nursing|law|chemistry|"
    r"pharmacy|biolog\w+|physics|medicine|actuarial)\b", re.I)

# "Minimum 4 years' experience" is a requirement. "Over 3.5 years you'll build
# experience" is a programme length. Only the first is a wall, so the number
# must be introduced by a demand word and not by a duration word.
YEARS = re.compile(r"\b(?:minimum(?:\s+of)?|at\s+least|a\s+minimum\s+of|"
                   r"requires?|required|must\s+have|with)\s+"
                   r"(\d{1,2})\s*\+?\s*(?:to|-|–)?\s*(?:\d{1,2})?\s*year[s]?'?\s*"
                   r"[^.;]{0,45}?\b(experience|exp\b)"
                   r"|\b(\d{1,2})\s*\+\s*year[s]?'?\s*[^.;]{0,30}?\b(experience)", re.I)
YEARS_DURATION = re.compile(r"\b(over|across|during|throughout|spanning|programme\s+of|"
                            r"lasts?|duration)\b", re.I)

# Degree lists that name any of these leave the door open for her.
OK_DEGREE = re.compile(r"\b(business|commerc\w+|finance|financial|economic\w*|management|"
                       r"account\w+|analytic\w+|data\s+science|statistic\w*|mathematic\w*|"
                       r"information\s+systems|any\s+discipline|related\s+(discipline|field|area|subject)|"
                       r"relevant\s+(discipline|field|area|subject)s?|numerate|other\s+relevant)\b", re.I)

# Careers-site chrome that is not the job.
NAV_NOISE = re.compile(r"(cookie\s+preferences|accept\s+all\s+cookies|skip\s+to\s+main\s+content|"
                       r"career\s+streams|explore\s+all\s+jobs|privacy\s+policy)", re.I)

GRAD_TITLE = re.compile(r"\b(graduate|intern|internship|placement|trainee|apprentice|"
                        r"co[- ]?op|early\s+careers?)\b", re.I)

LANGUAGES = re.compile(r"\b(fluent|fluency|native|business\s+level|proficient)\b[^.;]{0,40}?"
                       r"\b(french|german|spanish|dutch|italian|portuguese|polish|swedish|"
                       r"danish|norwegian|finnish|czech|hungarian|romanian|greek|turkish|"
                       r"arabic|mandarin|japanese|korean)\b", re.I)

# She graduated in August 2026. A "graduate programme" that requires you to
# still be enrolled, or to return to college afterwards, is an internship in
# all but name and is closed to her - so it is a block, not a flag.
STILL_A_STUDENT = re.compile(
    r"(must\s+be\s+(currently\s+)?(enrolled|registered|studying)"
    r"|currently\s+(enrolled|registered|studying|pursuing\s+a\s+(degree|bachelor|master))"
    r"|enrolled\s+in\s+(a\s+)?(university|college|full[- ]time\s+(study|education|degree))"
    r"|returning\s+to\s+(full[- ]time\s+)?(study|college|university|education)"
    r"|return\s+to\s+(your\s+)?stud(y|ies)"
    r"|(final|penultimate|second|third)\s+year\s+student"
    r"|undergraduate\s+student"
    r"|as\s+part\s+of\s+your\s+(course|degree|programme\s+of\s+study)"
    r"|work\s+placement\s+(year|as\s+part)"
    r"|sandwich\s+(year|placement)"
    r"|student\s+placement"
    r"|for\s+the\s+duration\s+of\s+the\s+(internship|placement|co[- ]?op)"
    r"|available\s+to\s+work\s+.{0,30}\s+while\s+studying)", re.I)

# A programme longer than two years is a commitment she does not want. The
# number must sit next to a programme/contract word, or "3 years' experience"
# would read as a three-year contract.
WORDNUM = {"one":1,"two":2,"three":3,"four":4,"five":5,"six":6}
DURATION = re.compile(
    r"\b(?:(\d{1,2}(?:\.\d)?)|(one|two|three|four|five|six))[\s-]*"
    r"(year|month)s?\b[^.;]{0,60}?"
    r"\b(programme|program|scheme|contract|rotation|graduate\s+programme|traineeship|placement|fixed[\s-]term)\b"
    r"|\b(programme|program|scheme|contract|rotation|traineeship)\b[^.;]{0,60}?"
    r"\b(?:(\d{1,2}(?:\.\d)?)|(one|two|three|four|five|six))[\s-]*(year|month)s?\b",
    re.I)
MAX_MONTHS_OK = 24

MAX_YEARS_OK = 3          # 3 is a flag, 4+ is a block
WINDOW = 170


def _sentence(text: str, start: int, end: int) -> str:
    a = max(0, start - WINDOW); b = min(len(text), end + WINDOW)
    return " ".join(text[a:b].split())


def assess(job: dict) -> dict:
    """Return {'status', 'reasons', 'bonuses'} - never mutates, never deletes."""
    title = job.get("title") or ""
    desc  = job.get("description") or ""
    text  = f"{title}\n{desc}"
    reasons, bonuses, flags = [], [], []

    # 1. discipline -------------------------------------------------------
    if not RESCUE.search(title):
        for label, pat in OUT_OF_FIELD.items():
            m = re.search(pat, title, re.I)
            if m:
                reasons.append({"code": "field", "detail": f"{label} role",
                                "quote": title})
                break
        else:
            # title was neutral; only block on the description if the title
            # gives us nothing to go on at all
            if not IN_FIELD.search(title) and not GRAD_TITLE.search(title):
                body = desc[:1500]
                if NAV_NOISE.search(body):      # careers-site chrome, not the job
                    body = ""
                for label, pat in OUT_OF_FIELD.items():
                    m = re.search(pat, body, re.I)
                    if m:
                        reasons.append({"code": "field", "detail": f"looks like a {label} role",
                                        "quote": _sentence(desc, m.start(), m.end())})
                        break

    # 2. credentials ------------------------------------------------------
    for name, pat in CREDENTIALS.items():
        for m in re.finditer(pat, desc):
            w = _sentence(desc, m.start(), m.end())
            if OFFERED.search(w):
                bonuses.append({"code": "qualification_supported",
                                "detail": f"{name} supported or desirable, not required",
                                "quote": w})
                break
            if REQUIRED.search(w):
                reasons.append({"code": "qualification", "detail": f"{name} required",
                                "quote": w})
                break

    # 3. degree discipline -------------------------------------------------
    m = DEGREE_BLOCK.search(desc)
    if m:
        w = _sentence(desc, m.start(), m.end())
        if OK_DEGREE.search(w):
            pass          # the list names something she holds, or is open-ended
        else:
            reasons.append({"code": "degree", "detail": "degree in a discipline she does not hold",
                            "quote": w})

    # 4. years -------------------------------------------------------------
    hits = []
    for m in YEARS.finditer(desc):
        n = int(m.group(1) or m.group(3))
        if not 1 <= n <= 15:
            continue
        w = _sentence(desc, m.start(), m.end())
        if YEARS_DURATION.search(w):        # programme length, not a requirement
            continue
        hits.append((n, m))
    if hits and not GRAD_TITLE.search(title):
        lowest, m = min(hits, key=lambda x: x[0])
        if lowest > MAX_YEARS_OK:
            reasons.append({"code": "experience", "detail": f"{lowest}+ years required",
                            "quote": _sentence(desc, m.start(), m.end())})
        elif lowest == MAX_YEARS_OK:
            flags.append({"code": "experience", "detail": "3 years asked for; she has 1",
                          "quote": _sentence(desc, m.start(), m.end())})

    # 5. programme length ----------------------------------------------------
    for m in DURATION.finditer(desc):
        num  = m.group(1) or m.group(5)
        word = m.group(2) or m.group(6)
        unit = (m.group(3) or m.group(7) or "").lower()
        try:
            n = float(num) if num else WORDNUM.get((word or "").lower(), 0)
        except ValueError:
            continue
        if not n:
            continue
        months = n * 12 if unit.startswith("year") else n
        if months > MAX_MONTHS_OK:
            reasons.append({"code": "duration",
                            "detail": f"commitment of about {months/12:.1f} years",
                            "quote": _sentence(desc, m.start(), m.end())})
            break

    # 6. still-a-student ----------------------------------------------------
    m = STILL_A_STUDENT.search(desc)
    if m:
        reasons.append({"code": "student", "detail": "open only to current students",
                        "quote": _sentence(desc, m.start(), m.end())})

    # 7. language ----------------------------------------------------------
    m = LANGUAGES.search(desc)
    if m and REQUIRED.search(_sentence(desc, m.start(), m.end())):
        reasons.append({"code": "language", "detail": f"{m.group(2).title()} required",
                        "quote": _sentence(desc, m.start(), m.end())})

    status = "blocked" if reasons else ("flagged" if flags else "eligible")
    return {"status": status, "reasons": reasons, "flags": flags, "bonuses": bonuses}
