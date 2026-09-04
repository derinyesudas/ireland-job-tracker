"""
The enterprise and Irish-market platforms, added after the first live
resolution run showed which ones the register's employers actually use.

The eight mainstream platforms in ats_clients cover startups and scale-ups
well, but they miss most of the large Irish employers Derin is targeting -
the insurers, the banks, the professional-services firms. Those run on older
enterprise suites (iCIMS, Taleo, Avature, Cornerstone, SuccessFactors) or, at
the Irish mid-market end, on platforms that barely exist outside Ireland
(Occupop, HireHive).

Every reader here follows the same contract as the rest: take a token, return
a list of raw postings, raise FetchError rather than blowing up the run.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.parse

from scraper.ats_clients import FetchError, _get, _get_html, _post

# These were local reimplementations of helpers that already existed in
# ats_clients. The POST one additionally lacked the retry the shared version
# has, so Taleo and Cornerstone gave up on the first blip; consolidating fixes
# that as a side effect.
_text = _get_html
_post_json = _post


# --------------------------------------------------------------------- iCIMS
# Token: the subdomain, e.g. "northerntrust" for careers-northerntrust.icims.com
# iCIMS publishes a plain search page; the jobs are in the HTML as list rows.

_ICIMS_ROW_RE = re.compile(
    r'<a[^>]+href="(?P<url>[^"]*/jobs/(?P<id>\d+)/[^"]*)"[^>]*>(?P<title>[^<]{3,160})</a>', re.I
)
_ICIMS_LOC_RE = re.compile(r'"(?:job)?location"[^>]*>\s*([^<]{2,80})', re.I)


def icims(token: str) -> list[dict]:
    host = token if "." in token else f"careers-{token}.icims.com"
    if not host.startswith("http"):
        host = "https://" + host
    out: list[dict] = []
    seen: set[str] = set()
    for page in range(0, 3):
        url = f"{host.rstrip('/')}/jobs/search?ss=1&searchRelation=keyword_all&in_iframe=1&pr={page}"
        try:
            page_html = _text(url)
        except FetchError:
            break
        rows = list(_ICIMS_ROW_RE.finditer(page_html))
        if not rows:
            break
        for m in rows:
            jid = m.group("id")
            if jid in seen:
                continue
            seen.add(jid)
            link = m.group("url")
            if link.startswith("/"):
                link = host.rstrip("/") + link
            out.append({
                "id": jid,
                "title": html.unescape(m.group("title")).strip(),
                "url": link,
                "location": "",
                "description": "",
            })
        if len(rows) < 10:
            break
    if not out:
        raise FetchError("icims: no rows")
    return out


# --------------------------------------------------------------------- Taleo
# Token: "<host>|<org>" e.g. "aviva.taleo.net|AVIVA".

def taleo(token: str) -> list[dict]:
    host, _, org = token.partition("|")
    host = host.replace("https://", "").replace("http://", "").strip("/")
    org = org or host.split(".")[0]
    url = (f"https://{host}/careersection/rest/jobboard/searchjobs"
           f"?lang=en&portal=101430233")
    payload = {
        "multilineEnabled": False, "sortingSelection": {
            "sortBySelectionParam": "3", "ascendingSortingOrder": "false"},
        "fieldData": {"fields": {"KEYWORD": "", "LOCATION": ""}, "valid": True},
        "filterSelectionParam": {"searchFilterSelections": []},
        "advancedSearchFiltersSelectionParam": {"searchFilterSelections": []},
        "pageNo": 1,
    }
    data = _post_json(url, payload)
    rows = (((data or {}).get("requisitionList")) or [])
    out = []
    for r in rows:
        cols = r.get("column") or []
        out.append({
            "id": str(r.get("jobId") or r.get("contestNo") or ""),
            "title": (cols[0] if cols else "") or r.get("title", ""),
            "location": cols[1] if len(cols) > 1 else "",
            "url": f"https://{host}/careersection/jobdetail.ftl?job={r.get('contestNo','')}",
            "description": "",
            "posted": r.get("postedDate", ""),
        })
    if not out:
        raise FetchError("taleo: empty")
    return out


# ------------------------------------------------------------------- Avature
# PwC and several other professional-services firms run on Avature.
# Token: the careers host, e.g. "pwc.avature.net" or a full careers URL.

_AV_JSON_RE = re.compile(r'<script[^>]+type="application/json"[^>]*>(.*?)</script>', re.S | re.I)


def avature(token: str) -> list[dict]:
    base = token if token.startswith("http") else f"https://{token}"
    out: list[dict] = []
    for path in ("/careers/SearchJobs?jobOffset=0&jobRecordsPerPage=100",
                 "/careers/SearchJobs", ""):
        try:
            page = _text(base.rstrip("/") + path)
        except FetchError:
            continue
        for m in re.finditer(
            r'<a[^>]+href="(?P<u>[^"]*/JobDetail[^"]*)"[^>]*>\s*(?P<t>[^<]{3,160})</a>',
            page, re.I,
        ):
            link = m.group("u")
            if link.startswith("/"):
                link = base.rstrip("/") + link
            out.append({
                "id": link.rsplit("/", 1)[-1][:60],
                "title": html.unescape(m.group("t")).strip(),
                "url": link, "location": "", "description": "",
            })
        if out:
            break
    if not out:
        raise FetchError("avature: no job links")
    # de-duplicate, keeping order
    seen, uniq = set(), []
    for j in out:
        if j["url"] in seen:
            continue
        seen.add(j["url"])
        uniq.append(j)
    return uniq


# --------------------------------------------------------------- Cornerstone
# Token: the subdomain, e.g. "kerrygroup" for kerrygroup.csod.com

def cornerstone(token: str) -> list[dict]:
    host = token if "." in token else f"{token}.csod.com"
    host = host.replace("https://", "").strip("/")
    url = (f"https://{host}/services/x/career-site/v1/search"
           f"?page=1&pageSize=100")
    try:
        data = _post_json(url, {"careerSiteId": 1, "cultureId": 1, "search": "",
                                "sortBy": "", "pageNumber": 1, "pageSize": 100})
    except FetchError:
        data = _get(f"https://{host}/services/x/career-site/v1/sites")
    rows = []
    if isinstance(data, dict):
        rows = (data.get("data", {}).get("requisitions")
                or data.get("requisitions") or data.get("data") or [])
    if not isinstance(rows, list) or not rows:
        raise FetchError("cornerstone: empty")
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        out.append({
            "id": str(r.get("requisitionId") or r.get("id") or ""),
            "title": r.get("displayJobTitle") or r.get("title") or "",
            "location": ", ".join(
                filter(None, [(r.get("locations") or [{}])[0].get("city", ""),
                              (r.get("locations") or [{}])[0].get("country", "")])
            ) if isinstance(r.get("locations"), list) else str(r.get("location", "")),
            "url": f"https://{host}/ux/ats/careersite/1/requisition/{r.get('requisitionId','')}",
            "description": r.get("description", "") or r.get("externalDescription", ""),
            "posted": r.get("postedDate", ""),
        })
    return out


# --------------------------------------------------------------- Teamtailor

def teamtailor(token: str) -> list[dict]:
    host = token if "." in token else f"{token}.teamtailor.com"
    host = host.replace("https://", "").strip("/")
    page = _text(f"https://{host}/jobs")
    out = []
    for m in re.finditer(r'<a[^>]+href="(?P<u>https?://[^"]*/jobs/[^"]+)"[^>]*>(?P<t>.{3,200}?)</a>',
                         page, re.S | re.I):
        title = re.sub(r"<[^>]+>", " ", m.group("t"))
        title = html.unescape(re.sub(r"\s+", " ", title)).strip()
        if not title or len(title) > 160:
            continue
        out.append({"id": m.group("u").rsplit("/", 1)[-1], "title": title,
                    "url": m.group("u"), "location": "", "description": ""})
    if not out:
        raise FetchError("teamtailor: none")
    seen, uniq = set(), []
    for j in out:
        if j["url"] in seen:
            continue
        seen.add(j["url"]); uniq.append(j)
    return uniq


# ---------------------------------------------------------------- Occupop
# An Irish platform - a lot of the mid-market employers in the register use it.

def occupop(token: str) -> list[dict]:
    slug = token.strip("/").split("/")[-1]
    for url in (f"https://api.occupop.com/api/v1/public/company/{slug}/jobs",
                f"https://app.occupop.com/api/careers/{slug}/jobs"):
        try:
            data = _get(url)
        except Exception:  # noqa: BLE001
            continue
        rows = data if isinstance(data, list) else (data or {}).get("jobs", [])
        if rows:
            return [{
                "id": str(r.get("id") or r.get("uuid") or ""),
                "title": r.get("title") or r.get("job_title") or "",
                "location": r.get("location") or r.get("city") or "",
                "url": r.get("url") or r.get("apply_url") or "",
                "description": r.get("description") or "",
                "posted": r.get("created_at") or r.get("published_at") or "",
            } for r in rows if isinstance(r, dict)]
    raise FetchError("occupop: no feed")


# ---------------------------------------------------------------- HireHive
# Another Irish platform. It publishes a clean public JSON feed.

def hirehive(token: str) -> list[dict]:
    host = token if "." in token else f"{token}.hirehive.com"
    host = host.replace("https://", "").strip("/")
    for url in (f"https://{host}/api/v1/jobs", f"https://{host}/jobs.json"):
        try:
            data = _get(url)
        except Exception:  # noqa: BLE001
            continue
        rows = data if isinstance(data, list) else (data or {}).get("jobs", [])
        if rows:
            return [{
                "id": str(r.get("id") or ""),
                "title": r.get("title") or r.get("name") or "",
                "location": (r.get("location") or {}).get("name", "")
                if isinstance(r.get("location"), dict) else (r.get("location") or ""),
                "url": r.get("url") or r.get("publicUrl") or f"https://{host}",
                "description": r.get("description") or "",
                "posted": r.get("publishedDate") or r.get("createdDate") or "",
            } for r in rows if isinstance(r, dict)]
    raise FetchError("hirehive: no feed")


# ---------------------------------------------------------------- Eightfold

def eightfold(token: str) -> list[dict]:
    slug = token.replace("https://", "").strip("/").split("/")[0].split(".")[0]
    url = (f"https://api.eightfold.ai/api/apply/v2/jobs"
           f"?domain={slug}.com&start=0&num=100&sort_by=timestamp")
    data = _get(url)
    rows = (data or {}).get("positions") or []
    if not rows:
        raise FetchError("eightfold: empty")
    return [{
        "id": str(r.get("id") or ""),
        "title": r.get("name", ""),
        "location": r.get("location", ""),
        "url": r.get("canonicalPositionUrl") or r.get("applyUrl") or "",
        "description": r.get("job_description", "") or r.get("description", ""),
        "posted": r.get("t_create", ""),
    } for r in rows]


# ------------------------------------------------------------------- Jobvite

def jobvite(token: str) -> list[dict]:
    data = _get(f"https://jobs.jobvite.com/api/v1/company/{token}/jobs")
    rows = (data or {}).get("jobs") or (data if isinstance(data, list) else [])
    if not rows:
        raise FetchError("jobvite: empty")
    return [{
        "id": str(r.get("eId") or r.get("id") or ""),
        "title": r.get("title", ""),
        "location": r.get("location", ""),
        "url": r.get("applyUrl") or r.get("url") or "",
        "description": r.get("description", ""),
        "posted": r.get("date", ""),
    } for r in rows if isinstance(r, dict)]


# ------------------------------------------------------------------ BambooHR

def bamboohr(token: str) -> list[dict]:
    slug = token.replace("https://", "").split(".")[0]
    data = _get(f"https://{slug}.bamboohr.com/careers/list")
    rows = (data or {}).get("result") or []
    if not rows:
        raise FetchError("bamboohr: empty")
    out = []
    for r in rows:
        loc = r.get("location") or {}
        out.append({
            "id": str(r.get("id", "")),
            "title": r.get("jobOpeningName", ""),
            "location": ", ".join(filter(None, [loc.get("city", ""), loc.get("state", ""),
                                                loc.get("country", "")])) if isinstance(loc, dict) else "",
            "url": f"https://{slug}.bamboohr.com/careers/{r.get('id','')}",
            "description": "",
            "posted": r.get("datePosted", ""),
        })
    return out


# ------------------------------------------------------------------- Rippling

def rippling(token: str) -> list[dict]:
    data = _get(f"https://api.rippling.com/platform/api/ats/v1/board/{token}/jobs")
    rows = data if isinstance(data, list) else (data or {}).get("items", [])
    if not rows:
        raise FetchError("rippling: empty")
    return [{
        "id": str(r.get("uuid") or r.get("id") or ""),
        "title": r.get("name", ""),
        "location": (r.get("workLocation") or {}).get("label", "")
        if isinstance(r.get("workLocation"), dict) else "",
        "url": r.get("url") or f"https://ats.rippling.com/{token}/jobs/{r.get('uuid','')}",
        "description": r.get("descriptionHtml", "") or r.get("description", ""),
        "posted": "",
    } for r in rows if isinstance(r, dict)]


# -------------------------------------------------------------------- Phenom
# Phenom People, the branded careers-site platform behind several of the very
# large employers in the register - careers.marsh.com serves both Marsh Ireland
# and Mercer Ireland, and Mastercard and Fiserv run on it too.
#
# Nothing in the careers URL gives the platform away: the host is the
# employer's own and the branding is theirs. The tell is in the page source,
# where the assets come off cdn-prod-static.phenompeople.com.
#
# Token: "<careers-host>" or "<careers-host>|<domain>", e.g.
#     "careers.marsh.com|marsh.com"
#     "careers.mastercard.com"
# Phenom keys its search on a `domain` parameter, which is usually the host
# minus its "careers." label but is not always - one careers host can serve
# several employer domains, which is exactly the careers.marsh.com case. So the
# caller can supply both, and when they only give the host we try the derived
# domain and then the host itself.

_PHENOM_PAGE = 50
_PHENOM_MAX_JOBS = 1000
_PHENOM_MAX_PAGES = 25

# Tried in order; the first that returns jobs wins and is the one paged
# through. The second is the first with the sort dropped, for deployments that
# reject a sort key they do not know rather than ignoring it.
_PHENOM_ENDPOINTS = (
    "https://{host}/api/apply/v2/jobs?domain={domain}&start={start}&num={num}&sortBy=relevance",
    "https://{host}/api/apply/v2/jobs?domain={domain}&start={start}&num={num}",
    "https://{host}/widgets?type=jobs&domain={domain}&start={start}&num={num}",
)

# Where the jobs array lives. Deployments disagree, so probe the known shapes
# in order rather than assuming one; `refineSearch` and `eagerLoadRefineSearch`
# are the shapes Phenom's own front end reads.
_PHENOM_JOB_PATHS = (
    ("jobs",),
    ("refineSearch", "data", "jobs"),
    ("eagerLoadRefineSearch", "data", "jobs"),
    ("data", "jobs"),
    ("data", "refineSearch", "data", "jobs"),
    ("results",),
    ("jobList",),
    ("positions",),
    ("hits",),
)

# Host labels that are the careers site rather than part of the employer's
# domain. Only these are stripped - taking the last two labels instead would
# turn careers.example.co.uk into "co.uk".
_PHENOM_HOST_PREFIXES = ("careers", "career", "jobs", "job", "apply", "talent",
                         "recruiting", "recruitment", "join", "www")

_PHENOM_TITLE_KEYS = ("title", "jobTitle", "name", "postingTitle")
_PHENOM_ID_KEYS = ("jobId", "ats_job_id", "jobSeqNo", "id", "reqId",
                   "requisitionId", "displayJobId")
# For building a link when the row carries none. Phenom's job pages are keyed
# on the long external id rather than the short requisition number - the Fiserv
# row already on the board proves the shape:
#   careers.fiserv.com/us/en/job/FFFYJUSR10399755EXTERNALENUS/SME-Payments-Consultant
_PHENOM_URL_ID_KEYS = ("ats_job_id", "jobSeqNo", "jobId", "id")
_PHENOM_URL_KEYS = ("applyUrl", "jobUrl", "canonicalUrl", "canonicalPositionUrl",
                    "url", "detailUrl", "applyUrlNew", "link")
_PHENOM_LOC_KEYS = ("location", "cityState", "locationName", "primaryLocation",
                    "multi_location", "locations")
_PHENOM_DESC_KEYS = ("description", "jobDescription", "descriptionTeaser",
                     "shortDescription", "jobSummary", "summary")
_PHENOM_POSTED_KEYS = ("postedDate", "posted_date", "datePosted", "dateCreated",
                       "createDate", "postedOn", "originalPostingDate")
_PHENOM_CLOSES_KEYS = ("expiryDate", "validThrough", "jobEndDate", "closingDate",
                       "applyEndDate", "postingEndDate")
_PHENOM_DEPT_KEYS = ("category", "department", "jobFamily", "businessUnit",
                     "subCategory")
_PHENOM_TYPE_KEYS = ("type", "employmentType", "jobType", "employment_type",
                     "scheduleType")


def _phenom_str(row: dict, keys: tuple) -> str:
    """First non-empty value across a set of keys, flattening the usual nesting."""
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
        if isinstance(value, dict):
            for inner in ("name", "label", "text", "value", "city"):
                if isinstance(value.get(inner), str) and value[inner].strip():
                    return value[inner].strip()
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    return item.strip()
                if isinstance(item, dict):
                    for inner in ("name", "label", "text", "city"):
                        if isinstance(item.get(inner), str) and item[inner].strip():
                            return item[inner].strip()
    return ""


def _phenom_date(row: dict, keys: tuple):
    """
    A date as the feed gave it - a number stays a number.

    normalise._iso reads epoch milliseconds, but only out of an int or a float,
    so passing one through _phenom_str and stringifying it would turn a
    perfectly good date into thirteen digits of raw text. Deployments that send
    the epoch as a string get converted back for the same reason.
    """
    for key in keys:
        value = row.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and value > 0:
            return value
        if isinstance(value, str) and value.strip():
            text = value.strip()
            return int(text) if text.isdigit() and len(text) >= 10 else text
    return ""


def _phenom_dig(node, path: tuple) -> list:
    for key in path:
        if not isinstance(node, dict):
            return []
        node = node.get(key)
    return node if isinstance(node, list) else []


def _phenom_rows(data) -> list[dict]:
    """Find the jobs array in whatever shape this deployment answered with."""
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if not isinstance(data, dict):
        return []
    for path in _PHENOM_JOB_PATHS:
        rows = [r for r in _phenom_dig(data, path) if isinstance(r, dict)]
        if rows:
            return rows
    # An unfamiliar shape. ats_extra's generic walk already knows how to find a
    # job array in one, so use it rather than growing a second copy - imported
    # inside the function because ats_more and ats_extra are both pulled in by
    # ats_clients, and a module-level import either way round is circular.
    try:
        from scraper.ats_extra import _find_job_array
    except ImportError:  # pragma: no cover
        return []
    return _find_job_array(data)


def _phenom_abs(host: str, link: str) -> str:
    link = (link or "").strip()
    if link.startswith(("http://", "https://")):
        return link
    if link.startswith("//"):
        return "https:" + link
    if link.startswith("/"):
        return f"https://{host}{link}"
    return ""


def _phenom_location(row: dict) -> str:
    found = _phenom_str(row, _PHENOM_LOC_KEYS)
    if found:
        return found
    bits = [row.get("city"), row.get("state"), row.get("country")]
    return ", ".join(b.strip() for b in bits if isinstance(b, str) and b.strip())


def _phenom_description(row: dict) -> str:
    """
    The longest description the row carries.

    Phenom sends `descriptionTeaser` - one sentence - alongside a `description`
    that is sometimes the whole ad and sometimes absent. Taking the first key
    that exists would score a lot of these jobs on a single line, which is the
    same mistake SmartRecruiters and Workday cost us, so take whichever is
    actually longer.
    """
    best = ""
    for key in _PHENOM_DESC_KEYS:
        value = row.get(key)
        if isinstance(value, str) and len(value.strip()) > len(best):
            best = value.strip()
    return best


def _phenom_salary(row: dict):
    """
    Whatever pay information the row carries, or "".

    A ready-made string is passed straight through; a min/max pair is handed on
    in the schema.org shape normalise._salary already renders. A pair with no
    currency is deliberately NOT sent that way - _salary assumes euro when none
    is given, and a US requisition priced in euro is worse than no salary.
    """
    text = _phenom_str(row, ("salaryRange", "salary_range", "payRange",
                             "salaryText", "compensation"))
    if text:
        return text
    lo = row.get("minSalary") or row.get("salaryMin") or row.get("payMin")
    hi = row.get("maxSalary") or row.get("salaryMax") or row.get("payMax")
    currency = _phenom_str(row, ("currency", "salaryCurrency", "payCurrency"))
    if not currency or not (lo or hi):
        return ""
    unit = _phenom_str(row, ("salaryPeriod", "payFrequency", "salaryInterval"))
    return {"currency": currency,
            "value": {"minValue": lo, "maxValue": hi, "unitText": unit}}


def _phenom_job(host: str, row: dict) -> dict | None:
    # Some deployments wrap the posting a level down instead of inlining it.
    if not _phenom_str(row, _PHENOM_TITLE_KEYS):
        for key in ("job", "data", "jobData"):
            if isinstance(row.get(key), dict) and _phenom_str(row[key], _PHENOM_TITLE_KEYS):
                row = row[key]
                break

    title = html.unescape(_phenom_str(row, _PHENOM_TITLE_KEYS))
    if not title:
        return None
    ident = _phenom_str(row, _PHENOM_ID_KEYS)
    link = ""
    for key in _PHENOM_URL_KEYS:
        link = _phenom_abs(host, row.get(key) if isinstance(row.get(key), str) else "")
        if link:
            break
    if not link:
        # Phenom's own job pages sit at /<country>/<lang>/job/<id>/<slug>, but
        # the locale segment differs per deployment (Fiserv serves /us/en,
        # Marsh /global/en), so build the locale-free form and let the site
        # redirect. A job with no link at all is dropped by the filters.
        url_ident = _phenom_str(row, _PHENOM_URL_ID_KEYS)
        link = f"https://{host}/job/{url_ident}" if url_ident else ""
    return {
        "id": ident,
        "title": title,
        "location": _phenom_location(row),
        "url": link,
        "description": _phenom_description(row),
        "posted": _phenom_date(row, _PHENOM_POSTED_KEYS),
        "closes": _phenom_date(row, _PHENOM_CLOSES_KEYS),
        "salary": _phenom_salary(row),
        "department": _phenom_str(row, _PHENOM_DEPT_KEYS),
        "employment_type": _phenom_str(row, _PHENOM_TYPE_KEYS),
    }


def _phenom_domains(host: str) -> list[str]:
    """The domain to search on, most likely first."""
    out: list[str] = []
    bits = host.split(".")
    if len(bits) > 2 and bits[0].lower() in _PHENOM_HOST_PREFIXES:
        out.append(".".join(bits[1:]))
    out.append(host)
    return out


def _phenom_page(host: str, domain: str, template: str, rows: list[dict]) -> list[dict]:
    """Walk the endpoint that answered, starting from the page already fetched."""
    out: list[dict] = []
    seen: set[str] = set()
    start = 0
    for _ in range(_PHENOM_MAX_PAGES):
        added = 0
        for row in rows:
            job = _phenom_job(host, row)
            if not job:
                continue
            key = job["url"] or job["id"]
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(job)
            added += 1
        # Advance by the number of rows the server actually sent, not by the
        # page size we asked for. Deployments cap `num` at their own figure and
        # simply return fewer, and stepping on by 50 regardless would skip
        # every job between the cap and the next page.
        start += len(rows)
        if not added or len(out) >= _PHENOM_MAX_JOBS:
            break
        try:
            data = _get(template.format(host=host, domain=domain,
                                        start=start, num=_PHENOM_PAGE))
        except FetchError:
            break  # a failure mid-pagination must not throw away the pages we have
        rows = _phenom_rows(data)
        if not rows:
            break
    return out


def phenom(token: str) -> list[dict]:
    host, _, domain = token.partition("|")
    host = host.replace("https://", "").replace("http://", "").strip("/").split("/")[0]
    domain = domain.replace("https://", "").replace("http://", "").strip("/").split("/")[0]
    if not host:
        raise FetchError("phenom: token must be '<careers-host>' or '<careers-host>|<domain>'")
    domains = [domain] if domain else _phenom_domains(host)

    tried = 0
    last_err = ""
    for dom in domains:
        for template in _PHENOM_ENDPOINTS:
            tried += 1
            try:
                data = _get(template.format(host=host, domain=dom,
                                            start=0, num=_PHENOM_PAGE))
            except FetchError as exc:
                last_err = str(exc)
                continue
            rows = _phenom_rows(data)
            if not rows:
                # An empty array here usually means the domain is wrong rather
                # than that the employer has no vacancies, so keep going.
                last_err = last_err or f"no jobs array for domain '{dom}'"
                continue
            jobs = _phenom_page(host, dom, template, rows)
            if jobs:
                return jobs
    raise FetchError(
        f"phenom: {tried} endpoint variants on {host} "
        f"(domains tried: {', '.join(domains)}) returned no jobs"
        + (f"; last error: {last_err}" if last_err else "")
    )


# In the MORE_FETCHERS registry at the foot of ats_more.py, add:
#
#     "phenom": phenom,


# ============================================================================


# --------------------------------------------------------------- TalentBrew
# Radancy's TalentBrew: the careers-site platform a lot of very large
# employers run behind their own branding. In this register it is Citi
# (jobs.citi.com). The give-away is that the page loads its assets from
# tbcdn.talentbrew.com while every endpoint it calls sits on the employer's
# own host, so the token here is just that host:
#
#     "jobs.citi.com"           - search the whole board
#     "jobs.citi.com|Ireland"   - pin the location filter, instead of the
#                                 Ireland-then-everything ladder below
#
# The job list is drawn by /search-jobs/results, which answers with JSON whose
# "results" key holds a chunk of already-rendered HTML - the rows of the list
# - next to a count of the hits. So this reader is half JSON client, half
# HTML scraper: read the JSON, then pull the rows out of the fragment the
# same way the readers in ats_extra pull job links out of a careers page.

_TB_SEARCH_PATHS = ("/search-jobs/results", "/en/search-jobs/results")
_TB_RECORDS_PER_PAGE = 100
_TB_MAX_PAGES = 45          # the same per-company ceiling joblinks works to
_TB_DESCRIPTION_CAP = 40

# Tenants differ on what they call the markup and the count that goes with it.
# Looked up against a lower-cased copy of the response, so casing varies free.
_TB_FRAGMENT_KEYS = ("results", "resultshtml", "resulthtml", "html",
                     "searchresults", "jobs")
_TB_TOTAL_KEYS = ("hits", "totalhits", "totalcount", "totalresults",
                  "resultcount", "count")

# The row's own opening tag is captured separately: tenants that carry the id,
# the location or the date as data- attributes hang them on the <li> itself,
# and a pattern that keeps only the tag's contents throws all three away.
_TB_ROW_RE = re.compile(r"<li\b(?P<attrs>[^>]*)>(?P<row>.*?)</li\s*>", re.S | re.I)
_TB_ANCHOR_RE = re.compile(
    r'<a\b[^>]*\bhref=["\'](?P<url>[^"\']+)["\'][^>]*>(?P<inner>.*?)</a\s*>', re.S | re.I
)
# A link to one posting, as opposed to a facet, a sort order or a job alert -
# those live in the same list markup. "/search-jobs/" does not match: the
# characters before "jobs" there are "h-", not a slash.
_TB_JOB_HREF_RE = re.compile(r"/job[/?]|/jobs/|jobid=", re.I)
_TB_ID_RE = re.compile(r'data-(?:job-)?id=["\']([^"\']{1,60})["\']', re.I)
_TB_HEADING_RE = re.compile(r"<(h[1-6])\b[^>]*>(?P<t>.*?)</\1\s*>", re.S | re.I)
_TB_LOC_ATTR_RE = re.compile(
    r'data-(?:job-)?(?:location|city)=["\']([^"\']{2,120})["\']', re.I
)
_TB_DATE_ATTR_RE = re.compile(r'data-[a-z-]*date[a-z-]*=["\']([^"\']{4,40})["\']', re.I)


def _tb_class_re(word: str) -> "re.Pattern[str]":
    """An element whose class mentions `word`, closed by its own tag name."""
    return re.compile(
        r'<(span|div|p|h[1-6]|li|td)\b[^>]*class=["\'][^"\']*' + word
        + r'[^"\']*["\'][^>]*>(?P<t>.*?)</\1\s*>',
        re.S | re.I,
    )


_TB_TITLE_CLASS_RE = _tb_class_re("title")
_TB_LOCATION_CLASS_RE = _tb_class_re("location")
_TB_DATE_CLASS_RE = _tb_class_re("date")


def _tb_text(fragment: str) -> str:
    """Tags out, entities decoded, whitespace collapsed."""
    text = re.sub(r"<[^>]+>", " ", fragment or "")
    return html.unescape(html.unescape(re.sub(r"\s+", " ", text))).strip()


def _tb_abs(host: str, href: str) -> str:
    """Absolute https link for an href that is usually root-relative."""
    href = (href or "").strip()
    if not href or href.lower().startswith(("mailto:", "tel:", "javascript:", "#")):
        return ""
    if href.startswith("//"):
        href = "https:" + href
    return urllib.parse.urljoin(f"https://{host}/", href)


def _tb_unwrap(data) -> tuple[str, int, bool]:
    """
    Pull the results markup and the hit count out of whatever came back.

    Accepts the parsed JSON, a JSON string, or a page of HTML, because the
    same endpoint gives all three depending on the tenant and on whether the
    request looked like the page's own XHR.

    The third value says whether the response was RECOGNISED, which is not the
    same as whether it carried jobs. The last page of a search answers with an
    empty results string, and that is an answer - reading it as a failure
    would send the reader off trying the other request shapes at the end of
    every pagination.
    """
    if isinstance(data, str):
        stripped = data.lstrip()
        if stripped[:1] not in ("{", "["):
            # Already the markup - trust it only if it holds a job link, so an
            # error page or a cookie wall does not read as an empty board.
            return data, 0, bool(_TB_JOB_HREF_RE.search(data))
        try:
            data = json.loads(stripped)
        except ValueError:
            return data, 0, bool(_TB_JOB_HREF_RE.search(data))
    if not isinstance(data, dict):
        return "", 0, False

    lowered = {k.lower(): v for k, v in data.items() if isinstance(k, str)}

    fragment = ""
    for key in _TB_FRAGMENT_KEYS:
        value = lowered.get(key)
        # "<" guards against a tenant whose "results" is a status word, and
        # against a list of job dicts being mistaken for markup.
        if isinstance(value, str) and "<" in value:
            fragment = value
            break

    total = 0
    for key in _TB_TOTAL_KEYS:
        value = lowered.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            total = int(value)
            break
        if isinstance(value, str) and value.replace(",", "").strip().isdigit():
            total = int(value.replace(",", "").strip())
            break

    known = any(key in lowered for key in _TB_FRAGMENT_KEYS + _TB_TOTAL_KEYS)
    return fragment, total, known


def _tb_rows(host: str, fragment: str) -> list[dict]:
    """Read one page of results markup into raw postings."""
    blocks = [(m.group("attrs"), m.group("row")) for m in _TB_ROW_RE.finditer(fragment)]
    if not blocks:
        # Some tenants render the list as bare anchors, and the HTML fallback
        # in _tb_fetch can hand us a whole page rather than a fragment.
        # Treating each anchor as its own row covers both.
        blocks = [("", m.group(0)) for m in _TB_ANCHOR_RE.finditer(fragment)]

    out: list[dict] = []
    for attrs, block in blocks:
        # Class-named elements are looked for in the row's CONTENTS only, so
        # that a row whose own class happens to read "...title..." cannot
        # return the entire card as the title. Attributes are looked for in
        # the opening tag as well, which is where they usually live.
        scope = attrs + " " + block
        anchor = _TB_ANCHOR_RE.search(block)
        if not anchor:
            continue
        href = anchor.group("url")
        if not _TB_JOB_HREF_RE.search(href):
            continue
        link = _tb_abs(host, href)
        if not link:
            continue

        title = ""
        for pattern in (_TB_HEADING_RE, _TB_TITLE_CLASS_RE):
            m = pattern.search(block)
            if m:
                title = _tb_text(m.group("t"))
                if title:
                    break
        if not title:
            # An anchor wrapping the whole card runs title, location and date
            # together, so only keep that when it is short enough to be a
            # title on its own.
            title = _tb_text(anchor.group("inner"))
        if not title or len(title) > 160:
            continue

        location = ""
        m = _TB_LOCATION_CLASS_RE.search(block)
        if m:
            location = _tb_text(m.group("t"))
        if not location:
            m = _TB_LOC_ATTR_RE.search(scope)
            location = html.unescape(m.group(1)).strip() if m else ""

        posted = ""
        m = _TB_DATE_CLASS_RE.search(block)
        if m:
            posted = _tb_text(m.group("t"))
        if not posted:
            m = _TB_DATE_ATTR_RE.search(scope)
            posted = m.group(1).strip() if m else ""

        m = _TB_ID_RE.search(scope)
        jid = m.group(1) if m else link.rstrip("/").rsplit("/", 1)[-1][:60]

        out.append({
            "id": jid,
            "title": title,
            "location": location[:120],
            "url": link,
            "description": "",
            "posted": posted[:40],
        })
    return out


def _tb_fetch(url: str, base: str, params: dict, referer: str,
              mode: str) -> tuple[str, int, str]:
    """
    Read one page of results, and remember how this tenant likes to answer.

    The documented route is a GET that returns JSON, but the platform also
    exposes a POST twin at /search-jobs/resultspost, and a tenant that does
    not recognise the request as the page's own XHR will hand back rendered
    HTML instead. Whichever worked is passed back so the rest of the
    pagination goes straight to it rather than failing its way down the list
    on every page.
    """
    if mode in ("json", "html"):
        if mode == "json":
            try:
                data = _get(url, headers={"X-Requested-With": "XMLHttpRequest",
                                          "Referer": referer})
            except FetchError:
                data = None
            fragment, hits, known = _tb_unwrap(data)
            if known:
                return fragment, hits, "json"
        try:
            body = _text(url, accept="application/json, text/javascript, */*;q=0.01")
        except FetchError:
            body = ""
        fragment, hits, known = _tb_unwrap(body)
        # Once a tenant has been seen answering in HTML, an empty page is the
        # end of the list rather than a reason to go looking for another shape.
        if known or (mode == "html" and body):
            return fragment, hits, "html"

    fragment, hits, known = _tb_unwrap(_post_json(base + "post", params))
    if not known:
        raise FetchError("talentbrew: no results markup in the response")
    return fragment, hits, "post"


def _tb_search(host: str, path: str, location: str) -> list[dict]:
    """Walk one search from page one to the end of its results."""
    base = f"https://{host}{path}"
    referer = f"https://{host}/search-jobs"
    out: list[dict] = []
    seen: set[str] = set()
    first_page_rows = 0
    total = 0
    mode = "json"

    for page in range(1, _TB_MAX_PAGES + 1):
        params = {
            "ActiveFacetID": 0,
            "CurrentPage": page,
            "RecordsPerPage": _TB_RECORDS_PER_PAGE,
            "Distance": 50,
            "RadiusUnitType": 0,
            "Keyword": "",
            "Location": location,
            "ShowRadius": "False",
            "IsPagination": "True" if page > 1 else "False",
        }
        url = f"{base}?{urllib.parse.urlencode(params)}"
        try:
            fragment, hits, mode = _tb_fetch(url, base, params, referer, mode)
        except FetchError:
            # A blip half way through pagination should not throw away the
            # pages already read - the same rule the Workday pager works to.
            break

        rows = _tb_rows(host, fragment)
        fresh = [r for r in rows if r["url"] not in seen]
        for row in fresh:
            seen.add(row["url"])
        out.extend(fresh)
        if hits:
            total = hits

        # Stop on the first page that adds nothing new. A tenant that ignores
        # CurrentPage answers every request with page one, and without this
        # the reader would fetch the same rows forty-five times.
        if not fresh:
            break
        if page == 1:
            first_page_rows = len(rows)
        # RecordsPerPage is a request, not a promise: a tenant clamps it to
        # whatever its site is configured for. So the end-of-list signal is a
        # page SHORTER THAN THE FIRST ONE, not shorter than what we asked for
        # - the latter would stop every clamped tenant after a single page.
        elif len(rows) < first_page_rows:
            break
        if total and len(out) >= total:
            break
        time.sleep(0.25)

    return out


def _tb_add_descriptions(jobs: list[dict], cap: int = _TB_DESCRIPTION_CAP) -> None:
    """
    Fill in the advert text from each posting's own page.

    The results fragment carries a title, a location and a link and nothing
    else - the same gap that had Workday, Oracle and SmartRecruiters postings
    scored on their title alone until each of those readers went back for the
    full ad. TalentBrew renders the individual job pages server-side, so the
    text is there to be read.

    Best effort by construction: anything that fails leaves the posting
    exactly as the list gave it.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    try:
        from scraper.ats_extra import _readable_text
    except ImportError:  # pragma: no cover
        return

    def add(job: dict) -> None:
        try:
            page = _text(job["url"])
        except FetchError:
            return
        text = _readable_text(page)
        if len(text) > 200:
            job["description"] = text

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(as_completed([pool.submit(add, j) for j in jobs[:cap]]))


