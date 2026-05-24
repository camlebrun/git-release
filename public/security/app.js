'use strict';

const R2_BASE      = 'https://pub-d7a866e02d744f3fb57bc3859858a5df.r2.dev';
const MANIFEST_URL = `${R2_BASE}/manifest.json`;

const _VALID_SEV = new Set(['critical', 'high', 'medium', 'low', 'none', 'unknown']);
function safeSev(s) { return _VALID_SEV.has(s) ? s : 'none'; }

const SEV_ORDER = { critical: 4, high: 3, medium: 2, low: 1, none: 0, unknown: 0 };

const ACTION_META = {
  'patch-now':  { label: 'Patch now',  cls: 'action-critical' },
  'patch-soon': { label: 'Patch soon', cls: 'action-high'     },
  'monitor':    { label: 'Monitor',    cls: 'action-medium'   },
  'safe':       { label: 'Safe',       cls: 'action-low'      },
};

// Derive action from severity when no LLM analysis
const SEV_TO_ACTION = { critical: 'patch-now', high: 'patch-soon', medium: 'monitor', low: 'safe', none: 'safe' };
const OLD_DAYS = 365;

function isOld(a) {
  if (!a.published_at) return false;
  return (Date.now() - new Date(a.published_at)) / 86400000 > OLD_DAYS;
}

function resolveAction(a) {
  const llmAction = a.analysis?.action;
  const base = ACTION_META[llmAction] ? llmAction : (SEV_TO_ACTION[a.severity] ?? 'monitor');
  // Downgrade anything older than 1 year unless explicitly critical
  return base !== 'patch-now' && isOld(a) ? 'safe' : base;
}

// ── State ──────────────────────────────────────────────────────────────────
let allAdvisories = [];
let activeAction  = 'all';
let activeAge     = 'all';
let activeRepo    = 'all';

document.addEventListener('DOMContentLoaded', () => {
  setupDrawer();
  setupSearch();
  setupActionFilters();
  setupAgeFilters();
  loadAdvisories();
});

