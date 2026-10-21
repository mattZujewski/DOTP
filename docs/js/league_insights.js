/* Pure calculations shared by the story views and offline regression checks. */
(function(root) {
  'use strict';
  function draftCohort(picks, rosterMap, ownerNames) {
    const rows = ownerNames.map(owner => {
      const slots = picks.filter(p => p.owner_name === owner);
      const selected = slots.filter(p => p.pick_status === 'selected');
      const rostered = selected.filter(p => rosterMap[p.player_id]);
      const retained = rostered.filter(p => rosterMap[p.player_id].owner_real_name === owner);
      return {owner, slots: slots.length, selected: selected.length, rostered: rostered.length,
        retained: retained.length, rate: selected.length ? rostered.length / selected.length : null};
    });
    for (const row of rows) {
      row.rank = row.rate == null ? null : 1 + rows.filter(r => r.rate != null && r.rate > row.rate).length;
      row.grade = row.rank == null ? '—' : ['A', 'B', 'C', 'D'][Math.min(3, Math.floor((row.rank - 1) / 3))];
    }
    return rows.sort((a,b) => (a.rank ?? 99) - (b.rank ?? 99) || a.owner.localeCompare(b.owner));
  }
  function tradeRoutes(events, owner) {
    const routes = new Map();
    for (const event of events.filter(t => t.parties.includes(owner))) {
      for (const partner of event.parties.filter(p => p !== owner)) {
        if (!routes.has(partner)) routes.set(partner, {owner: partner, events: [], incoming: 0, outgoing: 0});
        const route = routes.get(partner), own = event.assets_by_party[owner], other = event.assets_by_party[partner];
        route.events.push(event.event_id);
        // Count only explicit sender/recipient matches, including multi-party deals.
        route.incoming += (own?.received || []).filter(n => (other?.sent || []).includes(n)).length;
        route.outgoing += (own?.sent || []).filter(n => (other?.received || []).includes(n)).length;
      }
    }
    return [...routes.values()].sort((a,b) => b.events.length - a.events.length);
  }
  function draftHistory(seasons, rosterMap, ownerNames) {
    const classes=seasons.flatMap(s=>draftCohort(s.picks,rosterMap,ownerNames).filter(r=>r.rank!=null).map(r=>({...r,year:s.year})));
    const rows=ownerNames.map(owner=>{const own=classes.filter(r=>r.owner===owner);return {owner,classes:own,average:own.length?own.reduce((n,r)=>n+r.rank,0)/own.length:Infinity};}).filter(r=>r.classes.length);
    for(const r of rows)r.rank=1+rows.filter(o=>o.average<r.average).length;
    return rows.sort((a,b)=>a.rank-b.rank||a.owner.localeCompare(b.owner));
  }
  const api = {draftCohort, tradeRoutes, draftHistory};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.DOTPInsights = api;
})(typeof window === 'undefined' ? this : window);
