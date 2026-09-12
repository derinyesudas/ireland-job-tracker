/* ==========================================================================
   Ireland Job Tracker - front end
   Plain JavaScript on purpose: no build step, no framework to update, and you
   can read every line of it. Loads two files the scraper writes
   (data/jobs.json and data/stats.json) and draws the page from them.
   ========================================================================== */

const STORE_KEY = 'ijt-state-v1';
const THEME_KEY = 'ijt-theme';

let JOBS = [];
let STATS = {};
let STATE = load();          // { [jobId]: { status, appliedAt, notes } }
let QUICK = new Set();
let TAB = 'jobs';                       // 'jobs' | 'applied' | 'hidden'
let PAGE = 1;

const APPLIED_STATES = ['applied', 'interview', 'offer', 'rejected'];

/* You scrape ninety-six times a day. Without a mark for what is new since you
   were last here, that work only ever produces a list that looks the same. */
const VISIT_KEY = 'ijt-last-visit';
const LAST_VISIT = (() => {
  try {
    const v = localStorage.getItem(VISIT_KEY);
    localStorage.setItem(VISIT_KEY, new Date().toISOString());
    return v;                            // null on a first ever visit
  } catch { return null; }
})();
const isNewSinceVisit = j =>
  !!LAST_VISIT && (j.first_seen || '') > LAST_VISIT;

/* An application with no movement for a fortnight has almost certainly been
   passed over. Saying so is kinder than leaving it sitting there looking live,
   and it is the prompt to chase or to let go. */
const GHOST_DAYS = 14;
const isApplied = st => APPLIED_STATES.includes(st);

/* ------------------------------------------------------------ local state */

function load() {
  try { return JSON.parse(localStorage.getItem(STORE_KEY)) || {}; }
  catch { return {}; }
}
function save() {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(STATE)); }
  catch { /* private browsing - state just won't persist */ }
}
function statusOf(id) { return (STATE[id] || {}).status || ''; }
function isHidden(id) { return !!(STATE[id] || {}).hidden; }

/* Dismissing a job never destroys anything - it moves to the Hidden tab, and
   one click there puts it back. A tracker you cannot undo is a tracker you
   stop trusting. */
function setHidden(id, hidden) {
  const job = JOBS.find(j => j.id === id);
  if (!STATE[id]) STATE[id] = {};
  if (hidden) {
    STATE[id].hidden = true;
    STATE[id].hiddenAt = new Date().toISOString();
    if (job) STATE[id].snapshot = snapshotOf(job);
  } else {
    delete STATE[id].hidden;
    delete STATE[id].hiddenAt;
  }
  save();
  render();
}

function snapshotOf(job) {
  return {
    title: job.title, company: job.company, location: job.location,
    url: job.url, score: job.score, band: job.band, source: job.source,
    department: job.department, employment_type: job.employment_type,
    posted_at: job.posted_at, permits: job.permits,
    sponsor_tier: job.sponsor_tier, salary: job.salary, closes_at: job.closes_at
  };
}

/* Applications outlive the advert. A job you applied to three weeks ago will
   eventually drop off the live board, and it must not vanish out of your own
   record when it does - so the Applied tab falls back to the snapshot taken
   when you marked it. */
function appliedJobs() {
  return Object.entries(STATE)
    .filter(([, st]) => isApplied(st.status))
    .map(([id, st]) => JOBS.find(j => j.id === id) || Object.assign({ id }, st.snapshot || {}))
    .filter(j => j && j.title);
}

function hiddenJobs() {
  return Object.entries(STATE)
    .filter(([, st]) => st.hidden)
    .map(([id, st]) => JOBS.find(j => j.id === id) || Object.assign({ id }, st.snapshot || {}))
    .filter(j => j && j.title);
}

function bucketCounts() {
  const applied = appliedJobs().length;
  const hidden = hiddenJobs().length;
  // The tab counts what the tab will show. A closed vacancy is not on the
  // board, so counting it here contradicted both the header and the list.
  const jobs = JOBS.filter(j =>
    !j.closed && !isHidden(j.id) && !isApplied(statusOf(j.id))).length;
  return { jobs, applied, hidden };
}

function setStatus(id, status) {
  const job = JOBS.find(j => j.id === id);
  if (!STATE[id]) STATE[id] = {};
  if (STATE[id].status === status) {
    delete STATE[id].status;
  } else {
    STATE[id].status = status;
    if (status === 'applied' && !STATE[id].appliedAt) {
      STATE[id].appliedAt = new Date().toISOString();
    }
    // Keep a snapshot so the Excel export still works after a job expires
    // off the live feed.
    if (job) STATE[id].snapshot = snapshotOf(job);
  }
  save();
  scheduleSync();
  render();
}

/* ---------------------------------------------------------------- helpers */

