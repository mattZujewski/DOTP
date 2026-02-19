/**
 * standings_charts.js — League Standings Dashboard
 * Loaded by standings.html. Requires Chart.js and charts.js (DOTP).
 */

(async function () {
  'use strict';
  const D = window.DOTP;

  // ── Load data ─────────────────────────────────────────────────────
  let teamsData, journeysData, tradesData;
  try {
    [teamsData, journeysData, tradesData] = await Promise.all([
      D.loadJSON('data/teams.json'),
      D.loadJSON('data/journeys.json'),
      D.loadJSON('data/trades.json'),
    ]);
  } catch (e) {
    document.body.innerHTML += `<div class="error-msg" style="margin:40px auto;max-width:600px">
      ⚠ Failed to load data.<br>${e.message}</div>`;
    return;
  }

  window.dotpNav?.setNavDate(teamsData.meta.generated_at);

  const owners  = teamsData.owners;
  const allYears = [...(teamsData.meta.seasons || [])].sort();
  const stints   = journeysData.stints || [];
  const tradeEvents = tradesData.trade_events || [];

  // ── Pre-compute per-owner-per-season stats ────────────────────────
  // trades: count by owner × year
  const tradesByOwnerYear = {};  // owner → year → count
  tradeEvents.forEach(ev => {
    (ev.parties || []).forEach(o => {
      if (!tradesByOwnerYear[o]) tradesByOwnerYear[o] = {};
      const y = String(ev.year || '');
      if (y) tradesByOwnerYear[o][y] = (tradesByOwnerYear[o][y] || 0) + 1;
    });
  });

  // unique players: owner × year (from stints whose start_date falls in year)
  const playersByOwnerYear = {};  // owner → year → Set<player_name>
  stints.forEach(s => {
    const o = s.owner_real_name;
    if (!o || o === 'Unknown') return;
    const y = s.start_date ? s.start_date.slice(0, 4) : null;
    if (!y) return;
    if (!playersByOwnerYear[o]) playersByOwnerYear[o] = {};
    if (!playersByOwnerYear[o][y]) playersByOwnerYear[o][y] = new Set();
    playersByOwnerYear[o][y].add(s.player_name);
  });

  // tenure: owner × year → median days (from completed stints starting that year)
  const tenureByOwnerYear = {};  // owner → year → [tenure_days]
  stints.forEach(s => {
    const o = s.owner_real_name;
    if (!o || o === 'Unknown' || s.is_current) return;
    const y = s.start_date ? s.start_date.slice(0, 4) : null;
    if (!y || !s.tenure_days) return;
    if (!tenureByOwnerYear[o]) tenureByOwnerYear[o] = {};
    if (!tenureByOwnerYear[o][y]) tenureByOwnerYear[o][y] = [];
    tenureByOwnerYear[o][y].push(s.tenure_days);
  });

  function median(arr) {
    if (!arr || !arr.length) return null;
    const s = [...arr].sort((a, b) => a - b);
    const m = Math.floor(s.length / 2);
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  }

  // ── State ─────────────────────────────────────────────────────────
  let activeSeason = 'all';   // 'all' or a year string like '2025'
  let playersChart = null, tradesChart = null, tenureChart = null;

  // ── Season filter bar ─────────────────────────────────────────────
  const seasonBar = document.getElementById('season-filter-bar');
  if (seasonBar) {
    seasonBar.innerHTML = `
      <label>Season:</label>
      <button class="filter-btn active" data-season="all">All-Time</button>
      ${allYears.map(y => `<button class="filter-btn" data-season="${y}">${y}</button>`).join('')}
    `;
    seasonBar.addEventListener('click', e => {
      const btn = e.target.closest('.filter-btn');
      if (!btn) return;
      activeSeason = btn.dataset.season;
      seasonBar.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      renderAll();
    });
  }

  // ── Build stats for current filter ───────────────────────────────
  function getStatsForSeason(ownerReal, season) {
    const isAll = season === 'all';
    const years = isAll ? allYears.map(String) : [String(season)];

    const trades = years.reduce((s, y) => s + (tradesByOwnerYear[ownerReal]?.[y] || 0), 0);

    const playerSet = new Set();
    years.forEach(y => {
      const s = playersByOwnerYear[ownerReal]?.[y];
      if (s) s.forEach(p => playerSet.add(p));
    });
    const uniquePlayers = playerSet.size;

    const allDays = years.flatMap(y => tenureByOwnerYear[ownerReal]?.[y] || []);
    const med = median(allDays);

    const tradedWith = {};
    tradeEvents.forEach(ev => {
      if (!(ev.parties || []).includes(ownerReal)) return;
      const y = String(ev.year || '');
      if (!isAll && !years.includes(y)) return;
      (ev.parties || []).forEach(p => {
        if (p !== ownerReal) tradedWith[p] = (tradedWith[p] || 0) + 1;
      });
    });
    const topPartner = Object.entries(tradedWith).sort((a, b) => b[1] - a[1])[0];

    return {
      trades,
      uniquePlayers,
      medianTenure: med != null ? Math.round(med) : null,
      topPartner: topPartner ? topPartner[0] : '—',
      topPartnerCount: topPartner ? topPartner[1] : 0,
    };
  }

  // ── Render standings table ────────────────────────────────────────
  function renderTable() {
    const thead = document.getElementById('standings-thead');
    const tbody = document.getElementById('standings-tbody');
    const title = document.getElementById('standings-table-title');
    const desc  = document.getElementById('standings-table-desc');
    if (!thead || !tbody) return;

    const isAll = activeSeason === 'all';
    title.textContent = isAll ? 'All-Time Owner Stats' : `${activeSeason} Season Stats`;
    desc.textContent  = isAll
      ? 'Aggregated stats across all seasons. Click headers to sort. Click a row to open Team View.'
      : `Stats for the ${activeSeason} season only. Click headers to sort. Click a row to open Team View.`;

    thead.innerHTML = `<tr>
      <th data-sort="name" style="min-width:130px">Owner</th>
      <th data-sort="team" style="min-width:130px">${isAll ? 'Current Team' : `${activeSeason} Team`}</th>
      <th data-sort="trades" style="text-align:right">Trades</th>
      <th data-sort="players" style="text-align:right">Unique Players</th>
      <th data-sort="tenure" style="text-align:right">Median Tenure</th>
      <th data-sort="partner">Top Trade Partner</th>
    </tr>`;

    const rows = owners.map(o => {
      const stats = getStatsForSeason(o.real_name, activeSeason);
      const teamName = isAll
        ? (o.current_team || '—')
        : ((o.history || []).find(h => String(h.season) === String(activeSeason))?.team_name || '—');
      return { owner: o, stats, teamName };
    });

    // Default sort: trades desc
    rows.sort((a, b) => b.stats.trades - a.stats.trades);

    tbody.innerHTML = rows.map(({ owner: o, stats: s, teamName }) => {
      const dot = `<span style="width:10px;height:10px;border-radius:50%;background:${D.ownerColor(o.real_name)};display:inline-block;margin-right:6px;flex-shrink:0"></span>`;
      const tenureStr = s.medianTenure != null ? `${s.medianTenure}d` : '—';
      return `<tr class="clickable"
          data-name="${o.real_name}"
          data-team="${teamName}"
          data-trades="${s.trades}"
          data-players="${s.uniquePlayers}"
          data-tenure="${s.medianTenure ?? -1}"
          data-partner="${s.topPartner}"
          onclick="window.location.href='team.html?owner=${encodeURIComponent(o.real_name)}'">
        <td><div style="display:flex;align-items:center">${dot}<strong>${o.real_name}</strong></div></td>
        <td style="font-size:0.85rem;color:var(--text-secondary)">${teamName}</td>
        <td style="text-align:right;font-weight:700;color:var(--brand-green)">${s.trades}</td>
        <td style="text-align:right">${s.uniquePlayers}</td>
        <td style="text-align:right;color:var(--text-secondary)">${tenureStr}</td>
        <td style="font-size:0.82rem">${s.topPartner !== '—' ? `${s.topPartner} (${s.topPartnerCount})` : '—'}</td>
      </tr>`;
    }).join('');

    // Make sortable
    D.makeSortable(document.getElementById('standings-table'));
  }

  // ── Render unique players bar chart ──────────────────────────────
  function renderPlayersBar() {
    const ctx = document.getElementById('chart-players-bar');
    if (!ctx) return;
    if (playersChart) { playersChart.destroy(); playersChart = null; }

    const isAll = activeSeason === 'all';
    const data = owners.map(o => {
      const s = getStatsForSeason(o.real_name, activeSeason);
      return { owner: o.real_name, value: s.uniquePlayers };
    }).sort((a, b) => b.value - a.value);

    playersChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: data.map(d => d.owner.split(' ').pop()),
        datasets: [{
          label: isAll ? 'Unique Players (All-Time)' : `Unique Players (${activeSeason})`,
          data: data.map(d => d.value),
          backgroundColor: data.map(d => D.ownerColor(d.owner) + 'cc'),
          borderColor:     data.map(d => D.ownerColor(d.owner)),
          borderWidth: 1.5,
          borderRadius: 4,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: items => data[items[0].dataIndex].owner,
              label: ctx => ` ${ctx.parsed.y} unique players`,
            },
          },
        },
        scales: {
          x: { grid: { display: false }, ticks: { maxRotation: 30 } },
          y: { beginAtZero: true, ticks: { precision: 0 },
               title: { display: true, text: 'Unique Players' } },
        },
        onClick: (_, els) => {
          if (!els.length) return;
          window.location.href = `team.html?owner=${encodeURIComponent(data[els[0].index].owner)}`;
        },
      },
    });

    const top = data[0];
    document.getElementById('insight-players-bar').innerHTML = top
      ? `<strong>${top.owner}</strong> has rostered the most unique players${isAll ? ' all-time' : ` in ${activeSeason}`} — <strong>${top.value}</strong>.`
      : '';
  }

  // ── Render trades bar chart ───────────────────────────────────────
  function renderTradesChart() {
    const ctx = document.getElementById('chart-trades-owner');
    if (!ctx) return;
    if (tradesChart) { tradesChart.destroy(); tradesChart = null; }

    const isAll = activeSeason === 'all';

    if (isAll) {
      // Stacked bar by year
      const ownersSorted = owners
        .map(o => ({ name: o.real_name, total: allYears.reduce((s, y) => s + (tradesByOwnerYear[o.real_name]?.[String(y)] || 0), 0) }))
        .sort((a, b) => b.total - a.total);

      tradesChart = new Chart(ctx, {
        type: 'bar',
        data: {
          labels: ownersSorted.map(o => o.name.split(' ').pop()),
          datasets: allYears.map((yr, i) => ({
            label: String(yr),
            data: ownersSorted.map(o => tradesByOwnerYear[o.name]?.[String(yr)] || 0),
            backgroundColor: `hsl(${(i * 51 + 185) % 360},60%,52%)`,
            borderRadius: i === allYears.length - 1 ? 4 : 0,
          })),
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: true, position: 'top' } },
          scales: {
            x: { stacked: true, grid: { display: false }, ticks: { maxRotation: 30 } },
            y: { stacked: true, beginAtZero: true, ticks: { precision: 0 },
                 title: { display: true, text: 'Trade Participations' } },
          },
          onClick: (_, els) => {
            if (!els.length) return;
            window.location.href = `team.html?owner=${encodeURIComponent(ownersSorted[els[0].index].name)}`;
          },
        },
      });

      const top = ownersSorted[0];
      document.getElementById('insight-trades-owner').innerHTML = top
        ? `<strong>${top.name}</strong> has the most all-time trade participations — <strong>${top.total}</strong>.`
        : '';
    } else {
      // Single season
      const yr = String(activeSeason);
      const data = owners
        .map(o => ({ owner: o.real_name, value: tradesByOwnerYear[o.real_name]?.[yr] || 0 }))
        .sort((a, b) => b.value - a.value);

      tradesChart = new Chart(ctx, {
        type: 'bar',
        data: {
          labels: data.map(d => d.owner.split(' ').pop()),
          datasets: [{
            label: `${activeSeason} Trades`,
            data: data.map(d => d.value),
            backgroundColor: data.map(d => D.ownerColor(d.owner) + 'cc'),
            borderColor:     data.map(d => D.ownerColor(d.owner)),
            borderWidth: 1.5, borderRadius: 4,
          }],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { grid: { display: false }, ticks: { maxRotation: 30 } },
            y: { beginAtZero: true, ticks: { precision: 0 },
                 title: { display: true, text: `${activeSeason} Trade Participations` } },
          },
          onClick: (_, els) => {
            if (!els.length) return;
            window.location.href = `team.html?owner=${encodeURIComponent(data[els[0].index].owner)}`;
          },
        },
      });

      const top = data[0];
      document.getElementById('insight-trades-owner').innerHTML = top
        ? `In ${activeSeason}, <strong>${top.owner}</strong> was the most active trader with <strong>${top.value}</strong> trade participations.`
        : `No trades recorded for ${activeSeason}.`;
    }
  }

  // ── Render tenure chart ───────────────────────────────────────────
  function renderTenureChart() {
    const ctx = document.getElementById('chart-tenure-owner');
    if (!ctx) return;
    if (tenureChart) { tenureChart.destroy(); tenureChart = null; }

    const isAll = activeSeason === 'all';
    const years = isAll ? allYears.map(String) : [String(activeSeason)];

    const data = owners.map(o => {
      const allDays = years.flatMap(y => tenureByOwnerYear[o.real_name]?.[y] || []);
      return { owner: o.real_name, value: median(allDays) ?? 0 };
    }).sort((a, b) => b.value - a.value);

    tenureChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: data.map(d => d.owner.split(' ').pop()),
        datasets: [{
          label: 'Median Tenure (days)',
          data: data.map(d => Math.round(d.value)),
          backgroundColor: data.map(d => D.ownerColor(d.owner) + 'cc'),
          borderColor:     data.map(d => D.ownerColor(d.owner)),
          borderWidth: 1.5, borderRadius: 4,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: items => data[items[0].dataIndex].owner,
              label: ctx => ` ${ctx.parsed.y} day median tenure`,
            },
          },
        },
        scales: {
          x: { grid: { display: false }, ticks: { maxRotation: 30 } },
          y: { beginAtZero: true, ticks: { precision: 0 },
               title: { display: true, text: 'Median Days on Roster (completed stints)' } },
        },
        onClick: (_, els) => {
          if (!els.length) return;
          window.location.href = `team.html?owner=${encodeURIComponent(data[els[0].index].owner)}`;
        },
      },
    });

    const top = data[0];
    const bot = data[data.length - 1];
    document.getElementById('insight-tenure-owner').innerHTML = top && bot
      ? `<strong>${top.owner}</strong> keeps players longest (${Math.round(top.value)}d median).
         <strong>${bot.owner}</strong> turns over the roster most frequently (${Math.round(bot.value)}d median).
         Higher values = more stable roster.`
      : '';
  }

  // ── Season History Grid ───────────────────────────────────────────
  function renderHistoryGrid() {
    const container = document.getElementById('season-history-grid');
    if (!container) return;

    const seasons = allYears;
    const ownersSorted = [...owners].sort((a, b) => a.real_name.localeCompare(b.real_name));

    let html = `<div style="overflow-x:auto"><table class="data-table" style="min-width:700px">
      <thead><tr>
        <th style="min-width:130px">Owner</th>
        ${seasons.map(y => `<th style="text-align:center;min-width:110px">${y}</th>`).join('')}
      </tr></thead>
      <tbody>`;

    ownersSorted.forEach(o => {
      const dot = `<span style="width:10px;height:10px;border-radius:50%;background:${D.ownerColor(o.real_name)};display:inline-block;margin-right:6px"></span>`;
      html += `<tr>
        <td><div style="display:flex;align-items:center">${dot}<strong>${o.real_name.split(' ').pop()}</strong></div></td>`;
      seasons.forEach(yr => {
        const entry = (o.history || []).find(h => h.season === yr);
        const name = entry ? entry.team_name : '—';
        html += `<td style="text-align:center;font-size:0.78rem;cursor:pointer;color:var(--text-secondary)"
          onclick="window.location.href='team.html?owner=${encodeURIComponent(o.real_name)}'"
          title="${o.real_name} — ${yr}">${name}</td>`;
      });
      html += '</tr>';
    });

    html += '</tbody></table></div>';
    container.innerHTML = html;
  }

  // ── Update season context text ────────────────────────────────────
  function updateContext() {
    const ctx = document.getElementById('season-context');
    if (!ctx) return;
    if (activeSeason === 'all') {
      ctx.textContent = `Showing all-time stats across ${allYears.length} seasons (${allYears[0]}–${allYears[allYears.length-1]}).`;
    } else {
      const seasonOwners = owners.map(o => {
        const entry = (o.history || []).find(h => String(h.season) === String(activeSeason));
        return entry ? `${o.real_name} (${entry.team_name})` : null;
      }).filter(Boolean);
      ctx.textContent = `Showing ${activeSeason} season — ${seasonOwners.length} teams active.`;
    }
  }

  // ── Render all ────────────────────────────────────────────────────
  function renderAll() {
    updateContext();
    renderTable();
    renderPlayersBar();
    renderTradesChart();
    renderTenureChart();
  }

  // Initial render (all seasons history grid only renders once)
  renderAll();
  renderHistoryGrid();

  // Re-render on theme change
  document.addEventListener('themechange', () => {
    D.applyChartDefaults();
    renderPlayersBar();
    renderTradesChart();
    renderTenureChart();
  });

})();
