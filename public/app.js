/* git-release digest — Bento Grid Edition */
'use strict';

const _VALID_SEV = new Set(['critical', 'high', 'medium', 'low', 'none', 'unknown']);
function safeSev(s) { return _VALID_SEV.has(s) ? s : 'none'; }

// R2 public URL (CORS configured in Cloudflare dashboard)
const R2_BASE = 'https://pub-d7a866e02d744f3fb57bc3859858a5df.r2.dev';
const MANIFEST_URL = `${R2_BASE}/manifest.json`;

let allRecords = [];
let allAdvisories = [];
let activeSev = 'all';
let activeGroup = 'all';
let activeRepo = 'all';

const REPO_DISPLAY = {
  'dagster-io/dagster':      'Dagster',
  'kestra-io/kestra':        'Kestra',
  'apache/airflow':          'Airflow',
};

const GROUP_MAP = {
  'dbt-core':     ['dbt-core'],
  'dbt-adapters': ['dbt-adapters'],
  orchestration:  ['orchestration'],
};

const REPO_CHIPS = {
  'dbt-adapters': [
    { label: 'dbt-bigquery', repo: 'dbt-labs/dbt-bigquery' },
    { label: 'dbt-trino',    repo: 'starburstdata/dbt-trino' },
    { label: 'dbt-duckdb',   repo: 'duckdb/dbt-duckdb' },
  ],
  orchestration: [
    { label: 'Dagster', repo: 'dagster-io/dagster' },
    { label: 'Kestra',  repo: 'kestra-io/kestra' },
    { label: 'Airflow', repo: 'apache/airflow' },
  ],
};

// ── Boot ───────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  setupTabs();
  setupSearch();
  setupSevFilters();
  setupGroupChips();
  setupDrawer();
  loadDigest();
});

// ── Drawer ─────────────────────────────────────────────────────────────────
function setupDrawer() {
  const backdrop = document.getElementById('drawer-backdrop');
  const drawer   = document.getElementById('drawer');
  const closeBtn = document.getElementById('drawer-close');

  function closeDrawer() {
    drawer.classList.remove('open');
    backdrop.classList.add('hidden');
    document.body.style.overflow = '';
  }

  closeBtn.addEventListener('click', closeDrawer);
  backdrop.addEventListener('click', closeDrawer);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });
}

function openDrawer(record) {
  const a   = record.analysis ?? {};
  const sev = a.severity ?? 'none';

  document.getElementById('drawer-repo').textContent = REPO_DISPLAY[record.repo] ?? record.repo.split('/')[1];
  const sevEl = document.getElementById('drawer-sev');
  sevEl.textContent = sev;
  sevEl.className = `sev sev-${safeSev(sev)}`;

  document.getElementById('drawer-title').textContent = record.name || record.tag;
  document.getElementById('drawer-date').textContent  = formatDate(record.published_at);
  document.getElementById('drawer-summary').innerHTML = renderInline(a.summary ?? '');

  const changesWrap = document.getElementById('drawer-changes-wrap');
  const changesList = document.getElementById('drawer-changes');
  const changes = a.key_changes ?? [];
  if (changes.length) {
    changesList.innerHTML = changes.map(c => `<li>${renderInline(c)}</li>`).join('');
    changesWrap.classList.remove('hidden');
  } else {
    changesWrap.classList.add('hidden');
  }

  const tagsWrap = document.getElementById('drawer-tags-wrap');
  const tagsEl   = document.getElementById('drawer-tags');
  const tags = a.tags ?? [];
  if (tags.length) {
    tagsEl.innerHTML = tags.map(t => `<span class="tag">${esc(t)}</span>`).join('');
    tagsWrap.classList.remove('hidden');
  } else {
    tagsWrap.classList.add('hidden');
  }

  const cveWrap = document.getElementById('drawer-cve-wrap');
  const cvesEl  = document.getElementById('drawer-cves');
  const cveRefs = a.cve_references ?? [];
  if (cveRefs.length) {
    cvesEl.innerHTML = cveRefs.map(id =>
      `<a class="drawer-cve-chip" href="https://nvd.nist.gov/vuln/detail/${esc(id)}" target="_blank" rel="noopener">${esc(id)}</a>`
    ).join('');
    cveWrap.classList.remove('hidden');
  } else {
    cveWrap.classList.add('hidden');
  }

  document.getElementById('drawer-link').href = record.html_url ?? '#';

  const backdrop = document.getElementById('drawer-backdrop');
  const drawer   = document.getElementById('drawer');
  backdrop.classList.remove('hidden');
  drawer.classList.remove('hidden');
  requestAnimationFrame(() => drawer.classList.add('open'));
  document.body.style.overflow = 'hidden';
}

// ── Tabs ───────────────────────────────────────────────────────────────────
function setupTabs() {
  document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t === btn));
      document.querySelectorAll('.tab-panel').forEach(p => {
        const show = p.id === `tab-${btn.dataset.tab}`;
        p.classList.toggle('active', show);
        p.classList.toggle('hidden', !show);
      });
    });
  });
}

