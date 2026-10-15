"""
Decide whether Derin could actually apply for a job, by reading the advert.

The questions, asked of the title and the description:

  1. Is this a discipline she has a background in?   -> field
     (not tax, investment, engineering, healthcare, IT, legal, HR...)
  2. Does it demand a credential or professional body? -> qualification
  3. Does it demand more than two years, an experienced
     hire, or a senior grade?                        -> experience
  4. Does it demand a language she does not speak?   -> language
  5. Is it under 30 hours a week?                    -> hours
  6. Is it for students only, or longer than 2 years? -> student, duration
  7. Does it rule out sponsorship or Stamp 1G?       -> sponsorship

Fixed-term and temporary contracts are flagged, not blocked.

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
    customer\s+(services?|support|care|operations|experience)|client\s+(services?|support|onboarding)|
    service\s+desk|helpdesk|contact\s+centre|call\s+centre|
    sales\s+support|inside\s+sales|account\s+management|
    procurement|purchasing|supply\s+chain|planner|planning|
    business\s+support|project\s+(support|coordinator|administrator)|\bpmo\b|
    graduate\s+programme|graduate\s+program|rotational\s+programme
)\b""", re.I | re.X)

# The board used to show every job that was not ruled out, and most of what
# was left was simply not her line of work: lecturer posts, production lines,
# meat-plant news pages, account executives at software firms. A job now has
# to name her kind of work in its title to be shown at all.
FIELD_EXTRA = re.compile(r"""\b(
    workforce|real[\s-]?time|\bwfm\b|rostering|scheduling|planner|planning|
    quality|receptionist|secretar\w*|office|clerk|clerical|data\s+(entry|input|processing)|
    records|document\s+control\w*|assistant|trainee|graduate|apprentice\w*|
    sales|account\s+executive|business\s+development|\bbdr\b|\bsdr\b|
    tax|wealth|payments?|settlements?|reconciliation\w*|trade\s+support|asset\s+servicing|
    investor\s+services|depositary|fiduciary|transaction|onboarding|due\s+diligence|
    sanctions|credit\s+control\w*|billing|bookkeep\w*|invoic\w*|order\s+processing|
    logistics|commercial|actuarial\s+(operations|support|administrat\w+|assistant|data)|
    support\s+(associate|executive|officer|specialist|administrator)|
    customer\s+(advis[eo]r|agent|associate|representative|specialist|success|relations?)|
    \betfs?\b|exchange\s+traded\s+funds?|funds?\s+(services|operations)|asset\s+services|
    client\s+lifecycle|lifecycle\s+management|\bclm\b|employee\s+benefits|
    benefits\s+(consultant|administrator|analyst|associate|executive)|
    personal\s+lines|commercial\s+lines|broking|(account|retention|renewals?|policy)\s+(handler|executive|
    advis[eo]r|administrator|consultant|specialist)|renewal\s+invite|merchandis\w+|buyer|buying|
    sourcing|resilience|business\s+continuity|trade\s+credit|surety|underwrit\w+
)\b""", re.I | re.X)

# Graduate programmes in her field stay; the rest go. A title naming one of
# these and none of her anchors is a programme for somebody else's degree.
GRAD_OFF = re.compile(
    r"\b(culinary|chef|food|health\s*(and|&)\s*safety|safety|environment\w*|energy|"
    r"sustainab\w+|cyber|security|legal|law|engineering|engineer|manufacturing|production|"
    r"scien\w+|laborator\w+|nursing|clinical|pharmac\w+|veterinar\w+|agri\w*|marketing|design|"
    r"human\s+resources|\bhr\b|talent|software|research|r&d|quality)\b", re.I)
# Technology and digital programmes stay only when the title also names data,
# finance or the business side; the hard list above needs a strong anchor.
GRAD_SOFT_OFF = re.compile(r"\b(technology|digital|\bit\b|enterprise\s+delivery)\b", re.I)
GRAD_ANCHOR = re.compile(
    r"\b(data|finance|financial|business|commercial|insurance|banking|bank|risk|"
    r"pensions?|analytics|analyst|fund|treasury|payroll|procurement|supply\s+chain|"
    r"retail\s+banking)\b", re.I)
GRAD_WEAK_ANCHOR = re.compile(r"\b(operations|operational|change|advisory|consulting)\b", re.I)
# A law firm's trainee or intern intake is a route to qualifying as a solicitor.
LEGAL_PROGRAMME = re.compile(r"\b(trainee\s+solicitor|law\s+society|professional\s+practice\s+course|"
                             r"qualified\s+(lawyer|solicitor)|legal\s+work|law\s+student)", re.I)
# A graduate programme that starts on the factory floor is a production job.
FACTORY_FLOOR = re.compile(r"\b(factory|shop|production|plant)\s+floor\b|\bmeat\s+(processing|plant|industry)\b",
                           re.I)