def talentbrew(token: str) -> list[dict]:
    """
    Radancy TalentBrew. Token is the careers host, optionally "host|location".
    """
    host, _, pinned = token.partition("|")
    host = host.replace("https://", "").replace("http://", "").strip("/")
    host = host.split("/")[0].strip()
    if not host or "." not in host:
        raise FetchError("talentbrew: token must be the careers host, "
                         "e.g. 'jobs.citi.com'")

    # Same reasoning as the Workday client: these are global employers with
    # thousands of vacancies and only the Irish ones are ever wanted, so ask
    # the board to narrow first and walk the whole thing only if that comes
    # back empty.
    locations = [pinned.strip()] if pinned.strip() else ["Ireland", ""]

    for path in _TB_SEARCH_PATHS:
        for location in locations:
            jobs = _tb_search(host, path, location)
            if jobs:
                _tb_add_descriptions(jobs)
                return jobs

    raise FetchError("talentbrew: no job rows in the search results")


# ===========================================================================
# normalise.py
#
# Every ats_more reader already emits the common raw shape (id, title,
# location, url, description, posted), so TalentBrew needs no normaliser of
# its own - only its name in the list that from_common is registered for.
#
# In normalise.py, add "talentbrew" to the existing tuple:
#
#     for _src in ("icims", "taleo", "avature", "cornerstone", "teamtailor",
#                  "occupop", "hirehive", "eightfold", "jobvite", "bamboohr",
#                  "rippling", "talentbrew"):
#


MORE_FETCHERS = {
    "icims": icims,
    "taleo": taleo,
    "avature": avature,
    "cornerstone": cornerstone,
    "teamtailor": teamtailor,
    "occupop": occupop,
    "hirehive": hirehive,
    "eightfold": eightfold,
    "jobvite": jobvite,
    "bamboohr": bamboohr,
    "rippling": rippling,
    "phenom": phenom,
    "talentbrew": talentbrew,
}
