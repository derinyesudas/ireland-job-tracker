"""
Is this job on the Critical Skills Occupations List?

The CSOL entries are narrow. "Business analysts" is not on the list; what is
on it is "management consultants and business analysts specialising in big
data analytics with skills in IT, data mining, modelling, and advanced maths".
Matching the title alone would tag every Business Analyst advert in Ireland
and most of them would not qualify, so each rule needs the title AND the
specialisation the list actually names.

Source: Critical Skills Occupations List, Department of Enterprise, Tourism
and Employment, 2026 edition. Salary floor EUR 36,848.

A job is tagged only when:
  1. the title matches a CSOL occupation she could plausibly hold, AND
  2. the advert carries the qualifying skills that entry names, AND
  3. any salary it states is at or above the floor.

A job that states no salary is still tagged, marked "salary not stated" -
Irish adverts rarely publish one, and requiring it would mean the tag never
appeared. That is a judgement, so the card says which of the two it is.
"""

from __future__ import annotations
import re

SALARY_FLOOR = 36848

# (soc4, title pattern, required qualifying evidence, the CSOL line itself)
RULES = [
    ("2423",
     r"\b(business analyst|management consultant|data analyst|analytics consultant)\b",
     r"\b(big data|data mining|machine learning|predictive model\w*|statistical model\w*|"
     r"advanced analytics|data science|python|\bsql\b|\br\b programming|modelling|modeling)\b",
     "Management consultants and business analysts specialising in big data analytics "
     "with skills in IT, data mining, modelling, and advanced maths"),

    ("2424",
     r"\b(project manager|programme manager|project management|financial analyst|"
     r"investment analyst|risk analyst|credit analyst|fraud analyst)\b",
     r"\b(finance|investment|risk analytics|credit risk|fraud|portfolio|"
     r"financial model\w*|solvency|capital)\b",
     "Business and financial project management professionals specialising in finance & "
     "investment analytics, risk analytics, credit, fraud analytics"),

    ("2425",
     r"\b(actuar\w+|economist|statistician|quantitative analyst)\b",
     r"\b(big data|data mining|modelling|modeling|statistic\w*|advanced math\w*|\bsql\b|python)\b",
     "Actuaries, economists and statisticians specialising in big data analytics"),

    ("2421",
     r"\b(accountant|taxation|tax (manager|specialist|adviser|advisor)|financial controller)\b",
     r"\b(acca|aca\b|cima|cpa\b|chartered|certified|tax|compliance|regulation|solvency|"
     r"financial management|audit)\b",
     "Chartered and certified accountants, and taxation experts specialising in tax, "
     "compliance, regulation, solvency or financial management"),

    ("2135",
     r"\b(it business analyst|systems analyst|business systems analyst|systems designer|"
     r"solution\w* analyst)\b",
     r"\b(systems?|software|application\w*|integration|erp|sap|architecture|technical)\b",
     "IT business analysts, architects and systems designers"),

    ("2134",
     r"\b(it project manager|it programme manager|technology project manager|"
     r"digital project manager)\b",
     r"\b(software|systems?|technology|digital|implementation|agile|scrum)\b",
     "IT project and programme managers"),

    ("2462",
     r"\b(quality assurance|quality engineer|regulatory affairs|regulatory specialist|"
     r"\bqa\b (specialist|officer|analyst))\b",
     r"\b(regulatory|compliance|gmp|iso\b|validation|audit|pharmaceutical|medical device)\b",
     "Quality assurance and regulatory professionals"),
]

_COMPILED = [(s, re.compile(t, re.I), re.compile(e, re.I), line) for s, t, e, line in RULES]


def assess(job: dict) -> dict | None:
    """Return the CSOL verdict, or None when the job is not on the list."""
    title = job.get("title") or ""
    desc = job.get("description") or ""
    salary = job.get("salary_eur")

    for soc4, title_re, evid_re, line in _COMPILED:
        m = title_re.search(title)
        if not m:
            continue
        hits = sorted({h.group(0).lower() for h in evid_re.finditer(desc)})
        if not hits:
            continue                      # named the occupation, not the specialisation
        if salary and salary < SALARY_FLOOR:
            return None                   # stated, and below the floor - it does not qualify
        return {
            "soc4": soc4,
            "matched_title": m.group(0),
            "evidence": hits[:4],
            "csol_line": line,
            "salary_eur": salary,
            "salary_known": bool(salary),
            "floor": SALARY_FLOOR,
        }
    return None