OUT_OF_FIELD = {
    "engineering": r"\b(engineer\w*|technician|maintenance|plant\s+(operator|manager)|production\s+"
                   r"(supervisor|operator|manager|lead|planner\s+engineer)|process\s+(specialist|"
                   r"engineer|technician|development)|validation|packaging\s+(engineer|technologist)|"
                   r"site\s+(manager|engineer|supervisor)|surveyor|draughts\w*|\bcad\b|\bbim\b|"
                   r"commissioning|\bhvac\b|mechatronic\w*|construction|"
                   r"mechanical|electrical|electronic|automation|"
                   r"instrumentation|metrology|validation\s+technician|manufacturing\s+technician|"
                   r"process\s+technician|maintenance\s+technician|civil|structural|quantity\s+surveyor|"
                   r"cnc|tooling|firmware|hardware)\b",
    "software development": r"\b(software\s+(developer|engineer)|developer|programmer|devops|\bsre\b|"
                            r"full[\s-]stack|back[\s-]end|front[\s-]end|data\s+engineer|"
                            r"platform\s+engineer|cloud\s+(engineer|architect)|solutions?\s+architect|"
                            r"cyber\s*security|penetration\s+test|qa\s+engineer|test\s+engineer|"
                            r"machine\s+learning\s+engineer)\b",
    "IT support or infrastructure": r"\b(service\s+desk|help\s*desk|desktop\s+support|it\s+support|"
                                   r"technical\s+support|infrastructure|network\s+(admin\w*|engineer|data)|"
                                   r"m365|microsoft\s+365|office\s+365|teams\s+admin\w*|"
                                   r"sharepoint|active\s+directory|cloud\s+(admin\w*|oracle|ops)|"
                                   r"oracle\s+(ebs|cloud|infrastructure|dba|technical)|sap\s+(basis|abap|"
                                   r"technical)|\bdba\b|database\s+admin\w*|system\s+admin\w*|sysadmin|"
                                   r"attack\s+surface|threat|vulnerabilit\w+|penetration|\bsoc\b|"
                                   r"information\s+security|security\s+(analyst|engineer|operations|"
                                   r"architect|specialist|industry)|data\s+cent(er|re)|"
                                   r"application\s+(administrator|admin|support|specialist|engineer)|"
                                   r"it\s+(systems|specialist|coordinator|administrator|officer|technician|"
                                   r"operations|project|trainee|graduate|apprentice|analyst)|"
                                   r"test\s+(analyst|engineer|lead|automation)|software\s+test\w*|tester|"
                                   r"\bfix\b|charles\s+river|on[\s-]?site\s+support|"
                                   r"technical\s+(specialist|consultant|architect|writer)|"
                                   r"cyber\w*(?!\s+(insurance|claims|underwrit\w*))|telecom\w*|"
                                   r"network\s+(planner|planning|design\w*)|voice\s+operations|"
                                   r"platform\s+(engineer|administrator|admin))\b",
    "actuarial": r"\b(actuar\w+)(?!\s+(operations|support|administrat\w+|assistant|data))\b",
    "clinical or healthcare": r"\b(nurse|nursing|midwif\w+|clinical|physiotherap\w+|radiograph\w+|"
                              r"pharmacist|pharmacy\s+technician|dentist|dental|occupational\s+therap\w+|"
                              r"speech\s+and\s+language|healthcare\s+assistant|care\s+assistant|"
                              r"phlebotom\w+|sonograph\w+|paramedic|dietitian|dietician|nutritionist|"
                              r"health\s*care|care\s+(worker|staff|support|giver|manager|lead)|carer|"
                              r"support\s+worker|social\s+(care|worker|work)|patient|medical|doctor|"
                              r"physician|therapist|psycholog\w+|counsell\w+|optometr\w+|audiolog\w+|"
                              r"pharmac\w+|radiolog\w+|community\s+connector|family\s+support|"
                              r"childcare|early\s+years|creche|residential\s+(care|worker)|med\s*tech|"
                              r"orthopa?edic\w*|trauma|spine|surgical|surgery|hospital|cardio\w*|"
                              r"neuro\w*|oncolog\w*|diabet\w*|veterinar\w+)\b",
    "laboratory science": r"\b(laborator\w+|\blab\s+(analyst|technician|scientist)|scientist|chemist|"
                          r"microbiolog\w+|biolog\w+|toxicolog\w+|formulation|\bqc\b|"
                          r"quality\s+control|food\s+safety|haccp|quality\s+excellence)\b",
    "legal": r"\b(solicitor|barrister|paralegal|law\s+clerk|lawyer|attorney|litigation|"
             r"conveyanc\w+|counsel|legal\s+(advis\w+|analyst|assistant|executive|associate|"
             r"officer|specialist|quality|operations|secretary|administrator|intern|trainee|"
             r"graduate|engineer)|(company|corporate|assistant\s+company)\s+secretar\w*)\b",
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
                             r"\bux\b|\bui\b\s+design\w*|videograph\w+|public\s+relations|"
                             r"designer|design\s+(assistant|associate|graduate)|fashion)\b",
    "HR or recruitment": r"\b(recruiter|talent\s+(acquisition|partner|sourc\w+)|sourcer|resourcer|"
                         r"(hr|human\s+resources|people)\s+(advis\w+|generalist|business\s+partner|"
                         r"officer|specialist|partner))\b",
}

# Tax and investment are off her list outright - no title rescues them.
TAX = re.compile(r"\b(tax|taxation|\bvat\b|transfer\s+pricing)\b", re.I)
# "Pensions and Investments Administrator" is a pensions job and "Pricing &
# Portfolio Management Analyst" an insurance one; both keep their place.
INVESTMENT_EXEMPT = re.compile(r"\b(pensions?|pricing|underwrit\w*|insurance|claims|broking)\b", re.I)
TAX_OR_INVESTMENT = re.compile(
    r"\b(tax|taxation|\bvat\b|transfer\s+pricing|investments?|portfolio\s+(manager|management|analyst)|"
    r"wealth\s+(manager|management|advis\w+|planner|planning|consultant)|equity\s+research|"
    r"trader|trading|financial\s+(advis\w+|planner|planning(?!\s+(&|and)\s+analysis))|stockbrok\w+|"
    r"(?<!digital\s)asset\s+management(?!\s*[-–]?\s*(baggage|airfield|fleet|property|facilit\w+|"
    r"infrastructure|engineering|maintenance|physical))|event[\s-]driven|investment\s+(research|bank\w*)|"
    r"capital\s+markets|sales\s+(&|and)\s+trading|hedge\s+fund\s+(analyst|associate)|"
    r"corporate\s+finance|m\s*&\s*a\b|mergers|venture\s+capital|private\s+(client|wealth|bank\w*)|"
    r"quant\w*\s+(trader|trading|research\w*))\b", re.I)

# Title signals that the job is above her level. A graduate or trainee title
# is exempt - "Associate Manager Trainee Programme" is an intake.
SENIOR_TITLE = re.compile(
    r"\b(sr\.?|snr|senior|supervisor|team\s+lead(er)?|leader|lead\b(?!\s+gen\w*)|head\s+of|"
    r"principal|director|manager|vp|avp|vice\s+president|chief|expert|architect|iii|iv|complex|"
    r"business\s+partner)\b"
    # State Street and its peers grade by title suffix: Associate 1, Associate 2,
    # then Officer - several years in. "Compliance Officer" is a role, not a grade,
    # so only the suffix after a comma or dash counts.
    r"|[,–-]\s*off(icer)?\s*$"
    # "KYC Remediation SME" is a subject-matter expert, not a small business.
    r"|\bsme\s*$", re.I)

