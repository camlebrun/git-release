/* git-release digest — frontend app */
'use strict';

const _metaUrl = document.querySelector('meta[name="api-url"]')?.content ?? '';
// In dev Vite proxies /digest → localhost:8080, so API_URL is empty (same origin).
// In production deploy.sh replaces the meta tag with the real Cloud Function URL.
const API_URL = (_metaUrl && !_metaUrl.includes('REPLACE_WITH'))
  ? _metaUrl.replace(/\/$/, '')
  : '';

let allRecords = [];

// ── Boot ───────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  setupTabs();
  setupSearch();
  loadDigest();
});

// ── Tabs ───────────────────────────────────────────────────────────────────
function setupTabs() {
  document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t === btn));
      document.querySelectorAll('.tab-panel').forEach(p => {
        const show = p.id === `tab-${btn.dataset.tab}`;
        p.classList.toggle('hidden', !show);
        p.classList.toggle('active', show);
      });
    });
  });
}

// ── Search ─────────────────────────────────────────────────────────────────
function setupSearch() {
  document.getElementById('search').addEventListener('input', e => {
    const q = e.target.value.trim().toLowerCase();
    filterCards(q);
    filterCveRows(q);
  });
}

function filterCards(q) {
  const cards = document.querySelectorAll('.card');
  let visible = 0;
  cards.forEach(c => {
    const match = !q ||
      c.dataset.repo.includes(q) ||
      c.dataset.tags.includes(q) ||
      c.dataset.tag.includes(q) ||
      c.dataset.severity.includes(q);
    c.classList.toggle('hidden', !match);
    if (match) visible++;
  });
  document.getElementById('empty-digest').classList.toggle('hidden', visible > 0 || cards.length === 0);
}

function filterCveRows(q) {
  document.querySelectorAll('#cve-tbody tr').forEach(row => {
    row.classList.toggle('hidden', !!q && !row.textContent.toLowerCase().includes(q));
  });
}

// ── Data fetch ─────────────────────────────────────────────────────────────
async function loadDigest() {
  const loading = document.getElementById('loading');
  try {
    const resp = await fetch(`${API_URL}/digest?limit=100`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    allRecords = await resp.json();
    loading.classList.add('hidden');
    renderGrid(allRecords);
    renderCveTable(allRecords);
    updateCounts(allRecords);
  } catch (err) {
    loading.className = 'empty-state';
    loading.textContent = `⚠ Failed to load: ${err.message}`;
  }
}

function updateCounts(records) {
  document.getElementById('digest-count').textContent = records.length || '';
  const cveIds = new Set(records.flatMap(r => r.analysis?.cve_references ?? []));
  document.getElementById('cve-count').textContent = cveIds.size || '';
}

// ── Grid ───────────────────────────────────────────────────────────────────
function renderGrid(records) {
  const grid = document.getElementById('grid');
  if (!records.length) {
    document.getElementById('empty-digest').classList.remove('hidden');
    return;
  }
  grid.innerHTML = records.map(renderCard).join('');
}

function renderCard(r) {
  const a = r.analysis ?? {};
  const severity = a.severity ?? 'none';
  const tags = a.tags ?? [];
  const changes = (a.key_changes ?? []).slice(0, 6);
  const cveRefs = a.cve_references ?? [];
  const cveDetails = r.cve_details ?? [];

  const tagChips = tags.map(t => `<span class="chip">${esc(t)}</span>`).join('');
  const cveChips = cveRefs.map(id => {
    const d = cveDetails.find(x => x.id === id);
    const score = d?.cvss_score ? ` ${d.cvss_score}` : '';
    return `<span class="chip chip-cve"><a href="https://nvd.nist.gov/vuln/detail/${esc(id)}" target="_blank" rel="noopener">${esc(id)}${score}</a></span>`;
  }).join('');

  const changesList = changes.map(c => `<li>${esc(c)}</li>`).join('');
  const hasMeta = tagChips || cveChips;

  return `
<article class="card"
  data-repo="${esc(r.repo)}"
  data-tag="${esc(r.tag ?? '')}"
  data-tags="${esc(tags.join(' '))}"
  data-severity="${esc(severity)}">
  <div class="card-header">
    <div class="card-meta">
      <span class="card-repo">${esc(r.repo)}</span>
      <div class="card-title">
        <a href="${esc(r.html_url ?? '#')}" target="_blank" rel="noopener">${esc(r.name || r.tag)}</a>
      </div>
    </div>
    <div class="card-badges">
      <span class="sev sev-${severity}">${severity}</span>
      <span class="card-date">${formatDate(r.published_at)}</span>
    </div>
  </div>
  ${a.summary ? `<p class="card-summary">${esc(a.summary)}</p>` : ''}
  ${changesList ? `<ul class="card-changes">${changesList}</ul>` : ''}
  ${hasMeta ? `<div class="chips">${tagChips}${cveChips}</div>` : ''}
</article>`.trim();
}

// ── CVE table ──────────────────────────────────────────────────────────────
function renderCveTable(records) {
  const tbody = document.getElementById('cve-tbody');
  const empty = document.getElementById('empty-cves');

  const rows = [];
  for (const r of records) {
    for (const id of (r.analysis?.cve_references ?? [])) {
      const d = (r.cve_details ?? []).find(x => x.id === id) ?? {};
      rows.push({ id, d, repo: r.repo, tag: r.tag, severity: r.analysis?.severity ?? 'none' });
    }
  }

  if (!rows.length) { empty.classList.remove('hidden'); return; }

  const sevOrder = { critical: 0, high: 1, medium: 2, low: 3, none: 4 };
  rows.sort((a, b) => {
    const sd = (sevOrder[a.severity] ?? 5) - (sevOrder[b.severity] ?? 5);
    return sd !== 0 ? sd : (b.d.cvss_score ?? 0) - (a.d.cvss_score ?? 0);
  });

  tbody.innerHTML = rows.map(({ id, d, repo, tag, severity }) => {
    const score = d.cvss_score ?? null;
    const cvssClass = score >= 9 ? 'cvss-crit' : score >= 7 ? 'cvss-high' : score >= 4 ? 'cvss-medium' : score ? 'cvss-low' : '';
    const scoreHtml = score
      ? `<span class="cvss-pill ${cvssClass}">${score}</span>`
      : `<span class="cvss-pill">—</span>`;
    const desc = d.description ? esc(d.description.slice(0, 180)) + (d.description.length > 180 ? '…' : '') : '—';
    return `<tr>
      <td><a class="cve-link" href="https://nvd.nist.gov/vuln/detail/${esc(id)}" target="_blank" rel="noopener">${esc(id)}</a></td>
      <td>${scoreHtml}</td>
      <td><span class="sev sev-${severity}">${severity}</span></td>
      <td>${esc(repo)}</td>
      <td>${esc(tag ?? '')}</td>
      <td class="desc-cell">${desc}</td>
    </tr>`;
  }).join('');
}

// ── Helpers ────────────────────────────────────────────────────────────────
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
