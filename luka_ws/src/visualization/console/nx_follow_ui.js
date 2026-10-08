(() => {
  'use strict';
  const start = document.getElementById('nxFollowStart');
  const stop = document.getElementById('nxFollowStop');
  const label = document.getElementById('nxFollowStatus');
  const mode = document.getElementById('nxFollowMode');
  const profile = document.getElementById('nxFollowProfile');
  const selected = document.getElementById('nxFollowSelected');
  const hint = document.getElementById('nxFollowModeHint');
  if (!start || !stop || !label || !mode) return;
  mode.replaceChildren(new Option('官方 MOT 动态选人', 'official'));
  mode.disabled = true;
  if (profile) profile.hidden = true;
  if (selected) selected.hidden = true;
  if (hint) hint.textContent = '人脸登记仍可独立使用。跟随由官方MOT选人，不保证指定身份；默认只观察候选目标。';
  start.textContent = '启用官方跟随';
  let busy = false;
  async function refresh() {
    try {
      const response = await fetch('/api/follow/status', {cache: 'no-store'});
      if (!response.ok) throw Error('状态读取失败');
      const state = await response.json();
      start.disabled = busy || state.enabled || !state.module_available;
      label.textContent = (state.output_mode === 'nav2_action' ? 'Nav2目标模式' : '候选观察模式') +
        ' · ' + (state.reason || '等待官方模块');
    } catch (_) {
      start.disabled = true;
      label.textContent = '官方跟随状态不可用；没有实车停稳确认';
    }
  }
  async function command(name) {
    if (busy && name !== 'stop') return;
    busy = true;
    start.disabled = true;
    try {
      const response = await fetch('/api/follow/' + name, {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'}, body: '{}'
      });
      const result = await response.json();
      if (!response.ok) throw Error(result.error || '请求未接受');
      label.textContent = result.reason || '请求已接受';
    } catch (error) {
      label.textContent = error.message;
    } finally {
      busy = false;
      setTimeout(refresh, 200);
    }
  }
  start.onclick = () => command('start');
  stop.onclick = () => command('stop');
  setInterval(refresh, 500);
  refresh();
})();
