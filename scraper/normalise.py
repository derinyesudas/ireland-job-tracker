"""
Every ATS returns a different shape. This turns them all into one job record:

    {
      "id":          stable unique id
      "title":       job title
      "company":     company display name
      "location":    location string as given
      "url":         direct apply link
      "description": plain text of the job description
      "posted_at":   ISO date string or ""
      "source":      which ATS it came from
      "department":  team/department if the ATS gives one
      "employment_type": full-time / internship / etc if given
    }
"""

from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timezone

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[ \t\r\f\v]+")
NL_RE = re.compile(r"\n{3,}")


def strip_html(raw: str | None) -> str:
    """Turn an HTML job description into readable plain text."""
    if not raw:
        return ""
    text = raw.replace("</p>", "\n").replace("<br>", "\n").replace("<br/>", "\n")
    text = text.replace("<br />", "\n").replace("</li>", "\n").replace("</div>", "\n")
    text = TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = WS_RE.sub(" ", text)
    text = NL_RE.sub("\n\n", text)
    return text.strip()


SAFE_SCHEMES = ("http://", "https://")


def safe_url(raw) -> str:
    """
    Keep only ordinary web addresses.

    Job links are read off other people's career sites, and a link can carry a
    small program rather than a destination. The site refuses those when it
    draws the page; this refuses to write one to disk in the first place, so a
    bad address never reaches the job board at all. A job without a usable link
    is no use anyway - the filters drop it.
    """
    u = str(raw or "").strip()
    if not u:
        return ""
    return u if u.lower().startswith(SAFE_SCHEMES) else ""