/* A job's web address comes from someone else's careers site, and a link can
   carry a small program instead of a destination - "javascript:..." followed
   by anything the author likes. Escaping the text does not stop that, because
   the danger is the scheme, not the characters. So every address is parsed
   before it is used, and anything that is not ordinary http or https is
   replaced with a dead link. Verified against the real attack: a link that
   read the saved application history and posted it to another site. */
function safeUrl(raw) {
  if (!raw) return '';
  try {
    const u = new URL(String(raw), location.href);
    return (u.protocol === 'http:' || u.protocol === 'https:') ? u.href : '';
  } catch { return ''; }
}

const esc = s => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;')
  .replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function daysUntil(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d)) return null;
  return Math.ceil((d - new Date()) / 86400000);
}

function daysAgo(iso) {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (isNaN(t)) return null;
  return (Date.now() - t) / 86400000;
}

function ago(iso) {
  const d = daysAgo(iso);
  if (d == null) return '';
  if (d < 0.042) return 'just now';
  if (d < 1) return Math.round(d * 24) + 'h ago';
  if (d < 2) return 'yesterday';
  if (d < 30) return Math.round(d) + 'd ago';
  return Math.round(d / 30) + 'mo ago';
}

const BAND_COLOR = {
  excellent: 'var(--excellent)', strong: 'var(--strong)',
  decent: 'var(--decent)', stretch: 'var(--stretch)', weak: 'var(--weak)'
};

/* What today actually asks of you.
 *
 * A board of 1,429 jobs does not tell you what to do next; it tells you how
 * much there is. Two things are genuinely time-bound - an application nobody
 * has answered, and a good job going cold - so those get said out loud and
 * everything else stays a list. */

function todayLine() {
  const el = document.getElementById('today');
  if (!el) return;
  if (TAB !== 'jobs') { el.hidden = true; return; }

  const chase = Object.entries(STATE).filter(([, st]) => {
    if (st.status !== 'applied' || !st.appliedAt) return false;
    const d = daysAgo(st.appliedAt);
    return d != null && d >= GHOST_DAYS;
  }).length;

  const cooling = JOBS.filter(j => {
    if (j.closed || isHidden(j.id) || isApplied(statusOf(j.id))) return false;
    if ((j.score || 0) < 70) return false;
    const d = daysAgo(j.first_seen || j.posted_at);
    return d != null && d >= 6 && d <= 12;
  }).length;

  const bits = [];
  if (cooling) bits.push(`<strong>${cooling}</strong> strong ${cooling === 1 ? 'job is' : 'jobs are'} about a week old — these go first`);
  if (chase) bits.push(`<strong>${chase}</strong> ${chase === 1 ? 'application has' : 'applications have'} had no reply in ${GHOST_DAYS} days`);

  el.hidden = bits.length === 0;
  el.innerHTML = bits.join(' · ');
}

/* ----------------------------------------------------------------- filters */

function searchKey(job) {
  if (job._key === undefined) {
    job._key = (job.title + ' ' + job.company + ' ' + (job.location || '') + ' ' +
                (job.department || '') + ' ' + (job.description || '')).toLowerCase();
  }
  return job._key;
}

