"""
Fetch job postings straight from the applicant-tracking systems that companies
run their own careers pages on.

Why this approach rather than scraping LinkedIn or Indeed:
  * These are the companies' OWN public job feeds - the same JSON their careers
    page uses to draw itself. Reading them is allowed and stable.
  * No login, no API key, no proxies, nothing to get blocked.
  * We get the job the moment the company publishes it, rather than waiting for
    an aggregator to pick it up.

Each function takes a board token (the company's slug on that platform) and
returns a list of raw postings. Normalisation happens in normalise.py.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

# A number of large employers' career sites reject anything that doesn't look
# like a browser - the first live run got HTTP 403 from 16 of them, including
# TCS and AXA. These are ordinary public careers pages, so we present as a
# normal browser and keep the project's identity in a separate header rather
# than pretending to be nobody.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-IE,en-GB;q=0.9,en;q=0.8",
    "Accept-Encoding": "identity",
    "X-Purpose": "ireland-job-tracker (personal job search)",
}
TIMEOUT = 25
RETRIES = 2


class FetchError(Exception):
    """Raised when a board cannot be read after retries."""


def _get(url: str, headers: dict[str, str] | None = None) -> Any:
    """GET a URL and parse JSON, with a couple of polite retries."""
    hdrs = {**BROWSER_HEADERS, "Accept": "application/json"}
    if headers:
        hdrs.update(headers)

    last_err: Exception | None = None
    for attempt in range(RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            # 404 means the board token is wrong - no point retrying.
            if exc.code in (404, 410):
                raise FetchError(f"board not found ({exc.code})") from exc
            last_err = exc
        except Exception as exc:  # noqa: BLE001 - network is messy, keep going
            last_err = exc
        if attempt < RETRIES:
            time.sleep(1.5 * (attempt + 1))
    raise FetchError(str(last_err))


def _get_html(url: str, accept: str = "text/html,application/xhtml+xml,*/*;q=0.8",
              limit: int = 6_000_000) -> str:
    """
    GET a page as text.

    This lives here because three modules were each carrying their own copy -
    ats_extra's _get_text and ats_more's _text were the same function with
    different byte caps, which is exactly the kind of drift that leaves one of
    them fixed and the others not.
    """
    req = urllib.request.Request(url, headers={**BROWSER_HEADERS, "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read(limit).decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        raise FetchError(str(exc)) from exc


def _post(url: str, payload: dict[str, Any]) -> Any:
    """POST JSON (Workday needs this)."""
    body = json.dumps(payload).encode("utf-8")
    hdrs = {**BROWSER_HEADERS, "Accept": "application/json",
            "Content-Type": "application/json"}
    last_err: Exception | None = None
    for attempt in range(RETRIES + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 410):
                raise FetchError(f"board not found ({exc.code})") from exc
            last_err = exc
        except Exception as exc:  # noqa: BLE001
            last_err = exc
        if attempt < RETRIES:
            time.sleep(1.5 * (attempt + 1))
    raise FetchError(str(last_err))


# --------------------------------------------------------------------------
# One function per ATS platform.
# Each returns a list of dicts in that platform's own shape.
# --------------------------------------------------------------------------

def greenhouse(token: str) -> list[dict]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    data = _get(url)
    return data.get("jobs", []) or []


def lever(token: str) -> list[dict]:
    url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    data = _get(url)
    return data if isinstance(data, list) else []


def ashby(token: str) -> list[dict]:
    url = (
        f"https://api.ashbyhq.com/posting-api/job-board/{token}"
        "?includeCompensation=true"
    )
    data = _get(url)
    return data.get("jobs", []) or []


def workable(token: str) -> list[dict]:
    url = f"https://apply.workable.com/api/v1/widget/accounts/{token}?details=true"
    data = _get(url)
    return data.get("jobs", []) or []


def smartrecruiters(token: str) -> list[dict]:
    """
    SmartRecruiters, paginated 100 at a time.

    The listing endpoint returns NO job description at all - the first version
    shipped 35 jobs with empty descriptions, which meant they were scored on
    their title alone and ranked far below where they belonged. The full ad
    only exists on the per-posting endpoint, so fetch that too.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    out: list[dict] = []
    offset = 0
    while True:
        url = (
            f"https://api.smartrecruiters.com/v1/companies/{token}/postings"
            f"?limit=100&offset={offset}"
        )
        data = _get(url)
        chunk = data.get("content", []) or []
        out.extend(chunk)
        offset += 100
        if len(chunk) < 100 or offset > 1000:
            break

    def add_detail(posting: dict) -> None:
        pid = posting.get("id")
        if not pid:
            return
        try:
            detail = _get(
                f"https://api.smartrecruiters.com/v1/companies/{token}/postings/{pid}"
            )
        except FetchError:
            return
        if isinstance(detail, dict) and detail.get("jobAd"):
            posting["jobAd"] = detail["jobAd"]

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(as_completed([pool.submit(add_detail, p) for p in out[:120]]))

    return out


def recruitee(token: str) -> list[dict]:
    url = f"https://{token}.recruitee.com/api/offers/"
    data = _get(url)
    return data.get("offers", []) or []


