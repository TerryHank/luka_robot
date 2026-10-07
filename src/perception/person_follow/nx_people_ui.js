/* Monitor-only people UI. Include after nx_people_ui.html; no wheel commands. */
(() => {
  'use strict';
  const panel = document.getElementById('nxPeople');
  if (!panel || panel.dataset.initialized === 'true') return;
  panel.dataset.initialized = 'true';
  const el = suffix => document.getElementById('nxPeople' + suffix);
  const canvas = el('Canvas'), ctx = canvas.getContext('2d');
  const STALE_SECONDS = 0.7; // Match the worker's maximum frame age.
  const STATUS_INTERVAL_MS = 500;
  let state = null, receivedAt = 0, disconnected = true, busy = false;
  let polling = false, loadingFrame = false, frame = null, frameReceivedAt = 0, frameSourceAge = Infinity;
  let frameError = '', pendingDelete = null, stopped = false;
  let lastFrameStamp = null, drawnTracks = [], listSignature = '', profileSignature = '';
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const secondsSince = at => at ? (performance.now() - at) / 1000 : Infinity;
  const trackKey = track => String(track.track_id);
  const tracks = () => Array.isArray(state?.tracks) ? state.tracks : [];
  const selected = () => tracks().find(track => track.selected === true);
  const inMonitor = () => state?.mode === 'monitor' && state?.motion_enabled === false;
  function cameraAge() {
    if (!state) return Infinity;
    if (finite(state.camera_age)) return Math.max(0, state.camera_age) + secondsSince(receivedAt);
    const stamp = finite(state.frame_at) ? state.frame_at * (state.frame_at < 1e12 ? 1000 : 1) : Date.parse(state.frame_at || '');
    return Number.isFinite(stamp) ? Math.max(0, (Date.now() - stamp) / 1000) : Infinity;
  }
  const fresh = () => !disconnected && secondsSince(receivedAt) < STALE_SECONDS && cameraAge() < STALE_SECONDS;
  const usable = () => state?.active === true && !state.loading && !state.error && inMonitor() && fresh();
  const imageAge = () => frameSourceAge + secondsSince(frameReceivedAt);
  function identityName(track) {
    const identity = track?.identity;
    if (identity?.state === 'matched' && typeof identity.name === 'string' && identity.name.trim()) return identity.name;
    if (['face_too_small', 'blurred_face', 'low_quality'].includes(identity?.reason)) return '人脸不清晰／身份未确认';
    if (['no_face', 'not_visible', 'face_not_visible'].includes(identity?.state)) return '未看到人脸';
    return '未登记／身份未确认';
  }
  function distance(track) {
    return track.depth_valid === true && finite(track.distance_m) && track.distance_m > 0
      ? track.distance_m.toFixed(2) + ' m' : '距离未知';
  }
  function message(text) { el('Message').textContent = text || ''; }
  function textNode(tag, text, className) {
    const node = document.createElement(tag);
    node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  async function request(path, body) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), body === undefined ? 3500 : 20000);
    try {
      const response = await fetch('/api/people/' + path, {
        method: body === undefined ? 'GET' : 'POST', cache: 'no-store', credentials: 'same-origin',
        headers: body === undefined ? undefined : {'Content-Type': 'application/json'},
        body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal
      });
      const data = await response.json();
      if (!response.ok || data.ok === false) throw new Error(data.error || data.message || '请求未成功');
      return data;
    } finally { clearTimeout(timeout); }
  }
  async function action(path, body = {}) {
    if (busy) return;
    busy = true;
    message('正在处理…'); render();
    try {
      const result = await request(path, body);
      message(result.message || '已提交，请查看最新状态。');
      if (path === 'stop') { frame = null; lastFrameStamp = null; }
      if (path === 'delete-profile') pendingDelete = null;
      await poll();
    } catch (error) {
      message(error.name === 'AbortError' ? '请求超时，尚不能确认结果，请先检查服务状态。' : '操作失败：' + error.message);
    } finally { busy = false; render(); }
  }
  function validBox(track) {
    return Array.isArray(track.bbox) && track.bbox.length === 4 && track.bbox.every(finite) && track.bbox[2] > track.bbox[0] && track.bbox[3] > track.bbox[1];
  }
  function draw() {
    if (!ctx) return;
    const width = finite(state?.frame_width) && state.frame_width > 0 ? state.frame_width : 640;
    const height = finite(state?.frame_height) && state.frame_height > 0 ? state.frame_height : 480;
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width; canvas.height = height;
      canvas.parentElement.style.aspectRatio = width + '/' + height;
    }
    ctx.clearRect(0, 0, width, height);
    drawnTracks = [];
    if (!frame) return;
    ctx.drawImage(frame, 0, 0, width, height);
    if (!usable() || frameError || imageAge() >= STALE_SECONDS) return;
    // Capture the boxes with the displayed frame, so clicks never use newer boxes.
    for (const track of frame.peopleTracks) {
      if (!validBox(track)) continue;
      const [x1, y1, x2, y2] = track.bbox;
      const isSelected = tracks().some(t => trackKey(t) === trackKey(track) && t.selected === true);
      const label = identityName(track) + ' · #' + trackKey(track) + ' · ' + distance(track);
      ctx.strokeStyle = isSelected ? '#91efd0' : '#79b9f0'; ctx.lineWidth = isSelected ? 4 : 2;
      ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
      ctx.font = '14px sans-serif';
      const labelWidth = Math.min(width, ctx.measureText(label).width + 14);
      const labelX = Math.max(0, Math.min(x1, width - labelWidth));
      const labelY = Math.max(0, Math.min(y1 - 26, height - 26));
      ctx.fillStyle = '#0a1724e8'; ctx.fillRect(labelX, labelY, labelWidth, 26);
      ctx.fillStyle = isSelected ? '#91efd0' : '#e6edf3'; ctx.fillText(label, labelX + 7, labelY + 18, labelWidth - 14);
      drawnTracks.push(track);
    }
  }
  function renderTracks() {
    const signature = JSON.stringify([tracks(), usable(), busy, state?.enrollment?.active]);
    if (signature === listSignature) return;
    listSignature = signature;
    const nodes = tracks().map(track => {
      const button = textNode('button', '', 'np-track');
      button.type = 'button'; button.disabled = !usable() || busy || state?.enrollment?.active === true;
      button.setAttribute('aria-pressed', String(track.selected === true));
      button.append(textNode('span', identityName(track) + (track.selected ? ' · 已锁定' : '')));
      button.append(textNode('span', '追踪 #' + trackKey(track) + ' · ' + distance(track), 'np-muted'));
      button.addEventListener('click', () => action('select', {track_id: track.track_id}));
      return button;
    });
    el('Tracks').replaceChildren(...(nodes.length ? nodes : [textNode('span', state?.active ? '当前未发现人体' : '启动后显示人体目标', 'np-muted')]));
  }
  function renderProfiles() {
    const profiles = Array.isArray(state?.profiles) ? state.profiles : [];
    const signature = JSON.stringify([profiles, disconnected, busy, state?.active, state?.loading, state?.enrollment?.active]);
    if (signature !== profileSignature) {
      profileSignature = signature;
      const nodes = profiles.map(profile => {
        const row = textNode('div', '', 'np-profile');
        const samples = finite(profile.samples) ? profile.samples : finite(profile.sample_count) ? profile.sample_count : 0;
        row.append(textNode('span', String(profile.name || '未命名') + ' · ' + samples + ' 份特征'));
        const button = textNode('button', '删除'); button.type = 'button';
        button.disabled = busy || disconnected || !state?.active || state?.loading || state?.enrollment?.active === true;
        button.addEventListener('click', () => { pendingDelete = {id: profile.id, name: profile.name}; render(); });
        row.append(button); return row;
      });
      el('Profiles').replaceChildren(...(nodes.length ? nodes : [textNode('span', '暂无已登记身份', 'np-muted')]));
    }
    if (pendingDelete && !profiles.some(profile => String(profile.id) === String(pendingDelete.id))) pendingDelete = null;
    el('DeleteConfirm').hidden = !pendingDelete;
    el('DeleteText').textContent = pendingDelete ? '删除“' + pendingDelete.name + '”的本机人脸特征？再次识别该身份前需要重新登记。' : '';
    el('DeleteYes').disabled = busy || disconnected || !state?.active || state?.loading;
  }
  function render() {
    const ready = usable(), enrolling = state?.enrollment?.active === true;
    el('Badge').dataset.ready = String(ready);
    el('Badge').textContent = disconnected ? '连接中断' : !state?.active ? '已停止' : !inMonitor() ? '模式异常' : state.loading ? '模型加载中' : !fresh() || state.error ? '等待有效画面' : '静态识别中';
    el('Start').disabled = disconnected || busy || state?.active === true;
    el('Stop').disabled = disconnected || busy || state?.active !== true;
    el('Unlock').disabled = !ready || busy || !selected() || enrolling;
    el('Name').disabled = !ready || busy || enrolling;
    el('Enroll').disabled = !ready || busy || !selected() || enrolling || !el('Name').value.trim();
    el('CancelEnroll').disabled = disconnected || busy || !state?.active || !enrolling;
    el('State').textContent = disconnected ? '无法读取服务，请检查小车连接。' : state?.loading ? '正在加载本地模型，请稍候；目前不控制车轮。' : state?.error ? String(state.error) : !inMonitor() && state?.active ? '服务不是静态模式，已停用本页识别操作。' : state?.active ? '选择目标后可登记人脸；目前不执行跟随。' : '识别未启动';
    const person = selected();
    el('Target').textContent = person ? identityName(person) + ' · 追踪 #' + trackKey(person) + ' · ' + distance(person) + (ready ? '' : '（状态已过期）') : '未选择';
    const enrollment = state?.enrollment || {};
    el('Enrollment').hidden = !enrolling && (!enrollment.reason || !enrollment.message);
    const count = finite(enrollment.samples) ? enrollment.samples : 0, required = finite(enrollment.required) && enrollment.required > 0 ? enrollment.required : 1;
    const target = finite(enrollment.target) && enrollment.target >= required ? enrollment.target : required;
    el('FinishEnroll').disabled = !ready || busy || !enrolling || count < required;
    el('EnrollState').textContent = [enrolling ? '正在登记 ' + (enrollment.name || '') + '：' + count + ' / ' + target : '', enrolling && count >= required ? '已满足最低样本数，可点击“完成录入”，也可继续采集更多角度' : '', enrollment.message || ''].filter(Boolean).join(' · ');
    el('EnrollProgress').max = target; el('EnrollProgress').value = Math.min(count, target); el('EnrollProgress').hidden = !enrolling;
    const age = cameraAge();
    el('Stats').textContent = '相机数据年龄：' + (Number.isFinite(age) ? age.toFixed(1) + ' s' : '未知') + ' · 识别速度：' + (finite(state?.fps) ? state.fps.toFixed(1) + ' FPS' : '未知');
    let mask = disconnected ? '连接中断，画面不可用于判断当前状态' : !state?.active ? '静态识别尚未启动' : !inMonitor() ? '服务模式异常，已暂停本页操作' : state.loading ? '正在加载本地人体与人脸模型…' : state.error ? String(state.error) : !fresh() ? '相机画面已过期，请检查相机与识别服务' : frameError || (!frame ? '等待最新识别画面…' : imageAge() >= STALE_SECONDS ? '图像未更新，请检查连接' : '');
    el('Mask').hidden = !mask; el('Mask').textContent = mask;
    renderTracks(); renderProfiles(); draw();
  }
  async function refreshFrame() {
    if (loadingFrame || !usable() || document.hidden || stopped) return;
    if (state.frame_at && state.frame_at === lastFrameStamp && frame && !frameError) return;
    loadingFrame = true;
    let snapshot = state;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3000);
    let url;
    try {
      if (Object.prototype.hasOwnProperty.call(snapshot, 'frame_jpeg_base64')) {
        if (typeof snapshot.frame_jpeg_base64 !== 'string' || !snapshot.frame_jpeg_base64) {
          frame = null; frameError = '等待可用识别画面…'; return;
        }
        const snapshotReceivedAt = receivedAt;
        const image = new Image(); image.src = 'data:image/jpeg;base64,' + snapshot.frame_jpeg_base64;
        await image.decode();
        if (stopped || !usable() || state.frame_at !== snapshot.frame_at) return;
        image.peopleTracks = Array.isArray(snapshot.tracks) ? snapshot.tracks : [];
        frame = image; frameReceivedAt = snapshotReceivedAt; frameSourceAge = snapshot.camera_age;
        frameError = ''; lastFrameStamp = snapshot.frame_at;
        return;
      }
      // Status and JPEG are separate endpoints. Accept only a JPEG bracketed by
      // the same source stamp for compatibility with an older worker. Newer
      // workers include JPEG and boxes atomically in status, handled above.
      for (let attempt = 0; attempt < 2; attempt++) {
        const response = await fetch('/api/people/frame.jpg?t=' + Date.now(), {cache: 'no-store', credentials: 'same-origin', signal: controller.signal});
        if (!response.ok || !(response.headers.get('Content-Type') || '').startsWith('image/')) throw new Error('相机图像暂不可用');
        const blob = await response.blob();
        const verified = await request('status');
        const verifiedAt = performance.now();
        if (!verified.active || verified.loading || verified.error || !finite(verified.camera_age) || verified.camera_age >= STALE_SECONDS) break;
        if (!snapshot.frame_at || snapshot.frame_at !== verified.frame_at) { snapshot = verified; continue; }
        url = URL.createObjectURL(blob);
        const image = new Image(); image.src = url;
        await image.decode();
        if (state?.active !== true || stopped || !usable()) return;
        image.peopleTracks = Array.isArray(snapshot.tracks) ? snapshot.tracks : [];
        frame = image; frameReceivedAt = verifiedAt; frameSourceAge = verified.camera_age;
        frameError = ''; lastFrameStamp = snapshot.frame_at;
        return;
      }
      frameError = '正在同步画面与人体框，请稍候…';
    } catch (error) { frameError = error.name === 'AbortError' ? '图像读取超时，不能确认当前画面' : '图像读取失败，不能确认当前画面'; }
    finally { clearTimeout(timeout); if (url) URL.revokeObjectURL(url); loadingFrame = false; render(); }
  }
  async function poll() {
    if (polling || stopped || document.hidden) return;
    polling = true;
    try {
      const next = await request('status');
      if (!next || typeof next.active !== 'boolean' || typeof next.mode !== 'string') throw new Error('状态格式异常');
      state = next; receivedAt = performance.now(); disconnected = false;
      if (!state.active) { frame = null; lastFrameStamp = null; frameError = ''; }
    } catch (_) { disconnected = true; }
    finally { polling = false; render(); }
    await refreshFrame();
  }
  el('Start').addEventListener('click', () => action('start'));
  el('Stop').addEventListener('click', () => action('stop'));
  el('Unlock').addEventListener('click', () => action('unlock'));
  el('Name').addEventListener('input', render);
  el('EnrollForm').addEventListener('submit', event => {
    event.preventDefault(); const person = selected(), name = el('Name').value.trim();
    if (!usable() || busy || !person || !name || state?.enrollment?.active) return;
    action('enroll', {name, track_id: person.track_id});
  });
  el('CancelEnroll').addEventListener('click', () => action('cancel-enrollment'));
  el('FinishEnroll').addEventListener('click', () => {
    const enrollment = state?.enrollment;
    if (usable() && enrollment?.active && finite(enrollment.samples) && finite(enrollment.required) && enrollment.samples >= enrollment.required) action('finish-enrollment');
  });
  el('DeleteNo').addEventListener('click', () => { pendingDelete = null; render(); });
  el('DeleteYes').addEventListener('click', () => { if (pendingDelete) action('delete-profile', {id: pendingDelete.id}); });
  canvas.addEventListener('click', event => {
    if (!usable() || busy || frameError || imageAge() >= STALE_SECONDS || state?.enrollment?.active) return;
    const rect = canvas.getBoundingClientRect();
    const x = (event.clientX - rect.left) * canvas.width / rect.width, y = (event.clientY - rect.top) * canvas.height / rect.height;
    const candidates = drawnTracks.filter(track => x >= track.bbox[0] && x <= track.bbox[2] && y >= track.bbox[1] && y <= track.bbox[3])
      .sort((a, b) => (a.bbox[2] - a.bbox[0]) * (a.bbox[3] - a.bbox[1]) - (b.bbox[2] - b.bbox[0]) * (b.bbox[3] - b.bbox[1]));
    if (candidates.length && tracks().some(track => trackKey(track) === trackKey(candidates[0]))) action('select', {track_id: candidates[0].track_id});
  });
  let statusTimer = setInterval(poll, STATUS_INTERVAL_MS);
  let freshnessTimer = setInterval(() => { if (!document.hidden) render(); }, 250);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) { render(); poll(); } });
  window.addEventListener('pagehide', () => { stopped = true; clearInterval(statusTimer); clearInterval(freshnessTimer); });
  window.addEventListener('pageshow', event => {
    if (!event.persisted || !stopped) return;
    stopped = false; disconnected = true; frame = null; lastFrameStamp = null;
    statusTimer = setInterval(poll, STATUS_INTERVAL_MS);
    freshnessTimer = setInterval(() => { if (!document.hidden) render(); }, 250);
    render(); poll();
  });
  poll();
})();
