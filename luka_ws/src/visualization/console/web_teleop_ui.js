(() => {
  const view = document.getElementById('nc-navigation');
  if (!view || document.getElementById('nxWebTeleop')) return;
  const panel = document.createElement('section');
  panel.id = 'nxWebTeleop';
  panel.innerHTML = `
    <div class="wt-head"><div><h2>网页遥控</h2><p>双摇杆按住操作，松开即停车；断网或雷达数据过期时自动停车。</p></div><strong id="wtState">正在检查底盘…</strong></div>
    <div class="wt-controls">
      <div class="wt-sticks">
        <div class="wt-stick-group"><span>左摇杆 · 移动</span><div class="wt-stick" id="wtMove" role="application" aria-label="移动摇杆，前后左右平移"><div class="wt-cross"></div><div class="wt-thumb"></div></div><small>上前进 · 下后退 · 左右平移</small></div>
        <div class="wt-stick-group"><span>右摇杆 · 转向</span><div class="wt-stick wt-turn" id="wtTurn" role="application" aria-label="转向摇杆，左右自转"><div class="wt-cross"></div><div class="wt-thumb"></div></div><small>向左左转 · 向右右转</small></div>
      </div>
      <div class="wt-actions"><button id="wtGear" type="button">速度：1/5 档 · 0.40 m/s ↻</button><button id="wtStop" type="button">立即停车</button></div>
    </div>
    <p class="wt-foot">点击速度按钮依次切换 1–5 档（前进最高 0.4–0.8 m/s）；两个摇杆可同时操作。遥控开始时会取消导航、跟随和重定位。</p>`;
  view.prepend(panel);
  const state = panel.querySelector('#wtState');
  const gearButton = panel.querySelector('#wtGear');
  const sticks = {
    move: {element:panel.querySelector('#wtMove'), pointer:null, x:0, y:0},
    turn: {element:panel.querySelector('#wtTurn'), pointer:null, x:0, y:0}
  };
  const headers = {'Content-Type':'application/json', 'X-Luka-Control':'hold-to-drive'};
  let token = null, starting = false, timer = null, pending = false, online = false;
  const held = () => sticks.move.pointer !== null || sticks.turn.pointer !== null;
  async function post(action, data = {}) {
    const response = await fetch('/api/teleop/' + action, {
      method:'POST', headers, body:JSON.stringify(data), cache:'no-store'
    });
    const result = await response.json();
    if (!response.ok) throw Error(result.error || '遥控连接失败');
    return result;
  }
  function axes() {
    return {move_x:sticks.move.x, move_y:-sticks.move.y, turn_x:sticks.turn.x};
  }
  async function pulse() {
    if (!token || pending) return;
    pending = true;
    try { await post('pulse', {token, axes:axes()}); }
    catch (error) { state.textContent = error.message; releaseAll(); }
    finally { pending = false; }
  }
  async function begin() {
    if (token || starting || !held()) return;
    starting = true;
    state.textContent = '正在接管…';
    try {
      const response = await post('start');
      token = response.token;
      if (!held()) { releaseAll(); return; }
      await pulse();
      if (held() && token) timer = setInterval(pulse, 100);
    } catch (error) { state.textContent = error.message; releaseAll(); }
    finally { starting = false; }
  }
  function stopSession() {
    if (timer) { clearInterval(timer); timer = null; }
    const old = token; token = null;
    if (old) post('stop', {token:old}).catch(() => {});
  }
  function resetStick(stick) {
    stick.pointer = null; stick.x = stick.y = 0;
    stick.element.classList.remove('wt-held');
    stick.element.querySelector('.wt-thumb').style.transform = 'translate(0px, 0px)';
  }
  function releaseAll() {
    resetStick(sticks.move); resetStick(sticks.turn);
    stopSession();
    gearButton.disabled = !online;
  }
  function releaseStick(stick, event) {
    if (stick.pointer !== event.pointerId) return;
    resetStick(stick);
    if (!held()) stopSession();
    else pulse();
    gearButton.disabled = !online || held();
  }
  function updateStick(stick, event, turnOnly) {
    const box = stick.element.getBoundingClientRect();
    const radius = box.width * .32;
    let x = (event.clientX - (box.left + box.width / 2)) / radius;
    let y = turnOnly ? 0 : (event.clientY - (box.top + box.height / 2)) / radius;
    const length = Math.hypot(x, y);
    if (length > 1) { x /= length; y /= length; }
    stick.x = x; stick.y = y;
    stick.element.querySelector('.wt-thumb').style.transform = 'translate(' + (x * radius) + 'px, ' + (y * radius) + 'px)';
  }
  for (const [name, stick] of Object.entries(sticks)) {
    const element = stick.element;
    element.addEventListener('pointerdown', event => {
      if (!online || stick.pointer !== null) return;
      event.preventDefault();
      stick.pointer = event.pointerId;
      element.classList.add('wt-held');
      element.setPointerCapture(event.pointerId);
      updateStick(stick, event, name === 'turn');
      gearButton.disabled = true;
      begin();
    });
    element.addEventListener('pointermove', event => {
      if (stick.pointer !== event.pointerId) return;
      updateStick(stick, event, name === 'turn');
    });
    element.addEventListener('pointerup', event => releaseStick(stick, event));
    element.addEventListener('pointercancel', event => releaseStick(stick, event));
    element.addEventListener('lostpointercapture', event => releaseStick(stick, event));
    element.addEventListener('contextmenu', event => event.preventDefault());
  }
  function showGear(result) {
    gearButton.textContent = '速度：' + result.gear_name + ' · ' + Number(result.speed_m_s).toFixed(2) + ' m/s ↻';
  }
  gearButton.onclick = async () => {
    if (held() || starting) { state.textContent = '请先松开摇杆再调速'; return; }
    gearButton.disabled = true;
    try {
      const result = await post('gear');
      showGear(result);
      state.textContent = '已切换至' + result.gear_name + '档';
    } catch (error) { state.textContent = error.message; }
    finally { gearButton.disabled = !online || held(); }
  };
  panel.querySelector('#wtStop').onclick = async () => {
    releaseAll();
    try {
      const response = await fetch('/api/nav/stop', {method:'POST'});
      const result = await response.json();
      state.textContent = response.ok ? '已停车' : (result.error || '停车失败');
    } catch (_) { state.textContent = '连接中断：底盘指令超时后自动停车'; }
  };
  window.addEventListener('blur', releaseAll);
  window.addEventListener('pagehide', () => {
    if (token) navigator.sendBeacon('/api/teleop/stop', new Blob([JSON.stringify({token})], {type:'application/json'}));
    releaseAll();
  });
  document.addEventListener('visibilitychange', () => { if (document.hidden) releaseAll(); });
  async function refresh() {
    try {
      const response = await fetch('/api/teleop/status', {cache:'no-store'});
      const result = await response.json();
      online = !!result.base_online;
      panel.classList.toggle('wt-offline', !online);
      gearButton.disabled = !online || held();
      showGear(result);
      if (!held()) state.textContent = online ? result.base_status : '底盘离线，遥控不可用';
      else if (/障碍|过期|暂停/.test(result.base_status)) state.textContent = result.base_status;
      else state.textContent = '操控中 · ' + result.base_status;
      if (!online && held()) releaseAll();
    } catch (_) {
      online = false; releaseAll();
      panel.classList.add('wt-offline');
      state.textContent = '连接中断，已停车';
    }
  }
  refresh(); setInterval(refresh, 500);
})();
