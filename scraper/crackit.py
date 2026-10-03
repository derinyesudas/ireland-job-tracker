"""
Crack-IT: office jobs she can get into now, whatever their fit score says.

The fit score ranks a job by how closely it matches her CV, which is the right
question for her best-fit roles and the wrong one for the jobs she can simply
walk into - an Operations Analyst at a bank, a Claims Handler, a Fund
Administrator, a graduate programme. Those score in the forties and sink. This
module picks them out by title so they get their own list, newest first.

A job is Crack-IT when all of these hold:

  * it passed the eligibility gates (nothing she has been told she cannot do),
  * its title names an entry-level office role from her list,
  * its title is not a senior one,
  * it asks for at most one year's experience, or does not say.
"""

from __future__ import annotations

import re

from scraper import eligible as E

MAX_YEARS = 1

# Order matters: the first family that matches labels the job.
FAMILIES: list[tuple[str, re.Pattern]] = [(label, re.compile(pat, re.I)) for label, pat in [
    ("Graduate / internship",
     r"\b(graduate|grad\s+(programme|program|scheme)|internship|intern|summer\s+analyst|"
     r"off[\s-]cycle|placement|trainee|traineeship|early\s+careers?|apprentice\w*|"
     r"entry[\s-]level)\b"
     # Big 4 and bank intakes name the year, not the word graduate:
     # "Audit Associate Dublin 2027", "Tax Associate Cork 2027".
     r"|\b(associate|analyst)\b.*\b20(2[6-9])\b|\b20(2[6-9])\b.*\b(associate|analyst)\b"),
    ("KYC / AML",
     r"\b(kyc|aml|cdd|edd|anti[\s-]money|financial\s+crime|client\s+onboarding|"
     r"client\s+lifecycle|\bclm\b|customer\s+due\s+diligence|due\s+diligence|sanctions|"
     r"transaction\s+monitoring|screening\s+analyst|fraud\s+(analyst|operations|associate|"
     r"investigator|specialist|officer|agent))\b"),
    ("Fund admin / asset servicing",
     r"\b(fund\s+(administrat\w+|accountant|accounting|services|operations|associate|analyst|"
     r"officer|controller)|asset\s+servicing|corporate\s+actions|\bnav\b|transfer\s+agency|"
     r"investor\s+(services|relations\s+administrator)|shareholder\s+services|custody|"
     r"securities\s+services|depositary|fiduciary\s+services|trustee\s+services|"
     r"reconciliation\w*|settlements?|trade\s+(support|operations|processing|settlement|"
     r"capture)|middle\s+office|back\s+office|income\s+processing|cash\s+(management|"
     r"operations)|markets?\s+operations|pricing\s+analyst|valuations?\s+analyst|"
     r"investment\s+(operations|support|administrat\w+)|alternative\s+investment|"
     r"wealth\s+operations|transaction\s+(analyst|processor|associate|administrator)|"
     r"private\s+(equity|markets)\s+(associate|analyst|administrator))\b"),
    ("Payments",
     r"\b(payments?\s+(analyst|operations|associate|specialist|officer|executive|assistant|"
     r"administrator|processor|team\s+member)|payment\s+operations|treasury\s+operations)\b"),
    ("Pensions / insurance / claims",
     r"\b(claims?\b[^,;|]{0,25}\b(handler|assistant|administrator|executive|officer|associate|"
     r"processor|technician|adjuster|analyst|specialist|team\s+member|advisor|adviser|"
     r"consultant|representative|negotiator|agent)|fnol|first\s+notification|"
     r"complaints?\s+(handler|officer|analyst|administrator|executive|advisor|adviser|"
     r"specialist)|pensions?\s+(administrator|admin\w*|associate|executive|officer|assistant|"
     r"analyst|consultant|specialist|team\s+member|advisor|adviser)|"
     r"retirement\s+(administrator|associate|analyst|specialist)|"
     r"policy\s+(administrator|servicing|admin\w*)|underwriting\s+(assistant|associate|"
     r"support|administrator|technician|analyst)|(associate|assistant|junior|trainee)\s+"
     r"underwriter|insurance\s+(administrator|associate|assistant|executive|operations|"
     r"advisor|adviser|analyst|consultant)|trade\s+credit|surety|"
     r"new\s+business\s+(administrator|associate|executive|team)|"
     r"benefits?\s+(administrator|analyst|associate)|actuarial\s+(operations|support|"
     r"administrat\w+|assistant|data))\b"),
    ("Operations",
     r"\b(operations?|ops)\b[^,;|]{0,30}\b(analyst|associate|administrator|assistant|executive|"
     r"officer|specialist|coordinator|support|representative|team\s+member|processor|clerk|"
     r"agent)\b|\b(analyst|associate|administrator|officer|specialist),?\s+(\w+\s+)?"
     r"operations\b"),
    ("Analyst",
     r"\b((business|data|bi|mi|reporting|insights?|process|supply\s+chain|planning|"
     r"commercial|sales\s+op\w*|revenue\s+op\w*|product\s+op\w*|pricing|research|"
     r"performance|financial|finance|credit|risk|compliance|regulatory|audit|technology|"
     r"consulting|investment|portfolio|controls?|quality|workforce|real[\s-]time|"
     r"capacity|governance|client|customer|operational|junior|associate)\s+analyst|"
     r"analyst\s*[,(\-–]\s*\w+|^analyst$|audit\s+associate|assurance\s+associate|"
     r"risk\s+associate|consulting\s+(analyst|associate)|advisory\s+associate)\b"),
    ("Accounts / finance assistant",
     r"\b(accounts\s+(assistant|payable|receivable|administrator|clerk|executive|associate|"
     r"officer|technician|specialist)|account\s+(assistant|clerk|technician)|"
     r"\bap\s+(specialist|clerk|associate|processor)|\bar\s+(specialist|associate)|"
     r"finance\s+(assistant|administrator|associate|executive|officer|clerk|"
     r"operations)|(financial|regulatory)\s+reporting\s+(officer|analyst|associate|"
     r"assistant|executive)|credit\s+control\w*|billing\s+(specialist|associate|analyst|"
     r"administrator|executive)|bookkeep\w+|purchase\s+ledger|sales\s+ledger|"
     r"procurement\s+(assistant|administrator|analyst|associate|executive)|"
     r"purchasing\s+(assistant|administrator)|tax\s+assistant|payroll\s+(administrator|"
     r"assistant|associate|executive|specialist|officer|analyst))\b"),
    ("Customer operations",
     r"\b(customer\s+(service|support|care|operations|experience|engagement|success|contact|"
     r"relations?|onboarding)|client\s+(service|services|servicing|support|relations?)|"
     r"contact\s+centre|call\s+centre|service\s+desk|help\s*desk|"
     r"customer\s+(advisor|adviser|agent|associate|representative|specialist))\b"),
    ("Office / admin",
     r"\b(administrat\w+|admin|office\s+(assistant|administrator|coordinator|support|junior|"
     r"executive)|receptionist|front\s+of\s+house|secretar(y|ial)|executive\s+assistant|"
     r"team\s+assistant|business\s+support|sales\s+support|data\s+(entry|input|processing|"
     r"administrator)|records?\s+(officer|assistant|administrator|clerk)|document\s+"
     r"(controller|administrator)|clerical|clerk|project\s+(support|coordinator|"
     r"administrator|assistant|officer)|pmo\s+(analyst|support|administrator|coordinator)|"
     r"programme\s+(support|coordinator|administrator)|rostering|coordinator|processor)\b"),
]]

