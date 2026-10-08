(()=>{
const host=document.getElementById('patrolRouteEditor');if(!host)return;
const customer=/^\/(user|product)(\/|$)/.test(location.pathname);
host.innerHTML=`<style>#patrolRouteEditor{padding:22px;margin:18px 0;border:1px solid #728b763d;border-radius:18px;background:var(--card,#172b24);color:inherit}#patrolRouteEditor .route-controls{display:flex;gap:10px;flex-wrap:wrap;align-items:center}#patrolRouteEditor select,#patrolRouteEditor input{padding:10px;border-radius:8px;max-width:100%}#patrolRouteEditor ol{padding:0;list-style:none}#patrolRouteEditor li{display:flex;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid #728b763d}#patrolRouteEditor li span{flex:1}#patrolRouteEditor button{cursor:pointer;padding:9px 13px;border-radius:8px}#patrolRouteEditor button:disabled{opacity:.45;cursor:default}</style>
<h3>规划巡航路线</h3><p>依次选择要经过的位置，巡航一遍并录像。新位置可先在“管理空间”地图中创建、命名并确认。</p>
<div class="route-controls"><select aria-label="可用巡航航点" data-r="select"></select><button data-r="add">＋ 加入路线</button><button data-r="reload">读取已保存路线</button></div>
<ol data-r="list"></ol><p data-r="summary"></p>
<div class="route-controls"><label>每站停留 <input data-r="dwell" type="number" min="0" max="60" step="1" value="4" style="width:75px"> 秒</label><button data-r="save">保存路线</button><button data-r="start">按此路线巡航录像</button><button data-r="stop">停止巡航</button></div>
<p data-r="message" role="status">正在读取路线…</p><small>修改后先保存；启动前核对地图定位。途中失败会停止任务并保存已有录像。</small>`;
if(customer)host.style.background='#fff';
const el=k=>host.querySelector(`[data-r="${k}"]`);let doc=null,ids=[],dirty=false,busy=false;
async function request(path,body){const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),25000);try{const r=await fetch(path,{cache:'no-store',signal:controller.signal,...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});const d=await r.json();if(!r.ok)throw Error(d.error||'请求失败');return d}finally{clearTimeout(timer)}}
const endpoint=customer?'/product/api/patrol-route':'/api/patrol/route';
function render(){el('list').replaceChildren();const names=new Map((doc?.destinations||[]).map(p=>[p.id,p.display_name]));ids.forEach((id,i)=>{const li=document.createElement('li'),s=document.createElement('span');s.textContent=`${i+1}. ${names.get(id)||'已失效航点：'+id}`;li.append(s);for(const [label,delta] of [['↑',-1],['↓',1],['删除',0]]){const b=document.createElement('button');b.textContent=label;b.setAttribute('aria-label',label+'第'+(i+1)+'站');b.disabled=busy||(delta===-1&&i===0)||(delta===1&&i===ids.length-1);b.onclick=()=>{if(delta)[ids[i],ids[i+delta]]=[ids[i+delta],ids[i]];else ids.splice(i,1);dirty=true;render()};li.append(b)}el('list').append(li)});
el('summary').textContent=ids.length?ids.map(i=>names.get(i)||'失效航点').join(' → ')+(dirty?' · 尚未保存':' · 已保存'):'尚未选择航点';
for(const k of ['add','save','dwell','select'])el(k).disabled=busy||!doc;
el('start').disabled=busy||!doc||dirty||!ids.length||Boolean(doc.error);el('reload').disabled=busy;
const hint=document.querySelector('#patrolProduct small');if(hint)hint.textContent=doc?.points?.map(p=>p.display_name).join(' → ')||'先规划路线';}
async function action(fn){if(busy)return;busy=true;render();try{await fn()}catch(e){el('message').textContent=e.name==='AbortError'?'请求超时，请检查任务状态后再操作':e.message}finally{busy=false;render()}}
function accept(d){doc=d;ids=[...d.ids];dirty=false;el('dwell').value=d.dwell_s;el('select').replaceChildren();for(const p of d.destinations){const o=document.createElement('option');o.value=p.id;o.textContent=p.display_name;el('select').append(o)}el('message').textContent=d.error||'路线已读取。保存不会让小车行驶。';}
el('reload').onclick=()=>{if(dirty&&!confirm('放弃尚未保存的路线修改？'))return;action(async()=>accept(await request(endpoint)))};
el('add').onclick=()=>{if(ids.length>=30){el('message').textContent='最多 30 站';return}if(el('select').value){ids.push(el('select').value);dirty=true;render()}};
el('dwell').oninput=()=>{dirty=true;render()};
el('save').onclick=()=>action(async()=>{accept(await request(endpoint,{revision:doc.revision,ids,dwell_s:Number(el('dwell').value)}));el('message').textContent='路线已保存，网页和语音巡航将使用此路线。'});
el('start').onclick=()=>{if(dirty||!doc||doc.error)return;if(!confirm('小车将按以下路线行驶一遍并录像：\n'+doc.points.map(p=>p.display_name).join(' → ')+'\n请确认地图定位正确。'))return;action(async()=>{const d=await request(customer?'/product/api/action':'/api/patrol/start',customer?{action:'patrol',revision:doc.revision}:{revision:doc.revision});el('message').textContent=d.message})};
el('stop').onclick=async()=>{try{const d=await request(customer?'/product/api/action':'/api/patrol/stop',customer?{action:'stop'}:{});el('message').textContent=d.message||'已请求停止'}catch(e){el('message').textContent=e.message}};
const old=document.getElementById(customer?'patrolProduct':'nxPatrolStart');if(old)old.onclick=()=>{host.scrollIntoView({behavior:'smooth',block:'center'});el('message').textContent='核对下方路线后，点击“按此路线巡航录像”。'};
// Customer page becomes visible only after local account login.
const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)&&!doc&&!busy)action(async()=>accept(await request(endpoint)))});observer.observe(host);render();
})();
