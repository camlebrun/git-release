/* git-release digest — Bento Grid Edition */
'use strict';

// R2 public URL (CORS configured in Cloudflare dashboard)
const R2_BASE = 'https://pub-d7a866e02d744f3fb57bc3859858a5df.r2.dev';
const MANIFEST_URL = `${R2_BASE}/manifest.json`;

let allRecords = [];
let allAdvisories = [];
let activeSev = 'all';
let activeRepo = 'all';   // group filter
let activeSubRepo = 'all'; // individual repo filter within group

// ── Boot ───────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  setupTabs();
  setupSearch();
  setupSevFilters();
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

  document.getElementById('drawer-repo').textContent = record.repo.split('/')[1].toUpperCase();
  const sevEl = document.getElementById('drawer-sev');
  sevEl.textContent = sev;
  sevEl.className = `sev sev-${sev}`;

  document.getElementById('drawer-title').textContent = record.name || record.tag;
  document.getElementById('drawer-date').textContent  = formatDate(record.published_at);
  document.getElementById('drawer-summary').textContent = a.summary ?? '';

  const changesWrap = document.getElementById('drawer-changes-wrap');
  const changesList = document.getElementById('drawer-changes');
  const changes = a.key_changes ?? [];
  if (changes.length) {
    changesList.innerHTML = changes.map(c => `<li>${esc(c)}</li>`).join('');
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
  document.querySelectorAll('.chip[data-sev]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.chip[data-sev]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeSev = btn.dataset.sev;
      applyFilters();
    });
  });
}

// ── Group + sub-repo filters ───────────────────────────────────────────────
const GROUP_LABELS = {
  'dbt-core':     'dbt Core',
  'dbt-adapters': 'dbt Adapters',
  'orchestration':'Orchestration',
};

// repo slug → display name
const REPO_LABELS = {
  'dbt-bigquery': 'BigQuery',
  'dbt-trino':    'Trino',
  'dbt-duckdb':   'DuckDB',
  'dbt-core':     'Core',
  'dagster':      'Dagster',
  'kestra':       'Kestra',
};

let _reposByGroup = {};

function buildRepoFilters(records) {
  // Build group → repos map
  _reposByGroup = {};
  records.forEach(r => {
    const g = r.group ?? 'other';
    if (!_reposByGroup[g]) _reposByGroup[g] = new Set();
    _reposByGroup[g].add(r.repo);
  });

  const groups = Object.keys(_reposByGroup).sort();
  const container = document.getElementById('repo-filters-inline');
  const subContainer = document.getElementById('repo-filters-sub');

  const groupButtons = groups.map(g =>
    `<button class="chip" data-group="${esc(g)}">${esc(GROUP_LABELS[g] ?? g)}</button>`
  ).join('');
  container.innerHTML = `<button class="chip active" data-group="all">All</button>${groupButtons}`;

  container.querySelectorAll('.chip').forEach(btn => {
    btn.addEventListener('click', () => {
      container.querySelectorAll('.chip').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeRepo = btn.dataset.group;
      activeSubRepo = 'all';
      buildSubFilters(activeRepo, subContainer);
      applyFilters();
    });
  });
}

function buildSubFilters(group, subContainer) {
  const repos = _reposByGroup[group];
  if (!repos || repos.size <= 1 || group === 'all') {
    subContainer.classList.add('hidden');
    subContainer.innerHTML = '';
    return;
  }
  const repoButtons = [...repos].sort().map(r => {
    const slug = r.split('/')[1];
    const label = REPO_LABELS[slug] ?? slug;
    return `<button class="chip" data-subrepo="${esc(r)}">${esc(label)}</button>`;
  }).join('');
  subContainer.innerHTML = `<button class="chip active" data-subrepo="all">All</button>${repoButtons}`;
  subContainer.classList.remove('hidden');

  subContainer.querySelectorAll('.chip').forEach(btn => {
    btn.addEventListener('click', () => {
      subContainer.querySelectorAll('.chip').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeSubRepo = btn.dataset.subrepo;
      applyFilters();
    });
  });
}

