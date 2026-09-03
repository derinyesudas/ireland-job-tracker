# Ireland Job Tracker

A live job board that watches Irish employers' own career sites and surfaces
graduate, internship and junior roles — each one scored out of 100 for how well
it fits my CV, and flagged when the employer is an active work-permit sponsor.

**Live site:** https://derinyesudas.github.io/ireland-job-tracker/

---

## Why I built it

Job hunting as a 2026 graduate in Ireland means checking the same forty career
pages over and over, and still missing roles because they were posted on a
Tuesday afternoon and buried by Wednesday. Aggregator sites are worse: they lag
by days, repost the same role six times, and tell you nothing about whether the
company will actually sponsor a work permit.

So this pulls jobs from the source, every 15 minutes, and ranks them against my
actual skills rather than against a keyword.

---

## How it works

```
Employment permit register  ─┐
(gov.ie, updated monthly)    │
                             ├─►  companies.json  ──►  scraper  ──►  jobs.json  ──►  live site
Curated graduate employers  ─┘    (who to watch,       (every 15      (scored,        (GitHub
                                   and on which ATS)    minutes)       filtered)       Pages)
```

### 1. Working out who to watch

Three sources are merged:

- **The official sponsor register.** The Department of Enterprise publishes a
  spreadsheet of every company issued an employment permit this year. That is a
  record of permits actually granted — not a claim on a job ad — which makes it
  the most reliable sponsorship signal available. The permit count also shows
  *how* active a sponsor each company is, and feeds directly into the score.
- **A hand-researched register of 296 Irish employers** (`data/ireland_register.json.enc`),
  each with its careers URL, sector, the specific entry routes into it
  (graduate programme, administrator intern, and so on), and a sponsorship
  confidence level. Where the register names the way in at an employer, a job
  matching that route scores higher.
- **A curated list** of large Irish graduate employers that hire heavily
  without necessarily topping the permit register.

### 2. Working out *how* they hire

Most companies run their careers page on a recruitment platform that exposes
the same public JSON feed the page itself draws from. `scripts/resolve_careers.py`
opens each company's careers URL and works down a ladder, stopping at the first
rung that actually returns jobs:

1. **A known platform** — twenty-two of them, from the ones startups use
   (Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, Personio)
   through the enterprise suites the large Irish employers actually run on
   (Workday, Oracle Recruiting, SuccessFactors, iCIMS, Taleo, Avature,
   Cornerstone, Eightfold) to the two that barely exist outside Ireland
   (Occupop, HireHive). Identified from the final URL or from the page's own
   JavaScript — a branded careers site usually gives itself away by calling
   its platform's API.
2. **Structured data on the careers page** — the schema.org JobPosting markup
   sites publish so their vacancies appear in Google's job results.
3. **The individual job pages** — where the list page has no feed, follow its
   links to each job and read the structured data off those instead.
4. **The site's own job endpoint** — where the page's JavaScript names an
   API-shaped URL with "job" in it, call it and work out the shape of whatever
   JSON comes back.
5. **The sitemap** — for sites that build their job list in the browser, where
   there is nothing in the HTML to follow. Google can't run their JavaScript
   either, so the job URLs are in the sitemap.
6. **An RSS or Atom feed**, for the handful of sites that still publish one.

Twenty-seven readers in total. Two of the rungs were added after the first
full resolution run showed where it was losing companies. Where the careers
page gives nothing away, its own scripts and iframes are opened and searched
too — a branded page very often has no trace of its platform in the HTML but
loads a bundle that calls it. And where the careers page turns out to be
marketing with the jobs a click away behind "Search our roles", that link is
followed and the whole ladder tried again on the page it leads to.

If a careers URL is dead, a set of alternatives is tried before the employer
is written off — companies reorganise their sites constantly, and a 404 is
rarely the end of the story.

Nothing is added on a guess. A company only enters the tracker once its feed
has been called for real and returned jobs, which is why the register's own
note about which platform an employer uses is used to *order* the candidates
rather than to decide.

This is why the tracker reads company career pages directly rather than
scraping LinkedIn or Indeed: these feeds are public, stable, need no login or
API key, and carry the job the moment the employer publishes it.

