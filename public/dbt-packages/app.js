'use strict';

const R2_BASE = 'https://pub-d7a866e02d744f3fb57bc3859858a5df.r2.dev';
const MANIFEST_URL = `${R2_BASE}/manifest.json`;

let allPkgs = [];
let activePkgType = 'all';
let activePkgName = 'all';
let activePkgSev  = 'all';
let pkgLatestOnly = true;

const PKG_TYPE = {
  'dbt-utils':           'utils',
  'dbt_artifacts':       'utils',
  'dbt-external-tables': 'utils',
  'dbt-expectations':    'data-quality',
  'elementary':          'data-quality',
  'soda-core':           'data-quality',
};

const PKG_DESC = {
  'dbt-utils':           'Common macros (date logic, cross-db helpers, set operations) used across almost every dbt project.',
  'dbt_artifacts':       'Loads dbt run artifacts (manifest, run results) into your warehouse for lineage and run tracking.',
  'dbt-external-tables': 'Stages and loads external tables (S3, GCS, ADLS) into your warehouse directly from dbt.',
  'dbt-expectations':    'Actively maintained fork by Metaplane — Great Expectations-style tests (distributions, cardinality, regex…) for dbt 1.7+.',
  'elementary':          'Native dbt observability: anomaly detection, schema change alerts, and a data reliability dashboard.',
  'soda-core':           'YAML-defined data quality checks (nulls, freshness, schema) that run in-pipeline or on a schedule.',
};

document.addEventListener('DOMContentLoaded', () => {
  setupFilters();
  setupSearch();
  setupDrawer();
  loadPackages();
});