function visible() {
  const q = document.getElementById('q').value.trim().toLowerCase();

  // The Applied and Hidden tabs are your own short lists, so only the search
  // box applies to them. Silently withholding an application because a score
  // slider is set somewhere would be a nasty surprise.
  if (TAB !== 'jobs') {
    const base = TAB === 'applied' ? appliedJobs() : hiddenJobs();
    const matches = j => !q || searchKey(j).includes(q);
    return base.filter(matches).sort((a, b) => (b.score || 0) - (a.score || 0));
  }

  const minScore = +document.getElementById('minscore').value;
  const company = document.getElementById('f-company').value;
  const location = document.getElementById('f-location').value;
  const band = document.getElementById('f-band').value;
  const age = document.getElementById('f-age').value;

  let out = JOBS.filter(job => {
    // Applied and dismissed jobs leave the main board. They are not lost -
    // each has its own tab - but they should stop competing for attention.
    if (isHidden(job.id)) return false;
    if (isApplied(statusOf(job.id))) return false;
    // A job that has come off its own careers page cannot be applied to, so it
    // leaves the board. It stays visible under Applied, where knowing that a
    // role you went for has closed is worth more than a tidy list.
    if (job.closed) return false;

    if (job.score < minScore) return false;
    if (company && job.company !== company) return false;
    if (band && job.band !== band) return false;
    if (location && !(job.location || '').includes(location)) return false;

    if (age) {
      const d = daysAgo(job.first_seen || job.posted_at);
      if (d == null || d > +age) return false;
    }

    // The haystack is built once, at load, not on every keystroke. Lowercasing
    // 1,429 descriptions - about 8.5 million characters - for every letter
    // typed is what made the search box feel heavy.
    if (q && !searchKey(job).includes(q)) return false;

    const st = statusOf(job.id);
    if (QUICK.has('saved') && st !== 'saved') return false;
    if (QUICK.has('closing')) {
      const d = daysUntil(job.closes_at);
      if (d === null || d < 0 || d > 14) return false;
    }
    if (QUICK.has('new') && !job.is_new) return false;
    if (QUICK.has('sponsor') && !(job.sponsor_tier >= 2)) return false;
    if (QUICK.has('dublin') && !/dublin/i.test(job.location || '')) return false;

    if (QUICK.has('grad')) {
      const t = (job.title + ' ' + (job.description || '')).toLowerCase();
      if (!/graduate|intern|placement|trainee|entry.level|junior|early career|apprentice/.test(t)) return false;
    }
    if (QUICK.has('lang')) {
      const hasLang = (job.breakdown || []).some(b => b.label === 'Language edge');
      if (!hasLang) return false;
    }
    return true;
  });

  const sort = document.getElementById('sort').value;
  // Fit alone is the wrong ranking for a job board.
  //
  // Postings in this market take applications for about nine days, and roughly
  // two in five applications reach a job inside its first forty-eight hours. A
  // role scoring 88 that you reach on day eight is a role you have lost, so the
  // default ordering values a good job you can still get over a better one you
  // probably cannot. The penalty is gentle - three points a day, capped - so a
  // genuinely excellent match never falls off the front page for being a week
  // old, it just stops outranking an equally good one posted this morning.
  const urgency = j => {
    const d = daysAgo(j.first_seen || j.posted_at);
    if (d == null) return (j.score || 0) - 6;
    return (j.score || 0) - Math.min(d * 3, 24);
  };
  if (sort === 'fresh') out.sort((a, b) => urgency(b) - urgency(a));
  if (sort === 'score') out.sort((a, b) => b.score - a.score);
  if (sort === 'new') out.sort((a, b) => (b.first_seen || '').localeCompare(a.first_seen || ''));
  if (sort === 'company') out.sort((a, b) => a.company.localeCompare(b.company) || b.score - a.score);
  if (sort === 'title') out.sort((a, b) => a.title.localeCompare(b.title));
  return out;
}

/* ------------------------------------------------------------------ render */

