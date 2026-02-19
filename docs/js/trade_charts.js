/**
 * trade_charts.js — All 7 Trade Analysis charts + trade events list
 * Loaded by trade.html. Requires Chart.js, D3, and charts.js (DOTP).
 */

(async function () {
  'use strict';
  const D = window.DOTP;

  // ── State ────────────────────────────────────────────────────────
  let tradesData, teamsData, journeysData;
  let activeOwnerFilter = null;   // null = all
  let activeYearFilter  = 'all';
  let activeTypeFilter  = null;   // FEAT-02: null = all types
  let allTradeEvents    = [];
  let filteredEvents    = [];

  // ── Load data ────────────────────────────────────────────────────
  try {
    [tradesData, teamsData, journeysData] = await Promise.all([
      D.loadJSON('data/trades.json'),
      D.loadJSON('data/teams.json'),
      D.loadJSON('data/journeys.json'),
    ]);
    await document.fonts.ready;
  } catch (e) {
    document.body.innerHTML += `<div class="error-msg" style="margin:40px auto;max-width:600px">
      ⚠ Failed to load data. Run <code>python build_dashboard.py</code> first.<br>${e.message}
    </div>`;
    return;
  }

  window.dotpNav?.setNavDate(teamsData.meta.generated_at);
  allTradeEvents = tradesData.trade_events;

  // ── Build player tenure lookup: player_id → list of stints ───────
  const playerStintsByName = {};  // player_name (lower) → [{owner, start, end, tenure_days, is_current}]
  (journeysData.stints || []).forEach(s => {
    const key = (s.player_name || '').toLowerCase();
    if (!playerStintsByName[key]) playerStintsByName[key] = [];
    playerStintsByName[key].push(s);
  });

  // ── Helper: find post-trade tenure for a player acquired on a given date ──
  function postTradeTenure(playerName, receivingOwner, tradeDateIso) {
    const key = (playerName || '').toLowerCase();
    const stints = playerStintsByName[key] || [];
    // Find the stint where this owner got the player near this trade date
    const matching = stints
      .filter(s => s.owner_real_name === receivingOwner && s.start_date >= tradeDateIso)
      .sort((a,b) => a.start_date.localeCompare(b.start_date));
    if (!matching.length) return null;
    const s = matching[0];
    return { days: s.tenure_days, isCurrent: s.is_current };
  }

  // ── Helper: get players received by an owner from assets_by_party ─
  // assets_by_party is {owner_real_name: {sent:[...], received:[...]}}
  // Returns players that this owner received = what OTHER owners sent to them.
  function getPlayersReceivedByOwner(ev, owner) {
    const assets = ev.assets_by_party || {};
    // Players owner sent = assets[owner].sent
    // Players owner received = what the OTHER parties sent
    const received = [];
    Object.entries(assets).forEach(([sender, data]) => {
      if (sender !== owner) {
        received.push(...(data.sent || []));
      }
    });
    return received;
  }

  function getPlayersSentByOwner(ev, owner) {
    return (ev.assets_by_party?.[owner]?.sent) || [];
  }

  // ── Helper: parse players from details_raw text (fallback) ────────
  function parsePlayersFromDetails(detailsRaw) {
    if (!detailsRaw) return {};
    const SKIP = /draft pick|budget\s*:/i;
    const PAREN = /\([^)]*\)/g;
    const result = {};

    const segments = detailsRaw.split(/(?=\S.+?\s+trades\s+away\s)/i);
    segments.forEach(seg => {
      const m = seg.match(/^(.+?)\s+trades\s+away\s+(.*)$/is);
      if (!m) return;
      const teamRaw = m[1].trim();
      const assetsRaw = m[2].trim();
      const cleaned = assetsRaw.replace(PAREN, ' ').replace(/\s+/g, ' ').trim();
      const parts = cleaned.split(/,/).map(p => p.trim()).filter(Boolean);
      const players = parts.filter(p => !SKIP.test(p) && p.length > 2);
      if (players.length) result[teamRaw] = players;
    });
    return result;
  }

  // Unique years
  const allYears = [...new Set(allTradeEvents.map(e => e.year).filter(Boolean))].sort();

  // ── Year filter buttons ───────────────────────────────────────────
  const yearFilterContainer = document.getElementById('year-filter-bar');
  if (yearFilterContainer) {
    yearFilterContainer.innerHTML = `
      <label>Season:</label>
      <button class="filter-btn active" data-year="all">All</button>
      ${allYears.map(y => `<button class="filter-btn" data-year="${y}">${y}</button>`).join('')}
    `;
    yearFilterContainer.addEventListener('click', e => {
      const btn = e.target.closest('.filter-btn');
      if (!btn) return;
      activeYearFilter = btn.dataset.year === 'all' ? 'all' : parseInt(btn.dataset.year);
      yearFilterContainer.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      applyFilters();
    });
  }

  // ── Filter logic ─────────────────────────────────────────────────
  function applyFilters() {
    updateOwnerFilterLabel();
    updateTypeFilterLabel();
    filteredEvents = allTradeEvents.filter(ev => {
      const yearOk  = activeYearFilter === 'all' || ev.year === activeYearFilter;
      const ownerOk = !activeOwnerFilter || (ev.parties || []).includes(activeOwnerFilter);
      const typeOk  = !activeTypeFilter  || ev.trade_type_label === activeTypeFilter;
      return yearOk && ownerOk && typeOk;
    });
    updateAllCharts();
    renderTradeList();
  }

  // Stub — called before definition; will be wired up after DOM elements exist
  function updateOwnerFilterLabel() {
    const el  = document.getElementById('owner-filter-label');
    const btn = document.getElementById('clear-owner-filter');
    if (el)  el.textContent    = activeOwnerFilter ? `Filtering: ${activeOwnerFilter}` : '';
    if (btn) btn.style.display = activeOwnerFilter ? 'inline-block' : 'none';
  }

  function updateTypeFilterLabel() {
    const el  = document.getElementById('type-filter-label');
    const btn = document.getElementById('clear-type-filter');
    if (el)  el.textContent    = activeTypeFilter ? `Showing: ${activeTypeFilter}` : '';
    if (btn) btn.style.display = activeTypeFilter ? 'inline-block' : 'none';
  }

  // Chart instances (for destroy/re-render on filter)
  const charts = {};

  function destroyChart(id) {
    if (charts[id]) { charts[id].destroy(); delete charts[id]; }
  }

  // ── Chart 1: Trades Per Owner ─────────────────────────────────────
  function renderTradesPerOwner() {
    destroyChart('perOwner');
    const counts = {};
    filteredEvents.forEach(ev => {
      (ev.parties || []).forEach(o => { counts[o] = (counts[o]||0)+1; });
    });
    const sorted = Object.entries(counts).sort((a,b)=>b[1]-a[1]);
    const labels = sorted.map(([o])=>o);
    const values = sorted.map(([,v])=>v);
    const bgColors = labels.map(o => activeOwnerFilter === o ? D.ownerColor(o) : D.ownerColorAlpha(o, 0.7));

    const ctx = document.getElementById('chart-per-owner');
    if (!ctx) return;
    charts.perOwner = new Chart(ctx, {
      type: 'bar',
      data: {
        labels,
        datasets: [{ data: values, backgroundColor: bgColors, borderRadius: 4 }],
      },
      options: {
        ...D.horizontalBarOptions({ yLabel: 'Trade Events' }),
        onClick: (_, els) => {
          if (!els.length) return;
          const owner = labels[els[0].index];
          activeOwnerFilter = activeOwnerFilter === owner ? null : owner;
          applyFilters();
        },
      },
    });

    // Insight
    const top = sorted[0];
    document.getElementById('insight-per-owner').innerHTML = top
      ? `<strong>${top[0]}</strong> leads with <strong>${top[1]}</strong> trade participations.
         Click a bar to filter all charts to that owner.`
      : '';
  }

  // ── Chart 2: Trade Partner Matrix (D3 heatmap) ───────────────────
  function renderTradeMatrix() {
    const container = document.getElementById('chart-matrix-d3');
    if (!container) return;
    container.innerHTML = '';

    // Build counts from filtered events
    const pairCounts = {};
    filteredEvents.forEach(ev => {
      const parties = [...(ev.parties||[])].sort();
      for (let i=0; i<parties.length; i++) {
        for (let j=i+1; j<parties.length; j++) {
          const key = `${parties[i]}|||${parties[j]}`;
          pairCounts[key] = (pairCounts[key]||0)+1;
        }
      }
    });

    const owners = D.OWNERS_ALPHA.filter(o =>
      Object.keys(pairCounts).some(k => k.includes(o))
    );
    if (owners.length < 2) {
      container.innerHTML = '<p class="text-muted text-center" style="padding:24px">Not enough data for selected filters.</p>';
      return;
    }

    const margin = { top: 20, right: 20, bottom: 120, left: 140 };
    const cellSize = Math.max(28, Math.min(48, Math.floor((container.clientWidth - margin.left - margin.right) / owners.length)));
    const width  = cellSize * owners.length + margin.left + margin.right;
    const height = cellSize * owners.length + margin.top  + margin.bottom;

    const svg = d3.select(container).append('svg')
      .attr('width', '100%')
      .attr('viewBox', `0 0 ${width} ${height}`);

    const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

    const maxCount = Math.max(...Object.values(pairCounts), 1);
    const colorScale = d3.scaleSequential(d3.interpolateYlOrRd).domain([0, maxCount]);

    const tip = D.makeD3Tooltip();

    // Draw lower triangle
    owners.forEach((rowOwner, ri) => {
      owners.forEach((colOwner, ci) => {
        if (ci >= ri) return; // upper triangle
        const key  = [rowOwner, colOwner].sort().join('|||');
        const cnt  = pairCounts[key] || 0;
        const rect = g.append('rect')
          .attr('x', ci * cellSize)
          .attr('y', ri * cellSize)
          .attr('width',  cellSize - 1)
          .attr('height', cellSize - 1)
          .attr('rx', 3)
          .attr('fill', cnt > 0 ? colorScale(cnt) : 'var(--bg-primary)')
          .attr('stroke', 'var(--border)')
          .attr('stroke-width', 0.5)
          .style('cursor', cnt > 0 ? 'pointer' : 'default');

        if (cnt > 0) {
          g.append('text')
            .attr('x', ci * cellSize + cellSize/2)
            .attr('y', ri * cellSize + cellSize/2 + 4)
            .attr('text-anchor', 'middle')
            .attr('font-size', Math.max(9, cellSize * 0.3))
            .attr('fill', cnt > maxCount * 0.6 ? '#fff' : '#333')
            .text(cnt);

          rect.on('mouseover', (event) => {
              tip.show(`<strong>${rowOwner}</strong> ↔ <strong>${colOwner}</strong><br>${cnt} trades`, event);
            })
            .on('mousemove', tip.move)
            .on('mouseout',  tip.hide)
            .on('click', () => {
              D.showModal(`
                <div class="modal-header">
                  <h3>${rowOwner} ↔ ${colOwner}</h3>
                  <button class="modal-close" onclick="DOTP.hideModal()">×</button>
                </div>
                <p style="color:var(--text-muted);margin-bottom:12px">${cnt} trade${cnt!==1?'s':''} between these owners</p>
                <ul class="trade-timeline">${
                  filteredEvents
                    .filter(ev => ev.parties.includes(rowOwner) && ev.parties.includes(colOwner))
                    .map(ev => `<li class="trade-event">
                      <div class="trade-event-date">${ev.date||'—'}</div>
                      <div class="trade-event-body">
                        <div class="trade-parties">${ev.parties.join(' ↔ ')}</div>
                        <div class="trade-details-raw">${ev.details_raw||''}</div>
                      </div>
                    </li>`).join('')
                }</ul>
              `);
            });
        }
      });
    });

    // Row labels (Y axis)
    owners.forEach((o, i) => {
      g.append('text')
        .attr('x', -6).attr('y', i * cellSize + cellSize/2 + 4)
        .attr('text-anchor', 'end')
        .attr('font-size', Math.max(9, Math.min(11, cellSize * 0.28)))
        .attr('fill', 'var(--text-secondary)')
        .text(o.split(' ').pop()); // last name only
    });

    // Col labels (X axis, rotated)
    owners.forEach((o, i) => {
      g.append('text')
        .attr('x', i * cellSize + cellSize/2)
        .attr('y', owners.length * cellSize + 8)
        .attr('text-anchor', 'start')
        .attr('font-size', Math.max(9, Math.min(11, cellSize * 0.28)))
        .attr('fill', 'var(--text-secondary)')
        .attr('transform', `rotate(40, ${i*cellSize+cellSize/2}, ${owners.length*cellSize+8})`)
        .text(o.split(' ').pop());
    });

    // Insight
    const topPair = Object.entries(pairCounts).sort((a,b)=>b[1]-a[1])[0];
    if (topPair) {
      const [a,b] = topPair[0].split('|||');
      document.getElementById('insight-matrix').innerHTML =
        `<strong>${a}</strong> and <strong>${b}</strong> have traded the most —
         <strong>${topPair[1]} times</strong>. Click any cell to see the trade list.`;
    }
  }

  // ── Chart 3: Trade Network (D3 force-directed) ───────────────────
  function renderTradeNetwork() {
    const container = document.getElementById('chart-network-d3');
    if (!container) return;
    container.innerHTML = '';

    const pairCounts = {};
    filteredEvents.forEach(ev => {
      const parties = [...(ev.parties||[])].sort();
      for (let i=0; i<parties.length; i++) {
        for (let j=i+1; j<parties.length; j++) {
          const key = `${parties[i]}|||${parties[j]}`;
          pairCounts[key] = (pairCounts[key]||0)+1;
        }
      }
    });

    const nodeTotals = {};
    Object.entries(pairCounts).forEach(([key, cnt]) => {
      const [a,b] = key.split('|||');
      nodeTotals[a] = (nodeTotals[a]||0)+cnt;
      nodeTotals[b] = (nodeTotals[b]||0)+cnt;
    });

    const nodes = Object.keys(nodeTotals).map(id=>({id}));
    const links = Object.entries(pairCounts)
      .filter(([,c])=>c>=1)
      .map(([key,c])=>{
        const [s,t]=key.split('|||');
        return {source:s, target:t, value:c};
      });

    if (nodes.length < 2) {
      container.innerHTML = '<p class="text-muted text-center" style="padding:24px">No network data for selected filters.</p>';
      return;
    }

    const W = container.clientWidth || 800;
    const H = Math.min(500, W * 0.65);

    const svg = d3.select(container).append('svg')
      .attr('width', '100%')
      .attr('viewBox', `0 0 ${W} ${H}`);

    const maxNode = Math.max(...Object.values(nodeTotals), 1);
    const maxLink = Math.max(...links.map(l=>l.value), 1);

    const tip = D.makeD3Tooltip();

    const sim = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(links).id(d=>d.id).strength(0.4).distance(d => 180 - d.value * 4))
      .force('charge', d3.forceManyBody().strength(-320))
      .force('center', d3.forceCenter(W/2, H/2))
      .force('collision', d3.forceCollide(38));

    const link = svg.append('g').selectAll('line').data(links).enter().append('line')
      .attr('stroke', 'var(--text-muted)')
      .attr('stroke-opacity', 0.5)
      .attr('stroke-width', d => Math.max(1, d.value * 0.5));

    const node = svg.append('g').selectAll('circle').data(nodes).enter().append('circle')
      .attr('r', d => 14 + (nodeTotals[d.id]/maxNode)*22)
      .attr('fill', d => D.ownerColor(d.id))
      .attr('fill-opacity', 0.85)
      .attr('stroke', 'var(--bg-card)')
      .attr('stroke-width', 2)
      .call(d3.drag()
        .on('start', (event,d) => { if (!event.active) sim.alphaTarget(0.3).restart(); d.fx=d.x; d.fy=d.y; })
        .on('drag',  (event,d) => { d.fx=event.x; d.fy=event.y; })
        .on('end',   (event,d) => { if (!event.active) sim.alphaTarget(0); /* keep fx/fy — node stays pinned */ })
      )
      .on('mouseover', (event, d) => {
        const top = links.filter(l=>l.source.id===d.id||l.target.id===d.id)
          .sort((a,b)=>b.value-a.value).slice(0,3)
          .map(l=>`${l.source.id===d.id?l.target.id:l.source.id}: ${l.value}`).join('<br>');
        tip.show(`<strong>${d.id}</strong><br>Total trades: ${nodeTotals[d.id]}<br><em>Top partners:</em><br>${top}`, event);
        // Highlight connected edges
        link.attr('stroke-opacity', l =>
          l.source.id===d.id||l.target.id===d.id ? 0.9 : 0.1
        );
      })
      .on('mousemove', tip.move)
      .on('mouseout', () => { tip.hide(); link.attr('stroke-opacity', 0.5); });

    // Edge labels for high-count pairs
    const edgeLabel = svg.append('g').selectAll('text').data(links.filter(l=>l.value>=5)).enter().append('text')
      .attr('text-anchor', 'middle')
      .attr('font-size', 9)
      .attr('fill', 'var(--text-muted)')
      .text(d=>d.value);

    const label = svg.append('g').selectAll('text').data(nodes).enter().append('text')
      .attr('text-anchor', 'middle')
      .attr('font-size', 9)
      .attr('font-weight', '600')
      .attr('fill', 'var(--text-primary)')
      .attr('pointer-events', 'none')
      .text(d=>d.id.split(' ').pop());

    sim.on('tick', () => {
      link.attr('x1',d=>d.source.x).attr('y1',d=>d.source.y)
          .attr('x2',d=>d.target.x).attr('y2',d=>d.target.y);
      node.attr('cx',d=>Math.max(20,Math.min(W-20,d.x)))
          .attr('cy',d=>Math.max(20,Math.min(H-20,d.y)));
      label.attr('x',d=>d.x).attr('y',d=>d.y+4);
      edgeLabel.attr('x',d=>(d.source.x+d.target.x)/2)
               .attr('y',d=>(d.source.y+d.target.y)/2);
    });

    document.getElementById('insight-network').innerHTML =
      `Force-directed graph of trade relationships. Node size = total trade volume.
       Drag nodes to rearrange. Hover for details.`;
  }

  // ── Chart 4: Trade Activity Timeline (Chart.js line) ─────────────
  function renderTimeline() {
    destroyChart('timeline');
    const ctx = document.getElementById('chart-timeline');
    if (!ctx) return;

    // Group by year-month
    const counts = {};
    filteredEvents.forEach(ev => {
      if (!ev.year || !ev.month_num) return;
      const k = `${ev.year}-${String(ev.month_num).padStart(2,'0')}`;
      counts[k] = (counts[k]||0)+1;
    });

    const keys = Object.keys(counts).sort();
    const labels = keys.map(k => {
      const [y, m] = k.split('-');
      return `${['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][+m-1]} '${y.slice(2)}`;
    });
    const values = keys.map(k=>counts[k]);

    if (keys.length === 0) { ctx.closest('.chart-wrapper').innerHTML = '<p class="text-muted text-center" style="padding:24px">No data.</p>'; return; }

    charts.timeline = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: 'Trade Events',
          data: values,
          borderColor: '#4472C4',
          backgroundColor: 'rgba(68,114,196,0.12)',
          fill: true,
          tension: 0.3,
          pointRadius: 4,
          pointHoverRadius: 7,
        }],
      },
      options: { ...D.lineOptions({ yLabel: 'Trade Events' }), maintainAspectRatio: false },
    });

    const peak = keys[values.indexOf(Math.max(...values))];
    const [py,pm] = (peak||'').split('-');
    document.getElementById('insight-timeline').innerHTML = peak
      ? `Trade activity peaked in <strong>${['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][+pm-1]} ${py}</strong>
         with <strong>${Math.max(...values)}</strong> trades — likely the trade deadline or offseason window.`
      : '';
  }

  // ── Chart 5: Trade Activity Heatmap (D3 grid) ────────────────────
  function renderHeatmap() {
    const container = document.getElementById('chart-heatmap-d3');
    if (!container) return;
    container.innerHTML = '';

    const counts = {};
    filteredEvents.forEach(ev => {
      if (!ev.year || !ev.month_num) return;
      const k = `${ev.year}-${ev.month_num}`;
      counts[k] = (counts[k]||0)+1;
    });

    const years  = allYears;
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    const maxVal = Math.max(...Object.values(counts), 1);

    const cellW = Math.max(28, Math.min(55, Math.floor((container.clientWidth - 60) / 12)));
    const cellH = 28;
    const W     = cellW * 12 + 60;
    const H     = cellH * years.length + 50;

    const colorScale = d3.scaleSequential(d3.interpolateYlOrRd).domain([0, maxVal]);
    const tip = D.makeD3Tooltip();

    const svg = d3.select(container).append('svg')
      .attr('width','100%').attr('viewBox',`0 0 ${W} ${H}`);

    const g = svg.append('g').attr('transform','translate(55,30)');

    years.forEach((yr, yi) => {
      months.forEach((mo, mi) => {
        const val = counts[`${yr}-${mi+1}`]||0;
        g.append('rect')
          .attr('x', mi*cellW).attr('y', yi*cellH)
          .attr('width', cellW-2).attr('height', cellH-2)
          .attr('rx', 3)
          .attr('fill', val>0 ? colorScale(val) : 'var(--bg-primary)')
          .attr('stroke','var(--border)').attr('stroke-width',0.5)
          .on('mouseover', e => tip.show(`<strong>${mo} ${yr}</strong>: ${val} trades`, e))
          .on('mousemove', tip.move).on('mouseout', tip.hide);

        if (val>0) {
          g.append('text')
            .attr('x', mi*cellW+cellW/2).attr('y', yi*cellH+cellH/2+4)
            .attr('text-anchor','middle').attr('font-size',9)
            .attr('fill', val>maxVal*0.6?'#fff':'#333').text(val);
        }
      });

      // Year label
      g.append('text').attr('x',-6).attr('y', yi*cellH+cellH/2+4)
        .attr('text-anchor','end').attr('font-size',10).attr('fill','var(--text-muted)').text(yr);
    });

    months.forEach((mo,mi) => {
      g.append('text').attr('x',mi*cellW+cellW/2).attr('y',-6)
        .attr('text-anchor','middle').attr('font-size',9).attr('fill','var(--text-muted)').text(mo);
    });

    document.getElementById('insight-heatmap').innerHTML =
      `Year × Month breakdown of all trade activity. Darker = more trades.`;
  }

  // ── Chart 6: 2-Team vs 3-Team Breakdown ──────────────────────────
  function renderMultiTeam() {
    destroyChart('multiTeam');
    const ctx = document.getElementById('chart-multiteam');
    if (!ctx) return;

    const byYear = {};
    filteredEvents.forEach(ev => {
      if (!ev.year) return;
      const yr = String(ev.year);
      if (!byYear[yr]) byYear[yr] = { '2-Team':0, '3-Team':0 };
      if (ev.party_count >= 3) byYear[yr]['3-Team']++;
      else byYear[yr]['2-Team']++;
    });

    const years = Object.keys(byYear).sort();
    if (!years.length) { ctx.closest('.chart-wrapper').innerHTML = '<p class="text-muted text-center" style="padding:24px">No data.</p>'; return; }

    charts.multiTeam = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: years,
        datasets: [
          { label: '2-Team', data: years.map(y=>byYear[y]['2-Team']), backgroundColor: 'rgba(68,114,196,0.75)', borderRadius: 4 },
          { label: '3-Team', data: years.map(y=>byYear[y]['3-Team']), backgroundColor: 'rgba(237,125,49,0.75)', borderRadius: 4 },
        ],
      },
      options: {
        ...D.barOptions({ stacked: true, xLabel: 'Season', yLabel: 'Trade Events' }),
        maintainAspectRatio: false,
      },
    });

    const total3 = filteredEvents.filter(e=>e.party_count>=3).length;
    const pct3   = filteredEvents.length > 0 ? Math.round(total3/filteredEvents.length*100) : 0;
    document.getElementById('insight-multiteam').innerHTML =
      `<strong>${total3}</strong> of ${filteredEvents.length} trades (${pct3}%) involved 3+ teams.
       Multi-team trades add complexity and signal an active trade market.`;
  }

  // ── Chart 7: Trade Volume by Season per Owner ─────────────────────
  function renderVolumeBySeasonOwner() {
    destroyChart('volSeason');
    const ctx = document.getElementById('chart-vol-season');
    if (!ctx) return;

    const byOwnerYear = {};
    filteredEvents.forEach(ev => {
      if (!ev.year) return;
      (ev.parties||[]).forEach(o => {
        if (!byOwnerYear[o]) byOwnerYear[o] = {};
        byOwnerYear[o][ev.year] = (byOwnerYear[o][ev.year]||0)+1;
      });
    });

    const ownersSorted = Object.entries(byOwnerYear)
      .sort((a,b)=>Object.values(b[1]).reduce((s,v)=>s+v,0)-Object.values(a[1]).reduce((s,v)=>s+v,0))
      .map(([o])=>o);

    const years = activeYearFilter === 'all' ? allYears : [activeYearFilter];

    charts.volSeason = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: ownersSorted,
        datasets: years.map((yr, i) => ({
          label: String(yr),
          data: ownersSorted.map(o => byOwnerYear[o]?.[yr]||0),
          backgroundColor: `hsl(${(i*47+200)%360},60%,52%)`,
          borderRadius: 3,
        })),
      },
      options: {
        ...D.barOptions({ xLabel: 'Owner', yLabel: 'Trades', stacked: false }),
        maintainAspectRatio: false,
        scales: {
          x: { ticks: { maxRotation: 35, minRotation: 25 }, grid: { display: false } },
          y: { beginAtZero: true, ticks: { precision: 0 } },
        },
      },
    });

    const topOwner = ownersSorted[0];
    if (topOwner) {
      const total = Object.values(byOwnerYear[topOwner]||{}).reduce((s,v)=>s+v,0);
      document.getElementById('insight-vol-season').innerHTML =
        `<strong>${topOwner}</strong> is the most active trader in this view with
         <strong>${total}</strong> total participations.`;
    }
  }

  // ── Trade Events List ─────────────────────────────────────────────
  function renderTradeList() {
    const tbody = document.getElementById('trade-list-tbody');
    if (!tbody) return;
    const subset = filteredEvents.slice(0, 150);

    tbody.innerHTML = subset.map((ev, i) => {
      const typeBadge = ev.party_count >= 3
        ? '<span class="badge badge-3team">3-Team</span>'
        : '<span class="badge badge-2team">2-Team</span>';

      // BUG-03: Build separate Sent and Received cells.
      // For 2-team trades: show from Party A's perspective (sent → received).
      // For 3-team trades: list each owner's sent and received stacked.
      const hasAssets = ev.assets_by_party && Object.keys(ev.assets_by_party).length > 0;

      const makePills = (players, receivingOwner) => players.map(p => {
        const t = receivingOwner ? postTradeTenure(p, receivingOwner, ev.date_iso || '') : null;
        const tenure = t
          ? `<span style="color:var(--text-muted);font-size:0.7rem;margin-left:2px">${t.isCurrent ? '★' : t.days + 'd'}</span>`
          : '';
        return `<span style="display:inline-flex;align-items:center;background:var(--bg-primary);border:1px solid var(--border);border-radius:10px;padding:1px 6px;font-size:0.74rem;margin:1px;white-space:nowrap">${p}${tenure}</span>`;
      }).join('');

      let sentCell = '', receivedCell = '';

      if (hasAssets) {
        const parties = ev.parties || [];
        if (ev.party_count >= 3) {
          // 3-team: show one line per owner with their color dot
          sentCell = parties.map(owner => {
            const sent = getPlayersSentByOwner(ev, owner);
            if (!sent.length) return '';
            const dot = `<span style="width:7px;height:7px;border-radius:50%;background:${D.ownerColor(owner)};display:inline-block;margin-right:3px;flex-shrink:0"></span>`;
            return `<div style="display:flex;align-items:center;flex-wrap:wrap;gap:1px;margin:1px 0">${dot}${makePills(sent, null)}</div>`;
          }).filter(Boolean).join('');
          receivedCell = parties.map(owner => {
            const received = getPlayersReceivedByOwner(ev, owner);
            if (!received.length) return '';
            const dot = `<span style="width:7px;height:7px;border-radius:50%;background:${D.ownerColor(owner)};display:inline-block;margin-right:3px;flex-shrink:0"></span>`;
            return `<div style="display:flex;align-items:center;flex-wrap:wrap;gap:1px;margin:1px 0">${dot}${makePills(received, owner)}</div>`;
          }).filter(Boolean).join('');
        } else {
          // 2-team: use first party as the reference perspective
          const partyA = parties[0];
          const partyB = parties[1];
          const sent     = partyA ? getPlayersSentByOwner(ev, partyA)     : [];
          const received = partyA ? getPlayersReceivedByOwner(ev, partyA) : [];
          sentCell     = sent.length     ? makePills(sent, partyB)     : '';
          receivedCell = received.length ? makePills(received, partyA) : '';
        }
      }

      if (!sentCell && !receivedCell) {
        const raw = (ev.details_raw || '').slice(0, 80);
        const fallback = `<span style="font-size:0.74rem;color:var(--text-muted)">${raw}${(ev.details_raw?.length || 0) > 80 ? '…' : ''}</span>`;
        sentCell = fallback;
        receivedCell = '';
      }

      const ownerDots = (ev.parties || []).map(p =>
        `<span style="display:inline-flex;align-items:center;gap:3px;font-size:0.78rem;white-space:nowrap">
           <span style="width:8px;height:8px;border-radius:50%;background:${D.ownerColor(p)};display:inline-block"></span>${p.split(' ').pop()}
         </span>`
      ).join('<span style="color:var(--text-muted);margin:0 2px">↔</span>');

      return `<tr class="clickable" data-idx="${i}">
        <td style="white-space:nowrap;font-size:0.8rem">${ev.date||'—'}</td>
        <td>${ownerDots}</td>
        <td>${sentCell}</td>
        <td>${receivedCell}</td>
        <td>${typeBadge}</td>
        <td style="text-align:center;font-size:0.8rem">${ev.year||'—'}</td>
      </tr>`;
    }).join('');

    tbody.querySelectorAll('tr').forEach((tr, i) => {
      tr.addEventListener('click', () => {
        const ev = subset[i];
        const hasAssets = ev.assets_by_party && Object.keys(ev.assets_by_party).length > 0;

        let detailRows = '';
        if (hasAssets) {
          detailRows = (ev.parties || []).map(owner => {
            const received = getPlayersReceivedByOwner(ev, owner);
            const sent     = getPlayersSentByOwner(ev, owner);
            if (!received.length && !sent.length) return '';
            const dot = `<span style="width:10px;height:10px;border-radius:50%;background:${D.ownerColor(owner)};display:inline-block"></span>`;
            const makeRow = (p, fromOwner) => {
              const t = postTradeTenure(p, fromOwner, ev.date_iso || '');
              const tenure = t
                ? `<span style="margin-left:8px;font-size:0.78rem;color:var(--text-muted)">${t.isCurrent ? '⭐ Still on roster' : `Kept ${t.days}d`}</span>`
                : '';
              return `<div style="padding:3px 0 3px 20px;border-bottom:1px solid var(--border);font-size:0.84rem">${p}${tenure}</div>`;
            };
            let block = `<div style="margin:10px 0"><div style="display:flex;align-items:center;gap:6px;font-weight:700;margin-bottom:6px">${dot}<strong>${owner}</strong></div>`;
            if (received.length) {
              block += `<div style="font-size:0.78rem;color:var(--text-muted);padding-left:20px;margin-bottom:2px">⬇ Received:</div>`;
              block += received.map(p => makeRow(p, owner)).join('');
            }
            if (sent.length) {
              block += `<div style="font-size:0.78rem;color:var(--text-muted);padding-left:20px;margin-top:6px;margin-bottom:2px">⬆ Sent:</div>`;
              block += sent.map(p => makeRow(p, /* old owner won't have journey */ null)).join('');
            }
            block += '</div>';
            return block;
          }).filter(Boolean).join('');
        }

        D.showModal(`
          <div class="modal-header">
            <h3>${ev.date||'—'} Trade</h3>
            <button class="modal-close" onclick="DOTP.hideModal()">×</button>
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px">
            ${(ev.parties||[]).map(p=>`<span style="display:inline-flex;align-items:center;gap:6px;background:var(--bg-primary);padding:4px 10px;border-radius:20px;font-size:0.82rem">
              <span style="width:10px;height:10px;border-radius:50%;background:${D.ownerColor(p)};display:inline-block"></span>
              <strong>${p}</strong>
            </span>`).join('<span style="color:var(--text-muted);font-size:1.1rem;align-self:center">↔</span>')}
          </div>
          ${detailRows || `<div style="background:var(--bg-primary);padding:12px;border-radius:6px;font-size:0.82rem;color:var(--text-secondary);white-space:pre-wrap;word-break:break-word">${ev.details_raw||'No details available.'}</div>`}
          <details style="margin-top:12px">
            <summary style="font-size:0.78rem;color:var(--text-muted);cursor:pointer">Raw details</summary>
            <div style="background:var(--bg-primary);padding:10px;border-radius:6px;font-size:0.78rem;color:var(--text-secondary);white-space:pre-wrap;word-break:break-word;margin-top:6px">${ev.details_raw||'—'}</div>
          </details>
        `);
      });
    });

    const countEl = document.getElementById('trade-list-count');
    if (countEl) {
      countEl.textContent = `Showing ${subset.length} of ${filteredEvents.length} trade events`;
    }
  }

  // ── Chart 7: Trade Type Breakdown (FEAT-02) ───────────────────────
  const TYPE_COLORS = {
    'Player-for-Player': 'rgba(68,114,196,0.82)',
    'Player-for-Pick':   'rgba(237,125,49,0.82)',
    'Player-for-FAAB':   'rgba(112,173,71,0.82)',
    'Pick-for-Pick':     'rgba(255,192,0,0.82)',
    'Pick-for-FAAB':     'rgba(91,155,213,0.82)',
    'Mixed':             'rgba(165,105,189,0.82)',
    'Other':             'rgba(150,150,150,0.82)',
  };
  const TYPE_ORDER = [
    'Player-for-Player','Player-for-Pick','Player-for-FAAB',
    'Pick-for-Pick','Pick-for-FAAB','Mixed','Other',
  ];

  function renderTradeTypeBreakdown() {
    destroyChart('tradeType');
    destroyChart('tradeSubtype');

    const ctx = document.getElementById('chart-trade-type');
    if (!ctx) return;

    // Count from filteredEvents so chart responds to year/owner filters
    const counts = {};
    filteredEvents.forEach(ev => {
      const lbl = ev.trade_type_label || 'Other';
      counts[lbl] = (counts[lbl] || 0) + 1;
    });
    const total = filteredEvents.length || 1;

    // Respect TYPE_ORDER for consistent colour mapping
    const labels = TYPE_ORDER.filter(t => counts[t] > 0);
    const values = labels.map(t => counts[t]);
    const bgColors = labels.map(t => TYPE_COLORS[t] || 'rgba(150,150,150,0.8)');

    charts.tradeType = new Chart(ctx, {
      type: 'doughnut',
      data: { labels, datasets: [{ data: values, backgroundColor: bgColors, borderWidth: 1, borderColor: 'var(--bg-card)' }] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '62%',
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: item => ` ${item.label}: ${item.parsed} (${Math.round(item.parsed / total * 100)}%)`,
            },
          },
        },
        onClick: (_, els) => {
          if (!els.length) return;
          const clicked = labels[els[0].index];
          activeTypeFilter = activeTypeFilter === clicked ? null : clicked;
          applyFilters();
          renderTradeTypeBreakdown(); // re-render to update highlight
        },
      },
    });

    // Summary table
    const tbody = document.getElementById('trade-type-tbody');
    if (tbody) {
      tbody.innerHTML = labels.map(t => {
        const cnt  = counts[t];
        const pct  = Math.round(cnt / total * 100);
        const dot  = `<span style="width:9px;height:9px;border-radius:50%;background:${TYPE_COLORS[t]||'#999'};display:inline-block;margin-right:6px;flex-shrink:0"></span>`;
        const isActive = activeTypeFilter === t;
        return `<tr class="clickable${isActive ? ' active-row' : ''}" data-type="${t}"
                    style="${isActive ? 'background:var(--bg-primary);font-weight:700' : ''}">
          <td><span style="display:inline-flex;align-items:center">${dot}${t}</span></td>
          <td style="text-align:right">${cnt}</td>
          <td style="text-align:right">${pct}%</td>
        </tr>`;
      }).join('');

      tbody.querySelectorAll('tr').forEach(tr => {
        tr.addEventListener('click', () => {
          const clicked = tr.dataset.type;
          activeTypeFilter = activeTypeFilter === clicked ? null : clicked;
          applyFilters();
          renderTradeTypeBreakdown();
        });
      });
    }

    // Sub-type bar chart (Player-for-Player only)
    const subtypeWrap = document.getElementById('trade-subtype-wrap');
    const subtypeCtx  = document.getElementById('chart-trade-subtype');
    const showSubtype = activeTypeFilter === 'Player-for-Player' || !activeTypeFilter;
    const subtypeSummary = tradesData.trade_type_summary?.['Player-for-Player']?.sub_types || {};

    if (subtypeWrap) subtypeWrap.style.display = (showSubtype && Object.keys(subtypeSummary).length > 0) ? 'block' : 'none';

    if (showSubtype && subtypeCtx && Object.keys(subtypeSummary).length > 0) {
      // Count sub-types from filteredEvents (not global summary) so filters apply
      const subCounts = {};
      filteredEvents
        .filter(ev => ev.trade_type_label === 'Player-for-Player' && ev.player_sub_type)
        .forEach(ev => { subCounts[ev.player_sub_type] = (subCounts[ev.player_sub_type] || 0) + 1; });

      const subLabels = Object.entries(subCounts).sort((a,b) => b[1]-a[1]).map(([l])=>l);
      const subValues = subLabels.map(l => subCounts[l]);

      if (subLabels.length) {
        charts.tradeSubtype = new Chart(subtypeCtx, {
          type: 'bar',
          data: {
            labels: subLabels,
            datasets: [{
              data: subValues,
              backgroundColor: 'rgba(68,114,196,0.72)',
              borderRadius: 4,
            }],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
              x: { grid: { display: false }, ticks: { font: { size: 11 } } },
              y: { beginAtZero: true, ticks: { precision: 0 } },
            },
          },
        });
      }
    }

    // Insight callout
    const insightEl = document.getElementById('insight-trade-type');
    if (insightEl) {
      const topType = labels[0];
      const topCnt  = counts[topType] || 0;
      const pfpCnt  = counts['Player-for-Player'] || 0;
      const pfpPct  = Math.round(pfpCnt / total * 100);
      insightEl.innerHTML = topType
        ? `<strong>${topType}</strong> is the most common trade structure
           (${topCnt} of ${total} trades, ${Math.round(topCnt/total*100)}%).
           ${pfpCnt && topType !== 'Player-for-Player' ? `Player-for-Player accounts for <strong>${pfpPct}%</strong>. ` : ''}
           Click any row or donut segment to filter the trade list to that type.`
        : '';
    }
  }

  // ── Update all charts ─────────────────────────────────────────────
  function updateAllCharts() {
    renderTradesPerOwner();
    renderTradeMatrix();
    renderTradeNetwork();
    renderTimeline();
    renderHeatmap();
    renderMultiTeam();
    renderVolumeBySeasonOwner();
    renderTradeTypeBreakdown();
  }

  // ── Clear owner filter button ────────────────────────────────────
  document.getElementById('clear-owner-filter')?.addEventListener('click', () => {
    activeOwnerFilter = null;
    applyFilters();
  });

  // ── Clear type filter button (FEAT-02) ────────────────────────────
  document.getElementById('clear-type-filter')?.addEventListener('click', () => {
    activeTypeFilter = null;
    applyFilters();
    renderTradeTypeBreakdown();
  });

  // ── Owner Compare ─────────────────────────────────────────────────
  (function initCompare() {
    const toggleBtn  = document.getElementById('compare-toggle-btn');
    const panel      = document.getElementById('compare-panel');
    const closeBtn   = document.getElementById('compare-close-btn');
    const selA       = document.getElementById('compare-owner-a');
    const selB       = document.getElementById('compare-owner-b');
    const runBtn     = document.getElementById('compare-run-btn');
    const summary    = document.getElementById('compare-summary');
    if (!toggleBtn || !panel) return;

    // Populate dropdowns with all owners from data
    const allOwners = [...new Set(allTradeEvents.flatMap(ev => ev.parties || []))].sort();
    const optHtml = allOwners.map(o => `<option value="${o}">${o}</option>`).join('');
    selA.innerHTML = `<option value="">Select Owner A…</option>${optHtml}`;
    selB.innerHTML = `<option value="">Select Owner B…</option>${optHtml}`;

    toggleBtn.addEventListener('click', () => {
      const open = panel.style.display !== 'none';
      panel.style.display = open ? 'none' : 'block';
      toggleBtn.classList.toggle('active', !open);
    });
    closeBtn.addEventListener('click', () => {
      panel.style.display = 'none';
      toggleBtn.classList.remove('active');
    });

    function updateRunBtn() {
      const a = selA.value, b = selB.value;
      runBtn.disabled = !a || !b || a === b;
      if (a && b && a !== b) {
        const cnt = allTradeEvents.filter(ev =>
          (ev.parties||[]).includes(a) && (ev.parties||[]).includes(b)
        ).length;
        summary.textContent = cnt > 0
          ? `${cnt} trade${cnt!==1?'s':''} between these two owners across all seasons.`
          : 'No trades found between these two owners.';
      } else {
        summary.textContent = '';
      }
    }
    selA.addEventListener('change', updateRunBtn);
    selB.addEventListener('change', updateRunBtn);

    runBtn.addEventListener('click', () => {
      const a = selA.value, b = selB.value;
      if (!a || !b || a === b) return;
      renderCompareModal(a, b);
    });
  })();

  function renderCompareModal(ownerA, ownerB) {
    const trades = allTradeEvents.filter(ev =>
      (ev.parties||[]).includes(ownerA) && (ev.parties||[]).includes(ownerB)
    ).sort((a,b)=>(b.date_iso||'').localeCompare(a.date_iso||''));

    const cnt = trades.length;
    const byYear = {};
    trades.forEach(ev => {
      const y = String(ev.year||'?');
      byYear[y] = (byYear[y]||0)+1;
    });
    const yearBreakdown = Object.entries(byYear).sort()
      .map(([y,c])=>`<span class="badge" style="background:var(--bg-primary);color:var(--text-secondary);border:1px solid var(--border)">${y}: ${c}</span>`)
      .join(' ');

    const tradeItems = trades.length ? trades.map(ev => `
      <li class="trade-event">
        <div class="trade-event-date">${ev.date||'—'}</div>
        <div class="trade-event-body">
          <div class="trade-parties">${(ev.parties||[]).join(' ↔ ')}</div>
          <div class="trade-details-raw">${ev.details_raw||'No details available.'}</div>
        </div>
      </li>`).join('')
      : '<li style="color:var(--text-muted);padding:16px 0;text-align:center">No trades found between these owners.</li>';

    D.showModal(`
      <div class="modal-header">
        <h3>
          <span style="display:inline-flex;align-items:center;gap:6px">
            <span style="width:12px;height:12px;border-radius:50%;background:${D.ownerColor(ownerA)};display:inline-block"></span>
            ${ownerA}
          </span>
          <span style="color:var(--text-muted);margin:0 8px">↔</span>
          <span style="display:inline-flex;align-items:center;gap:6px">
            <span style="width:12px;height:12px;border-radius:50%;background:${D.ownerColor(ownerB)};display:inline-block"></span>
            ${ownerB}
          </span>
        </h3>
        <button class="modal-close" onclick="DOTP.hideModal()">×</button>
      </div>
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:16px">
        <span class="badge badge-3team" style="font-size:0.82rem;padding:4px 12px">${cnt} trade${cnt!==1?'s':''} all-time</span>
        ${yearBreakdown}
      </div>
      <ul class="trade-timeline">${tradeItems}</ul>
    `);
  }

  // ── Initial render ────────────────────────────────────────────────
  applyFilters();

  // Re-render on theme change (chart defaults update, need re-draw)
  document.addEventListener('themechange', () => {
    D.applyChartDefaults();
    renderTradesPerOwner();
    renderTimeline();
    renderMultiTeam();
    renderVolumeBySeasonOwner();
    renderTradeMatrix();
    renderTradeNetwork();
    renderHeatmap();
    renderTradeTypeBreakdown();
  });

})();
