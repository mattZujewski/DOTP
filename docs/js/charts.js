/**
 * charts.js — Shared Chart.js defaults & utilities
 * All chart modules import from this global object: window.DOTP
 */

window.DOTP = window.DOTP || {};

(function (DOTP) {
  'use strict';

  // ── Owner color palette (Tableau10 — fixed by alpha order) ──────
  // Matches OWNERS_ALPHA in build_dashboard.py
  const OWNER_COLORS_RAW = [
    '#4e79a7', // Alex Beim
    '#f28e2b', // David Turley
    '#e15759', // Evan Soraci
    '#76b7b2', // Jack Dunne
    '#59a14f', // Jason Bartolini
    '#edc948', // Jose Garcia-Chope
    '#b07aa1', // Jordan Papula
    '#ff9da7', // Liam Burns
    '#9c755f', // Matthew Zujewski
    '#bab0ac', // Owen Hern
    '#1a6b3c', // Reed Heim  (brand green)
    '#d4a017', // Trent Radding
  ];

  const OWNERS_ALPHA = [
    'Alex Beim', 'David Turley', 'Evan Soraci', 'Jack Dunne',
    'Jason Bartolini', 'Jose Garcia-Chope', 'Jordan Papula', 'Liam Burns',
    'Matthew Zujewski', 'Owen Hern', 'Reed Heim', 'Trent Radding',
  ];

  function ownerColor(realName) {
    const idx = OWNERS_ALPHA.indexOf(realName);
    return idx >= 0 ? OWNER_COLORS_RAW[idx] : '#888';
  }

  function ownerColorAlpha(realName, alpha = 0.18) {
    const hex = ownerColor(realName);
    const r = parseInt(hex.slice(1,3),16);
    const g = parseInt(hex.slice(3,5),16);
    const b = parseInt(hex.slice(5,7),16);
    return `rgba(${r},${g},${b},${alpha})`;
  }

  // ── Acquisition / Status color maps ─────────────────────────────
  const ACQ_COLORS = {
    KEPT:    '#4e9af1',
    CLAIMED: '#f4a261',
    TRADED:  '#e76f51',
    DRAFTED: '#2a9d8f',
  };

  const STATUS_COLORS = {
    ACTIVE:          '#2a9d8f',
    INJURED_RESERVE: '#e63946',
    MINORS:          '#457b9d',
    RESERVE:         '#f4a261',
  };

  // ── Get CSS var (respects dark mode) ────────────────────────────
  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  // ── Chart.js global defaults ─────────────────────────────────────
  function applyChartDefaults() {
    if (typeof Chart === 'undefined') return;
    const textColor   = cssVar('--text-primary')   || '#1a1a2e';
    const mutedColor  = cssVar('--text-muted')     || '#8892a4';
    const borderColor = cssVar('--border')         || '#e2e8f0';
    const bgCard      = cssVar('--bg-card')        || '#ffffff';

    Chart.defaults.color             = textColor;
    Chart.defaults.borderColor       = borderColor;
    Chart.defaults.font.family       = "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    Chart.defaults.font.size         = 12;
    Chart.defaults.plugins.tooltip.backgroundColor = bgCard;
    Chart.defaults.plugins.tooltip.titleColor       = textColor;
    Chart.defaults.plugins.tooltip.bodyColor        = textColor;
    Chart.defaults.plugins.tooltip.borderColor      = borderColor;
    Chart.defaults.plugins.tooltip.borderWidth      = 1;
    Chart.defaults.plugins.tooltip.padding          = 10;
    Chart.defaults.plugins.tooltip.cornerRadius     = 6;
    Chart.defaults.plugins.tooltip.displayColors    = true;
    Chart.defaults.plugins.legend.labels.color      = textColor;
    Chart.defaults.plugins.legend.labels.boxWidth   = 12;
    Chart.defaults.plugins.legend.labels.padding    = 14;
    Chart.defaults.scale = Chart.defaults.scale || {};
    Chart.defaults.scale.grid = { color: borderColor };
    Chart.defaults.scale.ticks = { color: mutedColor };
  }

  // Re-apply on theme change
  document.addEventListener('themechange', applyChartDefaults);

  // ── Standard chart options factories ───────────────────────────
  function horizontalBarOptions({ title, xLabel, yLabel } = {}) {
    return {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        title: title ? { display: true, text: title, font: { size: 14, weight: '700' }, padding: { bottom: 12 } } : { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => ` ${ctx.parsed.y ?? ctx.parsed.x}`,
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { maxRotation: 35, font: { size: 11 } }, title: xLabel ? { display: true, text: xLabel } : { display: false } },
        y: { beginAtZero: true, grid: { drawBorder: false }, title: yLabel ? { display: true, text: yLabel } : { display: false } },
      },
    };
  }

  function lineOptions({ title, xLabel, yLabel } = {}) {
    return {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: true },
        title: title ? { display: true, text: title, font: { size: 14, weight: '700' }, padding: { bottom: 12 } } : { display: false },
      },
      scales: {
        x: { title: xLabel ? { display: true, text: xLabel } : { display: false } },
        y: {
          title: yLabel ? { display: true, text: yLabel } : { display: false },
          beginAtZero: true,
          ticks: { precision: 0 },
        },
      },
    };
  }

  function barOptions({ title, xLabel, yLabel, stacked = false } = {}) {
    return {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: stacked },
        title: title ? { display: true, text: title, font: { size: 14, weight: '700' }, padding: { bottom: 12 } } : { display: false },
      },
      scales: {
        x: {
          stacked,
          title: xLabel ? { display: true, text: xLabel } : { display: false },
          grid: { display: false },
        },
        y: {
          stacked,
          beginAtZero: true,
          ticks: { precision: 0 },
          title: yLabel ? { display: true, text: yLabel } : { display: false },
        },
      },
    };
  }

  // ── Badge helpers ───────────────────────────────────────────────
  const ACQ_BADGE_CLASS = {
    KEPT: 'badge-kept', CLAIMED: 'badge-claimed',
    TRADED: 'badge-traded', DRAFTED: 'badge-drafted',
  };
  const STATUS_BADGE_CLASS = {
    ACTIVE: 'badge-active', INJURED_RESERVE: 'badge-ir',
    MINORS: 'badge-minors', RESERVE: 'badge-reserve',
  };

  function acqBadge(type) {
    const cls = ACQ_BADGE_CLASS[type] || '';
    return `<span class="badge ${cls}">${type || '—'}</span>`;
  }
  function statusBadge(status) {
    const cls = STATUS_BADGE_CLASS[status] || '';
    const label = status === 'INJURED_RESERVE' ? 'IR' : (status || '—');
    return `<span class="badge ${cls}">${label}</span>`;
  }

  // ── Formatting helpers ──────────────────────────────────────────
  function fmtDate(isoStr) {
    if (!isoStr) return '—';
    try {
      const d = new Date(isoStr + 'T00:00:00');
      return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    } catch (_) { return isoStr; }
  }

  function fmtDays(days) {
    if (days == null || isNaN(days)) return '—';
    if (days >= 365) return `${(days / 365).toFixed(1)}y`;
    return `${days}d`;
  }

  // ── Sortable table helper ────────────────────────────────────────
  function makeSortable(tableEl) {
    const ths = tableEl.querySelectorAll('th[data-sort]');
    let currentCol = null, asc = true;

    ths.forEach(th => {
      th.style.cursor = 'pointer';
      th.addEventListener('click', () => {
        const col = th.dataset.sort;
        if (col === currentCol) { asc = !asc; } else { asc = false; currentCol = col; }
        ths.forEach(h => h.classList.remove('sort-asc', 'sort-desc'));
        th.classList.add(asc ? 'sort-asc' : 'sort-desc');

        const tbody = tableEl.querySelector('tbody');
        const rows = Array.from(tbody.querySelectorAll('tr'));
        rows.sort((a, b) => {
          const av = a.dataset[col] ?? a.cells[th.cellIndex]?.textContent ?? '';
          const bv = b.dataset[col] ?? b.cells[th.cellIndex]?.textContent ?? '';
          const an = parseFloat(av), bn = parseFloat(bv);
          if (!isNaN(an) && !isNaN(bn)) return asc ? an - bn : bn - an;
          return asc ? av.localeCompare(bv) : bv.localeCompare(av);
        });
        rows.forEach(r => tbody.appendChild(r));
      });
    });
  }

  // ── Modal helpers ────────────────────────────────────────────────
  function showModal(html) {
    let overlay = document.getElementById('dotp-modal-overlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'dotp-modal-overlay';
      overlay.className = 'modal-overlay';
      overlay.innerHTML = '<div class="modal-card" id="dotp-modal-card"></div>';
      document.body.appendChild(overlay);
      overlay.addEventListener('click', e => {
        if (e.target === overlay) hideModal();
      });
      document.addEventListener('keydown', e => {
        if (e.key === 'Escape') hideModal();
      });
    }
    document.getElementById('dotp-modal-card').innerHTML = html;
    overlay.classList.add('open');
  }

  function hideModal() {
    document.getElementById('dotp-modal-overlay')?.classList.remove('open');
  }

  // ── D3 tooltip ──────────────────────────────────────────────────
  function makeD3Tooltip() {
    let tip = document.getElementById('d3-global-tooltip');
    if (!tip) {
      tip = document.createElement('div');
      tip.id = 'd3-global-tooltip';
      tip.className = 'd3-tooltip';
      tip.style.display = 'none';
      document.body.appendChild(tip);
    }

    function show(html, event) {
      tip.innerHTML = html;
      tip.style.display = 'block';
      move(event);
    }
    function move(event) {
      if (!event) return;
      const x = event.pageX + 14;
      const y = event.pageY - 14;
      tip.style.left = Math.min(x, window.innerWidth - tip.offsetWidth - 10) + 'px';
      tip.style.top  = y + 'px';
    }
    function hide() { tip.style.display = 'none'; }

    return { show, move, hide };
  }

  // ── JSON loader with cache ───────────────────────────────────────
  const _cache = {};
  async function loadJSON(url) {
    if (_cache[url]) return _cache[url];
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Failed to load ${url}: ${res.status}`);
    const data = await res.json();
    _cache[url] = data;
    return data;
  }

  // ── Expose public API ────────────────────────────────────────────
  Object.assign(DOTP, {
    OWNERS_ALPHA,
    OWNER_COLORS_RAW,
    ACQ_COLORS,
    STATUS_COLORS,
    ownerColor,
    ownerColorAlpha,
    cssVar,
    applyChartDefaults,
    horizontalBarOptions,
    lineOptions,
    barOptions,
    acqBadge,
    statusBadge,
    fmtDate,
    fmtDays,
    makeSortable,
    showModal,
    hideModal,
    makeD3Tooltip,
    loadJSON,
  });

  // Apply chart defaults once Chart.js is available
  if (typeof Chart !== 'undefined') {
    applyChartDefaults();
  } else {
    document.addEventListener('DOMContentLoaded', applyChartDefaults);
  }

})(window.DOTP);