function cardHTML(job) {
  const st = statusOf(job.id);
  const color = BAND_COLOR[job.band] || 'var(--weak)';

  const tags = [];
  if (job.is_new) tags.push('<span class="tag new">NEW</span>');
  // Two different kinds of evidence, and the tag should not blur them.
  // A permit count is a government record of permits actually granted; a tier
  // with no permits behind it is Derin's own desk research. Printing
  // "Sponsor · 0 permits" made a real signal look like a contradiction.
  if (job.permits > 0) {
    tags.push(`<span class="tag sponsor">${job.sponsor_tier >= 3 ? 'Major sponsor' : 'Sponsor'} · ${job.permits} permit${job.permits === 1 ? '' : 's'} this year</span>`);
  } else if (job.sponsor_tier >= 3) {
    tags.push(`<span class="tag sponsor">Documented sponsor</span>`);
  } else if (job.sponsor_tier === 2) {
    tags.push(`<span class="tag sponsor">Likely sponsor</span>`);
  }
  else if (job.sponsor_tier === 1) tags.push('<span class="tag sponsor">On permit register</span>');

  // A count beats an adjective. This employer sponsored this many people.
  if (job.permits > 0)
    tags.push(`<span class="tag permits">Sponsored ${job.permits} ${job.permits === 1 ? 'person' : 'people'}</span>`);

  // Read the TITLE for what kind of role this is, and match whole words.
  //
  // This used to search the title and the whole job ad for /intern|placement/,
  // which meant "internal" and "international" both counted. 544 jobs wore the
  // Internship badge and 508 of them had no such word in their title - Davy's
  // 12-18 month contract, AIB's AML KYC Analyst. Worse, the chain is else-if,
  // so a wrong Internship badge took the place of the right one: only 42 jobs
  // showed "Entry level", and "Junior Data Analyst" was not among them.
  if (job.closed) tags.push('<span class="tag closed">Closed</span>');
  else if (isNewSinceVisit(job)) tags.push('<span class="tag sincevisit">Since you last looked</span>');

  const age = daysAgo(job.first_seen || job.posted_at);
  if (!job.closed && age != null && age >= 7 && (job.score || 0) >= 60)
    tags.push(`<span class="tag stale">${age}d old - apply or lose it</span>`);

  if (isApplied(statusOf(job.id))) {
    const since = daysAgo((STATE[job.id] || {}).appliedAt);
    if (since != null && since >= GHOST_DAYS && statusOf(job.id) === 'applied')
      tags.push(`<span class="tag ghosted">No word in ${since} days</span>`);
  }

  // What this role means for a permit. The ad's own words come first, because
  // an employer saying no outright is the only certain answer there is.
  if (job.sponsorship === 'refuses')
    tags.push('<span class="tag nosponsor">Says no sponsorship</span>');
  else if (job.sponsorship === 'offers')
    tags.push('<span class="tag yessponsor">Offers sponsorship</span>');

  if (job.permit_route === 'below_threshold')
    tags.push(`<span class="tag belowbar">€${(job.salary_eur/1000).toFixed(0)}k - under the permit bar</span>`);
  else if (job.permit_route === 'general')
    tags.push(`<span class="tag generalroute">€${(job.salary_eur/1000).toFixed(0)}k - General permit only</span>`);
  else if (job.permit_route === 'critical_skills')
    tags.push(`<span class="tag csep">€${(job.salary_eur/1000).toFixed(0)}k - clears Critical Skills</span>`);

  const title = job.title.toLowerCase();
  const full = (job.title + ' ' + (job.description || '')).toLowerCase();
  if (/\bgraduate (?:programme|program|scheme)\b/.test(full))
    tags.push('<span class="tag grad">Graduate programme</span>');
  else if (/\b(?:intern|interns|internship|internships|placement|co[- ]?op)\b/.test(title))
    tags.push('<span class="tag grad">Internship</span>');
  else if (/\b(?:junior|jnr|entry[- ]level|trainee|graduate|apprentice)\b/.test(title))
    tags.push('<span class="tag grad">Entry level</span>');

  if ((job.breakdown || []).some(b => b.label === 'Language edge'))
    tags.push('<span class="tag lang">Your languages help here</span>');

  // A closing date is the most actionable thing on the card, so it leads -
  // and turns urgent once it is inside a week.
  const days = daysUntil(job.closes_at);
  if (days !== null && days >= 0) {
    const urgent = days <= 7;
    tags.push(`<span class="tag ${urgent ? 'closing' : ''}">${
      days === 0 ? 'Closes today' : days === 1 ? 'Closes tomorrow'
        : `Closes in ${days} days`}</span>`);
  }
  if (job.salary) tags.push(`<span class="tag pay">${esc(job.salary)}</span>`);

  if (job.department) tags.push(`<span class="tag">${esc(job.department)}</span>`);
  tags.push(`<span class="tag">via ${esc(job.source)}</span>`);

  const rows = (job.breakdown || []).map(b => {
    const cls = b.points > 0 ? 'pos' : b.points < 0 ? 'neg' : 'zero';
    const sign = b.points > 0 ? '+' : '';
    return `<div class="why-row">
      <span class="lbl">${esc(b.label)}</span>
      <span class="pts ${cls}">${sign}${b.points}</span>
      <span class="note">${esc(b.note)}</span>
    </div>`;
  }).join('');

  const appField = (id, key, label, type = 'text', wide = false) => {
    const v = (STATE[id] || {})[key] || '';
    return `<label class="appf ${wide ? 'wide' : ''}">
      <span>${label}</span>
      <input type="${type}" data-field="${key}" data-id="${id}"
             value="${esc(v)}" placeholder="—">
    </label>`;
  };

  const statusBtns = `
    <button class="btn ${st === 'saved' ? 'on' : ''}" data-act="saved" data-id="${job.id}">
      ${st === 'saved' ? 'Saved' : 'Save'}
    </button>
    <button class="btn ${['applied','interview','offer','rejected'].includes(st) ? 'on' : ''}"
            data-act="applied" data-id="${job.id}">
      ${st === 'applied' ? 'Applied ✓' : st === 'interview' ? 'Interview' :
        st === 'offer' ? 'Offer' : st === 'rejected' ? 'Rejected' : 'Mark applied'}
    </button>
    ${['applied','interview','offer','rejected'].includes(st) ? `
      <select class="btn" data-stage="${job.id}">
        <option value="applied"   ${st==='applied'?'selected':''}>Applied</option>
        <option value="interview" ${st==='interview'?'selected':''}>Interview</option>
        <option value="offer"     ${st==='offer'?'selected':''}>Offer</option>
        <option value="rejected"  ${st==='rejected'?'selected':''}>Rejected</option>
      </select>` : ''}
  `;

  return `
  <article class="job ${['applied','rejected'].includes(st) ? 'applied' : ''} ${['applied','interview','offer','rejected'].includes(st) ? 'tracking' : ''}"
           style="--band:${color}" data-id="${job.id}">
    <div class="score-box">
      <div class="score-num">${job.score}</div>
      <div class="score-label">${esc(job.band)}</div>
      <div class="score-bar"><i style="width:${job.score}%"></i></div>
    </div>

    <div class="job-main">
      <h3 class="job-title">${safeUrl(job.url)
        ? `<a href="${esc(safeUrl(job.url))}" target="_blank" rel="noopener noreferrer">${esc(job.title)}</a>`
        : esc(job.title)}</h3>
      <div class="job-sub">
        <b>${esc(job.company)}</b> · ${esc(job.location || 'Ireland')} ·
        seen ${ago(job.first_seen)}
      </div>
      <div class="tags">${tags.join('')}</div>
    </div>

    <div class="job-actions">
      ${safeUrl(job.url)
        ? `<a class="btn primary" href="${esc(safeUrl(job.url))}" target="_blank" rel="noopener noreferrer">Open &amp; apply</a>`
        : `<span class="btn primary disabled" title="This posting had no usable link">No link</span>`}
      ${statusBtns}
      <button class="btn" data-act="why" data-id="${job.id}">Why ${job.score}?</button>
      ${isHidden(job.id)
        ? `<button class="btn restore" data-act="unhide" data-id="${job.id}">Put back</button>`
        : `<button class="btn dismiss" data-act="hide" data-id="${job.id}"
                   title="Take this off the board — filled, or not for you">Hide</button>`}
    </div>

    ${['applied','interview','offer','rejected'].includes(st) ? `
    <div class="appdetail">
      <h4>Application record <span>— goes straight into the workbook</span></h4>
      <div class="appgrid">
        ${appField(job.id, 'hmName',        'Hiring manager')}
        ${appField(job.id, 'hmEmail',       'Manager email', 'email')}
        ${appField(job.id, 'recruiter',     'Recruiter / contact')}
        ${appField(job.id, 'cvVersion',     'CV version sent')}
        ${appField(job.id, 'coverLetter',   'Cover letter sent')}
        ${appField(job.id, 'followUp',      'Follow-up date', 'date')}
        ${appField(job.id, 'interviewDate', 'Interview date', 'date')}
        ${appField(job.id, 'outcome',       'Outcome')}
      </div>
      ${appField(job.id, 'notes', 'Notes', 'text', true)}
    </div>` : ''}

    <div class="why">
      <h4>How this score was worked out</h4>
      ${rows}
      ${job.description ? `<div class="why-desc">${esc(job.description.slice(0, 2200))}</div>` : ''}
    </div>
  </article>`;
}