def personio(token: str) -> list[dict]:
    """Personio only serves XML, so parse it into dicts here."""
    import xml.etree.ElementTree as ET

    url = f"https://{token}.jobs.personio.de/xml?language=en"
    hdrs = {**BROWSER_HEADERS, "Accept": "application/xml"}
    req = urllib.request.Request(url, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
    except Exception as exc:  # noqa: BLE001
        raise FetchError(str(exc)) from exc

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise FetchError(f"bad xml: {exc}") from exc

    jobs: list[dict] = []
    for pos in root.iter("position"):
        job = {child.tag: (child.text or "") for child in pos}
        descs = []
        for jd in pos.iter("jobDescription"):
            name = jd.findtext("name") or ""
            value = jd.findtext("value") or ""
            descs.append(f"{name}\n{value}")
        job["_description"] = "\n\n".join(descs)
        jobs.append(job)
    return jobs


def workday(token: str) -> list[dict]:
    """
    Workday is the awkward one but a lot of large Irish employers use it.

    Token format we expect:  "tenant|wd_number|site"
    e.g. "accenture|3|AccentureCareers"  ->
         https://accenture.wd3.myworkdayjobs.com/wday/cxs/accenture/AccentureCareers/jobs
    """
    parts = token.split("|")
    if len(parts) != 3:
        raise FetchError("workday token must be 'tenant|wd_number|site'")
    tenant, wd_num, site = parts
    url = (
        f"https://{tenant}.wd{wd_num}.myworkdayjobs.com"
        f"/wday/cxs/{tenant}/{site}/jobs"
    )

    # Two Ireland-narrowing search terms are tried before falling back to the
    # unfiltered list. Large employers have thousands of jobs worldwide and we
    # only ever want the Irish ones, so asking Workday to narrow it beats
    # paging through Kuala Lumpur to find Dublin.
    for search_text in ("Ireland", "Dublin", ""):
        jobs = _workday_page(url, tenant, wd_num, site, search_text)
        if jobs:
            return jobs
    return []


def _workday_page(url: str, tenant: str, wd_num: str, site: str,
                  search_text: str) -> list[dict]:
    """
    Page through one Workday search.

    The first version trusted the `total` field to know when to stop, and every
    employer came back with exactly 40 jobs - Workday does not report `total`
    consistently across tenants. Pagination now stops on a SHORT PAGE, which is
    the only reliable end-of-list signal.
    """
    out: list[dict] = []
    offset = 0
    PAGE = 20
    HARD_CAP = 3000

    while True:
        payload = {
            "appliedFacets": {},
            "limit": PAGE,
            "offset": offset,
            "searchText": search_text,
        }
        try:
            data = _post(url, payload)
        except FetchError:
            # A mid-pagination failure shouldn't throw away the pages we have.
            break

        chunk = data.get("jobPostings", []) or []
        for job in chunk:
            job["_tenant"] = tenant
            job["_wd"] = wd_num
            job["_site"] = site
        out.extend(chunk)

        if len(chunk) < PAGE:
            break
        offset += PAGE
        if offset >= HARD_CAP:
            break
        time.sleep(0.25)

    _workday_add_descriptions(out, tenant, wd_num, site)
    return out


def _workday_add_descriptions(jobs: list[dict], tenant: str, wd_num: str,
                              site: str, cap: int = 120) -> None:
    """
    Fetch the full ad for each Workday posting.

    The list endpoint returns a one-line teaser, so 91 Workday jobs were being
    scored on their title alone - and Workday is the biggest single source of
    Irish employers here. The full description sits behind the same cxs path
    plus the posting's externalPath.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def add(job: dict) -> None:
        path = job.get("externalPath")
        if not path:
            return
        url = (
            f"https://{tenant}.wd{wd_num}.myworkdayjobs.com"
            f"/wday/cxs/{tenant}/{site}{path}"
        )
        try:
            data = _get(url)
        except FetchError:
            return
        info = data.get("jobPostingInfo") if isinstance(data, dict) else None
        if isinstance(info, dict):
            if info.get("jobDescription"):
                job["_description"] = info["jobDescription"]
            if info.get("location"):
                job["locationsText"] = info["location"]
            if info.get("startDate"):
                job["postedOn"] = info["startDate"]

    with ThreadPoolExecutor(max_workers=5) as pool:
        list(as_completed([pool.submit(add, j) for j in jobs[:cap]]))


# Registry so run.py can dispatch by name from companies.json
FETCHERS = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "workable": workable,
    "smartrecruiters": smartrecruiters,
    "recruitee": recruitee,
    "personio": personio,
    "workday": workday,
}


# Additional platforms live in ats_extra to keep this file readable. The import
# sits at the bottom because ats_extra reads helpers defined above.
def _register_extras() -> None:
    try:
        from scraper.ats_extra import EXTRA_FETCHERS
        FETCHERS.update(EXTRA_FETCHERS)
    except ImportError:  # pragma: no cover
        pass
    try:
        from scraper.ats_more import MORE_FETCHERS
        FETCHERS.update(MORE_FETCHERS)
    except ImportError:  # pragma: no cover
        pass


_register_extras()
