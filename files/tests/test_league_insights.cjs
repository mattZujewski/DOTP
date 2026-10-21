const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {draftCohort,tradeRoutes} = require('../../docs/js/league_insights.js');
const pick = (owner,id,status='selected') => ({owner_name:owner,player_id:id,pick_status:status});
const cohort=draftCohort([pick('A','p1'),pick('A','p2'),pick('A',null,'unfilled'),pick('B','p3'),pick('B','p4')],
 {p1:{owner_real_name:'B'},p3:{owner_real_name:'B'}},['A','B','C']);
assert.equal(cohort.find(r=>r.owner==='A').rate,.5,'Exclude unfilled slots from selections');
assert.equal(cohort.find(r=>r.owner==='A').retained,0,'Rostered elsewhere is not with drafter');
assert.equal(cohort.find(r=>r.owner==='B').retained,1);
assert.equal(cohort.find(r=>r.owner==='A').rank,cohort.find(r=>r.owner==='B').rank,'Equal rates share rank');
assert.equal(cohort.find(r=>r.owner==='C').grade,'—','No selections must not get an F or a zero rate');
const threeWay={event_id:'three',parties:['A','B','C'],assets_by_party:{A:{sent:['One'],received:['Three']},B:{sent:['Two'],received:['One']},C:{sent:['Three'],received:['Two']}}};
const routes=tradeRoutes([threeWay], 'A');
assert.equal(routes.find(r=>r.owner==='B').incoming,0,'Do not assign every player in a three-way deal to every partner');
assert.equal(routes.find(r=>r.owner==='B').outgoing,1);
assert.equal(routes.find(r=>r.owner==='C').incoming,1);
assert.equal(routes.find(r=>r.owner==='C').outgoing,0);
const read=name=>JSON.parse(fs.readFileSync(path.join(__dirname,'../../docs/data',name+'.json')));
const drafts=read('draft_results'),rosters=read('rosters'),teams=read('teams'),trades=read('trades');
const rosterMap=Object.fromEntries(rosters.players.map(p=>[p.player_id,p]));
for(const season of drafts.seasons){
 const rows=draftCohort(season.picks,rosterMap,teams.owners.map(o=>o.real_name));
 assert.equal(rows.reduce((n,r)=>n+r.selected,0),season.picks.filter(p=>p.pick_status==='selected').length);
 assert.equal(rows.reduce((n,r)=>n+r.slots,0),season.picks.length);
 for(const row of rows){assert.ok(row.retained<=row.rostered);assert.ok(row.rostered<=row.selected);}
}
// Every named player transfer must have one explicit sending/receiving party.
let incoming=0,outgoing=0;
for(const o of teams.owners)for(const r of tradeRoutes(trades.trade_events,o.real_name)){incoming+=r.incoming;outgoing+=r.outgoing;}
assert.equal(incoming,outgoing);
console.log('Draft survival, tied grades, missing cohorts, multi-party routes, and all exported records passed.');
const {draftHistory}=require('../../docs/js/league_insights.js');
const history=draftHistory([{year:2025,picks:[pick('A','x'),pick('B','y')]},{year:2026,picks:[pick('A','z')]}],{x:{owner_real_name:'A'},z:{owner_real_name:'A'}},['A','B','C']);
assert.equal(history[0].owner,'A');
assert.equal(history[0].average,1);
assert.equal(history.find(r=>r.owner==='B').classes.length,1,'Do not penalize years with no selections');
assert.ok(!history.some(r=>r.owner==='C'),'Unrated owners must not enter historical rankings');
console.log('Historical draft ranking and missing-year checks passed.');