# Titles that are the accountancy or audit profession: a training contract and
# ACA/ACCA exams, which she does not want. A fund or client accountant at a
# fund administrator is fund accounting, which is hers.
ACCOUNTANCY_TITLE = re.compile(
    r"\b(accountant|auditor|audit\s+(associate|senior|trainee|assistant|graduate|semi[\s-]senior)|"
    r"external\s+audit|statutory\s+audit|(accounting|accountancy|audit|assurance)\s+"
    r"(graduate|trainee|apprentice\w*)|aca\s+trainee|acca\s+trainee)\b", re.I)
FUND_ACCOUNTANT = re.compile(r"\b(fund|client|nav|investor|portfolio|fund\s+services)\s+accountants?\b", re.I)

# A market or language named in the title: "SDR (France)", "Account Executive
# Small Business Italy", "Hebrew Market". English-speaking markets stay.
LANGUAGE_TITLE = re.compile(
    r"\b(french|german|italian|spanish|dutch|hebrew|portuguese|polish|japanese|korean|mandarin|"
    r"cantonese|arabic|turkish|greek|czech|hungarian|romanian|russian|swedish|danish|norwegian|"
    r"finnish|italy|france|germany|spain|israel|netherlands|portugal|poland|dach|benelux|iberia|"
    r"latam|brazil|japan|korea)\b", re.I)

# Titles that look out-of-field but are hers. Checked first, wins outright.
RESCUE = re.compile(
    r"\b(business\s+intelligence\s+(developer|analyst)|bi\s+developer|report\s+developer|"
    r"reporting\s+(analyst|developer)|data\s+analyst|business\s+analyst|business\s+systems?\s+analyst|"
    r"sales\s+support|customer\s+(service|support)|client\s+service|"
    r"actuarial\s+(operations|support|administrat\w+|assistant|data)|\baml\b|\bkyc\b|"
    r"financial\s+crimes?|anti[\s-]money|business\s+(&|and)\s+\w+\s+analyst)\b", re.I)

# ------------------------------------------------------------- qualifications

CREDENTIALS = {
    "QFA":  r"\bQFA\b|qualified\s+financial\s+advi[sz]er",
    "APA":  r"\bAPA\b|accredited\s+product\s+advi[sz]er",
    "IIPM": r"\bIIPM\b",
    "IPASS": r"\bIPASS\b",
    "ACA / ACCA / CIMA / CPA": r"\bACA\b|\bACCA\b|\bCIMA\b|\bCPA\b|chartered\s+accountant",
    "CFA":  r"\bCFA\b",
    "FRM":  r"\bFRM\b",
    "actuarial exams": r"actuarial\s+(exam|qualif)|\bIFoA\b|institute\s+and\s+faculty\s+of\s+actuaries",
    "NMBI nursing registration": r"\bNMBI\b|an\s+bord\s+altranais|registered\s+nurse",
    "CORU registration": r"\bCORU\b",
    "Chartered Engineer": r"chartered\s+engineer|engineers\s+ireland",
    "legal qualification": r"qualified\s+solicitor|admitted\s+to\s+the\s+roll|law\s+society\s+of\s+ireland",
    "Teaching Council registration": r"teaching\s+council",
    "CII / LIA insurance qualification": r"\bCII\b|\bLIA\b|\bCIP\b|\bACII\b|\bAPP\b|"
                                         r"certified\s+insurance\s+practitioner|approved\s+product\s+professional",
}
# Accountancy and investment qualifications mean an accountancy or investment
# career - a training contract, exams, a professional body. She does not want
# those, whether the qualification is asked for or offered. Only an advert that
# calls one merely desirable keeps the job.
ACCOUNTANCY_QUALS = re.compile(
    r"\b(ACA|ACCA|CIMA|CPA|CFA|CTA|AITI|ATT|CIPFA|CAIA|ICAI)\b|chartered\s+accountan\w+|"
    r"trainee\s+accountant|chartered\s+tax|part[\s-]qualified|"
    r"qualified\s+accountant", re.I)
SOFT_MENTION = re.compile(r"\b(desirable|preferred|advantage\w*|beneficial|nice\s+to\s+have|"
                          r"a\s+plus|an\s+asset|not\s+essential|not\s+required|ideally|"
                          r"(would|may|could|might)\s+(also\s+)?suit)\b", re.I)
# A qualification listed among the perks is not a requirement of the job:
# "Support for professional accreditations such as ACCA and study leave".
PERK = re.compile(r"\b(support\s+(for|with|towards)|study\s+(support|leave)|exam\s+leave|sponsor\w*|"
                  r"funded|funding|paid\s+for|reimburs\w+|professional\s+(qualification|development)\s+"
                  r"support)\b", re.I)
# ...unless the job is built around getting it.
TRACK = re.compile(r"\b(interested\s+in\s+(pursuing|completing|studying)|pathway|training\s+contract|"
                   r"become\s+(a\s+)?(fully\s+)?(qualified|chartered)|you\s+will\s+(complete|sit|study|"
                   r"pursue|undertake)|complete\s+[\w,&\s]{0,40}?(exams|qualifications?)|actively\s+pursuing|"
                   r"progress\s+toward\w*|work\w*\s+towards)\b", re.I)
# Membership of a professional body as a condition of the job.
BODY_MEMBERSHIP = re.compile(
    r"\b(member(ship)?\s+of\s+(the\s+|a\s+|an\s+)?(recogni[sz]ed\s+|relevant\s+|professional\s+)?"
    r"[\w&'’ ]{0,50}?(institute|society|association|council|chartered|professional\s+body|"
    r"law\s+society|bar\s+of)|professional\s+body\s+membership|chartered\s+member|"
    r"registered\s+with\s+(the\s+)?(coru|nmbi|law\s+society|engineers\s+ireland|teaching\s+council|"
    r"psi|pharmaceutical\s+society|central\s+bank)|admitted\s+as\s+a\s+solicitor)\b", re.I)