# Seniority. "Manager" ends it, "management" does not: a Wealth Management
# Operations Analyst and a Risk Management graduate programme are both hers.
SENIOR = re.compile(
    r"\b(senior|sr\.?|snr|lead|principal|manager|director|head|vp|svp|evp|vice\s+president|avp|"
    r"managing|chief|staff|expert|architect|partner|counsel|supervisor|team\s+leader|"
    r"iii|iv|level\s+[3-9]|grade\s+[5-9])\b", re.I)

# Office roles only. A system administrator is IT, a store associate is retail,
# a check-in agent works at the airport.
NOT_OFFICE = re.compile(
    r"\b((system|systems|database|network|linux|windows|cloud|salesforce|sharepoint|"
    r"servicenow|crm|application|platform|security|m365|azure|jira|it|sap|oracle|workday)"
    r"\s+(administrator|admin)|store|shop|retail\s+(assistant|advisor|adviser|associate|"
    r"colleague|sales|team\s+member|worker|operative|supervisor)|sales\s+advisor|"
    r"visual\s+(advisor|merchandiser)|cashier|checkout|forecourt|barista|deli|"
    r"supermarket|warehouse|driver|restaurant|hotel|hospitality|bar\s+staff|waiter|"
    r"waitress|cabin\s+crew|airport|check[\s-]in|boarding|ramp|baggage|ground\s+(crew|"
    r"handling|operations)|field\s+(service|sales|engineer|technician)|technician|"
    r"quality\s+control|\bqc\b|manufacturing\s+(operations|operative|associate|technician|"
    r"operator|engineer)|production\s+(operative|associate|technician|worker|line|"
    r"supervisor|operator)|construction|laboratory|"
    r"it\s+(service\s+desk|support|helpdesk|help\s+desk)|desktop\s+support|"
    r"\bav\b|audio[\s-]?visual|\bsap\b|s/4|hana|guidewire|murex|calypso|charles\s+river|"
    r"\bfix\b|^it\s|\bit\s+(systems|service|support|operations|analyst|business|project|"
    r"desk)|isle\s+of\s+man|jersey|guernsey)\b", re.I)

