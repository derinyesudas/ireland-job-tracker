# Ireland Job Tracker

A job board that watches 260 Irish employers' own career sites, scores every
graduate and junior role out of 100 against my CV, and flags the ones from
employers who actually sponsor work permits.

**Live: https://derinyesudas.github.io/ireland-job-tracker/**

| | |
|---|---|
| Employers watched | 260 |
| Recruitment platforms it can read | 27 |
| How often it checks | every 15 minutes |
| Jobs on the board | around 900, each scored 0-100 |
| Running cost | nothing |

---

## Why I built it

Job hunting as a 2026 graduate in Ireland meant opening the same forty career
pages every morning, and still missing roles that went up on a Tuesday and were
buried by Wednesday. Aggregators are worse. They lag by days, repost the same
job six times, and tell you nothing about whether a company will sponsor a
permit.

So I built something that reads the employers directly, every 15 minutes, and
ranks what it finds against what I have actually done.

---

## Three things I got wrong first

These cost me more time than the build, and they are the reason it works now.

**1. It ran perfectly and was completely wrong.**

For a day the live page showed 40 companies while the database held 250. No
error, no failed run, nothing red anywhere. The scraper was running on schedule
and saving correctly. The separate step that publishes the page was never being
triggered: a commit made with GitHub's own token deliberately cannot start
another workflow, so nothing ever fired. Logs do not report a step that never
starts. The scrape now publishes as part of the same run, and I check the page
rather than the log.

**2. The scoring model that flattered me was useless.**

The first version matched keyword families and rated 34% of jobs a good fit.
That felt great until I read the matches. A food-production role scored for
mentioning shift reporting. "Service Desk Analyst with Italian" reached 71. A
supermarket job outranked a claims role at an insurer.

I rebuilt it so nothing scores on vocabulary alone: the job title has to match a
role I have real evidence for. Good fits fell from 34% to 2%. A short list I
trust beats a long list I ignore.

**3. I deleted my own improvement.**

I ran an optimisation test on the scoring weights. The best version gained 0.006
AUC with a bootstrap confidence interval that crossed zero, which means possibly
nothing at all. So I deleted it and kept the model I already had.

---

## How it works

```
Employment permit register  ─┐
(gov.ie, updated monthly)    │
                             ├─►  companies.json ──► scraper ──► jobs.json ──► live site
Curated graduate employers  ─┘    (who to watch,     (every 15    (scored,      (GitHub
                                   and on which ATS)  minutes)     filtered)     Pages)
```

### 1. Working out who to watch

Three sources are merged:

- **The official sponsor register.** The Department of Enterprise publishes
  every company issued an employment permit this year. That is a record of
  permits actually granted, not a claim on a job ad, which makes it the most
  reliable sponsorship signal available. The permit count feeds the score.
- **A register of 296 Irish employers I researched by hand**
  (`data/ireland_register.json.enc`): careers URL, sector, the specific entry
  routes into each one, and a sponsorship confidence level. Where the register
  names the way in, a job matching that route scores higher.
- **A curated list** of large Irish graduate employers that hire heavily
  without topping the permit register.

### 2. Working out how they hire

Most companies run their careers page on a recruitment platform that exposes the
same public feed the page itself reads. `scripts/resolve_careers.py` opens each
careers URL and works down a ladder, stopping at the first rung that returns
real jobs:

<details>
<summary><b>The six rungs, in order</b></summary>

1. **A known platform.** Twenty-two: what startups use (Greenhouse, Lever,
   Ashby, Workable, SmartRecruiters, Recruitee, Personio), the enterprise suites
   large Irish employers run on (Workday, Oracle, SuccessFactors, iCIMS, Taleo,
   Avature, Cornerstone, Eightfold), and two that barely exist outside Ireland
   (Occupop, HireHive).
2. **Structured data on the page,** the markup sites publish so their vacancies
   appear in Google's job results.
3. **The individual job pages,** where the list page has no feed.
4. **The site's own job endpoint,** where its JavaScript names an API-shaped URL.
5. **The sitemap.** Sites that build their list in the browser have nothing in
   the HTML to follow, but Google cannot run their JavaScript either, so the job
   URLs have to be there.
6. **An RSS or Atom feed,** for the few that still publish one.

Twenty-seven readers in total, two of them added after the first full run showed
where it was losing companies. Where a page gives nothing away, its own scripts
and iframes are searched too: a branded site often hides its platform in the
HTML but loads a bundle that calls it. Where the page is marketing with the jobs
behind "Search our roles", that link is followed and the ladder tried again.

Nothing is added on a guess. A company enters only once its feed has been called
for real and returned jobs. That is also why it reads employers directly rather
than scraping LinkedIn or Indeed: these feeds are public, stable, need no login
or API key, and carry the job the moment it is published.