# "Working towards" or "part-qualified" asks for exams she has not started.
UNDERWAY = re.compile(r"\b(working\s+towards|studying\s+(for|towards)|part[\s-]qualified|"
                      r"currently\s+(studying|pursuing|completing)|partially\s+qualified)\b", re.I)

QUAL_WORD = re.compile(r"\b(qualifi\w+|holders?|hold|designation|certifi\w+|accredit\w+|"
                       r"registered|registration)\b", re.I)
REQUIRED = re.compile(r"\b(must\s+(hold|have|be|possess)|required|requirement|essential|"
                      r"mandatory|minimum\s+of|you\s+will\s+(hold|have|be)|qualified\s+in|"
                      r"fully\s+qualified|holds?\s+an?)\b", re.I)
OFFERED  = re.compile(r"\b(desirable|preferred|advantage|beneficial|nice\s+to\s+have|"
                      r"support(ed)?\s+(you\s+)?(to|in|through)|we\s+will\s+support|"
                      r"fully\s+supported|supported\s+by|financial\s+support|study\s+support|funded|"
                      r"sponsored|paid\s+for|opportunit\w+\s+to|you\s+will\s+(complete|gain|pursue|obtain)|"
                      r"gain\s+(an?\s+)?(industry[\s-]recogni[sz]ed\s+)?|training\s+(towards|for|in))\b", re.I)

# ------------------------------------------------------------------ the rest

DEGREE_BLOCK = re.compile(
    r"degree(?:\s+or\s+equivalent)?\s+in\s+[^.;•]{0,60}?\b(engineering|computer\s+science|nursing|"
    r"law|chemistry|pharmacy|biolog\w+|physics|medicine|actuarial|food\s+(science|technology)|"
    r"agricultur\w+|agri[\s-]?\w*|veterinary|dairy\s+science|microbiology)\b", re.I)

# "Minimum 4 years' experience" is a requirement. "Over 3.5 years you'll build
# experience" is a programme length. Only the first is a wall, so the number
# must be introduced by a demand word and not by a duration word.
YEARS = re.compile(r"\b(?:minimum(?:\s+of)?|at\s+least|a\s+minimum\s+of|"
                   r"requires?|required|must\s+have|with)\s+"
                   r"(\d{1,2})\s*\+?\s*(?:to|-|–)?\s*(?:\d{1,2})?\s*year[s]?'?\s*"
                   r"[^.;]{0,45}?\b(experience|exp\b)"
                   r"|\b(\d{1,2})\s*\+\s*year[s]?'?\s*[^.;]{0,30}?\b(experience)", re.I)
YEARS_DURATION = re.compile(r"\b(over|across|during|throughout|spanning|programme\s+of|"
                            r"lasts?|duration|after|first|next|within|for\s+the)\b", re.I)

# Most adverts spell the number out - "at least two years", "three to five
# years of experience", "Minimum of seven years related work experience" - and
# the digit-only pattern above read none of them, which is how a seven-year
# role sat on her board. Both are read now, and the lowest number wins.
_WORDNUM_Y = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
              "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12, "fifteen": 15}
_NUM = r"(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|twelve|fifteen)"
YEARS_WORDS = re.compile(
    rf"\b{_NUM}\s*(?:\(\d+\)\s*)?\+?\s*(?:(?:-|–|to|or)\s*{_NUM}\s*)?\+?\s*"
    rf"(?:or\s+more\s+)?(?:years?|yrs?)['’]?s?\s+(?:of\s+)?(?:[\w/&-]+\s+){{0,4}}?(?:experience|exp\b)",
    re.I)
YEARS_LEAD = re.compile(
    rf"\b(?:experience\s+of|min(?:imum)?\.?(?:\s+of)?|at\s+least|a\s+minimum\s+of|more\s+than|"
    rf"in\s+excess\s+of)\s+(?:at\s+least\s+)?{_NUM}\s*\+?\s*(?:years?|yrs?)", re.I)
# "4-6 years in a comparable role", "2-3 years in a data or analytics role":
# no word "experience" anywhere, and the commonest way an advert asks.
YEARS_ROLE = re.compile(
    rf"\b{_NUM}\s*(?:(?:-|–|to)\s*{_NUM}\s*)?\+?\s*(?:years?|yrs?)['’]?\s+(?:of\s+)?"
    rf"(?:in|within|working\s+in|spent\s+in)\s+(?:a|an|the)?\s*(?:[\w/&,-]+\s+){{0,5}}?"
    rf"(?:role|position|capacity|environment|setting|function|industry|sector|field|"
    rf"practice)s?\b", re.I)
# "Experience: 1-3 Years", "experience (min. 3 years)", "Experience - 2+ years".
YEARS_FIELD = re.compile(
    rf"\bexperience\s*(?:\(\s*|:\s*|-\s*|–\s*)(?:min(?:imum)?\.?\s*(?:of\s+)?|at\s+least\s+)?"
    rf"{_NUM}\s*(?:(?:-|–|to)\s*{_NUM}\s*)?\+?\s*(?:years?|yrs?)", re.I)
_OTHER_GRADE = re.compile(r"\b(senior|team\s+lead\w*|manager|supervisor)\b", re.I)
_ABOUT_US = re.compile(r"\b(we|our|us|company|firm|business|group|bank|organi[sz]ation|founded|history)\b", re.I)
_ABOUT_YOU = re.compile(r"\b(you|your|candidate|applicant|ideal|successful)\b", re.I)
MAX_YEARS = 2          # what she can be asked for; 3 or more takes it off the board


def _years_value(token: str) -> int | None:
    token = token.lower()
    return int(token) if token.isdigit() else _WORDNUM_Y.get(token)