// ── Filters ────────────────────────────────────────────────────────────────
function applyFilters() {
  const q = document.getElementById('search').value.trim().toLowerCase();

  const cards = document.querySelectorAll('.card');
  let visibleCards = 0;
  cards.forEach(c => {
    const sevOk = activeSev === 'all' || c.dataset.severity === activeSev;
    const groupOk = activeRepo === 'all' || c.dataset.group === activeRepo;
    const subOk = activeSubRepo === 'all' || c.dataset.repo === activeSubRepo;
    const searchOk = !q ||
      c.dataset.repo.toLowerCase().includes(q) ||
      c.dataset.tags.toLowerCase().includes(q) ||
      c.textContent.toLowerCase().includes(q);
    const show = sevOk && groupOk && subOk && searchOk;
    c.classList.toggle('hidden', !show);
    if (show) visibleCards++;
  });

  const advisories = document.querySelectorAll('.advisory-card');
  let visibleAdvisories = 0;
  advisories.forEach(a => {
    const sevOk = activeSev === 'all' || a.dataset.severity === activeSev;
    const groupOk = activeRepo === 'all' || a.dataset.group === activeRepo;
    const subOk = activeSubRepo === 'all' || a.dataset.repo === activeSubRepo;
    const repoOk = groupOk && subOk;
    const searchOk = !q || a.textContent.toLowerCase().includes(q);
    const show = sevOk && repoOk && searchOk;
    a.classList.toggle('hidden', !show);
    if (show) visibleAdvisories++;
  });

  document.getElementById('empty-digest').classList.toggle('hidden', visibleCards > 0 || cards.length === 0);
  document.getElementById('empty-advisories').classList.toggle('hidden', visibleAdvisories > 0 || advisories.length === 0);
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
    const nonPkg = allRecords.filter(r => r.group !== 'dbt-packages');
    renderGrid(nonPkg);
    renderAdvisories(allAdvisories);
    updateCounts(nonPkg, allAdvisories);
    buildRepoFilters(nonPkg);
  } catch (err) {
    loading.className = 'empty-state';
    loading.textContent = `⚠ Failed to load: ${err.message}`;
  }
}

function updateCounts(records, advisories) {
  document.getElementById('digest-count').textContent = records.length || '';
  document.getElementById('advisory-count').textContent = advisories.length || '';
}

// ── Bento Grid ─────────────────────────────────────────────────────────────
function renderGrid(records) {
  const grid = document.getElementById('grid');
  if (!records.length) {
    document.getElementById('empty-digest').classList.remove('hidden');
    return;
  }

  grid.innerHTML = records.map((r, idx) => {
    const a        = r.analysis ?? {};
    const severity = a.severity ?? 'none';
    const tags     = a.tags ?? [];
    const changes  = (a.key_changes ?? []).slice(0, 3);

    const changesList = changes.map(c => `<li>${esc(c)}</li>`).join('');
    const tagChips    = tags.map(t => `<span class="tag">${esc(t)}</span>`).join('');

    return `<article class="card" data-idx="${idx}"
  data-repo="${esc(r.repo)}"
  data-group="${esc(r.group ?? '')}"
  data-tags="${esc(tags.join(' '))}"
  data-severity="${esc(severity)}">
  <div class="card-header">
    <span class="card-repo">${esc(r.repo.split('/')[1])}</span>
    <span class="sev sev-${severity}">${severity}</span>
  </div>
  <h3 class="card-title">${esc(r.name || r.tag)}</h3>
  <p class="card-date">${formatDate(r.published_at)}</p>
  <p class="card-summary">${esc(a.summary ?? '')}</p>
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
const ACTION_LABEL = {
  'upgrade-immediately': '🚨 Upgrade immediately',
  'upgrade-this-sprint': '⚠️ Upgrade this sprint',
  'monitor': '👀 Monitor',
  'no-action': '✅ No action needed',
};

function renderAdvisories(advisories) {
  const container = document.getElementById('advisory-list');
  if (!advisories.length) {
    document.getElementById('empty-advisories').classList.remove('hidden');
    return;
  }

  container.innerHTML = advisories.map(a => {
    const sev  = a.severity ?? 'unknown';
    const an   = a.analysis ?? {};
    const ghsa = a.ghsa_id ?? '';
    const cve  = a.cve_id  ?? '';
    const link = a.html_url ?? a.url ?? '#';
    const desc = stripMd(an.impact || a.description || '').slice(0, 280);

    return `<a class="advisory-card"
   href="${esc(link)}"
   target="_blank"
   rel="noopener"
   data-repo="${esc(a.repo ?? '')}"
   data-group="${esc(a.group ?? '')}"
   data-severity="${esc(sev)}">
  <div class="advisory-header">
    <div class="advisory-ids">
      ${ghsa ? `<span class="advisory-id">${esc(ghsa)}</span>` : ''}
      ${cve  ? `<span class="advisory-cve">${esc(cve)}</span>`  : ''}
    </div>
    <span class="sev sev-${sev}">${sev}</span>
  </div>
  <span class="card-repo">${esc((a.repo ?? '').split('/')[1])}</span>
  <h3 class="advisory-title">${esc(a.summary)}</h3>
  <p class="advisory-desc">${esc(desc)}${desc.length === 280 ? '…' : ''}</p>
  ${an.affected_versions ? `<p class="card-date">Affected: <strong>${esc(an.affected_versions)}</strong>${an.fix_version ? ` → Fixed: <strong>${esc(an.fix_version)}</strong>` : ''}</p>` : ''}
  ${an.action ? `<p class="card-date">${esc(ACTION_LABEL[an.action] ?? an.action)}</p>` : ''}
  <p class="card-date">${formatDate(a.published_at)}</p>
</a>`.trim();
  }).join('');
}

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

function formatDate(iso) {
  if (!iso) return '';
  try {
    return new Intl.DateTimeFormat('en', { day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(iso));
  } catch { return iso; }
}