// ── Search ─────────────────────────────────────────────────────────────────
function setupSearch() {
  document.getElementById('search').addEventListener('input', () => applyFilters());
}

// ── Severity filters ───────────────────────────────────────────────────────
function setupSevFilters() {
  document.getElementById('sev-filter').addEventListener('change', e => {
    activeSev = e.target.value;
    applyFilters();
  });
}

// ── Group chips ────────────────────────────────────────────────────────────
function setupGroupChips() {
  const container = document.getElementById('group-chips');
  const sub = document.getElementById('repo-chips-sub');

  const groups = [
    { label: 'All',          key: 'all' },
    { label: 'dbt-core',     key: 'dbt-core' },
    { label: 'dbt-adapters', key: 'dbt-adapters' },
    { label: 'Orchestration',key: 'orchestration' },
  ];

  container.innerHTML = groups.map(g =>
    `<button class="chip${g.key === 'all' ? ' active' : ''}" data-group="${g.key}">${g.label}</button>`
  ).join('');

  container.addEventListener('click', e => {
    const btn = e.target.closest('[data-group]');
    if (!btn) return;
    const key = btn.dataset.group;

    if (key === activeGroup && key !== 'all') {
      activeGroup = 'all';
      activeRepo = 'all';
      showRepoChips(null);
    } else {
      activeGroup = key;
      activeRepo = 'all';
      showRepoChips(key === 'all' ? null : key);
    }

    container.querySelectorAll('.chip').forEach(c =>
      c.classList.toggle('active', c.dataset.group === activeGroup)
    );
    applyFilters();
  });

  sub.addEventListener('click', e => {
    const btn = e.target.closest('[data-repo]');
    if (!btn) return;
    const repo = btn.dataset.repo;
    activeRepo = repo === activeRepo ? 'all' : repo;
    sub.querySelectorAll('.chip').forEach(c =>
      c.classList.toggle('active', c.dataset.repo === activeRepo)
    );
    applyFilters();
  });
}

function showRepoChips(group) {
  const sub = document.getElementById('repo-chips-sub');
  activeRepo = 'all';

  if (!group || !REPO_CHIPS[group]) {
    sub.classList.add('hidden');
    sub.innerHTML = '';
    return;
  }

  sub.innerHTML = REPO_CHIPS[group].map(r =>
    `<button class="chip" data-repo="${r.repo}">${r.label}</button>`
  ).join('');
  sub.classList.remove('hidden');
}


// ── Filters ────────────────────────────────────────────────────────────────
function applyFilters() {
  const q = document.getElementById('search').value.trim().toLowerCase();

  const cards = document.querySelectorAll('.card');
  let visibleCards = 0;
  cards.forEach(c => {
    const sevOk = activeSev === 'all' || c.dataset.severity === activeSev;
    const groupOk = activeGroup === 'all' || (GROUP_MAP[activeGroup] ?? []).includes(c.dataset.group);
    const repoOk = activeRepo === 'all' || c.dataset.repo === activeRepo;
    const searchOk = !q ||
      c.dataset.repo.toLowerCase().includes(q) ||
      c.dataset.tags.toLowerCase().includes(q) ||
      c.textContent.toLowerCase().includes(q);
    const show = sevOk && groupOk && repoOk && searchOk;
    c.classList.toggle('hidden', !show);
    if (show) visibleCards++;
  });

  document.getElementById('empty-digest').classList.toggle('hidden', visibleCards > 0 || cards.length === 0);
}

