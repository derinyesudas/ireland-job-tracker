"""
Additional career-site readers, for the platforms that turned up in the Irish
employer register but were not covered by the first eight.

Confidence is not uniform here, and pretending otherwise would be dishonest:

  oraclecloud   HIGH   - documented public REST endpoint, stable
  pinpoint      HIGH   - documented public JSON endpoint
  workday_site  HIGH   - same mechanism as the main Workday client
  jsonld        MEDIUM - reads the Google-for-Jobs structured data most career
                         sites publish. Works wherever a site does job SEO,
                         which is most of them, but not all.
  successfactors LOW   - SAP does not publish a single public feed format.
                         Several patterns are tried, then it falls back to
                         jsonld. Expect a portion of these to need hand-work.

Every one of these is checked for real by scripts/verify_companies.py running
in CI, which has open network access. Nothing here is assumed to work.
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request

from scraper.ats_clients import FetchError, _get, _get_html, _get_html_at

_get_text = _get_html


# ---------------------------------------------------------------- oracle cloud

def oraclecloud(token: str) -> list[dict]:
    """
    Oracle Recruiting Cloud.

    Token format: "host|siteNumber"
      e.g. "ehzq.fa.us2.oraclecloud.com|CX_1001"
    """
    parts = token.split("|")
    if len(parts) != 2:
        raise FetchError("oraclecloud token must be 'host|siteNumber'")
    host, site = parts

    out: list[dict] = []
    offset = 0
    while True:
        finder = (
            f"findReqs;siteNumber={site},facetsList=LOCATIONS;WORK_FROM_HOME;"
            f"WORKPLACE_TYPES,limit=200,offset={offset},sortBy=POSTING_DATES_DESC"
        )
        url = (
            f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
            f"?onlyData=true&expand=requisitionList.secondaryLocations"
            f"&finder={urllib.parse.quote(finder, safe=';=,')}"
        )
        data = _get(url)
        items = data.get("items") or []
        if not items:
            break
        reqs = items[0].get("requisitionList") or []
        for r in reqs:
            r["_host"] = host
            r["_site"] = site
        out.extend(reqs)
        total = items[0].get("TotalJobsCount", 0)
        offset += 200
        if not reqs or offset >= total or offset > 1000:
            break

    # The requisition LIST carries no description - 47 Oracle jobs arrived with
    # an empty one and were scored on their title alone. The full ad lives on
    # the per-requisition endpoint.
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def add_detail(req: dict) -> None:
        rid = req.get("Id")
        if not rid:
            return
        finder = f'ById;Id="{rid}",siteNumber={site}'
        safe_chars = ';=,"'
        quoted = urllib.parse.quote(finder, safe=safe_chars)
        url = (
            f"https://{host}/hcmRestApi/resources/latest/"
            f"recruitingCEJobRequisitionDetails"
            f"?onlyData=true&expand=all&finder={quoted}"
        )
        try:
            data = _get(url)
        except FetchError:
            return
        items = data.get("items") or []
        if items and items[0].get("ExternalDescriptionStr"):
            req["ExternalDescriptionStr"] = items[0]["ExternalDescriptionStr"]

    with ThreadPoolExecutor(max_workers=5) as pool:
        list(as_completed([pool.submit(add_detail, r) for r in out[:120]]))

    return out


# --------------------------------------------------------------------- pinpoint

def pinpoint(token: str) -> list[dict]:
    """Pinpoint. Token is the subdomain, e.g. 'accenture' for accenture.pinpointhq.com."""
    host = token if "." in token else f"{token}.pinpointhq.com"
    data = _get(f"https://{host}/postings.json")
    if isinstance(data, dict):
        return data.get("data") or data.get("postings") or []
    return data if isinstance(data, list) else []


# -------------------------------------------------------------------- json-ld

JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.S | re.I,
)


def _walk_for_jobpostings(node, found: list[dict]) -> None:
    """JSON-LD nests unpredictably - walk the whole tree looking for JobPosting."""
    if isinstance(node, dict):
        t = node.get("@type")
        types = t if isinstance(t, list) else [t]
        if any(isinstance(x, str) and x.lower() == "jobposting" for x in types):
            found.append(node)
        for v in node.values():
            _walk_for_jobpostings(v, found)
    elif isinstance(node, list):
        for v in node:
            _walk_for_jobpostings(v, found)


def jsonld(token: str) -> list[dict]:
    """
    Generic reader for any careers page that publishes Google-for-Jobs
    structured data. Token is the full careers URL.

    Sites do this so their jobs appear in Google's jobs results, which means a
    large share of company career pages carry it whatever platform they run on.
    """
    html_text = _get_text(token)
    found: list[dict] = []
    for block in JSONLD_RE.findall(html_text):
        block = block.strip()
        if not block:
            continue
        try:
            _walk_for_jobpostings(json.loads(block), found)
        except json.JSONDecodeError:
            # Some sites emit slightly broken JSON-LD; salvage what parses.
            for chunk in re.findall(r"\{.*?\}(?=\s*[,\]]|\s*$)", block, re.S):
                try:
                    _walk_for_jobpostings(json.loads(chunk), found)
                except json.JSONDecodeError:
                    continue
    for job in found:
        job["_source_url"] = token
    if not found:
        raise FetchError("no JobPosting structured data on the page")
    return found


# ------------------------------------------------------------- successfactors



def successfactors(token: str) -> list[dict]:
    """
    SAP SuccessFactors.

    Token is either a full careers URL, or "host|companyId".
    SAP publishes no single public feed format, so this tries the RSS route
    that most tenants leave enabled, then falls back to structured data.
    """
    if "|" in token:
        host, company = token.split("|", 1)
        candidates = [
            f"https://{host}/services/jobs/rss?company={company}",
            f"https://{host}/career?company={company}&career_ns=job_listing",
        ]
    else:
        candidates = [token]

    for url in candidates:
        if url.endswith("rss") or "/rss?" in url:
            try:
                return _sf_rss(url)
            except FetchError:
                continue
        try:
            return jsonld(url)
        except FetchError:
            continue

    raise FetchError("no readable SuccessFactors feed found")


def _sf_rss(url: str) -> list[dict]:
    import xml.etree.ElementTree as ET

    text = _get_text(url, accept="application/rss+xml,application/xml")
    try:
        root = ET.fromstring(text.encode("utf-8", errors="replace"))
    except ET.ParseError as exc:
        raise FetchError(f"bad rss: {exc}") from exc

    jobs = []
    for item in root.iter("item"):
        jobs.append({child.tag: (child.text or "") for child in item})
    if not jobs:
        raise FetchError("empty rss feed")
    return jobs


EXTRA_FETCHERS = {
    "oraclecloud": oraclecloud,
    "pinpoint": pinpoint,
    "jsonld": jsonld,
    "successfactors": successfactors,
}


# ---------------------------------------------------------------------------
# joblinks - the generic reader for career sites with no usable feed
#
# The site inspection found ~130 employers whose careers page has no readable
# job feed: some hide a platform behind their own branding, some rolled their
# own, some render entirely in JavaScript. But nearly all of them share one
# thing - the individual JOB PAGES carry Google-for-Jobs structured data, even
# when the LIST page does not, because employers want their vacancies to show
# up in Google's job results.
#
# So instead of trying to reverse-engineer each site's list API, this walks the
# careers page for links that look like individual jobs, opens them, and reads
# the structured data off each one. Platform-agnostic by construction.
# ---------------------------------------------------------------------------

from concurrent.futures import ThreadPoolExecutor, as_completed  # noqa: E402
from urllib.parse import urljoin, urlparse, urldefrag  # noqa: E402

HREF_RE = re.compile(r'<a\b[^>]*\bhref=["\']([^"\'#][^"\']*)["\']', re.I)

# A link to one specific job, rather than to a category or a search page.
JOB_PATH_RE = re.compile(
    r"/(job|jobs|career|careers|vacancy|vacancies|position|positions|"
    r"opening|openings|opportunity|opportunities|requisition|role|roles)"
    r"[/-][^/?#]{3,}",
    re.I,
)
# Pages that look job-ish but are not individual jobs. Split in two because
# some of these are whole path segments ("/search/") and some are how a slug
# STARTS ("/careers/why-work-here"). Anchoring both the same way let marketing
# pages through on the first test.
NOT_A_JOB_SEGMENT_RE = re.compile(
    r"/(search|browse|all|list|category|categories|department|departments|"
    r"location|locations|team|teams|alerts?|apply|login|signin|signup|"
    r"register|privacy|cookies?|terms|legal|faq|contact|news|blog|events?)"
    r"(/|$|\?)",
    re.I,
)
NOT_A_JOB_SLUG_RE = re.compile(
    r"(why-|life-at|life-in|about-|our-|meet-|working-at|work-with|join-us|"
    r"diversity|inclusion|culture|benefit|reward|wellbeing|values|"
    r"hiring-process|how-we|what-we|career-path|talent-community|job-alert)",
    re.I,
)
NOT_A_JOB_RE = re.compile(
    r"[?&]page=|\.(pdf|docx?|xlsx?|pptx?|zip|jpe?g|png|gif|svg|css|js)($|\?)",
    re.I,
)
# An individual job page nearly always carries an id or a long slug.
LOOKS_SPECIFIC_RE = re.compile(r"(\d{4,}|[a-z0-9]{2,}-[a-z0-9]{2,}-[a-z0-9]{2,})", re.I)

TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S | re.I)

MAX_JOB_PAGES = 45


def _same_site(a: str, b: str) -> bool:
    """Two hostnames belonging to the same organisation.

    Deliberately blunt: the last two labels, or three where the second-last is
    a public suffix like .co.uk. Good enough to link careers.x.com to www.x.com
    without linking anything on .com to everything else on .com.
    """
    SECOND_LEVEL = {"co", "com", "org", "net", "ac", "gov", "edu"}
    pa = a.lower().split(":")[0].split(".")
    pb = b.lower().split(":")[0].split(".")
    def root(parts):
        if len(parts) >= 3 and parts[-2] in SECOND_LEVEL:
            return tuple(parts[-3:])
        return tuple(parts[-2:])
    return len(pa) >= 2 and len(pb) >= 2 and root(pa) == root(pb)


def _job_candidate_links(base_url: str, html_text: str) -> list[str]:
    host = urlparse(base_url).netloc
    seen: dict[str, None] = {}
    for href in HREF_RE.findall(html_text):
        href = href.strip()
        if not href or href.lower().startswith(("mailto:", "tel:", "javascript:")):
            continue
        full = urldefrag(urljoin(base_url, href))[0]
        p = urlparse(full)
        if p.scheme not in ("http", "https"):
            continue
        # Stay on the careers host, a sibling of it, or an obvious platform.
        # PM Group lists its jobs on careers.pmgroup-global.com from a page on
        # www.pmgroup-global.com. Same company, same registrable domain, and
        # comparing the full hostname threw away every one of them - the same
        # mistake as judging a redirected page by the address we asked for.
        if p.netloc != host and not _same_site(p.netloc, host) and not re.search(
            r"(greenhouse|lever|ashby|workable|smartrecruiters|recruitee|"
            r"myworkdayjobs|oraclecloud|successfactors|icims|avature|taleo|"
            r"phenom|jobvite|teamtailor|eightfold|pinpointhq)", p.netloc, re.I
        ):
            continue
        path = p.path
        if not JOB_PATH_RE.search(path):
            continue
        if (NOT_A_JOB_SEGMENT_RE.search(path) or NOT_A_JOB_SLUG_RE.search(path)
                or NOT_A_JOB_RE.search(full)):
            continue
        if not LOOKS_SPECIFIC_RE.search(path):
            continue
        seen.setdefault(full, None)
        if len(seen) >= MAX_JOB_PAGES * 2:
            break
    return list(seen)[:MAX_JOB_PAGES]


# Titles that are not titles.
#
# When a careers site needs JavaScript to draw the job, the page still returns
# HTML - a shell whose <title> is "JavaScript is disabled" or "Job Details" or
# the company's own name. The first live run put 415 such rows on the board:
# forty-five SSE jobs all called "JavaScript is disabled", one per URL. They
# are worse than useless, because they crowd out real jobs and every one of
# them looks like a different vacancy.
#
# The fix is not to drop those pages. Their URLs carry the real title, and
# often the location too - which is how a Scottish SSE role can be recognised
# and filtered out rather than sitting on an Irish job board.
_JUNK_TITLE_RE = re.compile(
    r"^(javascript is disabled|job details?|jobs?|careers?|vacancies|page not found|"
    r"404|error|loading|home|search results?|our (?:jobs|vacancies|opportunities)|"
    r"job search|opportunities|apply now|position details?|requisition details?|"
    r"role purpose|job description|manufacturing|working at .*|"
    # Navigation pages off university and large-employer careers sites. The
    # blind evaluation surfaced three of these from one university scoring in
    # the forties and fifties - "Students and Graduates" reads to the scorer
    # as a graduate programme, because that is exactly what the page is about.
    r"(?:for\s+)?employers?|(?:for\s+)?students?(?:\s+and\s+graduates?)?|"
    r"jobs?\s+and\s+internships?|internships?\s+and\s+jobs?|graduates?|"
    r"alumni|about\s+us|contact\s+us|news|events?|blog|privacy(?:\s+policy)?|"
    r"terms(?:\s+(?:and|&)\s+conditions)?|cookie[s]?(?:\s+policy)?|sitemap|"
    r"employer\s+.*|student\s+.*|recruit\s+.*|hire\s+.*|"
    r"work\s+(?:with|for)\s+us|life\s+at\s+.*|why\s+join\s+.*)$",
    re.I,
)
# A title is a noun phrase, not a sentence. Anything this long and this full of
# small words is marketing copy scraped off a hero banner.
_STOPWORDS = {"the", "and", "with", "for", "you", "your", "our", "we", "to", "of",
              "a", "is", "are", "it", "that", "have", "has", "in", "on", "at"}


def _looks_like_a_title(text: str) -> bool:
    if not text or _JUNK_TITLE_RE.match(text.strip()):
        return False
    words = text.split()
    if len(words) > 12:
        return False
    small = sum(1 for w in words if w.lower().strip(",.") in _STOPWORDS)
    return small <= max(1, len(words) // 3)


# Place names that mean "not Ireland" when they turn up in a job URL.
_ABROAD_IN_SLUG = (
    "united-kingdom", "england", "scotland", "wales", "northern-ireland",
    "london", "manchester", "birmingham", "glasgow", "edinburgh", "leeds",
    "united-states", "usa", "canada", "australia", "india", "germany",
    "france", "spain", "netherlands", "poland", "portugal", "italy",
    "singapore", "philippines", "belgium", "sweden", "denmark", "norway",
)
_IRISH_IN_SLUG = ("ireland", "dublin", "cork", "galway", "limerick", "waterford",
                  "kilkenny", "sligo", "athlone", "drogheda", "dundalk", "wexford")


def _from_slug(url: str) -> tuple[str, str]:
    """
    Read a title and a location out of a job URL.

    Careers sites build slugs out of exactly the fields we want:
        /jobs/contracts-manager-energy-markets-edinburgh-the-lothians-scotland-united-kingdom
    Everything before the first place name is the role; the place names are the
    location. Returns ("", "") when the slug carries neither.
    """
    slug = urllib.parse.urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"\.(html?|aspx?|php)$", "", slug, flags=re.I)
    slug = re.sub(r"^\d{4,}[-_]|[-_]\d{5,}$", "", slug)
    if not slug or len(slug) < 6:
        return "", ""

    parts = [p for p in re.split(r"[-_]+", slug) if p]
    if len(parts) < 2 or all(p.isdigit() for p in parts):
        return "", ""

    places = _ABROAD_IN_SLUG + _IRISH_IN_SLUG
    cut = len(parts)
    for i, part in enumerate(parts):
        low = part.lower()
        # match both one-word places and the leading word of hyphenated ones
        if any(low == pl or pl.startswith(low + "-") for pl in places):
            cut = i
            break

    title = " ".join(parts[:cut]).strip()
    location = " ".join(parts[cut:]).strip()
    if len(title) < 4 or len(title) > 90:
        return "", location.title()
    return title.title(), location.title()


def _read_one_job(url: str) -> dict | None:
    """Structured data if the page has it, otherwise a title/description guess."""
    try:
        page = _get_text(url)
    except FetchError:
        return None

    found: list[dict] = []
    for block in JSONLD_RE.findall(page):
        try:
            _walk_for_jobpostings(json.loads(block.strip()), found)
        except (json.JSONDecodeError, AttributeError):
            continue
    if found:
        job = found[0]
        job["_source_url"] = url
        return job

    # No structured data. Fall back to the page's own title, and be explicit
    # that the description is thin so the score reflects that honestly.
    raw_title = ""
    m = H1_RE.search(page) or TITLE_RE.search(page)
    if m:
        raw_title = re.sub(r"<[^>]+>", " ", m.group(1))
        # Twice: a fair number of sites emit "&amp;amp;" for an ampersand, and
        # one pass leaves "&amp;" sitting in the title.
        raw_title = html.unescape(html.unescape(raw_title))
        raw_title = " ".join(raw_title.split())
        # Strip the "| Company Careers" tail most title tags carry.
        raw_title = re.split(r"\s+[|–—-]\s+", raw_title)[0].strip()
    slug_title, slug_location = _from_slug(url)

    # Prefer the page's own title, but only when it is actually a title. A
    # JavaScript shell's <title> is the same string on every job, so the slug
    # is the more truthful source whenever the page's is boilerplate.
    if not _looks_like_a_title(raw_title):
        raw_title = slug_title
    if not raw_title or len(raw_title) < 4 or len(raw_title) > 140:
        return None

    return {
        "_fallback": True,
        "title": raw_title,
        "location": slug_location,
        "description": _readable_text(page),
        "url": url,
        "_source_url": url,
    }


# Everything that is furniture rather than the advert.
_STRIP_BLOCKS_RE = re.compile(
    r"<(script|style|noscript|svg|head|nav|header|footer|form|iframe)\b[^>]*>.*?</\1\s*>",
    re.S | re.I,
)
_BLOCK_END_RE = re.compile(
    r"</(p|div|li|tr|h[1-6]|section|article|br)\s*>|<br\s*/?>", re.I
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_NL_RE = re.compile(r"\n{3,}")

# Lines that are navigation or boilerplate rather than part of the job ad.
_BOILERPLATE_RE = re.compile(
    r"^(home|about|contact|search|menu|login|sign in|sign up|register|"
    r"cookies?|privacy|terms|accept all|manage preferences|skip to|share this|"
    r"apply now|back to (search|results|jobs)|follow us|newsletter|"
    r"all rights reserved|copyright|\u00a9.*)$",
    re.I,
)


def _readable_text(page: str, limit: int = 6000) -> str:
    """
    Pull the advert text out of a job page that publishes no structured data.

    The first version only took the meta description, which is a one-line SEO
    blurb - so 457 of 832 jobs arrived with effectively no description and were
    scored on their title alone. Most of those came from the sitemap and
    job-link readers, which is exactly where the harder-to-reach employers are,
    so they were the ones being under-ranked.
    """
    body = page
    m = re.search(r"<body\b[^>]*>(.*)</body\s*>", page, re.S | re.I)
    if m:
        body = m.group(1)

    body = _STRIP_BLOCKS_RE.sub(" ", body)
    body = _BLOCK_END_RE.sub("\n", body)
    body = _TAG_RE.sub(" ", body)
    body = html.unescape(body)
    body = _WS_RE.sub(" ", body)

    lines: list[str] = []
    seen: set[str] = set()
    for line in body.split("\n"):
        line = line.strip()
        if len(line) < 3 or _BOILERPLATE_RE.match(line):
            continue
        if line in seen:          # repeated nav items
            continue
        seen.add(line)
        lines.append(line)

    text = _NL_RE.sub("\n\n", "\n".join(lines)).strip()
    return text[:limit]


def joblinks(token: str) -> list[dict]:
    """
    Read a careers page that has no feed, by opening its individual job pages.

    Token is the careers URL. Deliberately polite: at most 45 job pages, six at
    a time. That is plenty to catch what a company posted recently, which is
    the whole point of checking every 15 minutes.
    """
    # Resolve against the page we were actually served, not the one we asked
    # for. eir.ie/jobs redirects to jobs.eir.care, and judging its links by the
    # eir.ie host threw away all thirty-nine of them.
    listing, landed = _get_html_at(token)
    links = _job_candidate_links(landed, listing)
    if not links:
        raise FetchError("no individual job links found on the page")

    jobs: list[dict] = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(_read_one_job, u) for u in links]
        for fut in as_completed(futures):
            job = fut.result()
            if job:
                jobs.append(job)

    if not jobs:
        raise FetchError(f"found {len(links)} job links but none were readable")
    return jobs


EXTRA_FETCHERS["joblinks"] = joblinks


# ---------------------------------------------------------------------------
# sitemap - for career sites that build their job list in the browser
#
# The inspection found 44 employers whose careers page ships almost no HTML:
# the job list is assembled by JavaScript after the page loads, so there are no
# links to follow and nothing to read. Fetching the page gets you an empty
# shell.
#
# But those same companies still need Google to index their vacancies, and
# Google does not run their JavaScript either. So they publish the job URLs in
# a sitemap. That is the back door: read the sitemap, keep the URLs that are
# individual jobs, and open those directly.
# ---------------------------------------------------------------------------

SITEMAP_IN_ROBOTS_RE = re.compile(r"^\s*sitemap:\s*(\S+)", re.I | re.M)
LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)

SITEMAP_GUESSES = [
    "/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml",
    "/sitemaps/sitemap.xml", "/jobs/sitemap.xml", "/careers/sitemap.xml",
]
MAX_CHILD_SITEMAPS = 6
MAX_SITEMAP_JOBS = 45


def _sitemap_candidates(careers_url: str) -> list[str]:
    p = urlparse(careers_url)
    root = f"{p.scheme}://{p.netloc}"
    found: list[str] = []

    # robots.txt is the declared location, so it beats guessing.
    try:
        robots = _get_text(f"{root}/robots.txt", accept="text/plain")
        for m in SITEMAP_IN_ROBOTS_RE.finditer(robots):
            url = m.group(1).strip()
            if url not in found:
                found.append(url)
    except FetchError:
        pass

    for guess in SITEMAP_GUESSES:
        if root + guess not in found:
            found.append(root + guess)
    return found[:8]


def _read_sitemap(url: str, depth: int = 0) -> list[str]:
    """Return the page URLs in a sitemap, following one level of index."""
    try:
        body = _get_text(url, accept="application/xml,text/xml,*/*")
    except FetchError:
        return []
    if "<loc" not in body.lower():
        return []

    locs = LOC_RE.findall(body)
    is_index = "<sitemapindex" in body[:2000].lower()

    if is_index and depth == 0:
        # Prefer child sitemaps whose own URL mentions jobs.
        children = sorted(locs, key=lambda u: 0 if JOB_PATH_RE.search(u) else 1)
        out: list[str] = []
        for child in children[:MAX_CHILD_SITEMAPS]:
            out.extend(_read_sitemap(child, depth + 1))
            if len(out) > 4000:
                break
        return out
    return locs


def sitemap(token: str) -> list[dict]:
    """
    Read jobs via the site's sitemap. Token is the careers URL.

    Ordered newest-first where the sitemap declares lastmod, because for a
    tracker checking every 15 minutes the recent postings are the whole point.
    """
    all_urls: list[str] = []
    for candidate in _sitemap_candidates(token):
        all_urls.extend(_read_sitemap(candidate))
        if len(all_urls) > 200:
            break
    if not all_urls:
        raise FetchError("no sitemap found")

    host = urlparse(token).netloc
    job_urls: list[str] = []
    for u in all_urls:
        p = urlparse(u)
        if p.netloc and p.netloc != host:
            continue
        path = p.path
        if not JOB_PATH_RE.search(path):
            continue
        if (NOT_A_JOB_SEGMENT_RE.search(path) or NOT_A_JOB_SLUG_RE.search(path)
                or NOT_A_JOB_RE.search(u)):
            continue
        if not LOOKS_SPECIFIC_RE.search(path):
            continue
        if u not in job_urls:
            job_urls.append(u)

    if not job_urls:
        raise FetchError(f"sitemap had {len(all_urls)} URLs but none looked like jobs")

    job_urls = job_urls[-MAX_SITEMAP_JOBS:]      # tail is usually the newest

    jobs: list[dict] = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for fut in as_completed([pool.submit(_read_one_job, u) for u in job_urls]):
            job = fut.result()
            if job:
                jobs.append(job)

    if not jobs:
        raise FetchError(f"{len(job_urls)} job URLs in the sitemap, none readable")
    return jobs


EXTRA_FETCHERS["sitemap"] = sitemap


# ---------------------------------------------------------------------------
# rssfeed - some career sites still publish a plain job feed
#
# Only a handful, but they are free wins: the feed is already structured and
# needs no guessing.
# ---------------------------------------------------------------------------

RSS_LINK_RE = re.compile(
    r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]+href=["\']([^"\']+)["\']',
    re.I,
)
COMMON_FEED_PATHS = [
    "/jobs/feed", "/jobs/rss", "/careers/feed", "/careers/rss",
    "/feed/jobs", "/rss/jobs", "/jobs.rss", "/vacancies/feed",
]


def rssfeed(token: str) -> list[dict]:
    """Read jobs from a declared or guessed RSS/Atom feed. Token is the careers URL."""
    import xml.etree.ElementTree as ET

    candidates: list[str] = []
    try:
        page = _get_text(token)
        for href in RSS_LINK_RE.findall(page):
            candidates.append(urljoin(token, href))
    except FetchError:
        page = ""

    p = urlparse(token)
    root = f"{p.scheme}://{p.netloc}"
    candidates.extend(root + path for path in COMMON_FEED_PATHS)

    for url in candidates[:10]:
        try:
            body = _get_text(url, accept="application/rss+xml,application/xml,*/*")
        except FetchError:
            continue
        if "<item" not in body.lower() and "<entry" not in body.lower():
            continue
        try:
            tree = ET.fromstring(body.encode("utf-8", errors="replace"))
        except ET.ParseError:
            continue

        jobs: list[dict] = []
        for node in list(tree.iter()):
            tag = node.tag.rsplit("}", 1)[-1].lower()
            if tag not in ("item", "entry"):
                continue
            record: dict = {"_source_url": url}
            for child in node:
                key = child.tag.rsplit("}", 1)[-1]
                if key == "link" and not (child.text or "").strip():
                    record["link"] = child.attrib.get("href", "")   # Atom
                else:
                    record[key] = (child.text or "").strip()
            if record.get("title"):
                jobs.append(record)
        if jobs:
            return jobs

    raise FetchError("no readable job feed")


# ---------------------------------------------------------------------------
# apiprobe - try the endpoints the site's own JavaScript calls
#
# The site inspection found 21 unresolved employers whose page references an
# API-shaped URL with "job" in it. Those are almost always the endpoint the
# page uses to draw its own job list - we just never tried calling them. This
# does, and works out the shape of whatever JSON comes back.
# ---------------------------------------------------------------------------

_API_CAND_RE = re.compile(r'["\'](?P<u>(?:https?:)?//[^"\'\s<>]{6,220}?|/[^"\'\s<>]{4,200}?)["\']')
_API_WORD_RE = re.compile(r"(job|vacan|career|opening|position|requisition|posting|opportunit)", re.I)
_API_SHAPE_RE = re.compile(r"(/api/|/rest/|\.json|/graphql|/services/|/v\d+/|/search)", re.I)
_ASSET_RE = re.compile(r"\.(css|png|jpe?g|svg|gif|woff2?|ico|mp4|js)($|\?)", re.I)

TITLE_KEYS = ("title", "name", "jobtitle", "positiontitle", "jobname",
              "postingtitle", "displayname", "vacancytitle")
URL_KEYS = ("url", "link", "applyurl", "joburl", "absoluteurl", "canonicalurl",
            "permalink", "detailurl", "href")
LOC_KEYS = ("location", "city", "joblocation", "locationname", "primarylocation",
            "office", "locationstext", "town", "region")
DESC_KEYS = ("description", "jobdescription", "summary", "content", "body",
             "shortdescription", "jobsummary", "details")
ID_KEYS = ("id", "jobid", "reqid", "requisitionid", "postingid", "slug", "ref")


def _pick(record: dict, keys: tuple) -> str:
    lowered = {k.lower(): v for k, v in record.items() if isinstance(k, str)}
    for key in keys:
        value = lowered.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            for inner in ("name", "label", "text", "value", "city"):
                if isinstance(value.get(inner), str) and value[inner].strip():
                    return value[inner].strip()
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, str):
                return first
            if isinstance(first, dict):
                for inner in ("name", "label", "text", "city"):
                    if isinstance(first.get(inner), str):
                        return first[inner]
    return ""


def _find_job_array(node, depth: int = 0) -> list[dict]:
    """Walk parsed JSON for the biggest list of dicts that look like jobs."""
    best: list[dict] = []
    if depth > 6:
        return best
    if isinstance(node, list):
        dicts = [x for x in node if isinstance(x, dict)]
        if len(dicts) >= 2 and sum(1 for d in dicts[:5] if _pick(d, TITLE_KEYS)) >= 2:
            best = dicts
        for item in node[:50]:
            found = _find_job_array(item, depth + 1)
            if len(found) > len(best):
                best = found
    elif isinstance(node, dict):
        for value in node.values():
            found = _find_job_array(value, depth + 1)
            if len(found) > len(best):
                best = found
    return best


def apiprobe(token: str) -> list[dict]:
    """Token is the careers URL. Finds and calls the site's own job endpoint."""
    page = _get_text(token)
    p = urlparse(token)
    base = f"{p.scheme}://{p.netloc}"

    candidates: list[str] = []
    for m in _API_CAND_RE.finditer(page):
        u = m.group("u")
        if not u or _ASSET_RE.search(u):
            continue
        if not (_API_WORD_RE.search(u) and _API_SHAPE_RE.search(u)):
            continue
        full = urljoin(base, "https://" + u[2:] if u.startswith("//") else u)
        if full not in candidates:
            candidates.append(full)

    for url in candidates[:12]:
        try:
            data = _get(url)
        except FetchError:
            continue
        rows = _find_job_array(data)
        if len(rows) < 2:
            continue
        out = []
        for row in rows[:200]:
            title = _pick(row, TITLE_KEYS)
            if not title:
                continue
            link = _pick(row, URL_KEYS)
            if link:
                link = urljoin(base, link)
            else:
                ident = _pick(row, ID_KEYS)
                link = urljoin(token, f"#{ident}") if ident else token
            out.append({
                "_api": True,
                "title": title,
                "url": link,
                "location": _pick(row, LOC_KEYS),
                "description": _pick(row, DESC_KEYS),
                "_source_url": url,
            })
        if out:
            return out

    raise FetchError(f"tried {len(candidates)} candidate endpoints, none returned jobs")


EXTRA_FETCHERS["rssfeed"] = rssfeed
EXTRA_FETCHERS["apiprobe"] = apiprobe
