'use strict';

const R2_BASE = 'https://pub-d7a866e02d744f3fb57bc3859858a5df.r2.dev';
const MANIFEST_URL = `${R2_BASE}/manifest.json`;

const _VALID_SEV = new Set(['critical', 'high', 'medium', 'low', 'none', 'unknown']);
function safeSev(s) { return _VALID_SEV.has(s) ? s : 'none'; }

let allReleases = [];
let activeTag = 'all';
let latestOnly = true;

document.addEventListener('DOMContentLoaded', () => {
  setupDrawer();
  setupSearch();
  setupLatestSelect();
  loadReleases();
});

async function loadReleases() {
  const loading = document.getElementById('loading');
  try {
    const manifest = await fetch(MANIFEST_URL, { cache: 'no-store' });
    if (!manifest.ok) throw new Error(`manifest HTTP ${manifest.status}`);
    const { digest } = await manifest.json();
    const resp = await fetch(`${R2_BASE}/${digest}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    const records = Array.isArray(data) ? data : (data.releases ?? []);
    allReleases = records.filter(r =>
      r.group === 'dbt-fusion' || r.repo === 'dbt-labs/dbt-fusion'
    );
    const advisories = Array.isArray(data) ? [] : (data.advisories ?? []);
    loading.classList.add('hidden');
    setCrossTabCounts(records, advisories);
    buildTagFilters(allReleases);
    render();
  } catch (err) {
    loading.className = 'empty-state';
    loading.textContent = `⚠ Failed to load: ${err.message}`;
  }
}

function setCrossTabCounts(releases, advisories) {
  const el = id => document.getElementById(id);
  const nonPkg = releases.filter(r => r.group !== 'dbt-packages' && r.group !== 'dbt-fusion' && r.repo !== 'dbt-labs/dbt-fusion');
  if (el('release-count'))  el('release-count').textContent  = nonPkg.length || '';
  if (el('advisory-count')) el('advisory-count').textContent = advisories.length || '';
  const pkgUnique = new Set(releases.filter(r => r.group === 'dbt-packages').map(r => r.repo)).size;
  if (el('pkg-count')) {
    el('pkg-count').textContent = pkgUnique || '';
    el('pkg-count').title = `${pkgUnique} packages tracked · latest release per package`;
  }
}

function buildTagFilters(releases) {
  const tagCounts = {};
  releases.forEach(r => {
    (r.analysis?.tags ?? []).forEach(t => {
      tagCounts[t] = (tagCounts[t] ?? 0) + 1;
    });
  });

  const tags = Object.keys(tagCounts).sort();
  if (!tags.length) return;

  const select = document.getElementById('tag-select');
  select.innerHTML = `<option value="all">All tags</option>` +
    tags.map(t => `<option value="${esc(t)}">${esc(t)}</option>`).join('');
  select.addEventListener('change', e => {
    activeTag = e.target.value;
    render();
  });
}

function setupLatestSelect() {
  document.getElementById('latest-select').addEventListener('change', e => {
    latestOnly = e.target.value === 'latest';
    render();
  });
}

function setupSearch() {
  document.getElementById('search').addEventListener('input', render);
}

function getLatest(releases) {
  if (!releases.length) return [];
  return [releases.reduce((best, r) =>
    new Date(r.published_at) > new Date(best.published_at) ? r : best
  )];
}

function render() {
  const q = document.getElementById('search').value.trim().toLowerCase();

  let filtered = latestOnly ? getLatest(allReleases) : [...allReleases];
  filtered.sort((a, b) => new Date(b.published_at) - new Date(a.published_at));

  if (activeTag !== 'all') {
    filtered = filtered.filter(r => (r.analysis?.tags ?? []).includes(activeTag));
  }

  if (q) {
    filtered = filtered.filter(r =>
      (r.name || r.tag || '').toLowerCase().includes(q) ||
      (r.analysis?.summary ?? '').toLowerCase().includes(q) ||
      (r.analysis?.tags ?? []).join(' ').toLowerCase().includes(q) ||
      (r.analysis?.key_changes ?? []).join(' ').toLowerCase().includes(q)
    );
  }


  const countEl = document.getElementById('fusion-count');
  if (countEl) countEl.textContent = filtered.length || '';

  const grid = document.getElementById('fusion-grid');
  const empty = document.getElementById('empty-fusion');

  if (!filtered.length) {
    grid.innerHTML = '';
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');

  grid.innerHTML = filtered.map((r, idx) => {
    const a        = r.analysis ?? {};
    const severity = a.severity ?? 'none';
    const tags     = a.tags ?? [];
    const changes  = (a.key_changes ?? []).slice(0, 3);

    const changesList = changes.map(c => `<li>${renderInline(c)}</li>`).join('');
    const tagChips    = tags.map(t => `<span class="tag">${esc(t)}</span>`).join('');

    return `<article class="card" data-idx="${idx}">
  <div class="card-header">
    <span class="card-repo">dbt-fusion</span>
    <span class="sev sev-${safeSev(severity)}">${esc(severity)}</span>
  </div>
  <h3 class="card-title">${esc(r.name || r.tag)}</h3>
  <p class="card-date">${formatDate(r.published_at)}</p>
  <p class="card-summary">${renderInline(a.summary ?? '')}</p>
  ${changesList ? `<ul class="card-changes">${changesList}</ul>` : ''}
  <div class="card-footer">
    ${tagChips ? `<div class="tags">${tagChips}</div>` : '<div></div>'}
    <span class="card-cta">Details <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M2.5 6h7M6.5 3l3 3-3 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></span>
  </div>
</article>`.trim();
  }).join('');

  grid.querySelectorAll('.card').forEach(el => {
    el.addEventListener('click', () => {
      const r = filtered[+el.dataset.idx];
      if (r) openDrawer(r);
    });
  });
}

// ── Drawer ──────────────────────────────────────────────────────────────────
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

  document.getElementById('drawer-repo').textContent = 'dbt-fusion';
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

// ── Helpers ──────────────────────────────────────────────────────────────────
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
