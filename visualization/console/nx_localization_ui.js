let nxPickStage=0,nxChosen=null;
const nxResult=document.getElementById('nxPoseResult');
let nxNoticeUntil=0,nxRequestPending=false;
function nxNotice(message,seconds=10){
  nxResult.textContent=message;
  nxNoticeUntil=Date.now()+seconds*1000;
}
document.getElementById('nxPosePick').onclick=()=>{
  nxPickStage=1;nxChosen=null;picking=false;
  nxNotice('请在地图上点击小车当前实际位置，然后再点车头朝向。',30);
};
canvas.addEventListener('click',ev=>{
  if(!nxPickStage||!state?.map?.width)return;
  ev.stopImmediatePropagation();
  const r=canvas.getBoundingClientRect(),p=worldPoint(ev.clientX-r.left,ev.clientY-r.top);
  if(nxPickStage===1){nxChosen=p;nxPickStage=2;
    document.getElementById('nxPoseX').value=p[0].toFixed(3);
    document.getElementById('nxPoseY').value=p[1].toFixed(3);
    nxNotice('位置已选；再点击车头所朝方向。',30);
  }else{
    if(Math.hypot(p[0]-nxChosen[0],p[1]-nxChosen[1])<.05)return;
    document.getElementById('nxPoseYaw').value=(Math.atan2(p[1]-nxChosen[1],p[0]-nxChosen[0])*180/Math.PI).toFixed(1);
    nxPickStage=0;nxNotice('位置和朝向已选，点击“应用粗定位”。',30);
  }
  draw();
},true);
async function nxLocate(mode){
  const body={};
  if(mode==='manual'){
    for(const [key,id] of [['x','nxPoseX'],['y','nxPoseY'],['yaw','nxPoseYaw']]){
      const value=document.getElementById(id).value;
      if(!value.trim()||!Number.isFinite(Number(value))){nxNotice('请填写位置和朝向，或在地图上选两次。');return;}
      body[key]=Number(value);
    }
    body.yaw*=Math.PI/180;
  }
  for(const id of ['nxPoseApply','nxPoseAuto'])document.getElementById(id).disabled=true;
  nxRequestPending=true;
  nxNotice(mode==='manual'?'正在提交粗定位…':'正在启动自动重定位…');
  try{
    const r=await fetch('/api/localization/'+mode,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const d=await r.json();if(!r.ok)throw Error(d.error);
    nxNotice(d.message||'定位请求已提交；正在读取状态。');
  }catch(e){nxNotice('定位未启动：'+e.message,20);}
  finally{
    nxRequestPending=false;
    for(const id of ['nxPoseApply','nxPoseAuto'])document.getElementById(id).disabled=false;
  }
}
document.getElementById('nxPoseApply').onclick=()=>nxLocate('manual');
document.getElementById('nxPoseAuto').onclick=()=>nxLocate('auto');
let nxScanMapStatus=null;
async function nxLocationStatus(){
  try{
    const d=await(await fetch('/api/localization/status')).json();
    nxScanMapStatus=d.scan_map||null;
    if(d.running){
      nxNoticeUntil=0;
      nxResult.textContent=d.message;
    }else if(!nxRequestPending&&!nxPickStage&&Date.now()>=nxNoticeUntil&&nxResult.textContent!==d.message){
      nxResult.textContent=d.message;
    }
    document.getElementById('nxPoseAssessment').textContent=d.assessment&&d.assessment!==d.message?d.assessment:'';
    for(const id of ['nxPoseApply','nxPoseAuto'])document.getElementById(id).disabled=d.running;
  }catch(e){if(!nxRequestPending&&Date.now()>=nxNoticeUntil)nxResult.textContent='定位状态连接失败';}
}
const nxOriginalDraw=draw;
draw=function(){
  nxOriginalDraw();
  if(!state?.map?.width)return;
  if(nxChosen){const q=pixel(...nxChosen);ctx.strokeStyle='#ffbd4a';ctx.lineWidth=3;ctx.beginPath();ctx.arc(...q,9,0,Math.PI*2);ctx.stroke();}
  const r=state.pose;
  if(!r||state.age.pose>3||!document.getElementById('nxRadarLines').checked||state.age.scan>1||state.age.scan<0)return;
  const origin=pixel(r.x,r.y),c=Math.cos(r.yaw),s=Math.sin(r.yaw);
  ctx.strokeStyle='rgba(45,212,191,0.20)';ctx.lineWidth=1;ctx.beginPath();
  for(const p of state.scan||[]){const q=pixel(r.x+c*p[0]-s*p[1],r.y+s*p[0]+c*p[1]);ctx.moveTo(...origin);ctx.lineTo(...q);}ctx.stroke();
};
document.getElementById('nxRadarLines').onchange=draw;
function nxDrawRadar(){
  if(!state)return;
  const c=document.getElementById('nxLocalRadar'),g=c.getContext('2d'),w=c.width,h=c.height,k=22;
  g.clearRect(0,0,w,h);g.strokeStyle='#334455';g.lineWidth=1;
  for(const radius of [1,2,3,4]){g.beginPath();g.arc(w/2,h/2,radius*k,0,Math.PI*2);g.stroke();}
  const fresh=state.age.scan>=0&&state.age.scan<1;
  if(fresh){g.strokeStyle='rgba(45,212,191,.25)';g.fillStyle='#2dd4bf';
    for(const p of state.scan||[]){const x=w/2-p[1]*k,y=h/2-p[0]*k;g.beginPath();g.moveTo(w/2,h/2);g.lineTo(x,y);g.stroke();g.fillRect(x-1,y-1,2,2);}}
  g.fillStyle='#a898ff';g.beginPath();g.moveTo(w/2,h/2-10);g.lineTo(w/2-6,h/2+6);g.lineTo(w/2+6,h/2+6);g.closePath();g.fill();
  document.getElementById('nxRadarState').textContent=fresh?`雷达正常：${(state.scan||[]).length} 点，${state.age.scan.toFixed(1)} 秒前；圆环间隔 1 米`:'雷达数据过期，检查传感器';
  const poseHint=state.pose&&state.age.pose<3?'已有地图位置估计。':'尚无有效地图定位：局部雷达仍可查看，请先手动粗定位或自动重定位。';
  let matchHint='雷达地图匹配：等待数据。';
  if(nxScanMapStatus){const m=nxScanMapStatus;
    if(m.valid)matchHint=`雷达地图匹配通过：中位误差 ${(m.median_m*100).toFixed(0)} cm，15 cm 内 ${(m.within_15cm*100).toFixed(0)}%。`;
    else{const why=m.reason==='heading_ambiguous'?'房间形状近似对称，多个车头方向都匹配，朝向不确定':m.reason==='heading_hypothesis_conflict'?'当前车头方向与其他方向的地图匹配结果冲突':(m.reason||'状态未知');
      const metric=m.median_m!=null?`，中位误差 ${(m.median_m*100).toFixed(0)} cm，15 cm 内 ${((m.within_15cm||0)*100).toFixed(0)}%`:'';
      const count=m.heading_candidate_count!=null?`；可行方向 ${m.heading_candidate_count} 个${m.best_heading_deg!=null?`，最佳候选 ${Number(m.best_heading_deg).toFixed(0)}°`:''}`:'';
      matchHint=`雷达地图匹配未通过：${why}${metric}${count}。请用地图点选实际车头方向或到非对称地标处再定位；导航和物体记忆暂不可用。`;}}
  document.getElementById('nxPoseHint').textContent=poseHint+' '+matchHint;
}
setInterval(nxDrawRadar,300);setInterval(nxLocationStatus,1000);nxLocationStatus();