def years_required(desc: str) -> tuple[int, str] | None:
    """The lowest number of years of experience the advert asks of the
    candidate, with the sentence that says so - or None."""
    best: tuple[int, str] | None = None
    for rx in (YEARS, YEARS_WORDS, YEARS_LEAD, YEARS_ROLE, YEARS_FIELD):
        for m in rx.finditer(desc):
            raw = next((g for g in m.groups() if g and (g.isdigit() or g.lower() in _WORDNUM_Y)), None)
            n = _years_value(raw) if raw else None
            if not n or not 1 <= n <= 15:
                continue
            around = desc[max(0, m.start() - 60):m.end() + 60]
            if rx is YEARS_LEAD and not re.search(r"experience", around, re.I):
                continue            # "at least two years" of something else
            if YEARS_DURATION.search(desc[max(0, m.start() - 40):m.start()]) and \
                    not re.search(r"experience", desc[m.start():m.end() + 5], re.I):
                continue            # a programme length, not a requirement
            before = desc[max(0, m.start() - 90):m.start()]
            same = _clause(desc, m.start(), m.end())
            if _OTHER_GRADE.search(same[:max(0, same.find(m.group(0)))]):
                continue            # "for the Senior grade, 5 years" - another grade of the job
            if _ABOUT_US.search(before[-60:]) and not _ABOUT_YOU.search(before[-60:]):
                continue            # "we have 25 years' experience"
            if best is None or n < best[0]:
                best = (n, _clause(desc, m.start(), m.end()))
    return best


# Hours and sponsorship - two things an advert can rule her out on that have
# nothing to do with what the job is.
PART_TIME_TITLE = re.compile(r"\b(part[\s-]?time|job[\s-]share|(\d{1,2}(?:\.\d+)?)\s*(?:hrs?|hours?))\b", re.I)
# Anything that puts a weekly figure on the contract. Under 30 is part-time.
PART_TIME_DESC = re.compile(
    r"\b(?:this\s+is\s+a\s+)?part[\s-]?time\s+(role|position|job|post|contract|basis|hours|opportunity|"
    r"vacancy|permanent|fixed)\b|\bthis\s+is\s+a\s+job[\s-]share\b|\bjob[\s-]share\s+(?:role|position|basis)\b"
    r"|\b0?\.\d+\s*(?:fte|wte)\b"
    r"|\b(\d{1,2}(?:\.\d+)?)(?:\s*(?:-|–|to)\s*(\d{1,2}(?:\.\d+)?))?\s*(?:hrs?|hours?)\s*"
    r"(?:(?:per|a|each|/)\s*(?:week|wk)\b|weekly\b|(?:fixed[\s-]term\s+|permanent\s+)?contract\b)"
    r"|\b(?:contracted|contract\s+of|working)\s+(\d{1,2}(?:\.\d+)?)\s*(?:hrs?|hours?)\b"
    r"|\bweekly\s+hours\s*[:\-]?\s*(\d{1,2}(?:\.\d+)?)", re.I)
_EXTRA_HOURS = re.compile(r"\b(overtime|additional|extra|on[\s-]call|travel|volunteer\w*|study|"
                          r"training|annual|leave|up\s+to\s+\d+\s*(hrs?|hours?)\s+of)\b", re.I)
STUDY_CONTEXT = re.compile(r"\b(study|studies|course|degree|mba|masters?|education|college|university|exam)", re.I)
# Find the keyword, then read its clause: a pattern that starts with a run of
# "any character but a full stop" is tried from every position in the advert
# and took half a minute over the board.
SPONSOR_WORD = re.compile(r"\bsponsor\w*", re.I)
_NEG = re.compile(r"\b(no|not|unable|cannot|can't|can\s+not|won't|will\s+not|do\s+not|does\s+not|"
                  r"don't|doesn't|without|isn't|aren't)\b", re.I)
_VISA = re.compile(r"\b(visa|employment\s+permit|work\s+permit|permits?|immigration|right\s+to\s+work|"
                   r"work\s+authori[sz]ation|stamp|this\s+(role|position|job|vacancy|opportunity))\b", re.I)
EU_ONLY = re.compile(r"\b(stamp\s*4|eu\s+citizens?|eea\s+citizens?|eu\s*/\s*eea|irish\s*/\s*eu|"
                     r"eu\s+nationals?|eea\s+nationals?|eu\s+passport|irish\s+citizens?)\b", re.I)
_MUST = re.compile(r"\b(must|only|required|requirement|need|needs|holder|eligible|essential)\b", re.I)
STUDENT_TITLE = re.compile(
    r"\b(intern|internship|co[\s-]?op|placement|summer\s+(analyst|associate|intern\w*)|off[\s-]cycle|"
    r"spring\s+(week|insight)|insight\s+(day|week|programme))\b", re.I)
OPEN_TO_GRADUATES = re.compile(
    r"\b(recent(ly)?\s+graduat\w+|(have|has)\s+(recently\s+)?graduated|graduated\s+(in|within|from)|"
    r"completed\s+(your|a|their)\s+(degree|studies)|graduate\s+internship|open\s+to\s+(recent\s+)?"
    r"graduates|graduates?\s+(are\s+)?(welcome|eligible))\b", re.I)

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
                       r"arabic|mandarin|japanese|korean|hebrew|russian|nordic\s+languages?|"
                       r"scandinavian\s+languages?|second\s+european\s+language)\b", re.I)

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
    r"\b(programme|program|scheme|contract|rotation|graduate\s+programme|traineeship|placement|fixed[\s-]term|"
    r"apprenticeship)\b"
    r"|\b(programme|program|scheme|contract|rotation|traineeship|apprenticeship)\b[^.;]{0,60}?"
    r"\b(?:(\d{1,2}(?:\.\d)?)|(one|two|three|four|five|six))[\s-]*(year|month)s?\b",
    re.I)
MAX_MONTHS_OK = 24

MAX_YEARS_OK = 3          # 3 is a flag, 4+ is a block
WINDOW = 170


def _sentence(text: str, start: int, end: int) -> str:
    a = max(0, start - WINDOW); b = min(len(text), end + WINDOW)
    return " ".join(text[a:b].split())


# Adverts arrive as HTML or as text with the bullets flattened away, and a
# window of characters either side of a word then spans three requirements at
# once: "degree or equivalent; QFA qualification and willingness to sit the
# CFP" read the "or equivalent" that belongs to the degree as softening the
# QFA. List items, line breaks and paragraph ends become bullets here, so a
# rule can read the one requirement the word sits in.
_BLOCK_TAG = re.compile(r"<\s*/?\s*(li|br|p|div|h[1-6]|tr|ul|ol|section)\b[^>]*>", re.I)
_ANY_TAG = re.compile(r"<[^>]+>")
_BOUNDARY = re.compile(r"[;•·▪●◦|!?\n]|(?<!\be\.g)(?<!\bi\.e)(?<!\bmin)(?<!\bapprox)\.(?=\s+[A-Z(•])")