const PER_PAGE = 20;

/* Page controls: first / prev / a window of numbers / next / last.
   The window keeps the bar a fixed width whether there are three pages or
   thirty, so it never reflows the layout as you move through it. */
function pagerHTML(page, pages, total) {
  if (pages <= 1) return '';
  const win = [];
  let from = Math.max(1, page - 2);
  let to = Math.min(pages, from + 4);
  from = Math.max(1, to - 4);
  for (let i = from; i <= to; i++) win.push(i);

  const btn = (p, label, cls = '', disabled = false) =>
    `<button class="page ${cls}" data-page="${p}" ${disabled ? 'disabled' : ''}>${label}</button>`;

  const first = page > 1 ? btn(1, '\u00ab', 'step') : btn(1, '\u00ab', 'step', true);
  const prev  = page > 1 ? btn(page - 1, 'Previous', 'step') : btn(1, 'Previous', 'step', true);
  const next  = page < pages ? btn(page + 1, 'Next', 'step') : btn(pages, 'Next', 'step', true);
  const last  = page < pages ? btn(pages, '\u00bb', 'step') : btn(pages, '\u00bb', 'step', true);

  const lo = (page - 1) * PER_PAGE + 1;
  const hi = Math.min(total, page * PER_PAGE);
  return `<nav class="pager" aria-label="Pages">
    ${first}${prev}
    ${from > 1 ? '<span class="gap">…</span>' : ''}
    ${win.map(i => btn(i, i, i === page ? 'on' : '')).join('')}
    ${to < pages ? '<span class="gap">…</span>' : ''}
    ${next}${last}
    <span class="pager-note">${lo}–${hi} of ${total}</span>
  </nav>`;
}

function render() {
  const list = visible();
  const host = document.getElementById('jobs');

  // Clamp the page: filtering down to two results while you are on page 9
  // must not leave you staring at an empty list.
  const pages = Math.max(1, Math.ceil(list.length / PER_PAGE));
  if (PAGE > pages) PAGE = pages;
  if (PAGE < 1) PAGE = 1;
  const slice = list.slice((PAGE - 1) * PER_PAGE, PAGE * PER_PAGE);

  const counts = bucketCounts();
  document.getElementById('t-jobs').textContent = counts.jobs;
  document.getElementById('t-applied').textContent = counts.applied;
  document.getElementById('t-hidden').textContent = counts.hidden;

  const EMPTY = {
    jobs: `<div class="empty"><h3>Nothing matches those filters</h3>
           <p>Try lowering the minimum score or clearing a filter.</p></div>`,
    applied: `<div class="empty"><h3>No applications logged yet</h3>
              <p>Press <b>Mark applied</b> on a job and it will move here, with a
              place to record the hiring manager and your follow-up dates.</p></div>`,
    hidden: `<div class="empty"><h3>Nothing hidden</h3>
             <p>Press <b>Hide</b> on a job that is filled or not for you and it
             comes here, out of the way but never lost.</p></div>`,
  };

  host.innerHTML = list.length
    ? slice.map(cardHTML).join('') + pagerHTML(PAGE, pages, list.length)
    : EMPTY[TAB];

  const noun = TAB === 'applied' ? 'applications' : TAB === 'hidden' ? 'hidden jobs' : 'jobs';
  document.getElementById('count').textContent = list.length
    ? (TAB === 'jobs' ? `Showing ${list.length} of ${counts.jobs} jobs`
                      : `${list.length} ${noun}`)
    : '';
  todayLine();

  const applied = Object.values(STATE)
    .filter(s => ['applied', 'interview', 'offer', 'rejected'].includes(s.status)).length;
  document.getElementById('s-applied').textContent = applied;
}

