/**
 * team_charts.js — Team View Dashboard
 * URL params: ?owner=Reed+Heim  OR  ?team=Reed's+Trading+Post
 * Loaded by team.html. Requires charts.js (DOTP) + Chart.js.
 */

(async function () {
  'use strict';
  const D = window.DOTP;

  // ── Load all data ─────────────────────────────────────────────────
  let teamsData, rostersData, journeysData, tradesData;
  try {
    [teamsData, rostersData, journeysData, tradesData] = await Promise.all([
      D.loadJSON('data/teams.json'),
      D.loadJSON('data/rosters.json'),
      D.loadJSON('data/journeys.json'),
      D.loadJSON('data/trades.json'),
    ]);
  } catch (e) {
    document.getElementById('team-content').innerHTML =
      `<div class="error-msg">⚠ Failed to load data. Run <code>python build_dashboard.py</code> first.<br>${e.message}</div>`;
    return;
  }

  window.dotpNav?.setNavDate(teamsData.meta.generated_at);

  const owners = teamsData.owners;

  // ── Owner dropdown ────────────────────────────────────────────────
  const ownerSelect = document.getElementById('owner-select');
  owners.sort((a,b)=>a.real_name.localeCompare(b.real_name)).forEach(o => {
    const opt = document.createElement('option');
    opt.value = o.real_name;
    opt.textContent = `${o.real_name} — ${o.current_team}`;
    ownerSelect.appendChild(opt);
  });

  // ── URL param resolution ──────────────────────────────────────────
  const params  = new URLSearchParams(window.location.search);
  const paramOwner = params.get('owner');
  const paramTeam  = params.get('team');

  let initialOwner = paramOwner;
  if (!initialOwner && paramTeam) {
    const found = owners.find(o =>
      o.history.some(h => h.team_name === paramTeam) || o.current_team === paramTeam
    );
    if (found) initialOwner = found.real_name;
  }
  if (!initialOwner) initialOwner = owners[0]?.real_name;

  if (initialOwner) ownerSelect.value = initialOwner;

  ownerSelect.addEventListener('change', () => loadOwner(ownerSelect.value));

  // ── Render owner ──────────────────────────────────────────────────
  async function loadOwner(ownerName) {
    // Update URL without reload
    const url = new URL(window.location);
    url.searchParams.set('owner', ownerName);
    window.history.replaceState({}, '', url);

    const ownerData = owners.find(o => o.real_name === ownerName);
    if (!ownerData) return;

    const content = document.getElementById('team-content');
    content.innerHTML = '<div class="loading-spinner" style="height:200px"><div class="spinner"></div> Loading…</div>';

    // Gather data for this owner
    const rosterPlayers = rostersData.by_owner[ownerName] || [];
    const ownerStints   = journeysData.stints.filter(s => s.owner_real_name === ownerName);
    const ownerTrades   = tradesData.trade_events.filter(ev => (ev.parties||[]).includes(ownerName));
    const stats         = ownerData.stats || {};
    const color         = D.ownerColor(ownerName);

    // Per-year stats
    const yearStats = {};
    ownerTrades.forEach(ev => {
      const yr = ev.year;
      if (!yr) return;
      if (!yearStats[yr]) yearStats[yr] = { trades: 0, players: new Set() };
      yearStats[yr].trades++;
    });
    ownerStints.forEach(s => {
      const yr = s.start_date ? parseInt(s.start_date.slice(0,4)) : null;
      if (!yr) return;
      if (!yearStats[yr]) yearStats[yr] = { trades: 0, players: new Set() };
      yearStats[yr].players.add(s.player_name);
    });

    // Build "all players ever rostered" summary from stints
    const playerSummaryMap = {};
    ownerStints.forEach(s => {
      const pid = s.player_id;
      if (!playerSummaryMap[pid]) {
        playerSummaryMap[pid] = {
          player_id: pid, player_name: s.player_name,
          total_stints: 0, total_days: 0,
          last_start: s.start_date, acquisitions: {},
          is_current: false,
        };
      }
      const pm = playerSummaryMap[pid];
      pm.total_stints++;
      pm.total_days += s.tenure_days || 0;
      pm.acquisitions[s.acquisition_type] = (pm.acquisitions[s.acquisition_type]||0)+1;
      if (s.is_current) pm.is_current = true;
      if ((s.start_date||'') > (pm.last_start||'')) pm.last_start = s.start_date;
    });
    const allPlayersEver = Object.values(playerSummaryMap)
      .sort((a,b)=>b.total_days-a.total_days);

    content.innerHTML = `
      <!-- Identity Card -->
      <div class="owner-identity-card">
        <div style="display:flex;align-items:center;gap:14px;margin-bottom:12px">
          <div style="width:44px;height:44px;border-radius:50%;background:${color};display:flex;align-items:center;justify-content:center;font-size:1.4rem;color:#fff;font-weight:800;flex-shrink:0">
            ${ownerName.split(' ').map(w=>w[0]).join('').slice(0,2)}
          </div>
          <div>
            <div class="owner-name">${ownerName}</div>
            <div class="owner-team">Current: ${ownerData.current_team}</div>
          </div>
        </div>

        <!-- Season Ribbon -->
        <div class="season-ribbon">
          ${[...ownerData.history].sort((a,b)=>a.season-b.season).map(h => `
            <div class="season-pill ${h.season===2026?'current':''}">
              <span class="season-yr">${h.season}</span>
              <span class="season-team">${h.team_name}</span>
            </div>
          `).join('')}
        </div>

        <!-- Quick Stats -->
        <div class="stat-bar" style="justify-content:flex-start;margin-bottom:0">
          <div class="stat-card" style="min-width:110px">
            <span class="stat-label">Trades</span>
            <span class="stat-value">${stats.total_trades||0}</span>
          </div>
          <div class="stat-card" style="min-width:110px">
            <span class="stat-label">All-Time Players</span>
            <span class="stat-value gold">${allPlayersEver.length}</span>
          </div>
          <div class="stat-card" style="min-width:130px">
            <span class="stat-label">Top Trade Partner</span>
            <span class="stat-value" style="font-size:1rem">${stats.most_traded_with||'—'}</span>
          </div>
          <div class="stat-card" style="min-width:110px">
            <span class="stat-label">Fav. Acquisition</span>
            <span class="stat-value" style="font-size:0.9rem">${stats.most_common_acquisition||'—'}</span>
          </div>
          <div class="stat-card" style="min-width:110px">
            <span class="stat-label">Avg Tenure</span>
            <span class="stat-value" style="font-size:0.9rem">${stats.median_player_tenure_days ? Math.round(stats.median_player_tenure_days)+'d' : '—'}</span>
          </div>
        </div>
      </div>

      <!-- Current Roster -->
      <div class="chart-section">
        <h2>Current Roster (2026)</h2>
        <p class="chart-description">${rosterPlayers.length} players rostered. Click a row to see their full ownership journey.</p>
        <div class="data-table-wrapper">
          <table class="data-table" id="roster-table">
            <thead>
              <tr>
                <th data-sort="name">Player</th>
                <th data-sort="pos">POS</th>
                <th data-sort="status">Status</th>
                <th data-sort="acq">Acquired Via</th>
                <th data-sort="since">On Roster Since</th>
                <th data-sort="stints" style="text-align:center">Times Owned</th>
              </tr>
            </thead>
            <tbody id="roster-tbody"></tbody>
          </table>
        </div>
      </div>

      <!-- Season Breakdown Chart -->
      <div class="chart-section">
        <h2>Season Activity</h2>
        <p class="chart-description">Trades and unique players per season for this owner.</p>
        <div class="chart-wrapper">
          <canvas id="season-activity-chart" height="240"></canvas>
        </div>
      </div>

      <!-- All Players Ever Rostered -->
      <div class="chart-section">
        <h2>All Players Ever Rostered (${allPlayersEver.length})</h2>
        <p class="chart-description">Every player ${ownerName} has ever owned. Click a row to see their full journey through the league.</p>
        <div class="data-table-wrapper">
          <table class="data-table" id="all-players-table">
            <thead>
              <tr>
                <th data-sort="name">Player</th>
                <th data-sort="stints" style="text-align:center">Times Owned</th>
                <th data-sort="days" style="text-align:right">Total Days</th>
                <th data-sort="last">Last Acquired</th>
                <th data-sort="acq">How</th>
                <th data-sort="current" style="text-align:center">Current?</th>
              </tr>
            </thead>
            <tbody id="all-players-tbody"></tbody>
          </table>
        </div>
      </div>

      <!-- Trade History -->
      <div class="chart-section">
        <h2>Trade History (${ownerTrades.length} trades)</h2>
        <p class="chart-description">All trades involving ${ownerName}, newest first. Players received shown inline (★ = still on roster). Click for full details.</p>
        <div class="data-table-wrapper">
          <table class="data-table" id="trade-history-table">
            <thead>
              <tr>
                <th style="width:90px">Date</th>
                <th style="width:130px">Partners</th>
                <th>Received</th>
                <th style="width:60px">Type</th>
              </tr>
            </thead>
            <tbody id="trade-history-tbody"></tbody>
          </table>
        </div>
      </div>
    `;

    // ── Populate Roster Table ───────────────────────────────────────
    const rosterTbody = document.getElementById('roster-tbody');
    if (rosterTbody) {
      rosterTbody.innerHTML = rosterPlayers.map(p => {
        // Look up how many times this owner has had this player from stints
        const timesOwned = ownerStints.filter(s => s.player_id === p.player_id).length;
        return `
        <tr class="clickable" data-player-id="${p.player_id}" data-name="${p.player_name}" data-stints="${timesOwned}" data-pos="${p.position}" data-status="${p.roster_status}" data-acq="${p.acquisition_type||''}" data-since="${p.stint_start||''}">
          <td><strong>${p.player_name}</strong></td>
          <td>${p.position||'—'}</td>
          <td>${D.statusBadge(p.roster_status)}</td>
          <td>${D.acqBadge(p.acquisition_type)}</td>
          <td style="color:var(--text-muted);font-size:0.82rem">${D.fmtDate(p.stint_start)}</td>
          <td style="text-align:center;font-weight:${timesOwned>1?'700':'400'};color:${timesOwned>1?'var(--brand-green)':'inherit'}">${timesOwned}</td>
        </tr>`;
      }).join('');

      rosterTbody.querySelectorAll('tr').forEach(tr => {
        tr.addEventListener('click', () => {
          const pid  = tr.dataset.playerId;
          const name = tr.dataset.name;
          showPlayerJourneyModal(pid, name);
        });
      });

      D.makeSortable(document.getElementById('roster-table'));
    }

    // ── All Players Ever Rostered ───────────────────────────────────
    const allPlayersTbody = document.getElementById('all-players-tbody');
    if (allPlayersTbody) {
      allPlayersTbody.innerHTML = allPlayersEver.map(pm => {
        const dominantAcq = Object.entries(pm.acquisitions)
          .sort((a,b)=>b[1]-a[1])[0]?.[0] || '';
        return `<tr class="clickable" data-player-id="${pm.player_id}" data-name="${pm.player_name}" data-stints="${pm.total_stints}" data-days="${pm.total_days}" data-last="${pm.last_start||''}" data-acq="${dominantAcq}" data-current="${pm.is_current?'yes':'no'}">
          <td><strong>${pm.player_name}</strong></td>
          <td style="text-align:center">${pm.total_stints}</td>
          <td style="text-align:right;font-weight:600">${pm.total_days > 0 ? pm.total_days+'d' : '—'}</td>
          <td style="color:var(--text-muted);font-size:0.82rem">${D.fmtDate(pm.last_start)}</td>
          <td>${dominantAcq ? D.acqBadge(dominantAcq) : '—'}</td>
          <td style="text-align:center">${pm.is_current ? '<span style="color:var(--brand-green);font-weight:700">✓</span>' : ''}</td>
        </tr>`;
      }).join('');
      allPlayersTbody.querySelectorAll('tr').forEach(tr => {
        tr.addEventListener('click', () => showPlayerJourneyModal(tr.dataset.playerId, tr.dataset.name));
      });
      D.makeSortable(document.getElementById('all-players-table'));
    }

    // ── Season Activity Chart — use requestAnimationFrame to ensure canvas is in DOM ─
    const seasonCtx = document.getElementById('season-activity-chart');
    if (seasonCtx) {
      const allYears = new Set([
        ...Object.keys(yearStats),
        ...ownerData.history.map(h => String(h.season)),
      ]);
      const years = [...allYears].sort();
      // Ensure yearStats has entries for all years (even zeros)
      years.forEach(y => {
        if (!yearStats[y]) yearStats[y] = { trades: 0, players: new Set() };
      });
      new Chart(seasonCtx, {
        type: 'bar',
        data: {
          labels: years,
          datasets: [
            {
              label: 'Trades',
              data: years.map(y => yearStats[y]?.trades||0),
              backgroundColor: color + 'aa',
              borderColor: color,
              borderWidth: 1.5,
              borderRadius: 4,
              yAxisID: 'y',
            },
            {
              label: 'Unique Players',
              data: years.map(y => yearStats[y]?.players?.size||0),
              backgroundColor: D.ACQ_COLORS.CLAIMED + '99',
              borderColor: D.ACQ_COLORS.CLAIMED,
              borderWidth: 1.5,
              borderRadius: 4,
              type: 'line',
              yAxisID: 'y2',
              tension: 0.3,
              fill: false,
              pointRadius: 5,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: true,
          plugins: { legend: { display: true } },
          scales: {
            x: { grid: { display: false } },
            y:  { beginAtZero: true, position: 'left',  title: { display: true, text: 'Trades' },         ticks: { precision: 0 } },
            y2: { beginAtZero: true, position: 'right', title: { display: true, text: 'Unique Players' }, ticks: { precision: 0 }, grid: { drawOnChartArea: false } },
          },
        },
      });
    }

    // ── Trade History Table ─────────────────────────────────────────
    const tradeTbody = document.getElementById('trade-history-tbody');
    if (tradeTbody) {
      const sortedTrades = [...ownerTrades].sort((a,b)=>
        (b.date_iso||'').localeCompare(a.date_iso||'')
      );

      // Build player-name → is_current lookup from current roster
      const currentPlayerNames = new Set(rosterPlayers.map(p => p.player_name.toLowerCase()));

      tradeTbody.innerHTML = sortedTrades.slice(0, 80).map((ev, idx) => {
        const partners = (ev.parties||[]).filter(p=>p!==ownerName);
        const typeBadge = ev.party_count >= 3
          ? '<span class="badge badge-3team">3-Team</span>'
          : '<span class="badge badge-2team">2-Team</span>';

        // What did this owner receive?
        const received = Object.entries(ev.assets_by_party || {})
          .filter(([sender]) => sender !== ownerName)
          .flatMap(([, data]) => data.sent || []);

        const pills = received.map(p => {
          const isCurrent = currentPlayerNames.has(p.toLowerCase());
          return `<span style="display:inline-flex;align-items:center;background:var(--bg-primary);border:1px solid var(--border);border-radius:10px;padding:1px 6px;font-size:0.73rem;margin:1px;white-space:nowrap${isCurrent ? ';border-color:var(--brand-green);color:var(--brand-green);font-weight:600' : ''}">${p}${isCurrent ? ' ★' : ''}</span>`;
        }).join('');

        return `<tr class="clickable" data-idx="${idx}">
          <td style="white-space:nowrap;color:var(--text-muted);font-size:0.8rem">${ev.date||'—'}</td>
          <td style="font-size:0.82rem"><strong>${partners.map(p=>p.split(' ').pop()).join(' + ')||'—'}</strong></td>
          <td><div style="display:flex;flex-wrap:wrap;gap:1px">${pills || `<span style="font-size:0.74rem;color:var(--text-muted)">${(ev.details_raw||'').slice(0,80)}${(ev.details_raw?.length||0)>80?'…':''}</span>`}</div></td>
          <td>${typeBadge}</td>
        </tr>`;
      }).join('');

      const tradeRows = tradeTbody.querySelectorAll('tr');
      tradeRows.forEach((tr, i) => {
        tr.addEventListener('click', () => {
          const ev = sortedTrades[i];
          if (!ev) return;

          // Build detailed received/sent view
          const assetRows = (ev.parties||[]).map(p => {
            const received = Object.entries(ev.assets_by_party||{})
              .filter(([sender]) => sender !== p)
              .flatMap(([,data]) => data.sent||[]);
            const sent = ev.assets_by_party?.[p]?.sent || [];
            if (!received.length && !sent.length) return '';
            const dot = `<span style="width:9px;height:9px;border-radius:50%;background:${D.ownerColor(p)};display:inline-block"></span>`;
            let blk = `<div style="margin:8px 0"><div style="display:flex;align-items:center;gap:5px;font-weight:700;margin-bottom:4px">${dot}<strong>${p}</strong></div>`;
            if (received.length) {
              blk += `<div style="padding-left:18px;font-size:0.78rem;color:var(--text-muted);margin-bottom:2px">Received:</div>`;
              received.forEach(pl => { blk += `<div style="padding:2px 0 2px 18px;font-size:0.84rem;border-bottom:1px solid var(--border)">${pl}</div>`; });
            }
            if (sent.length) {
              blk += `<div style="padding-left:18px;font-size:0.78rem;color:var(--text-muted);margin-top:6px;margin-bottom:2px">Sent:</div>`;
              sent.forEach(pl => { blk += `<div style="padding:2px 0 2px 18px;font-size:0.84rem;border-bottom:1px solid var(--border)">${pl}</div>`; });
            }
            return blk + '</div>';
          }).filter(Boolean).join('');

          D.showModal(`
            <div class="modal-header">
              <h3>${ev.date||'—'} Trade</h3>
              <button class="modal-close" onclick="DOTP.hideModal()">×</button>
            </div>
            <div style="margin-bottom:12px">
              ${(ev.parties||[]).map(p=>`<span style="display:inline-flex;align-items:center;gap:5px;margin:3px">
                <span style="width:9px;height:9px;border-radius:50%;background:${D.ownerColor(p)};display:inline-block"></span>
                <strong>${p}</strong>
              </span>`).join('<span style="margin:0 4px;color:var(--text-muted)">↔</span>')}
            </div>
            ${assetRows || `<div style="background:var(--bg-primary);padding:12px;border-radius:6px;font-size:0.82rem;color:var(--text-secondary);white-space:pre-wrap;word-break:break-word">${ev.details_raw||'No details.'}</div>`}
            <details style="margin-top:10px">
              <summary style="font-size:0.78rem;color:var(--text-muted);cursor:pointer">Raw details</summary>
              <div style="background:var(--bg-primary);padding:10px;border-radius:6px;font-size:0.78rem;color:var(--text-secondary);white-space:pre-wrap;word-break:break-word;margin-top:6px">${ev.details_raw||'—'}</div>
            </details>
          `);
        });
      });
    }
  }

  // ── Player Journey Modal ──────────────────────────────────────────
  function showPlayerJourneyModal(playerId, playerName) {
    const pStints = (journeysData.stints||[])
      .filter(s => s.player_id === playerId)
      .sort((a,b)=>(a.start_date||'').localeCompare(b.start_date||''));

    const info = journeysData.player_index?.[playerId];

    const timelineHtml = pStints.map(s => {
      const tenure = s.tenure_days != null ? `${s.tenure_days}d` : (s.is_current ? 'Current' : '—');
      return `<div class="journey-stop ${s.is_current?'current':''}">
        <div class="journey-stop-header">
          <span class="journey-stop-team">${s.team_name}</span>
          ${D.acqBadge(s.acquisition_type)}
          <span class="journey-stop-tenure">${tenure}</span>
        </div>
        <div class="journey-stop-dates">
          ${D.fmtDate(s.start_date)} → ${s.end_date ? D.fmtDate(s.end_date) : '<strong style="color:var(--brand-green)">Present</strong>'}
          · <em>${s.owner_real_name}</em>
        </div>
      </div>`;
    }).join('');

    D.showModal(`
      <div class="modal-header">
        <h3>⚾ ${playerName}</h3>
        <button class="modal-close" onclick="DOTP.hideModal()">×</button>
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px">
        <div class="stat-card" style="min-width:80px">
          <span class="stat-label">Owners</span>
          <span class="stat-value" style="font-size:1.2rem">${info?.distinct_owners ?? info?.distinct_teams ?? '—'}</span>
        </div>
        <div class="stat-card" style="min-width:80px">
          <span class="stat-label">Stints</span>
          <span class="stat-value" style="font-size:1.2rem">${info?.total_stints||'—'}</span>
        </div>
        <div class="stat-card" style="min-width:110px">
          <span class="stat-label">Current Owner</span>
          <span class="stat-value" style="font-size:0.9rem;font-weight:700">${info?.current_owner||'Free Agent'}</span>
        </div>
      </div>
      <div class="journey-timeline">${timelineHtml||'<p class="text-muted">No journey data.</p>'}</div>
    `);
  }

  // ── Initial load ──────────────────────────────────────────────────
  if (initialOwner) loadOwner(initialOwner);
  else {
    document.getElementById('team-content').innerHTML =
      '<p class="text-muted text-center" style="padding:40px">Select an owner above to get started.</p>';
  }

})();