def _clean(desc: str) -> str:
    import html as _html
    text = _BLOCK_TAG.sub(" • ", desc or "")
    text = _ANY_TAG.sub(" ", text)
    text = _html.unescape(_html.unescape(text))
    text = re.sub(r"[\r\n]+", " • ", text)
    text = re.sub(r"(\s*•\s*)+", " • ", text)
    return " ".join(text.split())


def _clause(text: str, start: int, end: int, reach: int = 220) -> str:
    """The requirement a match sits in: from the boundary before it to the
    boundary after it, never more than `reach` characters either way."""
    a = max(0, start - reach)
    before = list(_BOUNDARY.finditer(text, a, start))
    a = before[-1].end() if before else a
    m = _BOUNDARY.search(text, end, min(len(text), end + reach))
    b = m.start() if m else min(len(text), end + reach)
    return text[a:b].strip(" •")


# "Must be fully authorised to work in Ireland, or hold a valid work permit,
# for the full duration of the 23-month contract (September 2027 - August
# 2029)" - a programme that runs past a graduate's permission to work and will
# not sponsor the gap.
FULL_DURATION = re.compile(
    r"\b(authori[sz]ed|eligible|entitled|permitted|permission|right|valid\s+work\s+permit)\b"
    r"[^•;]{0,120}?\b(full|entire|whole)\s+(duration|length|term|period)\b", re.I)

# An experienced hire, said without a number: "we are looking for an
# experienced Motor Claims Handler", "Proven experience in a similar role
# within Asset Management". A soft word in the same requirement keeps the job.
EXPERIENCED_HIRE = re.compile(
    r"\b(looking\s+for|seeking|recruit\w*|requires?|need)\s+(an?\s+)?"
    r"(?:[\w-]+,\s+){0,2}experienced\b(?!\s+or\s+(newly|recently)|\s+(graduate|trainee))"
    r"|\bfor\s+an?\s+(highly\s+|suitably\s+)?experienced\b(?!\s+or\s+(newly|recently)|\s+(graduate|trainee))"
    r"|\b(proven|previous|prior|demonstrable|demonstrated)\s+(work\s+)?experience\s+(in|within|as)\s+"
    r"(a|an)\s+(similar|comparable|equivalent|same)\s+(role|position|capacity)"
    r"|\b(extensive|significant|substantial|considerable)\s+(relevant\s+|industry\s+|practical\s+)?"
    r"(experience|track\s+record)\b"
    r"|(?:^|•\s*)experienced\s+(in|with|at)\b|\b(you\s+are|you're|you\s+will\s+be)\s+(an?\s+)?experienced\b",
    re.I | re.M)
# "Proven experience in an Account Executive role" on an Account Executive
# advert: the job asks for someone who has done this job before.
SAME_ROLE = re.compile(r"\b(proven|previous|prior|demonstrable|demonstrated|relevant)\s+(work\s+)?experience\s+"
                       r"(in|as|within)\s+(a|an)\s+([\w/&-]+(?:\s+[\w/&-]+){0,4}?)\s+(role|position|capacity)\b",
                       re.I)
_GENERIC_WORDS = {"similar", "comparable", "relevant", "related", "the", "a", "an", "and", "or", "of",
                  "role", "team", "office", "busy", "fast", "paced", "fast-paced", "professional",
                  "corporate", "dynamic", "client", "customer", "facing", "client-facing",
                  "customer-facing", "support", "administrative", "admin"}
# An advert whose requirements are a technologist's, whatever the title says.
IT_REQUIREMENT = re.compile(r"\bexperience\s+(in|with)\s+(cyber\s*security|information\s+security|"
                            r"network\s+(architecture|security|engineering)|software\s+development|"
                            r"penetration\s+testing|vulnerability\s+management)\b", re.I)
SOFT_EXPERIENCE = re.compile(r"\b(desirable|preferred|advantage\w*|beneficial|nice\s+to\s+have|a\s+plus|"
                             r"an\s+asset|ideally|not\s+essential|not\s+required|bonus|helpful|welcome)\b",
                             re.I)

# Fixed-term and temporary contracts. Graduate programmes are exempt - most
# run on a contract, and the duration rule already reads their length.
FTC_TITLE = re.compile(
    r"\b(ftc|fixed[\s-]term|temp|temporary|maternity\s+(cover|leave)|mat\s+cover|"
    r"agency\s+contract|contract\s+role|interim)\b|\(\s*contract\s*\)|\bcontract\)|"
    r"\b\d{1,2}[\s-]*months?\b(?![^()]*\bpermanent)", re.I)
FTC_DESC = re.compile(
    r"\b(?:this\s+is\s+an?|this\s+(?:role|position|job|post|vacancy)\s+is\s+(?:an?|being\s+offered\s+"
    r"(?:as|on)\s+an?)|offered\s+(?:as|on)\s+an?|on\s+an?)\s+(?:\d{1,2}|six|nine|twelve|eighteen)?"
    r"[\s-]*(?:months?\s+)?(?:fixed[\s-]term|temporary|ftc|maternity\s+cover)\b"
    r"|\b(?:\d{1,2}|six|nine|twelve|eighteen)[\s-]*months?\s+(?:fixed[\s-]term|temporary|ftc)\b"
    r"|\bfixed[\s-]term\s+contract\s+(?:of|for)\s+(?:\d{1,2}|six|nine|twelve|eighteen)\s+months?", re.I)


def _slug_words(url: str) -> str:
    import urllib.parse
    path = urllib.parse.unquote(urllib.parse.urlparse(url or "").path or "")
    parts = [p for p in path.split("/") if p and not p.isdigit()]
    return re.sub(r"[-_+.]+", " ", parts[-1] if parts else "")