async function loadPackages() {
  const loading = document.getElementById('loading');
  try {
    const manifest = await fetch(MANIFEST_URL, { cache: 'no-store' });
    if (!manifest.ok) throw new Error(`manifest HTTP ${manifest.status}`);
    const { digest } = await manifest.json();
    const resp = await fetch(`${R2_BASE}/${digest}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    const records = Array.isArray(data) ? data : (data.releases ?? []);
    allPkgs = records.filter(r => r.group === 'dbt-packages');
    const advisories = Array.isArray(data) ? [] : (data.advisories ?? []);
    loading.classList.add('hidden');
    setCrossTabCounts(records, advisories);
    buildNameFilters(allPkgs);
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
  const fusionRecs   = releases.filter(r => r.group === 'dbt-fusion' || r.repo === 'dbt-labs/dbt-fusion');
  const fusionLatest = fusionRecs.length
    ? [fusionRecs.reduce((best, r) => new Date(r.published_at) > new Date(best.published_at) ? r : best)]
    : [];
  if (el('fusion-count')) {
    el('fusion-count').textContent = fusionLatest.length || '';
    el('fusion-count').title = `${fusionLatest.length} latest release · ${fusionRecs.length} total in history`;
  }
}

function buildNameFilters(pkgs) {
  const slugs = [...new Set(pkgs.map(r => r.repo.split('/')[1]))].sort();
  const select = document.getElementById('pkg-name-select');
  select.innerHTML = `<option value="all">All packages</option>` +
    slugs.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join('');
  select.addEventListener('change', e => {
    activePkgName = e.target.value;
    if (activePkgName !== 'all') {
      document.getElementById('pkg-type-select').value = 'all';
      activePkgType = 'all';
    }
    render();
  });
}

function setupFilters() {
  document.getElementById('pkg-type-select').addEventListener('change', e => {
    activePkgType = e.target.value;
    activePkgName = 'all';
    document.getElementById('pkg-name-select').value = 'all';
    render();
  });

  document.getElementById('pkg-sev-select').addEventListener('change', e => {
    activePkgSev = e.target.value;
    render();
  });

  document.getElementById('pkg-latest-select').addEventListener('change', e => {
    pkgLatestOnly = e.target.value === 'latest';
    render();
  });
}

function setupSearch() {
  document.getElementById('search').addEventListener('input', render);
}

function getLatestPerRepo(pkgs) {
  const latestMap = new Map();
  pkgs.forEach(r => {
    const existing = latestMap.get(r.repo);
    if (!existing || new Date(r.published_at) > new Date(existing.published_at)) {
      latestMap.set(r.repo, r);
    }
  });
  return [...latestMap.values()].sort((a, b) => a.repo.localeCompare(b.repo));
}

function render() {
  const q = document.getElementById('search').value.trim().toLowerCase();

  let filtered = pkgLatestOnly ? getLatestPerRepo(allPkgs) : [...allPkgs];

  if (activePkgName !== 'all') {
    filtered = filtered.filter(r => r.repo.split('/')[1] === activePkgName);
  } else if (activePkgType !== 'all') {
    filtered = filtered.filter(r => PKG_TYPE[r.repo.split('/')[1]] === activePkgType);
  }

  if (activePkgSev !== 'all') {
    filtered = filtered.filter(r => (r.analysis?.severity ?? 'none') === activePkgSev);
  }

  if (q) {
    filtered = filtered.filter(r =>
      r.repo.toLowerCase().includes(q) ||
      (r.name || r.tag || '').toLowerCase().includes(q) ||
      (r.analysis?.summary ?? '').toLowerCase().includes(q) ||
      (r.analysis?.tags ?? []).join(' ').toLowerCase().includes(q)
    );
  }

  document.getElementById('pkg-count').textContent = filtered.length || '';

  const grid = document.getElementById('pkg-grid');
  const empty = document.getElementById('empty-pkg');

  if (!filtered.length) {
    grid.innerHTML = '';
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');

  const latestIds = new Set(getLatestPerRepo(allPkgs).map(r => r.id));

  grid.innerHTML = filtered.map((r, idx) => {
    const a       = r.analysis ?? {};
    const slug    = r.repo.split('/')[1];
    const pkgType = PKG_TYPE[slug] ?? 'other';
    const purpose = a.purpose || PKG_DESC[slug] || '';
    const tags    = a.tags ?? [];
    const changes = (a.key_changes ?? []).slice(0, 2);
    const isLatest     = latestIds.has(r.id);
    const isDeprecated = r.deprecated === true;

    const tagChips    = tags.slice(0, 2).map(t => `<span class="tag">${esc(t)}</span>`).join('');
    const changesList = changes.map(c => `<li>${renderInline(c)}</li>`).join('');

    const shortDesc = PKG_DESC[slug] ?? '';

    return `<article class="card${isDeprecated ? ' card-deprecated' : ''}" data-idx="${idx}">
  <div class="card-header">
    <div class="card-repo-wrap">
      <span class="card-repo">${esc(slug)}</span>
      ${shortDesc ? `<span class="pkg-info" data-tooltip="${esc(shortDesc)}" tabindex="0" aria-label="About this package">
        <svg class="pkg-info-icon" width="13" height="13" viewBox="0 0 16 16" fill="none">
          <circle cx="8" cy="8" r="7" stroke="currentColor" stroke-width="1.5"/>
          <path d="M8 7v5M8 5v.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
        </svg>
      </span>` : ''}
    </div>
    <div style="display:flex;gap:6px;align-items:center">
      ${isDeprecated ? '<span class="pkg-deprecated-badge">deprecated</span>' : isLatest ? '<span class="pkg-latest-badge">latest</span>' : ''}
      <span class="pkg-type-badge pkg-type-${esc(pkgType)}">${pkgType === 'data-quality' ? 'data quality' : esc(pkgType)}</span>
    </div>
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

  setupTooltips();
}

function setupTooltips() {
  const tooltip = document.getElementById('pkg-global-tooltip');
  if (!tooltip) return;

  document.querySelectorAll('.pkg-info').forEach(el => {
    el.addEventListener('mouseenter', () => {
      tooltip.textContent = el.dataset.tooltip;
      tooltip.classList.add('visible');
      positionTooltip(el, tooltip);
    });
    el.addEventListener('mouseleave', () => tooltip.classList.remove('visible'));
    el.addEventListener('focus', () => {
      tooltip.textContent = el.dataset.tooltip;
      tooltip.classList.add('visible');
      positionTooltip(el, tooltip);
    });
    el.addEventListener('blur', () => tooltip.classList.remove('visible'));
  });
}

function positionTooltip(anchor, tooltip) {
  const rect = anchor.getBoundingClientRect();
  const ttH  = tooltip.offsetHeight || 60;
  const ttW  = tooltip.offsetWidth  || 240;

  let top  = rect.top + window.scrollY - ttH - 10;
  let left = rect.left + window.scrollX - 6;

  // Flip below if not enough room above
  if (top < window.scrollY + 8) {
    top = rect.bottom + window.scrollY + 10;
    tooltip.classList.add('flipped');
  } else {
    tooltip.classList.remove('flipped');
  }

  // Keep within viewport horizontally
  if (left + ttW > window.innerWidth - 8) {
    left = window.innerWidth - ttW - 8;
  }
  if (left < 8) left = 8;

  tooltip.style.top  = `${top}px`;
  tooltip.style.left = `${left}px`;
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

  document.getElementById('drawer-repo').textContent = record.repo.split('/')[1];
  const sevEl = document.getElementById('drawer-sev');
  sevEl.textContent = sev;
  sevEl.className = `sev sev-${sev}`;

  document.getElementById('drawer-title').textContent   = record.name || record.tag;
  document.getElementById('drawer-date').textContent    = formatDate(record.published_at);

  const noticeWrap = document.getElementById('drawer-notice');
  if (record.notice) {
    document.getElementById('drawer-notice-text').textContent = record.notice;
    noticeWrap.classList.remove('hidden');
  } else {
    noticeWrap.classList.add('hidden');
  }

  const deprecatedWrap = document.getElementById('drawer-deprecated');
  if (record.deprecated && record.deprecated_notice) {
    document.getElementById('drawer-deprecated-text').textContent = record.deprecated_notice;
    deprecatedWrap.classList.remove('hidden');
  } else {
    deprecatedWrap.classList.add('hidden');
  }

  const purposeWrap = document.getElementById('drawer-purpose');
  const purposeText = document.getElementById('drawer-purpose-text');
  const rawPurpose  = a.purpose ? stripHtml(a.purpose) : '';
  if (rawPurpose) {
    purposeText.textContent = rawPurpose;
    purposeWrap.classList.remove('hidden');
  } else {
    purposeWrap.classList.add('hidden');
  }

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

// ── Helpers ─────────────────────────────────────────────────────────────────
function stripHtml(str) {
  return String(str ?? '')
    .replace(/<[^>]+>/g, '')
    .replace(/\s+/g, ' ')
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