// ── Load ───────────────────────────────────────────────────────────────────
async function loadAdvisories() {
  const loading = document.getElementById('loading');
  try {
    const manifest = await fetch(MANIFEST_URL, { cache: 'no-store' });
    if (!manifest.ok) throw new Error(`manifest HTTP ${manifest.status}`);
    const { digest } = await manifest.json();
    const resp = await fetch(`${R2_BASE}/${digest}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data  = await resp.json();
    allAdvisories = Array.isArray(data) ? [] : (data.advisories ?? []);
    allAdvisories.sort((a, b) =>
      (SEV_ORDER[b.severity] ?? 0) - (SEV_ORDER[a.severity] ?? 0) ||
      new Date(b.published_at) - new Date(a.published_at)
    );
    loading.classList.add('hidden');
    document.getElementById('total-count').textContent   = allAdvisories.length || '';
    const releases = Array.isArray(data) ? data : (data.releases ?? []);
    const nonPkg = releases.filter(r => r.group !== 'dbt-packages' && r.group !== 'dbt-fusion' && r.repo !== 'dbt-labs/dbt-fusion');
    document.getElementById('release-count').textContent = nonPkg.length || '';
    buildRepoFilters(allAdvisories);
    renderAll();
    applyFilters();
  } catch (err) {
    loading.className = 'empty-state';
    loading.textContent = `⚠ Failed to load: ${err.message}`;
  }
}

// ── Render all cards once ──────────────────────────────────────────────────
function renderAll() {
  const grid = document.getElementById('grid');
  grid.innerHTML = allAdvisories.map((a, idx) => {
    const sev    = a.severity ?? 'unknown';
    const action = resolveAction(a);
    const meta   = ACTION_META[action];
    const desc   = stripMd(a.analysis?.impact || a.description || '').slice(0, 200);
    const an     = a.analysis ?? {};

    return `<article class="card"
  data-idx="${idx}"
  data-action="${esc(action)}"
  data-age="${isOld(a) ? 'old' : 'recent'}"
  data-repo="${esc(a.repo ?? '')}">
  <div class="card-header" style="flex-direction:column;align-items:stretch;gap:4px">
    <div style="display:flex;align-items:center;justify-content:space-between;gap:6px">
      ${a.ghsa_id ? `<span class="advisory-id">${esc(a.ghsa_id)}</span>` : ''}
      <div style="display:flex;align-items:center;gap:6px;flex-shrink:0">
        ${meta ? `<span class="tag tag-action ${esc(meta.cls)}">${esc(meta.label)}</span>` : ''}
        <span class="sev sev-${safeSev(sev)}">${esc(sev)}</span>
      </div>
    </div>
    ${a.cve_id ? `<span class="advisory-cve" style="align-self:flex-start">${esc(a.cve_id)}</span>` : ''}
  </div>
  <h3 class="card-title">${esc(a.summary ?? 'Advisory')}</h3>
  <p class="card-date"><strong>${esc((a.repo ?? '').split('/')[1])}</strong> · ${formatDate(a.published_at)}</p>
  ${desc ? `<p class="card-summary">${esc(desc)}${desc.length === 200 ? '…' : ''}</p>` : ''}
  ${cleanVer(an.affected_versions) ? `<p class="card-date" style="margin-top:4px">Affected: <strong>${esc(cleanVer(an.affected_versions))}</strong>${cleanVer(an.fix_version) ? ` · Fix: <strong>${esc(cleanVer(an.fix_version))}</strong>` : ''}</p>` : ''}
  <div class="card-footer">
    <span></span>
    <span class="card-cta">Details <svg width="12" height="12" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M2.5 6h7M6.5 3l3 3-3 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></span>
  </div>
</article>`.trim();
  }).join('');

  grid.querySelectorAll('.card').forEach(el => {
    el.addEventListener('click', () => {
      const a = allAdvisories[+el.dataset.idx];
      if (a) openDrawer(a);
    });
  });
}

// ── Filters ────────────────────────────────────────────────────────────────
function applyFilters() {
  const q = document.getElementById('search').value.trim().toLowerCase();
  let visible = 0;

  document.querySelectorAll('#grid .card').forEach(c => {
    const actionOk = activeAction === 'all' || c.dataset.action === activeAction;
    const ageOk    = activeAge    === 'all' || c.dataset.age    === activeAge;
    const repoOk   = activeRepo   === 'all' || c.dataset.repo   === activeRepo;
    const searchOk = !q || c.textContent.toLowerCase().includes(q);
    const show = actionOk && ageOk && repoOk && searchOk;
    c.classList.toggle('hidden', !show);
    if (show) visible++;
  });

  document.getElementById('empty-state').classList.toggle(
    'hidden', visible > 0 || allAdvisories.length === 0
  );
}

function setupActionFilters() {
  document.querySelectorAll('.chip[data-action]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.chip[data-action]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeAction = btn.dataset.action;
      applyFilters();
    });
  });
}

function setupAgeFilters() {
  document.querySelectorAll('.chip[data-age]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.chip[data-age]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeAge = btn.dataset.age;
      applyFilters();
    });
  });
}

function setupSearch() {
  document.getElementById('search').addEventListener('input', applyFilters);
}

function buildRepoFilters(advisories) {
  const repos = [...new Set(advisories.map(a => a.repo).filter(Boolean))].sort();
  if (repos.length <= 1) return;

  const container = document.getElementById('repo-filters');
  container.innerHTML =
    `<button class="chip active" data-repo="all">All repos</button>` +
    repos.map(r => {
      const slug = r.split('/')[1];
      return `<button class="chip" data-repo="${esc(r)}">${esc(slug)}</button>`;
    }).join('');

  container.querySelectorAll('.chip').forEach(btn => {
    btn.addEventListener('click', () => {
      container.querySelectorAll('.chip').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeRepo = btn.dataset.repo;
      applyFilters();
    });
  });
}

// ── Drawer ─────────────────────────────────────────────────────────────────
function setupDrawer() {
  const backdrop = document.getElementById('drawer-backdrop');
  const drawer   = document.getElementById('drawer');
  const close    = () => {
    drawer.classList.remove('open');
    backdrop.classList.add('hidden');
    document.body.style.overflow = '';
  };
  document.getElementById('drawer-close').addEventListener('click', close);
  backdrop.addEventListener('click', close);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
}

function openDrawer(a) {
  const an     = a.analysis ?? {};
  const sev    = a.severity ?? 'unknown';
  const action = resolveAction(a);
  const meta   = ACTION_META[action];

  document.getElementById('drawer-repo').textContent = (a.repo ?? '').split('/')[1].toUpperCase();
  const sevEl = document.getElementById('drawer-sev');
  sevEl.textContent = sev;
  sevEl.className   = `sev sev-${safeSev(sev)}`;

  document.getElementById('drawer-ids').innerHTML = [
    a.ghsa_id ? `<span class="advisory-id">${esc(a.ghsa_id)}</span>` : '',
    a.cve_id  ? `<span class="advisory-cve">${esc(a.cve_id)}</span>`  : '',
  ].join('');

  document.getElementById('drawer-title').textContent = a.summary ?? 'Advisory';
  document.getElementById('drawer-date').textContent  = formatDate(a.published_at);

  const actionWrap = document.getElementById('drawer-action-wrap');
  const actionEl   = document.getElementById('drawer-action');
  if (meta) {
    actionEl.textContent = meta.label;
    actionEl.className   = `advisory-action-banner ${meta.cls}`;
    actionWrap.classList.remove('hidden');
  } else {
    actionWrap.classList.add('hidden');
  }

  setDrawerSection('drawer-impact-wrap',   'drawer-impact',   an.impact || '');
  const affVer = cleanVer(an.affected_versions);
  const fixVer = cleanVer(an.fix_version);
  if (affVer) {
    document.getElementById('drawer-versions').innerHTML =
      `Affected: <strong>${esc(affVer)}</strong>` +
      (fixVer ? ` · Fix: <strong>${esc(fixVer)}</strong>` : '');
    document.getElementById('drawer-versions-wrap').classList.remove('hidden');
  } else {
    document.getElementById('drawer-versions-wrap').classList.add('hidden');
  }

  const steps = an.action_steps ?? [];
  const stepsWrap = document.getElementById('drawer-steps-wrap');
  if (steps.length) {
    document.getElementById('drawer-steps').innerHTML = steps.map(s => `<li>${esc(s)}</li>`).join('');
    stepsWrap.classList.remove('hidden');
  } else {
    stepsWrap.classList.add('hidden');
  }

  // Raw description fallback
  const descWrap = document.getElementById('drawer-desc-wrap');
  if (!an.impact && a.description) {
    document.getElementById('drawer-desc').textContent = stripMd(a.description).slice(0, 800);
    descWrap.classList.remove('hidden');
  } else {
    descWrap.classList.add('hidden');
  }

  document.getElementById('drawer-link').href = a.html_url ?? a.url ?? '#';

  const backdrop = document.getElementById('drawer-backdrop');
  const drawer   = document.getElementById('drawer');
  backdrop.classList.remove('hidden');
  drawer.classList.remove('hidden');
  requestAnimationFrame(() => drawer.classList.add('open'));
  document.body.style.overflow = 'hidden';
}

function setDrawerSection(wrapId, contentId, text) {
  const wrap = document.getElementById(wrapId);
  if (text) {
    document.getElementById(contentId).textContent = text;
    wrap.classList.remove('hidden');
  } else {
    wrap.classList.add('hidden');
  }
}

// ── Helpers ────────────────────────────────────────────────────────────────
const _VAGUE = /^(see advisory|n\/a|unknown|tbd|none|null)$/i;
function cleanVer(v) { return v && !_VAGUE.test(String(v).trim()) ? String(v) : null; }

function stripMd(str) {
  return String(str ?? '')
    .replace(/#{1,6}\s+/g, '').replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/\*(.+?)\*/g, '$1').replace(/`{1,3}[^`]*`{1,3}/g, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1').replace(/^[-*+]\s+/gm, '')
    .replace(/\n{2,}/g, ' ').replace(/\n/g, ' ').trim();
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
