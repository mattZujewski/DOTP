/**
 * player_charts.js — All 6 Player History charts
 * Loaded by player_history.html. Requires Chart.js, D3, and charts.js (DOTP).
 */

(async function () {
  'use strict';
  const D = window.DOTP;

  // ── Load data ────────────────────────────────────────────────────
  let journeysData, teamsData;
  try {
    [journeysData, teamsData] = await Promise.all([
      D.loadJSON('data/journeys.json'),
      D.loadJSON('data/teams.json'),
    ]);
  } catch (e) {
    document.body.innerHTML += `<div class="error-msg" style="margin:40px auto;max-width:600px">
      ⚠ Failed to load data.<br>${e.message}</div>`;
    return;
  }

  window.dotpNav?.setNavDate(teamsData.meta.generated_at);

  const stints       = journeysData.stints;
  const playerIndex  = journeysData.player_index;
  const mostTraveled = journeysData.most_traveled_players;
  const throughput   = journeysData.owner_throughput;
  const tenureStats  = journeysData.tenure_stats;

  // ── Chart 1: Most Traveled Players (top 20) ──────────────────────
  (function renderMostTraveled() {
    const ctx = document.getElementById('chart-most-traveled');
    if (!ctx) return;

    const top20 = mostTraveled.slice(0, 20);
    const labels         = top20.map(p => p.player_name);
    const distinctOwners = top20.map(p => p.distinct_owners ?? p.distinct_teams ?? 0);
    const totalStints    = top20.map(p => p.total_stints);

    new Chart(ctx, {
      type: 'bar',
      data: {
        labels,
        datasets: [
          {
            label: 'Distinct Owners',
            data: distinctOwners,
            backgroundColor: 'rgba(224,123,57,0.75)',
            borderRadius: 4,
          },
          {
            label: 'Total Stints',
            data: totalStints,
            backgroundColor: 'rgba(26,107,60,0.5)',
            borderRadius: 4,
          },
        ],
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: true },
          tooltip: {
            callbacks: {
              afterBody: (items) => {
                const idx = items[0].dataIndex;
                const p = top20[idx];
                return p.current_owner ? `Current: ${p.current_owner}` : 'No longer rostered';
              },
            },
          },
        },
        scales: {
          x: { beginAtZero: true, ticks: { precision: 0 } },
          y: { grid: { display: false } },
        },
        onClick: (_, els) => {
          if (!els.length) return;
          const player = top20[els[0].index];
          showPlayerJourneyModal(player.player_id, player.player_name);
        },
      },
    });

    const top = top20[0];
    document.getElementById('insight-most-traveled').innerHTML = top
      ? `<strong>${top.player_name}</strong> has been owned by the most owners — <strong>${top.distinct_owners ?? top.distinct_teams} distinct owners</strong>
         with <strong>${top.total_stints} total roster stints</strong>. Click any bar to see their full journey.`
      : '';
  })();

  // ── Chart 2: Owner Player Throughput ─────────────────────────────
  (function renderThroughput() {
    const ctx = document.getElementById('chart-throughput');
    if (!ctx) return;

    const entries = Object.entries(throughput)
      .filter(([o]) => o !== 'Unknown')
      .sort((a,b) => b[1].unique_players - a[1].unique_players);
    const labels  = entries.map(([o]) => o);
    const values  = entries.map(([,v]) => v.unique_players);
    const colors  = labels.map(o => D.ownerColor(o));

    new Chart(ctx, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          data: values,
          backgroundColor: colors.map(c => c + 'bb'),
          borderColor: colors,
          borderWidth: 1.5,
          borderRadius: 4,
        }],
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => ` ${ctx.parsed.x} unique players`,
              afterBody: (items) => {
                const o = labels[items[0].dataIndex];
                const d = throughput[o];
                if (!d) return '';
                const ab = d.acquisition_breakdown || {};
                return Object.entries(ab).map(([k,v])=>`${k}: ${v}`).join(' | ');
              },
            },
          },
        },
        scales: {
          x: { beginAtZero: true, ticks: { precision: 0 }, title: { display: true, text: 'Unique Players Ever Rostered' } },
          y: { grid: { display: false } },
        },
        onClick: (_, els) => {
          if (!els.length) return;
          const owner = labels[els[0].index];
          window.location.href = `team.html?owner=${encodeURIComponent(owner)}`;
        },
      },
    });

    const top = entries[0];
    document.getElementById('insight-throughput').innerHTML = top
      ? `<strong>${top[0]}</strong> has rostered the most unique players —
         <strong>${top[1].unique_players}</strong> across all seasons. Click any bar to go to their Team View.`
      : '';
  })();

  // ── Chart 3: Ownership Flow Network (D3 directed) ────────────────
  (function renderFlowNetwork() {
    const container = document.getElementById('chart-flow-d3');
    if (!container) return;
    container.innerHTML = '';

    // Build directed edges from stints (player → owner transitions)
    const edgeCounts = {};
    const playerStints = {};

    stints.forEach(s => {
      const pid = s.player_id;
      if (!playerStints[pid]) playerStints[pid] = [];
      playerStints[pid].push(s);
    });

    Object.values(playerStints).forEach(pstints => {
      const sorted = [...pstints].sort((a,b)=> (a.start_date||'').localeCompare(b.start_date||''));
      for (let i = 0; i < sorted.length - 1; i++) {
        const src = sorted[i].owner_real_name;
        const dst = sorted[i+1].owner_real_name;
        if (!src || !dst || src === dst || src === 'Unknown' || dst === 'Unknown') continue;
        const key = `${src}|||${dst}`;
        edgeCounts[key] = (edgeCounts[key]||0)+1;
      }
    });

    const MIN_WEIGHT = 3;
    const nodes = new Set();
    const links = [];

    Object.entries(edgeCounts).forEach(([key, w]) => {
      if (w < MIN_WEIGHT) return;
      const [s,t] = key.split('|||');
      nodes.add(s); nodes.add(t);
      links.push({ source: s, target: t, value: w });
    });

    const nodeArr = [...nodes].map(id => ({ id }));
    if (nodeArr.length < 2) {
      container.innerHTML = '<p class="text-muted text-center" style="padding:24px">Not enough flow data.</p>';
      return;
    }

    const nodeTotals = {};
    links.forEach(l => {
      nodeTotals[l.source] = (nodeTotals[l.source]||0)+l.value;
      nodeTotals[l.target] = (nodeTotals[l.target]||0)+l.value;
    });
    const maxNode = Math.max(...Object.values(nodeTotals), 1);

    const W = container.clientWidth || 800;
    const H = Math.min(520, W * 0.7);

    const svg = d3.select(container).append('svg')
      .attr('width','100%').attr('viewBox',`0 0 ${W} ${H}`);

    // Arrow marker
    svg.append('defs').append('marker')
      .attr('id','arrow').attr('viewBox','0 -5 10 10')
      .attr('refX',22).attr('refY',0)
      .attr('markerWidth',6).attr('markerHeight',6)
      .attr('orient','auto')
      .append('path').attr('d','M0,-5L10,0L0,5').attr('fill','var(--text-muted)');

    const sim = d3.forceSimulation(nodeArr)
      .force('link', d3.forceLink(links).id(d=>d.id).strength(0.35).distance(d=>200-d.value*3))
      .force('charge', d3.forceManyBody().strength(-350))
      .force('center', d3.forceCenter(W/2, H/2))
      .force('collision', d3.forceCollide(42));

    const tip = D.makeD3Tooltip();

    const link = svg.append('g').selectAll('path').data(links).enter().append('path')
      .attr('fill','none')
      .attr('stroke','var(--text-muted)')
      .attr('stroke-opacity', 0.55)
      .attr('stroke-width', d=>Math.max(1, d.value*0.4))
      .attr('marker-end','url(#arrow)');

    const node = svg.append('g').selectAll('circle').data(nodeArr).enter().append('circle')
      .attr('r', d => 14 + (nodeTotals[d.id]||0)/maxNode*24)
      .attr('fill', d => D.ownerColor(d.id))
      .attr('fill-opacity', 0.82)
      .attr('stroke','var(--bg-card)').attr('stroke-width',2)
      .call(d3.drag()
        .on('start',(e,d)=>{if(!e.active)sim.alphaTarget(0.3).restart();d.fx=d.x;d.fy=d.y;})
        .on('drag', (e,d)=>{d.fx=e.x;d.fy=e.y;})
        .on('end',  (e,d)=>{if(!e.active)sim.alphaTarget(0);/* keep fx/fy to pin node */})
      )
      .on('mouseover',(e,d)=>{
        const incoming = links.filter(l=>l.target===d.id||l.target.id===d.id).map(l=>`← ${l.source.id||l.source}: ${l.value}`);
        const outgoing = links.filter(l=>l.source===d.id||l.source.id===d.id).map(l=>`→ ${l.target.id||l.target}: ${l.value}`);
        tip.show(`<strong>${d.id}</strong><br>${[...outgoing,...incoming].join('<br>')}`, e);
      })
      .on('mousemove',tip.move).on('mouseout',tip.hide);

    const label = svg.append('g').selectAll('text').data(nodeArr).enter().append('text')
      .attr('text-anchor','middle').attr('font-size',9).attr('font-weight','600')
      .attr('fill','var(--text-primary)').attr('pointer-events','none')
      .text(d=>d.id.split(' ').pop());

    const edgeLabel = svg.append('g').selectAll('text').data(links.filter(l=>l.value>=6)).enter().append('text')
      .attr('text-anchor','middle').attr('font-size',8).attr('fill','var(--text-muted)').text(d=>d.value);

    sim.on('tick',()=>{
      link.attr('d', d => {
        const dx = d.target.x-d.source.x, dy = d.target.y-d.source.y;
        const dr = Math.sqrt(dx*dx+dy*dy)*1.5;
        return `M${d.source.x},${d.source.y}A${dr},${dr} 0 0,1 ${d.target.x},${d.target.y}`;
      });
      node.attr('cx',d=>Math.max(24,Math.min(W-24,d.x))).attr('cy',d=>Math.max(24,Math.min(H-24,d.y)));
      label.attr('x',d=>d.x).attr('y',d=>d.y+4);
      edgeLabel.attr('x',d=>(d.source.x+d.target.x)/2).attr('y',d=>(d.source.y+d.target.y)/2);
    });

    document.getElementById('insight-flow').innerHTML =
      `Directed arrows show how players move between owners. Arrow thickness = player count. Drag nodes to rearrange. Only flows with 3+ players shown.`;
  })();

  // ── Chart 4: Acquisition Breakdown ───────────────────────────────
  (function renderAcqBreakdown() {
    const ctx = document.getElementById('chart-acq-breakdown');
    if (!ctx) return;

    const ownerFilter = document.getElementById('acq-owner-filter');
    const acqTypes = ['CLAIMED','TRADED','DRAFTED'];  // KEPT excluded — not a real acquisition
    let acqChart = null;

    function buildChart(filterOwner) {
      // Get all owners or just one — always exclude the 'Unknown' bucket
      let entries = Object.entries(throughput).filter(([o]) => o !== 'Unknown');
      if (filterOwner) {
        entries = entries.filter(([o]) => o === filterOwner);
      }
      if (!entries.length) return;

      // Sort by total acquisitions ascending (so largest bar is at top)
      entries.sort((a,b) => {
        const ta = Object.values(a[1].acquisition_breakdown||{}).reduce((s,v)=>s+v,0);
        const tb = Object.values(b[1].acquisition_breakdown||{}).reduce((s,v)=>s+v,0);
        return ta - tb;
      });

      const labels = entries.map(([o]) => o);

      if (acqChart) { acqChart.destroy(); acqChart = null; }

      acqChart = new Chart(ctx, {
        type: 'bar',
        data: {
          labels,
          datasets: acqTypes.map(type => ({
            label: type,
            data: labels.map(o => throughput[o]?.acquisition_breakdown?.[type] || 0),
            backgroundColor: D.ACQ_COLORS[type] + 'cc',
            borderRadius: 3,
          })),
        },
        options: {
          indexAxis: 'y',
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: true } },
          scales: {
            x: { stacked: true, beginAtZero: true, title: { display: true, text: 'Roster Acquisitions' } },
            y: { stacked: true, grid: { display: false }, ticks: { font: { size: 11 } } },
          },
        },
      });

      // Insight from highest-total owner
      const top = entries[entries.length - 1];
      const ab = throughput[top[0]]?.acquisition_breakdown || {};
      const domAcq = acqTypes.reduce((best, a) => (ab[a]||0) > (ab[best]||0) ? a : best, acqTypes[0]);
      document.getElementById('insight-acq').innerHTML =
        `<strong>${top[0]}</strong> has the most acquisitions overall.
         Their primary method is <strong>${domAcq}</strong> (${ab[domAcq]||0}) —
         revealing their roster-building philosophy.`;
    }

    // Populate dropdown
    if (ownerFilter) {
      ownerFilter.innerHTML = `<option value="">All Owners</option>` +
        Object.keys(throughput).filter(o => o !== 'Unknown').sort()
          .map(o => `<option value="${o}">${o}</option>`).join('');
      ownerFilter.addEventListener('change', () => buildChart(ownerFilter.value || null));
    }

    buildChart(null);  // null = all owners
  })();

  // ── Chart 5: Roster Composition — Donut Grid ─────────────────────
  (function renderRosterComposition() {
    const container = document.getElementById('chart-roster-composition');
    if (!container) return;
    container.innerHTML = '';

    // Load rosters.json for current status breakdowns
    D.loadJSON('data/rosters.json').then(rostersData => {
      const statusByTeam = rostersData.status_breakdown_by_team;
      const teams = Object.keys(statusByTeam).sort();
      const statuses = ['ACTIVE','INJURED_RESERVE','MINORS','RESERVE'];

      const grid = document.createElement('div');
      grid.style.cssText = 'display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:16px;';
      container.appendChild(grid);

      teams.forEach(team => {
        const data = statusByTeam[team] || {};
        const cell = document.createElement('div');
        cell.style.cssText = 'text-align:center;cursor:pointer;';

        const canvas = document.createElement('canvas');
        canvas.width = 140; canvas.height = 140;
        cell.appendChild(canvas);

        const title = document.createElement('div');
        title.style.cssText = 'font-size:0.75rem;font-weight:600;margin-top:6px;color:var(--text-secondary);';
        title.textContent = team.length > 20 ? team.slice(0,18)+'…' : team;
        cell.appendChild(title);
        grid.appendChild(cell);

        const labels = statuses.filter(s => (data[s]||0) > 0);
        const values = labels.map(s => data[s]||0);
        const colors = labels.map(s => D.STATUS_COLORS[s] || '#888');

        new Chart(canvas, {
          type: 'doughnut',
          data: { labels, datasets: [{ data: values, backgroundColor: colors, borderWidth: 1.5 }] },
          options: {
            responsive: false,
            plugins: {
              legend: { display: false },
              tooltip: { callbacks: { label: c => ` ${c.label}: ${c.parsed}` } },
            },
            onClick: () => { window.location.href = `team.html?team=${encodeURIComponent(team)}`; },
          },
        });
      });

      // Shared legend
      const legend = document.createElement('div');
      legend.style.cssText = 'display:flex;flex-wrap:wrap;gap:14px;justify-content:center;margin-top:16px;';
      statuses.forEach(s => {
        legend.innerHTML += `<span style="display:flex;align-items:center;gap:5px;font-size:0.78rem">
          <span style="width:10px;height:10px;border-radius:50%;background:${D.STATUS_COLORS[s]};display:inline-block"></span>
          ${s === 'INJURED_RESERVE' ? 'IR' : s}
        </span>`;
      });
      container.appendChild(legend);

      document.getElementById('insight-roster-comp').innerHTML =
        `Each donut shows the current roster split across ACTIVE, MINORS, IR, and RESERVE slots. Click a donut to jump to that team's view.`;
    });
  })();

  // ── Chart 6: Tenure Distribution ─────────────────────────────────
  (function renderTenure() {
    const ctxHist = document.getElementById('chart-tenure-hist');
    const ctxBox  = document.getElementById('chart-tenure-box');

    // ── Histogram with median line as a second dataset ────────────
    if (ctxHist && tenureStats.histogram?.length) {
      const hist = tenureStats.histogram.filter(b => b.count > 0);
      const medianDays = tenureStats.median_days || 0;

      // Find which bucket the median falls in (for vertical reference line)
      // We use a scatter + bar combo: bar = histogram, scatter point = median marker
      const labels = hist.map(b => `${b.bucket_start}d`);
      const counts = hist.map(b => b.count);

      // Find label index closest to median
      const medIdx = hist.reduce((best, b, i) =>
        Math.abs(b.bucket_start - medianDays) < Math.abs(hist[best].bucket_start - medianDays) ? i : best, 0);

      // Median line: a single-point dataset at full height
      const maxCount = Math.max(...counts, 1);
      const medianLineData = labels.map((_, i) => i === medIdx ? maxCount * 1.05 : null);

      new Chart(ctxHist, {
        type: 'bar',
        data: {
          labels,
          datasets: [
            {
              type: 'bar',
              label: 'Stints',
              data: counts,
              backgroundColor: 'rgba(69,123,157,0.7)',
              borderRadius: 2,
              order: 2,
            },
            {
              type: 'bar',
              label: `Median (${Math.round(medianDays)}d)`,
              data: medianLineData,
              backgroundColor: 'rgba(230,57,70,0.7)',
              borderColor: '#e63946',
              borderWidth: 1,
              barThickness: 3,
              order: 1,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: true },
            tooltip: {
              filter: item => item.datasetIndex === 0,  // only show on histogram bars
              callbacks: { label: ctx => ` ${ctx.parsed.y} stints` },
            },
          },
          scales: {
            x: {
              title: { display: true, text: 'Days on Roster' },
              ticks: { maxTicksLimit: 12, maxRotation: 35 },
            },
            y: { beginAtZero: true, title: { display: true, text: 'Number of Stints' } },
          },
        },
      });
    }

    // ── Tenure by acquisition type — grouped bar (median + mean) ─────
    if (ctxBox && tenureStats.by_acquisition_type) {
      const acqTypes = ['DRAFTED','TRADED','CLAIMED']   // KEPT excluded — not a real acquisition
        .filter(t => tenureStats.by_acquisition_type[t]);
      const byAcq = tenureStats.by_acquisition_type;

      new Chart(ctxBox, {
        type: 'bar',
        data: {
          labels: acqTypes,
          datasets: [
            {
              label: 'Median Days',
              data: acqTypes.map(t => Math.round(byAcq[t]?.median || 0)),
              backgroundColor: acqTypes.map(t => D.ACQ_COLORS[t] + 'cc'),
              borderColor:     acqTypes.map(t => D.ACQ_COLORS[t]),
              borderWidth: 2,
              borderRadius: 6,
              order: 1,
            },
            {
              label: 'Q1 (25th pct)',
              data: acqTypes.map(t => Math.round(byAcq[t]?.q1 || 0)),
              backgroundColor: acqTypes.map(t => D.ACQ_COLORS[t] + '44'),
              borderColor:     acqTypes.map(t => D.ACQ_COLORS[t]),
              borderWidth: 1,
              borderRadius: 4,
              order: 2,
            },
            {
              label: 'Q3 (75th pct)',
              data: acqTypes.map(t => Math.round(byAcq[t]?.q3 || 0)),
              backgroundColor: acqTypes.map(t => D.ACQ_COLORS[t] + '33'),
              borderColor:     acqTypes.map(t => D.ACQ_COLORS[t] + '88'),
              borderWidth: 1,
              borderDash: [4, 2],
              borderRadius: 4,
              order: 3,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: true },
            tooltip: {
              callbacks: {
                title: ([ctx]) => `${ctx.label} — Tenure Stats`,
                afterBody: ([ctx]) => {
                  const b = byAcq[ctx.label];
                  if (!b) return '';
                  return `Range: ${Math.round(b.min)}d – ${Math.round(b.max)}d`;
                },
              },
            },
          },
          scales: {
            x: { grid: { display: false } },
            y: { beginAtZero: true, title: { display: true, text: 'Days on Roster' } },
          },
        },
      });
    }

    const medDays = Math.round(tenureStats.median_days || 0);
    const byAcq   = tenureStats.by_acquisition_type || {};
    const acqOrder = ['DRAFTED','TRADED','CLAIMED'];  // KEPT excluded — not a real acquisition
    const longest  = acqOrder.filter(t => byAcq[t]).sort((a,b) => (byAcq[b]?.median||0)-(byAcq[a]?.median||0))[0];
    document.getElementById('insight-tenure').innerHTML =
      `Median ownership stint: <strong>${medDays} days</strong>.
       ${longest ? `Players acquired via <strong>${longest}</strong> tend to stay longest
       (median ${Math.round(byAcq[longest]?.median||0)}d) —
       reflecting how differently owners value each acquisition type.` : ''}`;
  })();

  // ── Player Journey Modal ──────────────────────────────────────────
  function showPlayerJourneyModal(playerId, playerName) {
    const pStints = stints
      .filter(s => s.player_id === playerId)
      .sort((a,b) => (a.start_date||'').localeCompare(b.start_date||''));

    const timelineHtml = pStints.map((s, i) => {
      const isLast = i === pStints.length - 1;
      const isCurrent = s.is_current;
      const tenure = s.tenure_days != null ? `${s.tenure_days}d` : (isCurrent ? 'Current' : '—');
      return `<div class="journey-stop ${isCurrent?'current':''}">
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

    const info = playerIndex[playerId];
    D.showModal(`
      <div class="modal-header">
        <h3>⚾ ${playerName}</h3>
        <button class="modal-close" onclick="DOTP.hideModal()">×</button>
      </div>
      <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:18px">
        <div class="stat-card" style="min-width:90px">
          <span class="stat-label">Owners</span>
          <span class="stat-value" style="font-size:1.3rem">${info?.distinct_owners ?? info?.distinct_teams ?? '—'}</span>
        </div>
        <div class="stat-card" style="min-width:90px">
          <span class="stat-label">Stints</span>
          <span class="stat-value" style="font-size:1.3rem">${info?.total_stints||'—'}</span>
        </div>
        <div class="stat-card" style="min-width:120px">
          <span class="stat-label">Current Owner</span>
          <span class="stat-value" style="font-size:0.95rem;font-weight:700">${info?.current_owner||'Free Agent'}</span>
        </div>
      </div>
      <div class="journey-timeline">${timelineHtml || '<p class="text-muted">No journey data.</p>'}</div>
    `);
  }

  // Expose globally so trade charts can also open it
  window.dotpShowPlayerJourney = showPlayerJourneyModal;

})();