</details>

### 3. Knowing when to stop

The tracker is capped at 290 employers, queued by how solid the sponsorship
evidence is and then how well the employer fits. The ones that never resolve are
the long tail: rarely hiring, or behind a bot wall only a real browser gets
through. Chasing them costs more than they return. Companies already tracked are
never displaced by the cap.

### 4. Filtering

Every posting passes three gates. It must be in Ireland (with a guard against
Dublin, California and Limerick, Pennsylvania), it must not be freelance or
contract, and it must not be an obviously senior role.

Anything scoring under 10 is dropped rather than shown. Those are not near
misses. They are software engineers and account executives that picked up a
point or two for being in Dublin at a sponsoring employer. Nothing in double
figures is ever dropped, so every borderline case survives.

### 5. Scoring

Each surviving job is scored out of 100 against my CV, not against a list of
words that resemble it. Every component traces to something I can point to, and
the card says which.

| Component | Max | What it rests on |
|---|---:|---|
| Role fit | 34 | The job title, matched against ten role families |
| Early careers | 20 | Graduate, internship or entry-level wording, or an intake year |
| Tools | 18 | Excel, Power BI, Tableau, R, weighted by certified, built with, or taught |
| Industry fit | 10 | Insurance, pensions, funds, banking |
| Location | 10 | Dublin down to the rest of Ireland |
| Sponsorship | 10 | Permits the company was actually issued this year |
| How I already work | 6 | KPIs, SLAs, data accuracy. Capped, because they are in every advert |
| Language edge | +8 | Roles where Hindi or Malayalam is an advantage |

The role families are weighted by the strength of the evidence behind them. A
year of work outranks an examined subject, and an examined subject outranks a
job title that merely sounds adjacent:

<details>
<summary><b>The ten role families and the evidence behind each</b></summary>

| Family | Weight | Evidence |
|---|---:|---|
| Insurance and financial operations | 34 | A year at TCS holding insurance data at 99% accuracy |
| Analytics and reporting | 34 | MSc Business Analytics, a Power BI alert console, regression and ARIMA in R, Advanced Excel at 100% |
| Workforce planning | 30 | Forecasting from the MSc, plus the KPI and SLA habit from TCS |
| Graduate programmes | 28 | An entry route in itself: these schemes ask for the MSc and a first-class degree |
| Finance entry roles | 26 | The BMS finance specialisation, plus TallyPrime and GST |
| Quality and process | 22 | Total Quality Management examined, and a year held to SLAs |
| Supply chain | 18 | Logistics and Supply Chain Management, plus Operations Research |
| Project support | 16 | Project Management examined, and the analytics on a six-person MSc project |
| Customer operations | 12 | Nine months on a supermarket checkout. Real, but dated and non-office |
| General administration | 10 | Administration with no domain attached |

</details>

Anything from study rather than work is gated to graduate and trainee routes,
and its weight halves where the advert names no entry route: studying a subject
qualifies you to be taught the job, not to have already done it. Tax is the
sharpest case. The taxation I studied was Indian, so an Irish tax graduate
programme that teaches Irish tax from the start is a genuine fit, while a role
wanting existing knowledge of it is not.

Three rules do most of the tightening:

- **The title decides the role.** A target word buried in the body earns
  nothing. The old model gave eight points for a mention anywhere, which is how
  boilerplate became a match.
- **A title matching nothing is capped at 35,** however familiar the advert
  reads, unless it is an explicit graduate intake.
- **Generic vocabulary is capped at six points.** "Reporting" and "attention to
  detail" are real parts of how I worked and are also in almost every job ad
  ever written, so they can colour a score but never carry one.

Then the penalties: a language I do not speak, skills I have never used and must
not claim, senior grades, and experience beyond a graduate's.

Every score comes with a breakdown on the card. Click **Why 82?** and it shows
exactly which points were won and lost. A score you cannot interrogate is a
score you cannot trust.

### 6. Publishing

GitHub Actions runs the scraper every 15 minutes, commits any change to the job
list, then publishes the site as its own second step. Public repositories get
unlimited Actions minutes, so the whole thing runs for nothing.

---

## The site

- Full-text search across titles, companies and descriptions
- Filters for score, company, location, fit band and posting age
- Quick filters: new today, graduate and internships, active sponsors, roles
  where my languages help, Dublin only
- **Three lists, not one.** Jobs, Applied and Hidden sit as tabs with live
  counts. Marking a job applied moves it into Applied; hiding one moves it to
  Hidden, where a click puts it back. Nothing is ever destroyed.
- **Applications outlive the advert.** The Applied tab keeps a snapshot, so a
  role applied for three weeks ago is still there after the posting comes down.