### 3. Knowing when to stop

The tracker is capped at 290 employers, and the queue is ordered by the two
things that decide whether watching a company is worth anything: how solid the
sponsorship evidence is, then how well the employer fits. A company earns its
place by being likely to hire someone who needs a permit *and* likely to post
the kind of role worth applying for.

The employers that never resolve are the long tail — rarely hiring, or behind
a bot wall that only a real browser gets through. Chasing them costs far more
than they return, so past the cap the run stops. Companies already tracked are
never displaced by the cap.

### 4. Filtering

Anything scoring under 10 is dropped outright rather than shown. Under the
CV-based scoring those are not near misses — they are software engineers,
product designers and account executives that picked up a point or two for
being in Dublin at a sponsoring employer. Nothing in double figures is ever
dropped, so every borderline case survives.

Every posting passes three gates: it must be in Ireland (with a guard against
Dublin, California and Limerick, Pennsylvania), it must not be a freelance or
contract engagement, and it must not be an obviously senior role.

### 5. Scoring

Each surviving job is scored out of 100 against my actual CV — not against a
list of words that resemble it.

That distinction is the whole design. The first version matched keyword
families, and the result was a board that felt plausible and was quietly
useless: a food-production role collected points for mentioning shift
reporting, "Service Desk Analyst with Italian" reached 71, and a supermarket
customer-service posting outranked a claims job at an insurer. Every component
below now traces to something on the CV, and the note on the card says which:

| Component | Max | What it rests on |
|---|---:|---|
| Role fit | 34 | The **title**, matched against six role families, each tied to specific evidence |
| Early careers | 20 | Graduate / internship / entry-level wording, or an intake year in the title |
| Tools you have | 18 | Excel, Power BI, Tableau, R — weighted by whether they are certified, built with, or taught |
| Industry fit | 10 | Insurance, pensions, funds, banking — in the title or the employer's sector |
| Location | 10 | Dublin down to the rest of Ireland |
| Sponsorship | 10 | Permits the company was actually issued this year |
| How you already work | 6 | KPIs, SLAs, data accuracy — capped, because they appear in nearly every advert |
| Language edge | +8 | Roles where Hindi or Malayalam is an advantage |

The role families, and the evidence behind each. The weights come from what
he can actually point to — a year of work outranks an examined subject, and an
examined subject outranks a job title that merely sounds adjacent:

| Family | Weight | Evidence |
|---|---:|---|
| Insurance & financial operations | 34 | A year at TCS as Data Process Enabler, Insurance Vertical — insurance data in Legacy and OMNI at 99% accuracy |
| Analytics & reporting | 34 | MSc Business Analytics; the Live Alert Console in Power BI; regression and ARIMA in R; Advanced Excel at 100%; Business Statistics and Operations Research in the BMS |
| Workforce planning | 30 | Forecasting from the MSc, plus the KPI/SLA habit from TCS |
| Graduate programmes | 28 | An entry route in its own right — the MSc and a first-class finance degree are what these schemes ask for |
| Finance entry roles | 26 | The BMS Finance specialisation: Auditing, Financial and Cost Accounting, Corporate Finance, Strategic Financial Management, Risk Management, Investment Analysis, plus TallyPrime and GST |
| Quality & process | 22 | Production and Total Quality Management, examined — and the practical half of it, a year held to 99% accuracy against SLAs |
| Supply chain | 18 | Logistics and Supply Chain Management, plus Operations Research |
| Project support | 16 | Project Management, examined; and he ran the analytics and the writing on a six-person MSc project |
| Customer operations | 12 | Nine months at a supermarket checkout in 2021 — real, but dated and non-office |
| General administration | 10 | Administration with no domain attached |

Everything from the degree rather than from a job is gated to graduate and
trainee routes: the weight halves where the advert names no entry route,
because studying a subject qualifies you to be taught the job, not to already
have done it. Tax is the sharpest case, and it came from Derin: the taxation
he studied was Indian, so an Irish tax *graduate programme* — which teaches
Irish tax from the start — is a genuine fit, while an Irish tax role wanting
existing knowledge of it is not.