def _field_reason(title: str, desc: str, url: str = "") -> dict | None:
    """Why this is not her kind of work, judged on the title - or None."""
    if TAX.search(title) or (TAX_OR_INVESTMENT.search(title) and not INVESTMENT_EXEMPT.search(title)):
        return {"code": "field", "detail": "tax or investment role", "quote": title}
    if not RESCUE.search(title):
        for label, pat in OUT_OF_FIELD.items():
            if re.search(pat, title, re.I):
                return {"code": "field", "detail": f"{label} role", "quote": title}
    if GRAD_TITLE.search(title):
        anchored = GRAD_ANCHOR.search(title)
        if GRAD_OFF.search(title) and not anchored:
            return {"code": "field", "detail": "graduate programme outside her field",
                    "quote": title}
        # The board title can drop the stream the URL still carries:
        # "Kerry Graduate Programme 2027" is ".../Kerry-Graduate-Programme-
        # 2027-Manufacturing-P43-A597/".
        slug = _slug_words(url)
        if not anchored and GRAD_TITLE.search(slug) and GRAD_OFF.search(slug) \
                and not GRAD_ANCHOR.search(slug):
            return {"code": "field", "detail": "graduate programme outside her field",
                    "quote": slug}
        if GRAD_SOFT_OFF.search(title) and not (anchored or GRAD_WEAK_ANCHOR.search(title)):
            return {"code": "field", "detail": "technology graduate programme",
                    "quote": title}
        m = LEGAL_PROGRAMME.search(desc)
        if m:
            return {"code": "field", "detail": "legal traineeship or internship",
                    "quote": _clause(desc, m.start(), m.end())}
        m = FACTORY_FLOOR.search(desc)
        if m:
            return {"code": "field", "detail": "graduate programme that starts on the factory floor",
                    "quote": _clause(desc, m.start(), m.end())}
        return None
    if re.search(r"\bquality\b", title, re.I):
        m = re.search(r"\b(gmp|gxp|gdp|manufactur\w+|batch\s+records?|capa|deviations?|hpra|fda|"
                      r"iso\s*13485|warehouse)\b", desc, re.I)
        if m:
            return {"code": "field", "detail": "quality role in manufacturing or pharma",
                    "quote": _clause(desc, m.start(), m.end())}
    if IN_FIELD.search(title) or FIELD_EXTRA.search(title):
        return None
    return {"code": "field", "detail": "not her line of work", "quote": title}