/* ------------------------------------------------------------ Excel export */

function applicationRows() {
  const rows = Object.entries(STATE)
    .filter(([, s]) => ['applied', 'interview', 'offer', 'rejected'].includes(s.status))
    .map(([id, s]) => {
      const j = JOBS.find(x => x.id === id) || s.snapshot || {};
      return {
        'Application Date': s.appliedAt ? s.appliedAt.slice(0, 10) : '',
        'Company': j.company || '',
        'Job Title': j.title || '',
        'Location': j.location || '',
        'Status': (s.status || '').replace(/^./, c => c.toUpperCase()),
        'Fit Score': j.score ?? '',
        'Fit Band': j.band || '',
        'Sponsor - permits issued': j.permits || 0,
        'Job Link': j.url || '',
        'Applied Via': j.source || '',
        'Department': j.department || '',
        'Employment Type': j.employment_type || '',
        'Job Posted': (j.posted_at || '').slice(0, 10),
        // These four cannot be read from a public job feed - no ATS publishes
        // them. Left blank deliberately rather than guessed.
        'Hiring Manager Name': s.hmName || '',
        'Hiring Manager Email': s.hmEmail || '',
        'Recruiter / Contact': s.recruiter || '',
        'CV Version Sent': s.cvVersion || '',
        'Cover Letter Sent': s.coverLetter || '',
        'Follow-up Date': s.followUp || '',
        'Interview Date': s.interviewDate || '',
        'Outcome': s.outcome || '',
        'Notes': s.notes || ''
      };
    })
    .sort((a, b) => (b['Application Date'] || '').localeCompare(a['Application Date'] || ''));

  return rows;
}

function buildWorkbook(rows) {
  const ws = XLSX.utils.json_to_sheet(rows);
  ws['!cols'] = [
    { wch: 15 }, { wch: 26 }, { wch: 40 }, { wch: 20 }, { wch: 11 },
    { wch: 9 }, { wch: 10 }, { wch: 20 }, { wch: 45 }, { wch: 14 },
    { wch: 20 }, { wch: 16 }, { wch: 12 }, { wch: 22 }, { wch: 28 },
    { wch: 22 }, { wch: 18 }, { wch: 16 }, { wch: 14 }, { wch: 14 },
    { wch: 14 }, { wch: 40 }
  ];
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, 'Applications');
  return wb;
}

function xlsxReady() {
  if (typeof XLSX !== 'undefined') return true;
  alert('The spreadsheet library did not load — check your connection and refresh.');
  return false;
}

function exportExcel() {
  if (!xlsxReady()) return;
  const rows = applicationRows();
  if (!rows.length) {
    alert('No applications logged yet. Mark a job as applied first.');
    return;
  }
  const stamp = new Date().toISOString().slice(0, 10);
  XLSX.writeFile(buildWorkbook(rows), `Job Applications ${stamp}.xlsx`);
}

/* ================================================================= live sync
   Marking a job "applied" writes the row straight into a workbook sitting in
   OneDrive, so the spreadsheet is current everywhere without a download step.

   This uses the browser's File System Access API rather than the Microsoft
   Graph API. Graph would mean registering an Azure application, running an
   OAuth flow and storing a refresh token - a lot of moving parts, and
   credentials to look after, for a spreadsheet on this machine. Here the file
   is chosen once through the browser's own save dialog; Chrome remembers the
   handle, and OneDrive syncs the file the same way it syncs anything else in
   that folder. Nothing is stored anywhere but this browser and that file.
   ========================================================================= */

const DB_NAME = 'ijt-sync';
const DB_STORE = 'handles';
let SYNC_HANDLE = null;
let syncTimer = null;

function idb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(DB_STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function idbSet(key, value) {
  const db = await idb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(DB_STORE, 'readwrite');
    tx.objectStore(DB_STORE).put(value, key);
    tx.oncomplete = resolve;
    tx.onerror = () => reject(tx.error);
  });
}