# A language she does not speak, named in the title.
LANG_TITLE = re.compile(
    r"\b(french|german|spanish|italian|dutch|portuguese|polish|swedish|danish|norwegian|"
    r"finnish|czech|hungarian|romanian|greek|turkish|arabic|mandarin|cantonese|japanese|"
    r"korean|hebrew|russian|nordic\s+languages?|dach|benelux)\b", re.I)

# "N years (of) [adjective] experience" is a requirement even without a demand
# word in front of it - "2 years' experience in a similar role" is how most
# Irish adverts say it, and eligible.YEARS only catches the ones that start
# "minimum" or "at least".
YEARS_PLAIN = re.compile(
    r"\b(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|–|to)\s*\d{1,2}\s*)?years?'?\s*(?:of\s+)?"
    r"(?:(?:relevant|proven|previous|prior|demonstrable|professional|industry|"
    r"hands[\s-]on|post[\s-]qualification|working|practical|related|direct|solid|"
    r"strong|good|similar)\s+)*(?:work\s+)?experience", re.I)


def years_asked(job: dict) -> tuple[int | None, str]:
    """The lowest number of years the advert demands, with the sentence."""
    desc = job.get("description") or ""
    best: tuple[int, str] | None = None
    for rx in (E.YEARS, YEARS_PLAIN):
        for m in rx.finditer(desc):
            g = [x for x in m.groups() if x and x.isdigit()]
            if not g:
                continue
            n = int(g[0])
            if not 1 <= n <= 15:
                continue
            w = E._sentence(desc, m.start(), m.end())
            if E.YEARS_DURATION.search(w):
                continue
            # "Senior Customer Service Representatives will have at least 2
            # years" sits in the same advert as the entry-level grade it
            # does not apply to.
            if re.search(r"\b(senior|experienced|team\s+lead\w*)\b",
                         desc[max(0, m.start() - 90):m.start()], re.I):
                continue
            if best is None or n < best[0]:
                best = (n, w)
    return (best[0], best[1]) if best else (None, "")


# An internship is for students unless the advert says otherwise. She has
# graduated, and asked for the ones that need you to still be enrolled to stay
# hidden - so an internship has to show it is open to graduates to get in.
STUDENT_TITLE = re.compile(
    r"\b(intern|internship|co[\s-]?op|placement|summer\s+(analyst|associate|"
    r"intern\w*)|off[\s-]cycle|spring\s+(week|insight)|insight\s+(day|week|"
    r"programme))\b", re.I)
OPEN_TO_GRADUATES = re.compile(
    r"\b(recent(ly)?\s+graduat\w+|(have|has)\s+(recently\s+)?graduated|"
    r"graduated\s+(in|within|from)|completed\s+(your|a|their)\s+(degree|studies)|"
    r"graduate\s+internship|open\s+to\s+(recent\s+)?graduates|"
    r"graduates?\s+(are\s+)?(welcome|eligible))\b", re.I)

# Careers-site pages that are not a vacancy.
NOT_A_JOB = re.compile(
    r"^(early\s+careers?|graduates?|graduate\s+(programmes?|programs?|careers?|"
    r"opportunities)|internships?|students?(\s+and\s+graduates?)?|careers?|"
    r"apprenticeships?)(\s+(at|in)\s+.*)?$"
    r"|\b(careers?\s+fair|career\s+fair|open\s+(evening|day)|information\s+(session|evening)|"
    r"webinar|insight\s+event|meet\s+the\s+team)\b", re.I)


def assess(job: dict, eligibility: str | None = None) -> dict | None:
    """{'family': label, 'years': n|None} for a Crack-IT job, else None."""
    status = eligibility or job.get("eligibility") or "eligible"
    if status == "blocked":
        return None
    title = " ".join((job.get("title") or "").split())
    if (not title or SENIOR.search(title) or NOT_OFFICE.search(title)
            or LANG_TITLE.search(title)):
        return None
    if NOT_A_JOB.search(title):
        return None
    family = next((label for label, rx in FAMILIES if rx.search(title)), None)
    if not family:
        return None
    if STUDENT_TITLE.search(title) and not OPEN_TO_GRADUATES.search(
            job.get("description") or ""):
        return None
    n, _ = years_asked(job)
    is_grad = bool(E.GRAD_TITLE.search(title))
    if n is not None and n > MAX_YEARS and not is_grad:
        return None
    return {"family": family, "years": n}