def assess(job: dict) -> dict:
    """Return {'status', 'reasons', 'flags', 'bonuses'} - never mutates, never deletes."""
    title = " ".join((job.get("title") or "").split())
    title = re.sub(r"\s+job\s+details\s*$", "", title, flags=re.I)
    desc  = job.get("description") or ""
    flat  = _clean(desc)
    is_grad = bool(GRAD_TITLE.search(title))
    reasons, bonuses, flags = [], [], []

    # 1. her line of work -------------------------------------------------
    r = _field_reason(title, flat, job.get("url") or "")
    if r:
        reasons.append(r)
    if not is_grad:
        m = SENIOR_TITLE.search(title)
        if m:
            reasons.append({"code": "experience", "detail": "senior or supervisory title",
                            "quote": title})
    if ACCOUNTANCY_TITLE.search(title) and not FUND_ACCOUNTANT.search(title) \
            and not (is_grad and re.search(r"\bfinance\b", title, re.I)):
        reasons.append({"code": "qualification",
                        "detail": "accountancy or audit track (ACA/ACCA)", "quote": title})
    m = LANGUAGE_TITLE.search(title)
    if m and not re.search(r"english[\s-]speak\w*", title, re.I):
        reasons.append({"code": "language", "detail": f"{m.group(1).title()} market or language",
                        "quote": title})

    # 2. qualifications and professional bodies --------------------------
    m = ACCOUNTANCY_QUALS.search(flat)
    while m:
        w = _clause(flat, m.start(), m.end())
        if SOFT_MENTION.search(w):
            pass
        elif PERK.search(w) and not (REQUIRED.search(w) or TRACK.search(w) or UNDERWAY.search(w)):
            bonuses.append({"code": "qualification_supported",
                            "detail": f"{m.group(0)} study support offered, not required", "quote": w})
        else:
            reasons.append({"code": "qualification",
                            "detail": f"accountancy or investment qualification ({m.group(0)})",
                            "quote": w})
            break
        m = ACCOUNTANCY_QUALS.search(flat, m.end())
    for name, pat in CREDENTIALS.items():
        for m in re.finditer(pat, flat):
            w = _clause(flat, m.start(), m.end())
            if SOFT_MENTION.search(w):
                bonuses.append({"code": "qualification_supported",
                                "detail": f"{name} desirable, not required", "quote": w})
                break
            if UNDERWAY.search(w):
                reasons.append({"code": "qualification",
                                "detail": f"{name} part-qualified or under way asked for",
                                "quote": w})
                break
            # "must be IPASS qualified or prepared to complete IPASS as part of
            # their training contract" offers the qualification on the job.
            on_the_job = re.search(r"\bor\s+(be\s+)?(prepared|willing|happy|open)\s+to\s+"
                                   r"(complete|undertake|study|obtain|achieve)", w, re.I)
            before = w[:max(0, w.find(m.group(0)))][-80:]
            perk = PERK.search(w) and not (REQUIRED.search(w) or TRACK.search(w))
            if on_the_job or perk or (OFFERED.search(w) and not REQUIRED.search(before)):
                bonuses.append({"code": "qualification_supported",
                                "detail": f"{name} supported or desirable, not required",
                                "quote": w})
                break
            # A credential named in a requirement is a requirement, whether or
            # not the advert spells out "required": "QFA qualification and
            # willingness to sit the CFP" asks for the QFA. A passing mention
            # ("a member firm of the LIA") asks for nothing.
            if REQUIRED.search(w) or QUAL_WORD.search(w):
                reasons.append({"code": "qualification", "detail": f"{name} required", "quote": w})
                break
    m = BODY_MEMBERSHIP.search(flat)
    if m:
        w = _clause(flat, m.start(), m.end())
        if not SOFT_MENTION.search(w) and not OFFERED.search(w):
            reasons.append({"code": "qualification",
                            "detail": "membership of a professional body required", "quote": w})

    # 3. degree discipline -------------------------------------------------
    m = DEGREE_BLOCK.search(flat)
    if m:
        w = _clause(flat, m.start(), m.end())
        if not OK_DEGREE.search(w):
            reasons.append({"code": "degree", "detail": "degree in a discipline she does not hold",
                            "quote": w})

    # 4. years -------------------------------------------------------------
    if not is_grad:
        hit = years_required(flat)
        if hit:
            n, w = hit
            if n > MAX_YEARS:
                reasons.append({"code": "experience", "detail": f"{n}+ years required",
                                "quote": w})
            elif n == MAX_YEARS:
                flags.append({"code": "experience",
                              "detail": f"{n} years asked for; she has 1", "quote": w})
        for m in EXPERIENCED_HIRE.finditer(flat):
            w = _clause(flat, m.start(), m.end())
            if SOFT_EXPERIENCE.search(w):
                continue
            asking = re.match(r"(looking|seeking|recruit|require|need|for)", m.group(0), re.I)
            if not asking and _ABOUT_US.search(w[:max(0, w.find(m.group(0)))][-40:]) \
                    and not _ABOUT_YOU.search(w):
                continue            # "we have extensive experience"
            reasons.append({"code": "experience", "detail": "asks for an experienced hire",
                            "quote": w})
            break
        else:
            head = re.sub(r"[^a-z ]", " ", title.lower()).split()
            for m in SAME_ROLE.finditer(flat):
                w = _clause(flat, m.start(), m.end())
                said = set(m.group(5).lower().split()) - _GENERIC_WORDS
                if head and head[-1] in said and not SOFT_EXPERIENCE.search(w):
                    reasons.append({"code": "experience",
                                    "detail": "asks for someone who has done this job before",
                                    "quote": w})
                    break
        m = IT_REQUIREMENT.search(flat)
        if m and not RESCUE.search(title):
            w = _clause(flat, m.start(), m.end())
            if not SOFT_EXPERIENCE.search(w):
                reasons.append({"code": "field", "detail": "IT or cyber role (from its requirements)",
                                "quote": w})

    # 5. programme or contract length - the title counts too ("36 month contract")
    for src in (title, flat):
        for m in DURATION.finditer(src):
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
                                "quote": _clause(src, m.start(), m.end())})
                break
        else:
            continue
        break

    # 5b. fixed-term and temporary contracts - marked, not hidden: she has
    # applied to a temporary role as well as passing over others.
    if not is_grad:
        m = FTC_TITLE.search(title)
        if m and not re.search(r"\bhours?\b", title[m.start():m.end() + 8], re.I):
            flags.append({"code": "contract", "detail": "fixed-term or temporary contract",
                          "quote": title})
        else:
            m = FTC_DESC.search(flat)
            if m:
                flags.append({"code": "contract", "detail": "fixed-term or temporary contract",
                              "quote": _clause(flat, m.start(), m.end())})

    # 6. students only ------------------------------------------------------
    m = STILL_A_STUDENT.search(flat)
    if m:
        reasons.append({"code": "student", "detail": "open only to current students",
                        "quote": _clause(flat, m.start(), m.end())})
    elif STUDENT_TITLE.search(title) and not OPEN_TO_GRADUATES.search(flat):
        reasons.append({"code": "student", "detail": "internship or placement for students",
                        "quote": title})

    # 7. language ----------------------------------------------------------
    # A fluency line in a requirements list is a requirement; only a soft word
    # ("an advantage", "a plus") makes it optional.
    for m in LANGUAGES.finditer(flat):
        w = _clause(flat, m.start(), m.end())
        if SOFT_EXPERIENCE.search(w) or SOFT_MENTION.search(w):
            continue
        reasons.append({"code": "language", "detail": f"{m.group(2).title()} required", "quote": w})
        break

    # 8. hours: anything under 30 a week ----------------------------------------
    hours_reason = None
    m = PART_TIME_TITLE.search(title)
    if m and not re.search(r"full[\s-]?time", title, re.I):
        if not m.group(2) or float(m.group(2)) < 30:
            hours_reason = {"code": "hours", "detail": "part-time (under 30 hours a week)",
                            "quote": title}
    if not hours_reason:
        for m in PART_TIME_DESC.finditer(flat):
            w = _clause(flat, m.start(), m.end())
            if STUDY_CONTEXT.search(w) or _EXTRA_HOURS.search(flat[max(0, m.start() - 40):m.start()]) \
                    or re.search(r"listed\s+as\s+full[\s-]time|flexible\s+arrangement", w, re.I):
                continue
            figures = [g for g in m.groups()[1:] if g]
            if figures:
                try:
                    if max(float(g) for g in figures) >= 30:
                        continue
                except ValueError:
                    continue
            hours_reason = {"code": "hours", "detail": "part-time (under 30 hours a week)",
                            "quote": w}
            break
    if hours_reason:
        reasons.append(hours_reason)

    # 9. sponsorship ----------------------------------------------------------
    for m in SPONSOR_WORD.finditer(flat):
        w = _clause(flat, m.start(), m.end())
        # "...unable to provide employment permit sponsorship. This includes
        # Stamp 1G" - the next sentence belongs with it.
        tail = flat[m.end():m.end() + 260]
        nxt = re.search(r"[^.!?•]{0,200}stamp\s*1\s*g[^.!?•]*", tail, re.I)
        if nxt:
            w = f"{w} {nxt.group(0).strip()}"
        if _NEG.search(w) and _VISA.search(w):
            reasons.append({"code": "sponsorship", "detail": "says no visa sponsorship",
                            "quote": w[:300]})
            break
    else:
        for m in EU_ONLY.finditer(flat):
            w = _clause(flat, m.start(), m.end())
            if _MUST.search(w) and not re.search(r"1\s*g\b", w, re.I):
                reasons.append({"code": "sponsorship",
                                "detail": "EU/EEA citizens or Stamp 4 only", "quote": w[:300]})
                break
        else:
            m = FULL_DURATION.search(flat)
            if m:
                reasons.append({"code": "sponsorship",
                                "detail": "needs the right to work for the whole contract, unsponsored",
                                "quote": _clause(flat, m.start(), m.end())})

    status = "blocked" if reasons else ("flagged" if flags else "eligible")
    return {"status": status, "reasons": reasons, "flags": flags, "bonuses": bonuses}
