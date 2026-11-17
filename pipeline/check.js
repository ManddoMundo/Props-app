const E=require('./engine.js'); const fs=require('fs'); const O='/home/claude/props/out/';
const D=JSON.parse(fs.readFileSync(O+'data.json'));
let worst=0,n=0;
{ const L=D.NFL, chk=JSON.parse(fs.readFileSync(O+'nfl_check.json'));
  for(const s of L.sides){ const r=E.nflSide(L.model,s,L.players.filter(p=>p.team===s.team),p=>p.active);
    for(const id in r){ const c=chk[id]; if(!c){console.log('missing',id);continue;} for(const k in c){ const jv = k==='f_pass'?r[id].parts.att : k==='f_rush'?r[id].parts.car : r[id].mu[k]; const d=Math.abs(jv-c[k]); worst=Math.max(worst,d/Math.max(1,c[k])); n++; } } }
  console.log('NFL checked',n,'worst rel diff',worst.toExponential(2), 'py rows',Object.keys(chk).length); }
worst=0;n=0;
{ const L=D.NBA, chk=JSON.parse(fs.readFileSync(O+'nba_check.json'));
  for(const s of L.sides){ const r=E.nbaSide(L.model,s,L.players.filter(p=>p.team===s.team),p=>p.active);
    for(const id in r){ const c=chk[s.game+'|'+id]; if(!c){console.log('missing',id);continue;} for(const k in c){ const v=k==='mn'?r[id].parts.mn:r[id].mu[k]; const d=Math.abs(v-c[k]); worst=Math.max(worst,d/Math.max(1,c[k])); n++; } } }
  console.log('NBA checked',n,'worst rel diff',worst.toExponential(2),'py rows',Object.keys(chk).length); }
// distribution sanity vs known values: Poisson-like and NB
const d=E.pmf(24.3,E.nbK(24.3,-2.73,1.69)); const s=E.split(d,24.5); console.log('pmf sum',d.reduce((a,b)=>a+b,0).toFixed(6),'mean',d.reduce((a,b,i)=>a+b*i,0).toFixed(3),s, 'fair',E.fairLine(d), 'ev -110 @55%',E.ev(.55,.45,-110).toFixed(4),'amer .6',E.amer(.6),'dec +150',E.dec(150));