- Save, Applied, Interview, Offer and Rejected tracking, twenty jobs to a page
- **A live Excel workbook.** Link a file once and every application writes itself
  into it the moment it is marked: company, role, date, status, fit score,
  sponsor evidence, link. The columns no feed publishes (hiring manager, their
  email, recruiter, follow-up dates) are typed onto the card and land in the
  same row. One-click `.xlsx` export when a download is all you want.

---

## Security

The site is static. GitHub hands visitors a set of files; there is no server of
mine, no database, no accounts and no uploads. That removes most of the usual
attack surface by construction: no sessions to steal, no login to brute-force,
no queries to inject. Four things did apply:

- **Job links are validated, not trusted.** Every address is read off a
  third-party site, and a link can carry a script instead of a destination.
  Escaping the text does not help, because the danger is the scheme. Each
  address is parsed twice, once when the scraper writes it and once when the
  page draws it, and anything that is not ordinary http or https is discarded.
  A posting with no usable link still appears, apply button disabled.
- **No third-party scripts.** The spreadsheet library lives in the repository
  rather than loading from a CDN. A script fetched from someone else's server
  runs with full access to the page, which makes the page only as trustworthy
  as that server on the day you visit.
- **A Content-Security-Policy** caps what survives anyway: scripts only from
  this site, no sending data elsewhere, no inline script.
- **The research is encrypted at rest.** The register, the resolved feeds and
  the scoring profile are AES-256-GCM files; what sits here is ciphertext and
  the key never appears in it. The workflow unlocks them from a passphrase held
  as a repository secret and locks them again before committing. PBKDF2 at
  600,000 rounds turns the passphrase into a key that unwraps a random data key,
  which is what actually encrypts the files. Wrapping that key once per
  passphrase means a second phrase can be issued and revoked without the first
  one ever changing.

Application history, saved jobs and notes live in the visitor's own browser and
are never uploaded, so there is nothing personal on the server to leak.

---

## Running it yourself

```bash
git clone https://github.com/derinyesudas/ireland-job-tracker
cd ireland-job-tracker
pip install cryptography openpyxl

# Unlock the research files
export TRACKER_KEY="your passphrase"
python scripts/vault.py open

python scripts/build_companies.py --limit 400   # rebuild the company list (slow)
python -m scraper.run --full                    # scrape

python scripts/vault.py close                   # lock them again before committing
cd site && python -m http.server 8000           # view
```

To retarget it at a different person, unlock the files and edit
`profile/derin.json`. Role families, skills, languages and weights all live
there. No code changes needed.

---

## Layout

<details>
<summary><b>Full file layout</b></summary>

```
scraper/
  ats_clients.py    the eight mainstream recruitment platforms
  ats_extra.py      Oracle, Pinpoint, SuccessFactors, and the generic readers
  ats_more.py       the enterprise suites, plus Occupop and HireHive
  normalise.py      one common job shape out of twenty-seven different ones
  filters.py        Ireland, early-career and engagement-type gates
  score.py          the 0-100 compatibility model
  run.py            the pipeline, with sharded scanning
scripts/
  resolve_careers.py  careers URL to working feed, verified by calling it
  inspect_sites.py    works out what an unresolved site would need
  build_companies.py  the government sponsor register
  crypt.py            key handling and file locking
  vault.py            unlocks the research before a run, locks it after
profile/derin.json.enc  everything personal, in one editable file
site/                   the front end, vanilla JS, no build step
data/                   the job board in the clear, the research encrypted
```

</details>

`site/data/` is generated and deliberately not committed. It held the same bytes
as `data/`, and carrying both doubled the repository's growth for nothing. The
publish job builds it before uploading the page.

---

## Notes and limits

<details>
<summary><b>Known limits and design trade-offs</b></summary>

- GitHub schedules cron jobs on a best-effort basis, so "every 15 minutes" is in
  practice "usually within 15 to 25". The Actions tab has a manual trigger.
- Every reader fetches the full advert, even where the listing endpoint returns
  only a teaser. One extra request per job, and worth it: a job scored on its
  title alone lands in roughly the wrong place.
- The generic readers open at most 45 job pages per company per run. Enough to
  catch anything recent, without hammering anyone's site.
- No feed publishes hiring manager names or emails, so the tracker does not
  invent them. Those columns are typed on the card.
- The live workbook uses the browser's File System Access API, not Microsoft
  Graph. Graph would mean an Azure app registration, an OAuth flow and a refresh
  token to look after, for a spreadsheet on one machine. Needs Chrome or Edge on
  desktop; elsewhere the download button does the same job.
- Around a hundred employers never resolved to a feed, most behind a bot wall
  only a real browser gets past. They are recorded in
  `data/resolution_report.json.enc` with the reason, rather than quietly dropped.

</details>

---

Built by [Derin Yesudas](https://github.com/derinyesudas), MSc Business
Analytics, University College Cork.
