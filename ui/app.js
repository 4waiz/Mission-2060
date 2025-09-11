const ws = new WebSocket(`ws://${location.host}/ws`);

const speed=0.6, strafe=0.4, yaw=0.8, dur=0.35;
const active = new Set();

function sendVelocity(){
  let vx=(active.has(87)?speed:0)+(active.has(83)?-speed:0);   // W/S
  let vy=(active.has(65)?strafe:0)+(active.has(68)?-strafe:0); // A/D
  let vr=(active.has(81)?yaw:0)+(active.has(69)?-yaw:0);       // Q/E
  if(vx||vy||vr){
    ws.send(JSON.stringify({type:"velocity", vx:vx, vy:vy, yaw:vr, dur:dur}));
  }
}

function glow(k, on){
  document.querySelectorAll(`.key[data-k="${k}"]`).forEach(el=>{
    el.classList.toggle('on', !!on);
  });
}

document.addEventListener('keydown', e=>{
  if(e.repeat) return;
  const k=e.key.toUpperCase().charCodeAt(0);
  if([81,87,69,65,83,68].includes(k)){ active.add(k); glow(k,true); sendVelocity(); }
  // actions
  if(e.key==='1') ws.send(JSON.stringify({type:"action", name:"stand"}));
  if(e.key==='2') ws.send(JSON.stringify({type:"action", name:"sit"}));
  if(e.key.toUpperCase()==='K') ws.send(JSON.stringify({type:"action", name:"estop_cut"}));
  if(e.key.toUpperCase()==='L') ws.send(JSON.stringify({type:"action", name:"estop_allow"}));
  if(e.key.toUpperCase()==='U') ws.send(JSON.stringify({type:"action", name:"undock"}));
  if(e.key.toUpperCase()==='P') ws.send(JSON.stringify({type:"action", name:"dock"}));
  if(e.key.toUpperCase()==='R') ws.send(JSON.stringify({type:"action", name:"release_lease"}));
  if(e.key.toUpperCase()==='T') ws.send(JSON.stringify({type:"action", name:"reacquire_lease"}));
});
document.addEventListener('keyup', e=>{
  const k=e.key.toUpperCase().charCodeAt(0);
  if([81,87,69,65,83,68].includes(k)){ active.delete(k); glow(k,false); }
});

document.querySelectorAll('.key').forEach(k=>{
  k.addEventListener('mousedown', ()=>{ active.add(+k.dataset.k); glow(+k.dataset.k,true); sendVelocity(); });
  k.addEventListener('mouseup',   ()=>{ active.delete(+k.dataset.k); glow(+k.dataset.k,false); });
  k.addEventListener('mouseleave',()=>{ active.delete(+k.dataset.k); glow(+k.dataset.k,false); });
});

document.querySelectorAll('.actions button').forEach(b=>{
  b.addEventListener('click', ()=>ws.send(JSON.stringify({type:"action", name:b.dataset.a})));
});

document.querySelectorAll('.thumb img').forEach(img=>{
  img.addEventListener('click', ()=>{
    document.getElementById('mainFeed').src = `/stream/${img.dataset.source}`;
    ws.send(JSON.stringify({type:"promote", name: img.dataset.source}));
  });
});

// minimal HUD ticker (fps/latency would require extra server metrics; optional)
setInterval(()=>{
  const hud=document.getElementById('overlayMain');
  const t=new Date().toLocaleTimeString();
  hud.innerText=`ONLINE  ::  ${t}`;
}, 500);
