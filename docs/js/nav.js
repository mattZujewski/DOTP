/**
 * nav.js — Navigation bar injection + dark mode
 * Injected on every page as the first body child.
 * Dark mode stored in localStorage('dotp_theme').
 * Dispatches 'themechange' event when toggled.
 */

(function () {
  'use strict';

  // ── Dark mode: apply BEFORE first paint (prevent FOUC) ──────────
  // (This inline <script> runs in <head>; nav.js also re-applies)
  const saved = localStorage.getItem('dotp_theme');
  if (saved === 'dark') document.documentElement.classList.add('dark');

  // ── Build nav HTML ──────────────────────────────────────────────
  function buildNav() {
    const path       = window.location.pathname;
    const isIndex    = path.endsWith('index.html') || path.endsWith('/') || path === '';
    const isTrade    = path.includes('trade.html');
    const isPlayer   = path.includes('player_history.html');
    const isTeam     = path.includes('team.html');
    const isStandings= path.includes('standings.html');

    function activeClass(flag) { return flag ? ' nav-active' : ''; }

    // Determine base path prefix for links (handle GitHub Pages subdirectory)
    const base = (() => {
      const parts = path.split('/').filter(Boolean);
      if (parts[parts.length - 1] && parts[parts.length - 1].includes('.html')) parts.pop();
      return parts.length === 0 ? '' : './';
    })();

    const html = `
<nav id="dotp-nav" aria-label="Main navigation">
  <a class="nav-logo" href="${base}index.html">🦆 DOTP</a>
  <div class="nav-links">
    <a class="nav-link${activeClass(isIndex)}"     href="${base}index.html">Home</a>
    <a class="nav-link${activeClass(isStandings)}" href="${base}standings.html">Standings</a>
    <a class="nav-link${activeClass(isTrade)}"     href="${base}trade.html">Trades</a>
    <a class="nav-link${activeClass(isPlayer)}"    href="${base}player_history.html">Players</a>
    <a class="nav-link${activeClass(isTeam)}"      href="${base}team.html">Teams</a>
  </div>
  <span class="nav-spacer"></span>
  <span class="nav-meta" id="nav-data-date"></span>
  <button id="dark-mode-toggle" aria-label="Toggle dark mode">🌙</button>
</nav>`;

    const container = document.createElement('div');
    container.innerHTML = html.trim();
    const nav = container.firstChild;
    document.body.insertBefore(nav, document.body.firstChild);

    // Update dark mode button label
    function updateToggle() {
      const btn = document.getElementById('dark-mode-toggle');
      if (btn) btn.textContent = document.documentElement.classList.contains('dark') ? '☀️' : '🌙';
    }
    updateToggle();

    // Dark mode toggle
    document.getElementById('dark-mode-toggle')?.addEventListener('click', () => {
      const isDark = document.documentElement.classList.toggle('dark');
      localStorage.setItem('dotp_theme', isDark ? 'dark' : 'light');
      updateToggle();
      document.dispatchEvent(new CustomEvent('themechange', { detail: { dark: isDark } }));
    });
  }

  // ── Set data-freshness date in nav once teams.json loads ────────
  function setNavDate(isoString) {
    const el = document.getElementById('nav-data-date');
    if (!el || !isoString) return;
    try {
      const dt = new Date(isoString);
      el.textContent = 'Data: ' + dt.toLocaleDateString('en-US', {
        month: 'short', day: 'numeric', year: 'numeric'
      });
    } catch (_) {}
  }

  // ── Run on DOM ready ────────────────────────────────────────────
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', buildNav);
  } else {
    buildNav();
  }

  // Expose helper globally so pages can call it after loading teams.json
  window.dotpNav = { setNavDate };
})();