Three rules do most of the tightening:

- **The title decides the role.** A target word buried in the body earns
  nothing. The old model gave eight points for a mention anywhere in the
  advert, which is how boilerplate turned into a match.
- **A job whose title matches nothing is capped at 35**, however familiar its
  advert reads — unless it is an explicit graduate intake, which is an entry
  route whatever the discipline.
- **Generic operational vocabulary is capped at six points.** "Reporting",
  "KPIs" and "attention to detail" are real parts of how I worked, and they
  are also in almost every job ad ever written, so they can colour a score but
  never carry one.

Then the penalties: a language I do not speak (the commonest form is in the
title — "Analyst *with Italian*"), skills I have never used and must not claim
(SQL, machine learning), senior grades, and years of experience beyond a
graduate's.

Every score comes with a breakdown on the card — click **Why 82?** and it shows
exactly which points were won and lost. A score you cannot interrogate is a
score you cannot trust.

### 6. Publishing

GitHub Actions runs the scraper on a 15-minute schedule, commits any change to
the job list, and then publishes the site itself. The whole thing runs on
GitHub's free tier — public repositories get unlimited Actions minutes.

That last step is deliberate, and it cost a day to learn. The obvious design is
to let the scrape's commit trigger the Pages workflow through a path filter,
and it silently does not work: a commit pushed with the built-in `GITHUB_TOKEN`
does **not** trigger other workflows, by design, so that a workflow cannot set
itself off in a loop. The scraper ran every fifteen minutes and committed
faithfully, and the live page sat on whatever data was there the last time
someone pressed the deploy button by hand — showing forty companies while the
repository held two hundred and fifty. Nothing errored. The scrape job now
deploys the site as its own second step, so the loop actually closes.

---

## The site

- Full-text search across titles, companies and descriptions
- Filters for score, company, location, fit band and posting age
- Quick filters: new today, graduate & internships, active sponsors, roles
  where my languages help, Dublin only
- **Three lists, not one.** Jobs, Applied and Hidden sit as tabs with live
  counts. Marking a job applied moves it off the board into Applied; hiding one
  — filled, or simply not for you — moves it to Hidden, where one click puts it
  back. Nothing is ever destroyed.
- Applications outlive the advert: the Applied tab keeps a snapshot, so a role
  you applied for three weeks ago is still in your record after the posting
  comes down.
- Twenty jobs to a page
- Save / Applied / Interview / Offer / Rejected tracking
- **A live Excel workbook.** Link a file once — in OneDrive, say — and every
  application writes itself into it the moment you mark it: company, role,
  date, status, fit score, sponsor evidence, link. The columns no job feed
  publishes (hiring manager, their email, recruiter, follow-up and interview
  dates) are typed straight onto the job card and land in the same row.
- One-click export to a formatted `.xlsx`, for when a download is all you want

---

## Running it yourself

```bash
git clone https://github.com/derinyesudas/ireland-job-tracker
cd ireland-job-tracker

# Unlock the research files (see "The research is encrypted" below)
pip install cryptography openpyxl
export TRACKER_KEY="your passphrase"
python scripts/vault.py open

# Rebuild the company list (slow - probes thousands of career feeds)
python scripts/build_companies.py --limit 400

# Scrape
python -m scraper.run --full

# Lock them again before committing anything
python scripts/vault.py close

# View
cd site && python -m http.server 8000
```

To retarget it at a different person, unlock the files and edit
`profile/derin.json` — role families, skills, languages and weights all live
there. No code changes needed.

---

## Layout

