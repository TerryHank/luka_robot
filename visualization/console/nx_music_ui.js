(()=>{
const host=document.getElementById('musicPanel');if(!host)return;
const customer=location.pathname==='/user'||location.pathname.startsWith('/product');
const endpoint=customer?'/product/api/music':'/api/music';
host.innerHTML='<h3>露卡音乐</h3><a href="/assistant-help" target="_blank">全部语音指令与使用说明 ↗</a><p>唤醒后说“播放歌名”“暂停音乐”“继续音乐”“停止音乐”。</p><p>已接入 ALAPI 网易云音乐。可同时填写歌名与歌手；部分歌曲可能无可播放权限。</p><form><input name="query" maxlength="80" placeholder="歌名或歌手" required><button type="submit">搜索并播放</button></form><div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:12px"><button data-action="pause">暂停</button><button data-action="resume">继续</button><button data-action="stop">停止音乐</button><button data-action="status">播放状态</button></div><label style="display:block;margin-top:12px">音乐音量 <input id="musicVolume" type="number" min="0" max="100" value="35"><button data-action="volume">设置</button></label><p role="status" id="musicMessage">音乐未在播放</p>';
const msg=host.querySelector('#musicMessage');
async function run(action,extra={}){msg.textContent='正在处理…';try{const r=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,...extra})});const d=await r.json();if(!r.ok)throw Error(d.error||'请求失败');msg.textContent=d.message;if(Number.isInteger(d.volume))host.querySelector('#musicVolume').value=d.volume;}catch(e){msg.textContent=e.message;}}
host.querySelector('form').onsubmit=e=>{e.preventDefault();run('play',{query:host.querySelector('[name=query]').value.trim()});};
host.querySelectorAll('[data-action]').forEach(b=>b.onclick=()=>run(b.dataset.action,b.dataset.action==='volume'?{volume:Number(host.querySelector('#musicVolume').value)}:{}));
let refreshing=false;
async function refresh(){if(refreshing||document.hidden||!host.getClientRects().length)return;refreshing=true;try{const r=await fetch(endpoint,{cache:'no-store'});if(!r.ok)return;const d=await r.json();const v=host.querySelector('#musicVolume');if(document.activeElement!==v&&Number.isInteger(d.volume))v.value=d.volume;}catch(e){}finally{refreshing=false;}}
setInterval(refresh,5000);refresh();
})();
