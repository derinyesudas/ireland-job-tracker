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
import re

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
}
