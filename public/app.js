/* git-release digest — frontend app */
'use strict';

const API_URL = document.querySelector('meta[name="api-url"]')?.content?.replace(/\/$/, '') ?? '';

// ── State ──────────────────────────────────────────────────────────────────
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
      const target = btn.dataset.tab;
      document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t === btn));
      document.querySelectorAll('.tab-panel').forEach(p => {
        p.classList.toggle('hidden', p.id !== `tab-${target}`);
        p.classList.toggle('active', p.id === `tab-${target}`);
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
      c.dataset.tag.includes(q);
    c.classList.toggle('hidden', !match);
    if (match) visible++;
  });
  document.getElementById('empty-digest').classList.toggle('hidden', visible > 0 || cards.length === 0);
}

function filterCveRows(q) {
  document.querySelectorAll('#cve-tbody tr').forEach(row => {
    const text = row.textContent.toLowerCase();
    row.classList.toggle('hidden', !!q && !text.includes(q));
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
    loading.textContent = `Failed to load releases: ${err.message}`;
  }
}

// ── Counts ─────────────────────────────────────────────────────────────────
function updateCounts(records) {
  document.getElementById('digest-count').textContent = records.length || '';
  const cveIds = new Set(records.flatMap(r => r.analysis?.cve_references ?? []));
  document.getElementById('cve-count').textContent = cveIds.size || '';
}

// ── Grid rendering ─────────────────────────────────────────────────────────
function renderGrid(records) {
  const grid = document.getElementById('grid');
  const empty = document.getElementById('empty-digest');

  if (!records.length) {
    empty.classList.remove('hidden');
    return;
  }

  grid.innerHTML = records.map(renderCard).join('');
}

function renderCard(r) {
  const analysis = r.analysis ?? {};
  const severity = analysis.severity ?? 'none';
  const tags = analysis.tags ?? [];
  const changes = analysis.key_changes ?? [];
  const cveRefs = analysis.cve_references ?? [];
  const cveDetails = r.cve_details ?? [];

  const tagChips = tags.map(t => `<span class="chip">${esc(t)}</span>`).join('');

  const cveChips = cveRefs.map(id => {
    const detail = cveDetails.find(d => d.id === id);
    const score = detail?.cvss_score ? ` (${detail.cvss_score})` : '';
    return `<span class="chip chip-cve"><a href="https://nvd.nist.gov/vuln/detail/${esc(id)}" target="_blank" rel="noopener">${esc(id)}${score}</a></span>`;
  }).join('');

  const changesList = changes.slice(0, 8).map(c => `<li>${esc(c)}</li>`).join('');

  return `
<article class="card"
  data-repo="${esc(r.repo)}"
  data-tag="${esc(r.tag ?? '')}"
  data-tags="${esc(tags.join(' '))}">
  <div class="card-header">
    <div>
      <div class="card-repo">${esc(r.repo)}</div>
      <div class="card-title">
        <a href="${esc(r.html_url ?? '#')}" target="_blank" rel="noopener">${esc(r.name || r.tag)}</a>
      </div>
    </div>
    <div style="display:flex;flex-direction:column;align-items:flex-end;gap:.3rem">
      <span class="sev sev-${severity}">${severity}</span>
      <span class="card-date">${formatDate(r.published_at)}</span>
    </div>
  </div>
  ${analysis.summary ? `<p class="card-summary">${esc(analysis.summary)}</p>` : ''}
  ${changesList ? `<ul class="card-changes">${changesList}</ul>` : ''}
  ${(tagChips || cveChips) ? `<div class="chips">${tagChips}${cveChips}</div>` : ''}
</article>`.trim();
}

// ── CVE table ──────────────────────────────────────────────────────────────
function renderCveTable(records) {
  const tbody = document.getElementById('cve-tbody');
  const empty = document.getElementById('empty-cves');

  // Collect all CVEs with context
  const rows = [];
  for (const r of records) {
    const cveRefs = r.analysis?.cve_references ?? [];
    const cveDetails = r.cve_details ?? [];
    for (const id of cveRefs) {
      const detail = cveDetails.find(d => d.id === id) ?? {};
      rows.push({ id, detail, repo: r.repo, tag: r.tag, severity: r.analysis?.severity ?? 'none' });
    }
  }

  if (!rows.length) {
    empty.classList.remove('hidden');
    return;
  }

  const sevOrder = { critical: 0, high: 1, medium: 2, low: 3, none: 4 };
  rows.sort((a, b) => {
    const sd = (sevOrder[a.severity] ?? 5) - (sevOrder[b.severity] ?? 5);
    if (sd !== 0) return sd;
    return (b.detail.cvss_score ?? 0) - (a.detail.cvss_score ?? 0);
  });

  tbody.innerHTML = rows.map(({ id, detail, repo, tag, severity }) => {
    const score = detail.cvss_score ?? '—';
    const desc = detail.description ? esc(detail.description.slice(0, 200)) + (detail.description.length > 200 ? '…' : '') : '—';
    return `<tr>
      <td><a class="cve-id-link" href="https://nvd.nist.gov/vuln/detail/${esc(id)}" target="_blank" rel="noopener">${esc(id)}</a></td>
      <td class="cvss-score">${score}</td>
      <td><span class="sev sev-${severity}">${severity}</span></td>
      <td>${esc(repo)}</td>
      <td>${esc(tag ?? '')}</td>
      <td>${desc}</td>
    </tr>`;
  }).join('');
}

// ── Helpers ────────────────────────────────────────────────────────────────
function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatDate(iso) {
  if (!iso) return '';
  try {
    return new Intl.DateTimeFormat('en', { day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(iso));
  } catch {
    return iso;
  }
}
