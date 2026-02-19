/**
 * standings_charts.js — League Standings Dashboard
 * Loaded by standings.html. Requires Chart.js and charts.js (DOTP).
 */

(async function () {
  'use strict';
  const D = window.DOTP;

  // ── Load data ─────────────────────────────────────────────────────
  let teamsData, journeysData, tradesData, standingsData;
  try {
    [teamsData, journeysData, tradesData, standingsData] = await Promise.all([
      D.loadJSON('data/teams.json'),
      D.loadJSON('data/journeys.json'),
      D.loadJSON('data/trades.json'),
      D.loadJSON('data/standings.json'),
    ]);
  } catch (e) {
    document.body.innerHTML += `<div class="error-msg" style="margin:40px auto;max-width:600px">
      ⚠ Failed to load data.<br>${e.message}</div>`;
    return;
  }

  window.dotpNav?.setNavDate(teamsData.meta.generated_at);

  const owners     = teamsData.owners;
  const allYears   = [...(teamsData.meta.seasons || [])].sort();
  const stints     = journeysData.stints || [];
  const tradeEvents = tradesData.trade_events || [];

  // Fantrax standings data
  const seasonStandings  = standingsData.season_standings  || [];   // [{season, rank, team_name, owner_real_name, pts, hr, ...}]
  const alltimeStandings = standingsData.alltime_standings || [];  // [{owner_real_name, total_pts, alltime_rank, ...}]

  // Index season standings by season
  const standingsBySeason = {};   // season → [row sorted by rank]
  seasonStandings.forEach(r => {
    const s = String(r.season);
    if (!standingsBySeason[s]) standingsBySeason[s] = [];
    standingsBySeason[s].push(r);
  });
  Object.values(standingsBySeason).forEach(arr => arr.sort((a, b) => (a.rank || 99) - (b.rank || 99)));

  // Index alltime by owner name
  const alltimeByOwner = {};
  alltimeStandings.forEach(r => { alltimeByOwner[r.owner_real_name] = r; });

  // ── Pre-compute per-owner-per-season stats (non-Fantrax) ──────────
  const tradesByOwnerYear = {};
  tradeEvents.forEach(ev => {
    (ev.parties || []).forEach(o => {
      if (!tradesByOwnerYear[o]) tradesByOwnerYear[o] = {};
      const y = String(ev.year || '');
      if (y) tradesByOwnerYear[o][y] = (tradesByOwnerYear[o][y] || 0) + 1;
    });
  });

  const playersByOwnerYear = {};
  stints.forEach(s => {
    const o = s.owner_real_name;
    if (!o || o === 'Unknown') return;
    const y = s.start_date ? s.start_date.slice(0, 4) : null;
    if (!y) return;
    if (!playersByOwnerYear[o]) playersByOwnerYear[o] = {};
    if (!playersByOwnerYear[o][y]) playersByOwnerYear[o][y] = new Set();
    playersByOwnerYear[o][y].add(s.player_name);
  });

  const tenureByOwnerYear = {};
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
  let activeSeason = 'all';
  let playersChart = null, tradesChart = null, tenureChart = null;
  let ptsRankChart = null;

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

  // ── Helpers ───────────────────────────────────────────────────────
  function fmt(v, decimals = 0) {
    if (v == null) return '—';
    if (decimals > 0) return Number(v).toFixed(decimals);
    return Number(v).toLocaleString();
  }

  function fmtOBP(v) {
    if (v == null) return '—';
    return Number(v).toFixed(3).replace(/^0/, '');   // .336 not 0.336
  }

  // ── Build stats for current filter (non-Fantrax) ──────────────────
  function getDynastyStats(ownerReal, season) {
    const isAll = season === 'all';
    const years = isAll ? allYears.map(String) : [String(season)];

    const trades = years.reduce((s, y) => s + (tradesByOwnerYear[ownerReal]?.[y] || 0), 0);

    const playerSet = new Set();
    years.forEach(y => {
      const s = playersByOwnerYear[ownerReal]?.[y];
      if (s) s.forEach(p => playerSet.add(p));
    });

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
      uniquePlayers: playerSet.size,
      medianTenure: med != null ? Math.round(med) : null,
      topPartner: topPartner ? topPartner[0] : '—',
      topPartnerCount: topPartner ? topPartner[1] : 0,
    };
  }

  // ── Render standings table (Fantrax + dynasty hybrid) ────────────
  function renderTable() {
    const thead = document.getElementById('standings-thead');
    const tbody = document.getElementById('standings-tbody');
    const title = document.getElementById('standings-table-title');
    const desc  = document.getElementById('standings-table-desc');
    if (!thead || !tbody) return;

    const isAll = activeSeason === 'all';
    title.textContent = isAll ? '🏆 All-Time Rotisserie Standings' : `📅 ${activeSeason} Season Standings`;
    desc.textContent  = isAll
      ? 'Cumulative Roto points across all 6 seasons. Click a column header to sort. Click a row for Team View.'
      : `Full-season Fantrax rotisserie standings for ${activeSeason}. Click headers to sort. Click a row for Team View.`;

    if (isAll) {
      // All-time table: rank, owner, seasons, total_pts, avg_pts, best_finish, hr, rbi, sb, k, ip, avg_era, avg_obp
      thead.innerHTML = `<tr>
        <th data-sort="rank"    style="text-align:right;width:36px">Rk</th>
        <th data-sort="name"    style="min-width:130px">Owner</th>
        <th data-sort="seasons" style="text-align:right">Seasons</th>
        <th data-sort="pts"     style="text-align:right">Total Pts</th>
        <th data-sort="avgpts"  style="text-align:right">Avg Pts</th>
        <th data-sort="best"    style="text-align:right">Best Finish</th>
        <th data-sort="hr"      style="text-align:right" title="Career HR">HR</th>
        <th data-sort="rbi"     style="text-align:right" title="Career RBI">RBI</th>
        <th data-sort="sb"      style="text-align:right" title="Career SB">SB</th>
        <th data-sort="ip"      style="text-align:right" title="Career IP">IP</th>
        <th data-sort="k"       style="text-align:right" title="Career K (pitching)">K</th>
        <th data-sort="era"     style="text-align:right" title="Avg ERA">ERA</th>
        <th data-sort="obp"     style="text-align:right" title="Avg OBP">OBP</th>
      </tr>`;

      const rows = alltimeStandings.map(o => {
        const dot = `<span style="width:10px;height:10px;border-radius:50%;background:${D.ownerColor(o.owner_real_name)};display:inline-block;margin-right:6px;flex-shrink:0"></span>`;
        const medal = o.alltime_rank === 1 ? '🥇' : o.alltime_rank === 2 ? '🥈' : o.alltime_rank === 3 ? '🥉' : '';
        const bestStr = o.best_rank ? `#${o.best_rank} (${o.best_season})` : '—';
        return `<tr class="clickable"
            data-rank="${o.alltime_rank}" data-name="${o.owner_real_name}"
            data-seasons="${o.seasons_played}" data-pts="${o.total_pts}"
            data-avgpts="${o.avg_pts_per_season || 0}" data-best="${o.best_rank || 99}"
            data-hr="${o.hr || 0}" data-rbi="${o.rbi || 0}" data-sb="${o.sb || 0}"
            data-ip="${o.ip || 0}" data-k="${o.k || 0}"
            data-era="${o.avg_era || 999}" data-obp="${o.avg_obp || 0}"
            onclick="window.location.href='team.html?owner=${encodeURIComponent(o.owner_real_name)}'">
          <td style="text-align:right;font-weight:700;color:var(--text-muted)">${medal || o.alltime_rank}</td>
          <td><div style="display:flex;align-items:center">${dot}<strong>${o.owner_real_name}</strong></div></td>
          <td style="text-align:right">${o.seasons_played}</td>
          <td style="text-align:right;font-weight:700;color:var(--brand-green)">${fmt(o.total_pts, 1)}</td>
          <td style="text-align:right;color:var(--text-secondary)">${fmt(o.avg_pts_per_season, 1)}</td>
          <td style="text-align:right;font-size:0.85rem">${bestStr}</td>
          <td style="text-align:right">${fmt(o.hr)}</td>
          <td style="text-align:right">${fmt(o.rbi)}</td>
          <td style="text-align:right">${fmt(o.sb)}</td>
          <td style="text-align:right;color:var(--text-muted)">${fmt(o.ip, 1)}</td>
          <td style="text-align:right">${fmt(o.k)}</td>
          <td style="text-align:right;color:var(--text-secondary)">${fmt(o.avg_era, 2)}</td>
          <td style="text-align:right;color:var(--text-secondary)">${fmtOBP(o.avg_obp)}</td>
        </tr>`;
      }).join('');

      tbody.innerHTML = rows;

    } else {
      // Season-specific table: full Fantrax roto standings
      thead.innerHTML = `<tr>
        <th data-sort="rank" style="text-align:right;width:36px">Rk</th>
        <th data-sort="team" style="min-width:130px">Team</th>
        <th data-sort="owner" style="min-width:80px">Owner</th>
        <th data-sort="pts"  style="text-align:right" title="Rotisserie Points">Pts</th>
        <th data-sort="gp"   style="text-align:right" title="Games Played">GP</th>
        <th data-sort="ab"   style="text-align:right" title="At Bats">AB</th>
        <th data-sort="h"    style="text-align:right" title="Hits">H</th>
        <th data-sort="r"    style="text-align:right" title="Runs">R</th>
        <th data-sort="hr"   style="text-align:right" title="Home Runs">HR</th>
        <th data-sort="rbi"  style="text-align:right" title="RBI">RBI</th>
        <th data-sort="sb"   style="text-align:right" title="Stolen Bases">SB</th>
        <th data-sort="obp"  style="text-align:right" title="On-Base Percentage">OBP</th>
        <th data-sort="ip"   style="text-align:right" title="Innings Pitched">IP</th>
        <th data-sort="k"    style="text-align:right" title="Strikeouts">K</th>
        <th data-sort="era"  style="text-align:right" title="ERA">ERA</th>
        <th data-sort="whip" style="text-align:right" title="WHIP">WHIP</th>
        <th data-sort="svh3" style="text-align:right" title="Saves + Holds/2">SVH3</th>
        <th data-sort="wqs"  style="text-align:right" title="Wins + Quality Starts">W+QS</th>
      </tr>`;

      const seasonRows = standingsBySeason[String(activeSeason)] || [];
      const rows = seasonRows.map(r => {
        const dot = `<span style="width:10px;height:10px;border-radius:50%;background:${D.ownerColor(r.owner_real_name)};display:inline-block;margin-right:5px;flex-shrink:0"></span>`;
        const medal = r.rank === 1 ? '🥇' : r.rank === 2 ? '🥈' : r.rank === 3 ? '🥉' : '';
        return `<tr class="clickable"
            data-rank="${r.rank}" data-team="${r.team_name}" data-owner="${r.owner_real_name}"
            data-pts="${r.pts||0}" data-gp="${r.gp||0}" data-ab="${r.ab||0}" data-h="${r.h||0}"
            data-r="${r.r||0}" data-hr="${r.hr||0}" data-rbi="${r.rbi||0}" data-sb="${r.sb||0}"
            data-obp="${r.obp||0}" data-ip="${r.ip||0}" data-k="${r.k||0}"
            data-era="${r.era||999}" data-whip="${r.whip||999}" data-svh3="${r.svh3||0}" data-wqs="${r.wqs||0}"
            onclick="window.location.href='team.html?owner=${encodeURIComponent(r.owner_real_name)}'">
          <td style="text-align:right;font-weight:700;color:var(--text-muted)">${medal || r.rank}</td>
          <td style="font-size:0.82rem"><div style="display:flex;align-items:center">${dot}${r.team_name}</div></td>
          <td style="font-size:0.78rem;color:var(--text-secondary)">${r.owner_real_name.split(' ').pop()}</td>
          <td style="text-align:right;font-weight:700;color:var(--brand-green)">${fmt(r.pts)}</td>
          <td style="text-align:right;color:var(--text-muted)">${fmt(r.gp)}</td>
          <td style="text-align:right;color:var(--text-muted)">${fmt(r.ab)}</td>
          <td style="text-align:right">${fmt(r.h)}</td>
          <td style="text-align:right">${fmt(r.r)}</td>
          <td style="text-align:right">${fmt(r.hr)}</td>
          <td style="text-align:right">${fmt(r.rbi)}</td>
          <td style="text-align:right">${fmt(r.sb)}</td>
          <td style="text-align:right">${fmtOBP(r.obp)}</td>
          <td style="text-align:right;color:var(--text-muted)">${fmt(r.ip, 1)}</td>
          <td style="text-align:right">${fmt(r.k)}</td>
          <td style="text-align:right">${fmt(r.era, 2)}</td>
          <td style="text-align:right">${fmt(r.whip, 3)}</td>
          <td style="text-align:right">${fmt(r.svh3, 1)}</td>
          <td style="text-align:right">${fmt(r.wqs, 1)}</td>
        </tr>`;
      }).join('');

      tbody.innerHTML = rows || `<tr><td colspan="18" class="text-center text-muted" style="padding:24px">No standings data for ${activeSeason}.</td></tr>`;
    }

    D.makeSortable(document.getElementById('standings-table'));
  }

  // ── Rotisserie Points Bar Chart ───────────────────────────────────
  function renderPtsRankChart() {
    const ctx = document.getElementById('chart-pts-rank');
    if (!ctx) return;
    if (ptsRankChart) { ptsRankChart.destroy(); ptsRankChart = null; }

    const isAll = activeSeason === 'all';

    if (isAll) {
      // All-time: stacked bar, each season's pts per owner
      const ownersSorted = [...alltimeStandings].sort((a, b) => b.total_pts - a.total_pts);

      const seasonColors = {
        2021: 'rgba(251,191,36,0.85)',
        2022: 'rgba(74,222,128,0.85)',
        2023: 'rgba(96,165,250,0.85)',
        2024: 'rgba(249,115,22,0.85)',
        2025: 'rgba(167,139,250,0.85)',
        2026: 'rgba(239,68,68,0.85)',
      };

      ptsRankChart = new Chart(ctx, {
        type: 'bar',
        data: {
          labels: ownersSorted.map(o => o.owner_real_name.split(' ').pop()),
          datasets: allYears.map(yr => ({
            label: String(yr),
            data: ownersSorted.map(o => {
              const sf = (o.season_finishes || []).find(f => f.season === yr);
              return sf ? (sf.pts || 0) : 0;
            }),
            backgroundColor: seasonColors[yr] || 'rgba(100,100,100,0.7)',
            borderRadius: 2,
          })),
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { display: true, position: 'top' },
            tooltip: {
              callbacks: {
                title: items => ownersSorted[items[0].dataIndex].owner_real_name,
                label: ctx => ` ${ctx.dataset.label}: ${ctx.parsed.y} pts`,
                afterBody: items => {
                  const o = ownersSorted[items[0].dataIndex];
                  return [`Total: ${o.total_pts} pts`, `Avg: ${o.avg_pts_per_season}/season`];
                },
              },
            },
          },
          scales: {
            x: { stacked: true, grid: { display: false }, ticks: { maxRotation: 30 } },
            y: { stacked: true, beginAtZero: true, ticks: { precision: 0 },
                 title: { display: true, text: 'Roto Points' } },
          },
          onClick: (_, els) => {
            if (!els.length) return;
            window.location.href = `team.html?owner=${encodeURIComponent(ownersSorted[els[0].index].owner_real_name)}`;
          },
        },
      });

      const top = ownersSorted[0];
      document.getElementById('insight-pts-rank').innerHTML = top
        ? `<strong>${top.owner_real_name}</strong> leads all-time with <strong>${top.total_pts} Roto points</strong> across ${top.seasons_played} seasons (avg ${top.avg_pts_per_season}/season). Best finish: #${top.best_rank} in ${top.best_season}.`
        : '';

    } else {
      // Single season
      const seasonRows = (standingsBySeason[String(activeSeason)] || []).slice().sort((a, b) => (a.rank || 99) - (b.rank || 99));
      if (!seasonRows.length) return;

      ptsRankChart = new Chart(ctx, {
        type: 'bar',
        data: {
          labels: seasonRows.map(r => r.team_name.length > 22 ? r.team_name.slice(0, 20) + '…' : r.team_name),
          datasets: [{
            label: `${activeSeason} Roto Points`,
            data: seasonRows.map(r => r.pts || 0),
            backgroundColor: seasonRows.map(r => D.ownerColor(r.owner_real_name) + 'cc'),
            borderColor:     seasonRows.map(r => D.ownerColor(r.owner_real_name)),
            borderWidth: 1.5, borderRadius: 4,
          }],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                title: items => seasonRows[items[0].dataIndex].team_name,
                label: ctx => ` ${ctx.parsed.y} Roto pts (Rank #${seasonRows[ctx.dataIndex]?.rank || '?'})`,
              },
            },
          },
          scales: {
            x: { grid: { display: false }, ticks: { maxRotation: 40, font: { size: 10 } } },
            y: { beginAtZero: true, ticks: { precision: 0 },
                 title: { display: true, text: 'Roto Points' } },
          },
          onClick: (_, els) => {
            if (!els.length) return;
            window.location.href = `team.html?owner=${encodeURIComponent(seasonRows[els[0].index].owner_real_name)}`;
          },
        },
      });

      const top = seasonRows[0];
      document.getElementById('insight-pts-rank').innerHTML = top
        ? `<strong>${top.team_name}</strong> (${top.owner_real_name.split(' ').pop()}) finished <strong>#1</strong> in ${activeSeason} with <strong>${top.pts} Roto points</strong>.`
        : '';
    }
  }

  // ── Stat Radar / Category Rankings chart ─────────────────────────
  function renderStatsBars() {
    // Renders a multi-stat horizontal bar per season (HR, RBI, SB, K, ERA rank)
    const ctx = document.getElementById('chart-stat-rankings');
    if (!ctx) return;

    const isAll = activeSeason === 'all';
    const label = isAll ? 'All-Time' : String(activeSeason);

    // For a specific season: show actual stat values sorted by pts rank
    const seasonRows = isAll
      ? alltimeStandings.slice().sort((a, b) => b.total_pts - a.total_pts)
      : (standingsBySeason[String(activeSeason)] || []).slice().sort((a, b) => (a.rank || 99) - (b.rank || 99));

    if (!seasonRows.length) return;

    // Destroy existing chart stored on element
    if (ctx._chart) { ctx._chart.destroy(); ctx._chart = null; }

    const names = isAll
      ? seasonRows.map(r => r.owner_real_name.split(' ').pop())
      : seasonRows.map(r => r.team_name.length > 18 ? r.team_name.slice(0, 16) + '…' : r.team_name);

    const colors = isAll
      ? seasonRows.map(r => D.ownerColor(r.owner_real_name))
      : seasonRows.map(r => D.ownerColor(r.owner_real_name));

    // Show HR, RBI, SB as grouped bar
    const hrData  = seasonRows.map(r => r.hr || 0);
    const rbiData = seasonRows.map(r => r.rbi || 0);
    const sbData  = seasonRows.map(r => r.sb || 0);

    ctx._chart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: names,
        datasets: [
          { label: 'HR',  data: hrData,  backgroundColor: 'rgba(239,68,68,0.75)',  borderRadius: 2 },
          { label: 'RBI', data: rbiData, backgroundColor: 'rgba(251,146,60,0.75)', borderRadius: 2 },
          { label: 'SB',  data: sbData,  backgroundColor: 'rgba(74,222,128,0.75)', borderRadius: 2 },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: true, position: 'top' },
          tooltip: {
            callbacks: {
              title: items => isAll ? seasonRows[items[0].dataIndex].owner_real_name : seasonRows[items[0].dataIndex].team_name,
            },
          },
        },
        scales: {
          x: { grid: { display: false }, ticks: { maxRotation: 40, font: { size: 10 } } },
          y: { beginAtZero: true, ticks: { precision: 0 },
               title: { display: true, text: `${label} Counting Stats` } },
        },
        onClick: (_, els) => {
          if (!els.length) return;
          const owner = isAll ? seasonRows[els[0].index].owner_real_name : seasonRows[els[0].index].owner_real_name;
          window.location.href = `team.html?owner=${encodeURIComponent(owner)}`;
        },
      },
    });
  }

  // ── Render unique players bar chart ──────────────────────────────
  function renderPlayersBar() {
    const ctx = document.getElementById('chart-players-bar');
    if (!ctx) return;
    if (playersChart) { playersChart.destroy(); playersChart = null; }

    const isAll = activeSeason === 'all';
    const data = owners.map(o => {
      const s = getDynastyStats(o.real_name, activeSeason);
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
         <strong>${bot.owner}</strong> turns over the roster most frequently (${Math.round(bot.value)}d median).`
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
        // Find season standings rank for this owner + year
        const sRow = (standingsBySeason[String(yr)] || []).find(r => r.owner_real_name === o.real_name);
        const entry = (o.history || []).find(h => h.season === yr);
        const name = entry ? entry.team_name : '—';
        const rankBadge = sRow ? `<span style="font-size:0.65rem;color:var(--text-muted);display:block">#${sRow.rank} · ${sRow.pts} pts</span>` : '';
        html += `<td style="text-align:center;font-size:0.78rem;cursor:pointer;color:var(--text-secondary);padding:6px 4px"
          onclick="window.location.href='team.html?owner=${encodeURIComponent(o.real_name)}'"
          title="${o.real_name} — ${yr}${sRow ? ` | Rank #${sRow.rank}, ${sRow.pts} pts` : ''}">
          ${name}${rankBadge}
        </td>`;
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
      const seasonRows = standingsBySeason[String(activeSeason)] || [];
      const winner = seasonRows.find(r => r.rank === 1);
      ctx.textContent = winner
        ? `${activeSeason} season — champion: ${winner.team_name} (${winner.owner_real_name}) with ${winner.pts} Roto pts.`
        : `Showing ${activeSeason} season.`;
    }
  }

  // ── Render all ────────────────────────────────────────────────────
  function renderAll() {
    updateContext();
    renderTable();
    renderPtsRankChart();
    renderStatsBars();
    renderPlayersBar();
    renderTradesChart();
    renderTenureChart();
  }

  // Initial render
  renderAll();
  renderHistoryGrid();

  // Re-render on theme change
  document.addEventListener('themechange', () => {
    D.applyChartDefaults();
    renderPtsRankChart();
    renderStatsBars();
    renderPlayersBar();
    renderTradesChart();
    renderTenureChart();
  });

})();