def make_id(company: str, title: str, url: str) -> str:
    key = f"{company.lower()}|{title.lower()}|{url}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _iso(value) -> str:
    """Best-effort conversion of whatever date the ATS gave us into ISO."""
    if not value:
        return ""
    if isinstance(value, (int, float)):
        # Lever uses epoch milliseconds
        try:
            secs = value / 1000 if value > 1e11 else value
            return datetime.fromtimestamp(secs, tz=timezone.utc).isoformat()
        except Exception:  # noqa: BLE001
            return ""
    text = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            dt = datetime.strptime(text.replace("Z", "+0000"), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            continue
    return text[:32]


# ---------------------------------------------------------------- per platform

def from_greenhouse(raw: dict, company: str) -> dict:
    loc = (raw.get("location") or {}).get("name", "")
    url = raw.get("absolute_url", "")
    title = raw.get("title", "")
    depts = raw.get("departments") or []
    return {
        "id": make_id(company, title, url),
        "title": title,
        "company": company,
        "location": loc,
        "url": url,
        "description": strip_html(raw.get("content")),
        "posted_at": _iso(raw.get("updated_at") or raw.get("first_published")),
        "source": "greenhouse",
        "department": depts[0].get("name", "") if depts else "",
        "employment_type": "",
    }


def from_lever(raw: dict, company: str) -> dict:
    cats = raw.get("categories") or {}
    title = raw.get("text", "")
    url = raw.get("hostedUrl", "")
    desc = raw.get("descriptionPlain") or strip_html(raw.get("description"))
    for section in raw.get("lists") or []:
        desc += "\n\n" + (section.get("text") or "") + "\n" + strip_html(section.get("content"))
    return {
        "id": make_id(company, title, url),
        "title": title,
        "company": company,
        "location": cats.get("location", "") or "",
        "url": url,
        "description": desc.strip(),
        "posted_at": _iso(raw.get("createdAt")),
        "source": "lever",
        "department": cats.get("team", "") or cats.get("department", "") or "",
        "employment_type": cats.get("commitment", "") or "",
    }


def from_ashby(raw: dict, company: str) -> dict:
    title = raw.get("title", "")
    url = raw.get("jobUrl") or raw.get("applyUrl") or ""
    return {
        "id": make_id(company, title, url),
        "title": title,
        "company": company,
        "location": raw.get("location", "") or "",
        "url": url,
        "description": strip_html(raw.get("descriptionHtml")) or raw.get("descriptionPlain", ""),
        "posted_at": _iso(raw.get("publishedAt")),
        "source": "ashby",
        "department": raw.get("department", "") or raw.get("team", "") or "",
        "employment_type": raw.get("employmentType", "") or "",
    }


def from_workable(raw: dict, company: str) -> dict:
    title = raw.get("title", "")
    url = raw.get("url") or raw.get("application_url") or ""
    loc_bits = [
        (raw.get("location") or {}).get("city", ""),
        (raw.get("location") or {}).get("country", ""),
    ]
    return {
        "id": make_id(company, title, url),
        "title": title,
        "company": company,
        "location": ", ".join([b for b in loc_bits if b]),
        "url": url,
        "description": strip_html(raw.get("description")),
        "posted_at": _iso(raw.get("published_on") or raw.get("created_at")),
        "source": "workable",
        "department": raw.get("department", "") or "",
        "employment_type": raw.get("employment_type", "") or "",
    }


def from_smartrecruiters(raw: dict, company: str) -> dict:
    title = raw.get("name", "")
    loc = raw.get("location") or {}
    loc_str = ", ".join([b for b in [loc.get("city", ""), loc.get("country", "")] if b])
    slug = raw.get("id", "")
    url = raw.get("applyUrl") or f"https://jobs.smartrecruiters.com/{company}/{slug}"
    # jobAd is a nested structure of titled sections, not a string. The first
    # version str()'d the whole dict, which produced Python repr rather than
    # readable text - so every SmartRecruiters job arrived with an unusable
    # description.
    ad = raw.get("jobAd") or {}
    parts: list[str] = []
    sections = ad.get("sections") if isinstance(ad, dict) else None
    if isinstance(sections, dict):
        for key in ("companyDescription", "jobDescription",
                    "qualifications", "additionalInformation"):
            section = sections.get(key)
            if isinstance(section, dict) and section.get("text"):
                parts.append(str(section["text"]))
    elif isinstance(ad, str):
        parts.append(ad)

    return {
        "id": make_id(company, title, url),
        "title": title,
        "company": company,
        "location": loc_str,
        "url": url,
        "description": strip_html("\n\n".join(parts)),
        "posted_at": _iso(raw.get("releasedDate")),
        "source": "smartrecruiters",
        "department": (raw.get("department") or {}).get("label", ""),
        "employment_type": (raw.get("typeOfEmployment") or {}).get("label", ""),
    }


def from_recruitee(raw: dict, company: str) -> dict:
    title = raw.get("title", "")
    url = raw.get("careers_url") or raw.get("careers_apply_url") or ""
    return {
        "id": make_id(company, title, url),
        "title": title,
        "company": company,
        "location": raw.get("location", "") or raw.get("city", "") or "",
        "url": url,
        "description": strip_html(raw.get("description")) + "\n" + strip_html(raw.get("requirements")),
        "posted_at": _iso(raw.get("published_at") or raw.get("created_at")),
        "source": "recruitee",
        "department": raw.get("department", "") or "",
        "employment_type": raw.get("employment_type_code", "") or "",
    }


def from_personio(raw: dict, company: str) -> dict:
    title = raw.get("name", "")
    job_id = raw.get("id", "")
    url = f"https://{company}.jobs.personio.de/job/{job_id}"
    return {
        "id": make_id(company, title, url),
        "title": title,
        "company": company,
        "location": raw.get("office", "") or "",
        "url": url,
        "description": strip_html(raw.get("_description", "")),
        "posted_at": _iso(raw.get("createdAt")),
        "source": "personio",
        "department": raw.get("department", "") or "",
        "employment_type": raw.get("employmentType", "") or "",
    }


def from_workday(raw: dict, company: str) -> dict:
    title = raw.get("title", "")
    tenant = raw.get("_tenant", "")
    wd = raw.get("_wd", "")
    site = raw.get("_site", "")
    path = raw.get("externalPath", "")
    url = f"https://{tenant}.wd{wd}.myworkdayjobs.com/en-US/{site}{path}"
    return {
        "id": make_id(company, title, url),
        "title": title,
        "company": company,
        "location": raw.get("locationsText", "") or "",
        "url": url,
        # The full ad when the detail fetch got it, else the list teaser.
        "description": strip_html(
            raw.get("_description")
            or (raw.get("bulletFields") and " ".join(raw["bulletFields"]))
            or ""
        ),
        "posted_at": _iso(raw.get("postedOn")),
        "source": "workday",
        "department": "",
        "employment_type": "",
    }


NORMALISERS = {
    "greenhouse": from_greenhouse,
    "lever": from_lever,
    "ashby": from_ashby,
    "workable": from_workable,
    "smartrecruiters": from_smartrecruiters,
    "recruitee": from_recruitee,
    "personio": from_personio,
    "workday": from_workday,
}


# --------------------------------------------------- additional platforms

def from_oraclecloud(raw: dict, company: str) -> dict:
    title = raw.get("Title", "")
    host = raw.get("_host", "")
    site = raw.get("_site", "")
    req_id = raw.get("Id", "")
    url = (
        f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{req_id}"
        if host else ""
    )
    locs = [raw.get("PrimaryLocation", "") or ""]
    for sl in raw.get("secondaryLocations") or []:
        if isinstance(sl, dict) and sl.get("Name"):
            locs.append(sl["Name"])
    desc = raw.get("ExternalDescriptionStr") or raw.get("ShortDescription") or ""
    return {
        "id": make_id(company, title, url),
        "title": title,
        "company": company,
        "location": ", ".join([l for l in locs if l]),
        "url": url,
        "description": strip_html(desc),
        "posted_at": _iso(raw.get("PostedDate")),
        "source": "oraclecloud",
        "department": raw.get("JobFamily", "") or "",
        "employment_type": raw.get("WorkplaceType", "") or "",
    }


def from_pinpoint(raw: dict, company: str) -> dict:
    attrs = raw.get("attributes") if isinstance(raw.get("attributes"), dict) else raw
    title = attrs.get("title", "") or raw.get("title", "")
    url = attrs.get("url") or raw.get("url") or ""
    loc = attrs.get("location") or raw.get("location") or {}
    loc_str = loc.get("name", "") if isinstance(loc, dict) else str(loc or "")
    dept = attrs.get("department") or raw.get("department") or {}
    dept_str = dept.get("name", "") if isinstance(dept, dict) else str(dept or "")
    return {
        "id": make_id(company, title, url),
        "title": title,
        "company": company,
        "location": loc_str,
        "url": url,
        "description": strip_html(attrs.get("description") or raw.get("description")),
        "posted_at": _iso(attrs.get("created_at") or raw.get("created_at")),
        "source": "pinpoint",
        "department": dept_str,
        "employment_type": attrs.get("employment_type", "") or "",
    }


def _salary(node) -> str:
    """
    schema.org baseSalary, rendered as something readable.

    The shape varies: a bare number, a MonetaryAmount wrapping a QuantitativeValue
    with min/max, or a single value. Anything unrecognisable returns "" rather
    than a half-formed string - a wrong salary is worse than no salary.
    """
    if not node:
        return ""
    if isinstance(node, (int, float)):
        return f"{node:,.0f}"
    if not isinstance(node, dict):
        return ""
    currency = node.get("currency") or node.get("currencyCode") or "EUR"
    symbol = {"EUR": "\u20ac", "GBP": "\u00a3", "USD": "$"}.get(str(currency).upper(), "")
    value = node.get("value", node)
    if isinstance(value, (int, float)):
        return f"{symbol}{value:,.0f}"
    if not isinstance(value, dict):
        return ""
    lo, hi = value.get("minValue"), value.get("maxValue")
    unit = str(value.get("unitText") or "").lower()
    suffix = {"year": "/yr", "month": "/mo", "week": "/wk",
              "day": "/day", "hour": "/hr"}.get(unit, "")
    try:
        if lo and hi and float(lo) != float(hi):
            return f"{symbol}{float(lo):,.0f}\u2013{symbol}{float(hi):,.0f}{suffix}"
        single = lo or hi or value.get("value")
        if single:
            return f"{symbol}{float(single):,.0f}{suffix}"
    except (TypeError, ValueError):
        return ""
    return ""


def from_jsonld(raw: dict, company: str) -> dict:
    """schema.org JobPosting - the Google-for-Jobs format."""
    title = raw.get("title", "") or ""

    # Location can be a dict, a list of dicts, or a plain string.
    def one_location(node) -> str:
        if isinstance(node, str):
            return node
        if isinstance(node, list):
            return ", ".join(filter(None, (one_location(n) for n in node)))
        if isinstance(node, dict):
            addr = node.get("address")
            if isinstance(addr, dict):
                bits = [
                    addr.get("addressLocality", ""),
                    addr.get("addressRegion", ""),
                    addr.get("addressCountry", "") if isinstance(addr.get("addressCountry"), str) else "",
                ]
                return ", ".join([b for b in bits if b])
            return node.get("name", "") or ""
        return ""

    location = one_location(raw.get("jobLocation"))
    if not location and raw.get("applicantLocationRequirements"):
        location = one_location(raw["applicantLocationRequirements"])
    if raw.get("jobLocationType") == "TELECOMMUTE" and "remote" not in location.lower():
        location = (location + " (Remote)").strip()

    url = raw.get("url") or raw.get("_source_url", "")
    org = raw.get("hiringOrganization")
    if isinstance(org, dict) and org.get("name"):
        company = org["name"] or company

    emp = raw.get("employmentType", "")
    if isinstance(emp, list):
        emp = ", ".join(str(e) for e in emp)

    # Graduate programmes close on a date, and a closing date matters more than
    # a posting date when you are deciding what to do this evening. Employers
    # publish it as validThrough for exactly that reason - Google shows it.
    closes = _iso(raw.get("validThrough"))

    return {
        "id": make_id(company, title, url),
        "title": title,
        "company": company,
        "location": location,
        "url": url,
        "description": strip_html(raw.get("description")),
        "posted_at": _iso(raw.get("datePosted")),
        "closes_at": closes,
        "salary": _salary(raw.get("baseSalary")),
        "source": "jsonld",
        "department": (raw.get("occupationalCategory") or "") if isinstance(raw.get("occupationalCategory"), str) else "",
        "employment_type": str(emp or ""),
    }


def from_successfactors(raw: dict, company: str) -> dict:
    """Handles both the RSS item shape and a JobPosting fallen through to here."""
    if "@type" in raw or "hiringOrganization" in raw:
        job = from_jsonld(raw, company)
        job["source"] = "successfactors"
        return job
    title = raw.get("title", "")
    url = raw.get("link", "")
    return {
        "id": make_id(company, title, url),
        "title": title,
        "company": company,
        "location": raw.get("location", "") or "",
        "url": url,
        "description": strip_html(raw.get("description")),
        "posted_at": _iso(raw.get("pubDate")),
        "source": "successfactors",
        "department": raw.get("category", "") or "",
        "employment_type": "",
    }


NORMALISERS.update({
    "oraclecloud": from_oraclecloud,
    "pinpoint": from_pinpoint,
    "jsonld": from_jsonld,
    "successfactors": from_successfactors,
})


def from_joblinks(raw: dict, company: str) -> dict:
    """
    Jobs read off individual job pages by the generic crawler.

    Two shapes arrive here: proper schema.org JobPosting (most of them), and a
    thin fallback built from the page title when a site publishes no structured
    data. The thin ones are marked so their weaker description is visible
    rather than being mistaken for a full ad.
    """
    if not raw.get("_fallback"):
        job = from_jsonld(raw, company)
        job["source"] = "joblinks"
        return job

    title = raw.get("title", "")
    url = raw.get("url", "") or raw.get("_source_url", "")
    return {
        "id": make_id(company, title, url),
        "title": title,
        "company": company,
        # Read out of the job's own URL where the site puts it there. Blank
        # still means unknown, and the Ireland filter falls back to the text.
        "location": raw.get("location", "") or "",
        "url": url,
        "description": raw.get("description", ""),
        "posted_at": "",
        "source": "joblinks",
        "department": "",
        "employment_type": "",
    }


NORMALISERS["joblinks"] = from_joblinks


def from_sitemap(raw: dict, company: str) -> dict:
    job = from_joblinks(raw, company)
    job["source"] = "sitemap"
    return job


NORMALISERS["sitemap"] = from_sitemap


def from_rssfeed(raw: dict, company: str) -> dict:
    title = raw.get("title", "")
    url = raw.get("link", "") or raw.get("_source_url", "")
    desc = raw.get("description") or raw.get("summary") or raw.get("content") or ""
    return {
        "id": make_id(company, title, url),
        "title": title,
        "company": company,
        "location": raw.get("location", "") or "",
        "url": url,
        "description": strip_html(desc),
        "posted_at": _iso(raw.get("pubDate") or raw.get("published") or raw.get("updated")),
        "source": "rssfeed",
        "department": raw.get("category", "") or "",
        "employment_type": "",
    }


def from_apiprobe(raw: dict, company: str) -> dict:
    title = raw.get("title", "")
    url = raw.get("url", "")
    return {
        "id": make_id(company, title, url),
        "title": title,
        "company": company,
        "location": raw.get("location", "") or "",
        "url": url,
        "description": strip_html(raw.get("description", "")),
        "posted_at": "",
        "source": "apiprobe",
        "department": "",
        "employment_type": "",
    }


NORMALISERS["rssfeed"] = from_rssfeed
NORMALISERS["apiprobe"] = from_apiprobe


# ------------------------------------------------- the enterprise platforms
# Every reader in ats_more already emits one common shape (id, title,
# location, url, description, posted), so they share a single normaliser
# rather than eleven near-identical ones.

def from_common(raw: dict, company: str, source: str) -> dict:
    title = (raw.get("title") or "").strip()
    url = raw.get("url") or ""
    return {
        "id": make_id(company, title, url),
        "title": title,
        "company": company,
        "location": (raw.get("location") or "").strip(),
        "url": url,
        "description": strip_html(raw.get("description") or ""),
        "posted_at": _iso(raw.get("posted")),
        "source": source,
        "department": raw.get("department", "") or "",
        "employment_type": raw.get("employment_type", "") or "",
    }


def _make_common(source: str):
    def _fn(raw: dict, company: str) -> dict:
        return from_common(raw, company, source)
    _fn.__name__ = f"from_{source}"
    return _fn


for _src in ("icims", "taleo", "avature", "cornerstone", "teamtailor", "occupop",
             "hirehive", "eightfold", "jobvite", "bamboohr", "rippling"):
    NORMALISERS[_src] = _make_common(_src)


# ---------------------------------------------------------------------------
# Every normaliser's output passes through here.
#
# Twenty-seven readers each build their own job record, and asking each to
# remember to sanitise its URL is asking for the one that forgets. Wrapping
# them once, after they are all registered, means a job with a dangerous or
# malformed link cannot exist anywhere downstream - not in jobs.json, not on
# the board, not in the Excel export. A job with no usable link is dropped by
# the filters, which is the right outcome: it is unapplyable.

def _guard_urls(fn):
    def wrapped(raw: dict, company: str) -> dict:
        job = fn(raw, company)
        if isinstance(job, dict):
            job["url"] = safe_url(job.get("url"))
        return job
    wrapped.__name__ = getattr(fn, "__name__", "normaliser")
    wrapped.__doc__ = fn.__doc__
    return wrapped


NORMALISERS = {name: _guard_urls(fn) for name, fn in NORMALISERS.items()}