// ── Data fetch ─────────────────────────────────────────────────────────────
async function loadDigest() {
  const loading = document.getElementById('loading');
  try {
    const manifest = await fetch(MANIFEST_URL, { cache: 'no-store' });
    if (!manifest.ok) throw new Error(`manifest HTTP ${manifest.status}`);
    const { digest } = await manifest.json();
    const resp = await fetch(`${R2_BASE}/${digest}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    allRecords = Array.isArray(data) ? data : (data.releases ?? []);
    allAdvisories = Array.isArray(data) ? [] : (data.advisories ?? []);
    loading.classList.add('hidden');
    const nonPkg = allRecords.filter(r =>
      r.group !== 'dbt-packages' &&
      r.group !== 'dbt-fusion' &&
      r.repo !== 'dbt-labs/dbt-fusion' &&
      r.group !== 'bigquery' &&
      r.repo !== 'google/bigquery' &&
      r.group !== 'lakehouse' &&
      r.repo !== 'google/lakehouse'
    );
    const pkgRecs    = allRecords.filter(r => r.group === 'dbt-packages');
    const fusionRecs = allRecords.filter(r => r.group === 'dbt-fusion' || r.repo === 'dbt-labs/dbt-fusion');
    const bqRecs     = allRecords.filter(r => r.group === 'bigquery' || r.repo === 'google/bigquery');
    const lhRecs     = allRecords.filter(r => r.group === 'lakehouse' || r.repo === 'google/lakehouse');
    renderGrid(nonPkg);
    updateCounts(nonPkg, allAdvisories, pkgRecs, fusionRecs, bqRecs, lhRecs);
  } catch (err) {
    loading.className = 'empty-state';
    loading.textContent = `⚠ Failed to load: ${err.message}`;
  }
}

function updateCounts(records, advisories, pkgRecs, fusionRecs, bqRecs = [], lhRecs = []) {
  document.getElementById('digest-count').textContent = records.length || '';
  document.getElementById('advisory-count').textContent = advisories.length || '';
  const pkgBadge = document.getElementById('pkg-count');
  if (pkgBadge) {
    const pkgUnique = new Set(pkgRecs.map(r => r.repo)).size;
    pkgBadge.textContent = pkgUnique || '';
    pkgBadge.title = `${pkgUnique} packages tracked · latest release per package`;
  }
  const fusionBadge = document.getElementById('fusion-count');
  if (fusionBadge) {
    const fusionLatest = fusionRecs.length
      ? [fusionRecs.reduce((best, r) => new Date(r.published_at) > new Date(best.published_at) ? r : best)]
      : [];
    fusionBadge.textContent = fusionLatest.length || '';
    fusionBadge.title = `${fusionLatest.length} latest release · ${fusionRecs.length} total in history`;
  }
  const bqBadge = document.getElementById('bq-count');
  if (bqBadge) {
    bqBadge.textContent = bqRecs.length || '';
    bqBadge.title = `${bqRecs.length} release windows tracked`;
  }
  const lhBadge = document.getElementById('lh-count');
  if (lhBadge) {
    lhBadge.textContent = lhRecs.length || '';
    lhBadge.title = `${lhRecs.length} release windows tracked`;
  }
}

// ── Bento Grid ─────────────────────────────────────────────────────────────
function renderGrid(records) {
  const grid = document.getElementById('grid');
  if (!records.length) {
    document.getElementById('empty-digest').classList.remove('hidden');
    return;
  }

  grid.innerHTML = records.map((r, idx) => {
    const a          = r.analysis ?? {};
    const severity   = a.severity ?? 'none';
    const allTags    = a.tags ?? [];
    const isPreRel   = allTags.includes('pre-release');
    const tags       = allTags.filter(t => t !== 'pre-release').slice(0, 3);
    const changes    = (a.key_changes ?? []).slice(0, 3);

    const changesList = changes.map(c => `<li>${renderInline(c)}</li>`).join('');
    const tagChips    = tags.map(t => `<span class="tag">${esc(t)}</span>`).join('');
    const preRelBadge = isPreRel
      ? `<span class="tag tag-prerelease">pre-release</span>`
      : '';

    return `<article class="card" data-idx="${idx}"
  data-repo="${esc(r.repo)}"
  data-group="${esc(r.group ?? '')}"
  data-tags="${esc(allTags.join(' '))}"
  data-severity="${esc(severity)}">
  <div class="card-header">
    <span class="card-repo">${esc(REPO_DISPLAY[r.repo] ?? r.repo.split('/')[1])}</span>
    <div style="display:flex;align-items:center;gap:6px;">${preRelBadge}<span class="sev sev-${safeSev(severity)}">${esc(severity)}</span></div>
  </div>
  <h3 class="card-title">${esc(r.name || r.tag)}</h3>
  <p class="card-date">${formatDate(r.published_at)}</p>
  <p class="card-summary">${renderInline(a.summary ?? '')}</p>
  ${changesList ? `<ul class="card-changes">${changesList}</ul>` : ''}
  <div class="card-footer">
    ${tagChips ? `<div class="tags">${tagChips}</div>` : '<div></div>'}
    <span class="card-cta">Details <svg width="12" height="12" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M2.5 6h7M6.5 3l3 3-3 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></span>
  </div>
</article>`.trim();
  }).join('');

  grid.querySelectorAll('.card').forEach(el => {
    el.addEventListener('click', () => {
      const r = records[+el.dataset.idx];
      if (r) openDrawer(r);
    });
  });
}

// ── Security Advisories ────────────────────────────────────────────────────

// ── Helpers ────────────────────────────────────────────────────────────────
function stripMd(str) {
  return String(str ?? '')
    .replace(/#{1,6}\s+/g, '')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/\*(.+?)\*/g, '$1')
    .replace(/`{1,3}[^`]*`{1,3}/g, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/^[-*+]\s+/gm, '')
    .replace(/\n{2,}/g, ' ')
    .replace(/\n/g, ' ')
    .trim();
}

function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function renderInline(str) {
  return esc(str).replace(/`([^`]+)`/g, '<code>$1</code>');
}

function formatDate(iso) {
  if (!iso) return '';
  try {
    return new Intl.DateTimeFormat('en', { day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(iso));
  } catch { return iso; }
}