```
scraper/
  ats_clients.py    the eight mainstream recruitment platforms
  ats_extra.py      Oracle, Pinpoint, SuccessFactors, and the generic readers
                    - structured data, job-link following, sitemap, RSS
  ats_more.py       the enterprise suites (iCIMS, Taleo, Avature, Cornerstone,
                    Eightfold) and the two Irish ones (Occupop, HireHive)
  normalise.py      one common job shape out of twenty-seven different ones
  filters.py        Ireland / early-career / engagement-type gates
  score.py          the 0-100 compatibility model
  run.py            the pipeline, with sharded scanning
scripts/
  resolve_careers.py  careers URL -> working feed, verified by calling it
  inspect_sites.py    works out what an unresolved site would need
  build_companies.py  the government sponsor register
  crypt.py            the encryption itself - key handling and file locking
  vault.py            unlocks the research before a run, locks it after
profile/derin.json.enc  everything personal, in one editable file - encrypted
site/               the front end (vanilla JS, no build step)
data/               the job board in the clear; the research encrypted

site/data/ is generated too, and deliberately NOT committed: it held the same
bytes as data/, and carrying both doubled the repository's growth for nothing.
The publish job builds it from data/ before uploading the page.
```

## Security

The site is static — GitHub hands visitors a set of files, and there is no
server of mine, no database, no accounts and no uploads. That removes most of
the usual web attack surface by construction: there are no sessions to steal,
no login to brute-force, no queries to inject. Four things did apply, and are
handled:

- **Job links are validated, not trusted.** Every posting's web address is read
  off a third-party careers site, and a link can carry a script instead of a
  destination. Escaping the text does not help — the danger is the scheme. So
  every address is parsed twice: once when the scraper writes it, once when the
  page draws it, and anything that is not ordinary `http`/`https` is discarded.
  A posting with no usable link still appears, with the apply button disabled.
- **No third-party scripts.** The spreadsheet library is kept in the repository
  rather than loaded from a public CDN. A script fetched from someone else's
  server runs with full access to the page and everything stored in it, which
  makes the page only as trustworthy as that server on the day you visit.
- **A Content-Security-Policy** caps the blast radius of anything that slipped
  through anyway: scripts may only come from this site, the page may not send
  data anywhere else, and inline script is refused.

- **The research is encrypted at rest.** The register, the resolved careers
  feeds, the site inspection notes and the CV scoring profile are AES-256-GCM
  files. What sits in this repository is ciphertext; the key never appears in
  it. The workflow unlocks them at the start of a run from a passphrase held as
  a repository secret, and locks them again before committing. The job board
  itself is deliberately left readable, because the site has to draw it.

  The scheme is ordinary: PBKDF2-HMAC-SHA256 at 600,000 rounds derives a key
  from the passphrase, and that key unwraps a random data key which is what
  actually encrypts the files. Storing the data key wrapped once per passphrase
  means a second phrase can be issued and later revoked without the first one
  ever changing — and a recovery code, kept on paper, is one such holder.

Application history, saved jobs and hiring-manager notes live in the visitor's
own browser and are never uploaded, so there is nothing personal on the server
to leak.

## Notes and limits

- GitHub schedules cron jobs on a best-effort basis, so "every 15 minutes" is
  in practice "usually within 15–25 minutes". The Actions tab has a manual
  trigger for when you want a check right now.
- Every reader now fetches the full advert, including the platforms whose
  listing endpoint only returns a teaser (Workday, Oracle, SmartRecruiters).
  That costs one extra request per job and is worth it: a job scored on its
  title alone lands in roughly the wrong place.
- The generic readers open at most 45 job pages per company per run. That is
  deliberate: it is enough to catch anything posted recently, which is the
  point of checking every 15 minutes, without hammering anyone's site.
- Hiring manager names and emails are not published by any ATS feed, so the
  tracker does not invent them: those columns are typed in on the job card and
  flow into the workbook from there.
- The live workbook uses the browser's File System Access API rather than the
  Microsoft Graph API. Graph would mean registering an Azure application,
  running an OAuth flow and looking after a refresh token — a lot of moving
  parts, and a credential to store, for a spreadsheet on one machine. Here the
  file is chosen once through the browser's own save dialog, and OneDrive syncs
  it like anything else in that folder. Needs Chrome or Edge on the desktop;
  everywhere else the download button does the same job.
- Around a hundred employers in the register never resolved to a feed. Most
  are behind a bot wall that only a real browser gets past. They are recorded
  in `data/resolution_report.json.enc` with the reason, rather than quietly
  dropped.

Built by [Derin Yesudas](https://github.com/derinyesudas) — MSc Business
Analytics, University College Cork.
