(() => {
  'use strict';
  const start = document.getElementById('nxFollowStart');
  const stop = document.getElementById('nxFollowStop');
  const label = document.getElementById('nxFollowStatus');
  const mode = document.getElementById('nxFollowMode');
  const profile = document.getElementById('nxFollowProfile');
  const selected = document.getElementById('nxFollowSelected');
  const modeHint = document.getElementById('nxFollowModeHint');
  if (!start || !stop || !label || !mode || !profile || !selected) return;
  let busy = false, latest = null, signature = '';
  const activePhases = ['acquiring', 'waiting_range'];
  function render() {
    const state = latest || {}, options = state.options || {}, acquisition = state.acquisition || {};
    const currentMode = mode.value;
    profile.hidden = currentMode !== 'profile';
    selected.hidden = currentMode !== 'track';
    if (modeHint) modeHint.textContent = currentMode === 'profile'
      ? '已登记人员：先用人脸核对，再用双目距离把人投到地图，Nav2 规划短观察点并绕障；距离或身份失效立即停车。'
      : '当前画面人体：用当前编号与双目地图位置跟随。遮挡或换号时立即停车；要自动找回请选择“已登记人员”。';
    const row = options.selected_track;
    selected.textContent = row?.visible
      ? '已选画面目标：' + (row.identity_name || '未登记人员') + ' · 编号 #' + row.track_id
      : '先点击左侧画面中的人体框，再启动跟随';
    const profiles = options.profiles || [];
    const nextSignature = JSON.stringify(profiles.map(p => [p.id, p.name]));
    if (nextSignature !== signature) {
      signature = nextSignature;
      const old = profile.value;
      const placeholder = document.createElement('option');
      placeholder.value = ''; placeholder.textContent = '请选择已登记人员';
      profile.replaceChildren(placeholder, ...profiles.map(p => {
        const option = document.createElement('option');
        option.value = p.id; option.textContent = p.name || '未命名人员';
        return option;
      }));
      if (profiles.some(p => p.id === old)) profile.value = old;
      else if (profiles.length === 1) profile.value = profiles[0].id;
    }
    const hasTarget = currentMode === 'profile' ? !!profile.value :
      row?.visible === true && row?.observation_strength !== 'weak';
    start.disabled = busy || state.enabled === true || activePhases.includes(acquisition.phase) || !hasTarget;
    stop.disabled = false;
    if (state.enabled) {
      const speed = Number(state.forward_m_s || 0);
      label.textContent = state.nav_mode
        ? 'Nav2 地图跟随 · ' + state.reason + ' · 测试限速 0.15 m/s'
        : '正在跟随 · ' + state.reason + ' · ' + (speed < 0 ? '退让 ' : '前进 ') + Math.abs(speed).toFixed(2) + ' m/s';
      if (state.nav_mode && state.map_assist?.reason) {
        label.textContent += ' · 测距：' + state.map_assist.reason;
      }
      if (state.front_clearance_m != null) label.textContent += ' · 前方最近 ' + Number(state.front_clearance_m).toFixed(2) + ' m';
    } else if (activePhases.includes(acquisition.phase) || acquisition.phase === 'blocked') {
      label.textContent = acquisition.message;
    } else {
      label.textContent = '未跟随 · ' + (state.reason === '未启动' || state.reason === '已手动停止' || state.reason === '已停车'
        ? '请选择目标后点击启动' : state.reason || '等待状态');
    }
  }
  async function refresh() {
    try {
      const response = await fetch('/api/follow/status', {cache: 'no-store'});
      if (!response.ok) throw Error('状态读取失败');
      latest = await response.json();
      render();
    } catch (_) {
      latest = null;
      label.textContent = '跟随状态连接中断，底盘会超时停车';
      start.disabled = true;
      stop.disabled = false;
    }
  }
  async function command(name, body) {
    if (busy && name !== 'stop') return;
    busy = true; start.disabled = true; stop.disabled = false;
    try {
      const response = await fetch('/api/follow/' + name, {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body || {})
      });
      const result = await response.json();
      if (!response.ok) throw Error(result.error || '操作失败');
      label.textContent = result.message || result.reason || '请求已提交';
    } catch (error) {
      label.textContent = '操作失败：' + error.message;
    } finally {
      busy = false;
      setTimeout(refresh, 200);
    }
  }
  mode.onchange = render;
  profile.onchange = render;
  start.onclick = () => {
    const currentMode = mode.value, options = latest?.options || {};
    const id = currentMode === 'profile' ? profile.value : options.selected_track_id;
    if (id == null || id === '') return;
    command('choose', {mode: currentMode, id});
  };
  stop.onclick = () => command('stop');
  setInterval(refresh, 500);
  refresh();
})();