async function idbGet(key) {
  const db = await idb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(DB_STORE, 'readonly');
    const r = tx.objectStore(DB_STORE).get(key);
    r.onsuccess = () => resolve(r.result || null);
    r.onerror = () => reject(r.error);
  });
}

function syncSupported() {
  return typeof window.showSaveFilePicker === 'function';
}

function setSyncLabel(text, on) {
  const btn = document.getElementById('sync');
  if (!btn) return;
  btn.textContent = text;
  btn.classList.toggle('on', !!on);
}

async function linkWorkbook() {
  if (!syncSupported()) {
    alert('Live sync needs Chrome or Edge on the desktop.\n\n' +
          'Use "Export to Excel" instead - it downloads the same workbook.');
    return;
  }
  try {
    const handle = await window.showSaveFilePicker({
      suggestedName: 'Job Applications.xlsx',
      types: [{
        description: 'Excel workbook',
        accept: { 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'] }
      }]
    });
    SYNC_HANDLE = handle;
    await idbSet('workbook', handle);
    await writeWorkbook(true);
    setSyncLabel('Synced \u2713', true);
  } catch (err) {
    if (err && err.name !== 'AbortError') {
      console.error(err);
      alert('Could not link the workbook: ' + err.message);
    }
  }
}

async function ensurePermission(handle, interactive) {
  const opts = { mode: 'readwrite' };
  if ((await handle.queryPermission(opts)) === 'granted') return true;
  if (!interactive) return false;
  return (await handle.requestPermission(opts)) === 'granted';
}

async function writeWorkbook(interactive = false) {
  if (!SYNC_HANDLE || typeof XLSX === 'undefined') return false;
  try {
    if (!(await ensurePermission(SYNC_HANDLE, interactive))) {
      setSyncLabel('Sync paused', false);
      return false;
    }
    const rows = applicationRows();
    if (!rows.length) return false;
    const data = XLSX.write(buildWorkbook(rows), { bookType: 'xlsx', type: 'array' });
    const w = await SYNC_HANDLE.createWritable();
    await w.write(new Blob([data]));
    await w.close();
    setSyncLabel(`Synced \u2713 ${rows.length}`, true);
    return true;
  } catch (err) {
    console.error('sync failed', err);
    setSyncLabel('Sync failed', false);
    return false;
  }
}

/* Every status change rewrites the workbook, debounced so a burst of clicks
   is one write rather than five. */
function scheduleSync() {
  if (!SYNC_HANDLE) return;
  clearTimeout(syncTimer);
  syncTimer = setTimeout(() => writeWorkbook(false), 900);
}

async function restoreSync() {
  if (!syncSupported()) {
    const btn = document.getElementById('sync');
    if (btn) btn.style.display = 'none';
    return;
  }
  try {
    const handle = await idbGet('workbook');
    if (!handle) return;
    SYNC_HANDLE = handle;
    if (await ensurePermission(handle, false)) {
      setSyncLabel('Synced \u2713', true);
      writeWorkbook(false);
    } else {
      // Chrome drops the grant between sessions; one click restores it.
      setSyncLabel('Resume sync', false);
    }
  } catch { /* no handle stored yet */ }
}

/* -------------------------------------------------------------------- init */

function fillSelect(id, values) {
  const el = document.getElementById(id);
  const first = el.options[0];
  el.innerHTML = '';
  el.appendChild(first);
  values.forEach(v => {
    const o = document.createElement('option');
    o.value = v; o.textContent = v;
    el.appendChild(o);
  });
}

async function init() {
  // Theme
  const saved = localStorage.getItem(THEME_KEY);
  if (saved) document.documentElement.dataset.theme = saved;
  const themeBtn = document.getElementById('theme');
  const syncTheme = () => {
    themeBtn.textContent = document.documentElement.dataset.theme === 'dark' ? 'Light' : 'Dark';
  };
  syncTheme();
  themeBtn.onclick = () => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem(THEME_KEY, next); } catch {}
    syncTheme();
  };

  // Data
  try {
    const [jobs, stats] = await Promise.all([
      fetch('data/jobs.json?t=' + Date.now()).then(r => r.json()),
      fetch('data/stats.json?t=' + Date.now()).then(r => r.json()).catch(() => ({}))
    ]);
    JOBS = jobs; STATS = stats;
  } catch (err) {
    document.getElementById('jobs').innerHTML =
      `<div class="empty"><h3>No job data yet</h3>
       <p>The scraper has not finished its first run. Check back in a few minutes.</p></div>`;
    return;
  }

  // "Live jobs" has to mean jobs you can still apply to. Counting the closed
  // ones alongside them put 1,488 in the header while the list below said
  // "showing 664" - which reads as an error rather than as two true numbers.
  document.getElementById('s-total').textContent =
    JOBS.filter(j => !j.closed).length;
  document.getElementById('s-new').textContent = JOBS.filter(j => j.is_new).length;
  // Two different numbers, and conflating them is misleading: the tracker
  // watches every company in the register, but only some of them have an
  // early-career role open on any given day.
  document.getElementById('s-companies').textContent = new Set(JOBS.map(j => j.company)).size;
  document.getElementById('s-watched').textContent = STATS.companies_total || '–';
  if (STATS.last_run) {
    document.getElementById('s-updated').textContent = ago(STATS.last_run);

    // GitHub runs the scanner on a best-effort schedule, and in practice best
    // effort has meant about one run every three hours rather than every
    // fifteen minutes. The time was already on screen; what was missing was any
    // sign of when it had stopped being a good number, and what to do then.
    const box = document.getElementById('s-updated').closest('.stat');
    const mins = (Date.now() - new Date(STATS.last_run)) / 60000;
    if (box && isFinite(mins)) {
      box.classList.toggle('stale-check', mins >= 60);
      box.classList.toggle('very-stale-check', mins >= 180);
      const label = box.querySelector('span');
      if (label) label.textContent = mins >= 180 ? 'last check \u2014 hit Scan now' : 'last check';
    }
  }

  fillSelect('f-company', [...new Set(JOBS.map(j => j.company))].sort());
  const cities = ['Dublin', 'Cork', 'Galway', 'Limerick', 'Waterford', 'Remote'];
  fillSelect('f-location', cities.filter(c =>
    JOBS.some(j => (j.location || '').includes(c))));

  // Wiring
  ['q', 'sort', 'f-company', 'f-location', 'f-band', 'f-age'].forEach(id => {
    // A pause of a fifth of a second reads as instant and spares the list a
    // full redraw per letter.
    let timer = null;
    document.getElementById(id).addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(() => { PAGE = 1; render(); }, 200);
    });
  });

  const slider = document.getElementById('minscore');
  slider.addEventListener('input', () => {
    document.getElementById('minscore-val').textContent = slider.value;
    render();
  });

  document.querySelectorAll('[data-quick]').forEach(btn => {
    btn.onclick = () => {
      const key = btn.dataset.quick;
      QUICK.has(key) ? QUICK.delete(key) : QUICK.add(key);
      PAGE = 1;
      btn.classList.toggle('on');
      render();
    };
  });

  document.getElementById('reset').onclick = () => {
    document.getElementById('q').value = '';
    slider.value = 0;
    document.getElementById('minscore-val').textContent = '0';
    ['sort', 'f-company', 'f-location', 'f-band', 'f-age']
      .forEach(id => document.getElementById(id).selectedIndex = 0);
    QUICK.clear();
    PAGE = 1;
    document.querySelectorAll('[data-quick]').forEach(b => b.classList.remove('on'));
    render();
  };

  document.getElementById('tabs').addEventListener('click', e => {
    const t = e.target.closest('[data-tab]');
    if (!t) return;
    TAB = t.dataset.tab;
    PAGE = 1;
    document.querySelectorAll('#tabs .tab').forEach(b => b.classList.toggle('on', b === t));
    // The filter panel belongs to the main board only.
    document.getElementById('filters-extra').classList.toggle('hidden-panel', TAB !== 'jobs');
    render();
  });

  document.getElementById('export').onclick = exportExcel;
  const syncBtn = document.getElementById('sync');
  if (syncBtn) {
    syncBtn.onclick = () => (SYNC_HANDLE ? writeWorkbook(true) : linkWorkbook());
  }
  restoreSync();

  document.getElementById('jobs').addEventListener('click', e => {
    const pg = e.target.closest('[data-page]');
    if (pg && !pg.disabled) {
      PAGE = +pg.dataset.page;
      render();
      document.querySelector('.tabs').scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }
    const btn = e.target.closest('[data-act]');
    if (!btn) return;
    const { act, id } = btn.dataset;
    if (act === 'why') {
      btn.closest('.job').classList.toggle('open');
    } else if (act === 'hide') {
      setHidden(id, true);
    } else if (act === 'unhide') {
      setHidden(id, false);
    } else {
      setStatus(id, act);
    }
  });

  document.getElementById('jobs').addEventListener('change', e => {
    const sel = e.target.closest('[data-stage]');
    if (!sel) return;
    const id = sel.dataset.stage;
    STATE[id].status = sel.value;
    save();
    scheduleSync();
    render();
  });

  // The hiring-manager and follow-up columns are typed in here, because no
  // job feed publishes them. Saved as you type, and synced to the workbook -
  // without re-rendering, which would steal focus mid-word.
  document.getElementById('jobs').addEventListener('input', e => {
    const f = e.target.closest('[data-field]');
    if (!f) return;
    const { field, id } = f.dataset;
    if (!STATE[id]) STATE[id] = {};
    STATE[id][field] = f.value;
    save();
    scheduleSync();
  });

  render();
}

init();
