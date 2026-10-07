/* Deterministic DOM regression: live status must never interrupt a name draft.
 * Run with: node person_follow/test_people_input.js
 * No network, camera, saved identities, or wheel commands are used.
 */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const uiPath = process.argv[2] || path.join(__dirname, '..', 'nx_migration', 'nx_people_ui.js');
const htmlPath = process.argv[3] || path.join(__dirname, '..', 'nx_migration', 'nx_people_ui.html');
const source = fs.readFileSync(uiPath, 'utf8');
const html = fs.readFileSync(htmlPath, 'utf8');
let now = 1000, failStatus = false, holdAction = null;
const intervals = new Map(), requests = [], elements = new Map(), drawnBoxes = [], drawnBoxStyles = [];
let timerId = 0;
const document = {hidden: false, activeElement: null, listeners: {},
  getElementById(id) { return elements.get(id); },
  createElement(tag) { return new Element(tag); },
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
};
class Element {
  constructor(tag = 'div', id = '') {
    this.tagName = tag; this.id = id; this.dataset = {}; this.style = {};
    this.listeners = {}; this.children = []; this.attributes = {};
    this.replaceChildrenCalls = 0;
    this.value = ''; this.textContent = ''; this.hidden = false;
    this.selectionStart = this.selectionEnd = 0; this.isComposing = false;
    this.disabledAssignments = 0; this._disabled = false; this._readOnly = false;
    this.width = 640; this.height = 480;
    this.parentElement = {style: {}};
  }
  set disabled(value) {
    this.disabledAssignments++;
    this._disabled = !!value;
    // Browsers blur an input immediately when it becomes disabled.
    if (value && document.activeElement === this) {
      document.activeElement = null;
      this.isComposing = false;
      this.emit('blur');
    }
  }
  get disabled() { return this._disabled; }
  set readOnly(value) { this._readOnly = !!value; }
  get readOnly() { return this._readOnly; }
  focus() { if (!this.disabled) document.activeElement = this; }
  setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; }
  setAttribute(key, value) { this.attributes[key] = value; }
  getAttribute(key) { return this.attributes[key]; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.replaceChildrenCalls++; this.children = nodes; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  emit(type, props = {}) {
    const event = {type, target: this, preventDefault() { this.defaultPrevented = true; }, ...props};
    if (type === 'compositionstart') this.isComposing = true;
    if (type === 'compositionend') this.isComposing = false;
    for (const fn of this.listeners[type] || []) fn(event);
    return event;
  }
  getContext() { return new Proxy({}, {get(target, key) {
    if (key === 'measureText') return () => ({width: 40});
    if (key === 'clearRect') return () => { drawnBoxes.length = 0; drawnBoxStyles.length = 0; };
    if (key === 'strokeRect') return (...box) => { drawnBoxes.push(box); drawnBoxStyles.push(target.strokeStyle); };
    if (Object.prototype.hasOwnProperty.call(target, key)) return target[key];
    return () => {};
  }, set(target, key, value) { target[key] = value; return true; }}); }
  getBoundingClientRect() { return {left: 0, top: 0, width: 320, height: 240}; }
  type(text) {
    assert.equal(document.activeElement, this, 'name field lost focus during polling');
    assert.equal(this.disabled, false, 'name draft was disabled');
    assert.equal(this.readOnly, false, 'name draft became read-only');
    this.value = this.value.slice(0, this.selectionStart) + text + this.value.slice(this.selectionEnd);
    this.selectionStart += text.length; this.selectionEnd = this.selectionStart;
    this.emit('input', {isComposing: this.isComposing});
  }
}
for (const match of html.matchAll(/<([a-z]+)\b([^>]*\bid="(nxPeople[^\"]*)"[^>]*)>/gi)) {
  const element = new Element(match[1], match[3]);
  element.disabled = /\bdisabled\b/.test(match[2]);
  elements.set(match[3], element);
}
const by = suffix => elements.get('nxPeople' + suffix);
let status = freshStatus();
function freshStatus(overrides = {}) {
  return {active: true, mode: 'monitor', motion_enabled: false, camera_age: .1,
    frame_at: now, frame_width: 640, frame_height: 480, frame_jpeg_base64: 'AA==',
    fps: 5, tracks: [{track_id: 11, selected: true, bbox: [10, 20, 220, 440], identity: {state: 'unknown'}, depth_valid: false}],
    profiles: [], enrollment: {active: false}, ...overrides};
}
const context = {
  document, window: {addEventListener() {}}, performance: {now: () => now},
  console, AbortController, URL, Date, Number, JSON, Object, Array, String,
  Image: class { async decode() {} },
  setInterval(fn, ms) { const id = ++timerId; intervals.set(id, {fn, ms}); return id; },
  clearInterval(id) { intervals.delete(id); },
  setTimeout() { return ++timerId; }, clearTimeout() {},
  async fetch(url, options = {}) {
    const route = url.split('/').pop().split('?')[0];
    if (route === 'status') {
      if (failStatus) throw new Error('test connection unavailable');
      return {ok: true, json: async () => structuredClone(status)};
    }
    requests.push({route, body: options.body && JSON.parse(options.body)});
    if (holdAction) await holdAction.promise;
    return {ok: true, json: async () => ({ok: true})};
  }
};
const settle = async () => { for (let i = 0; i < 15; i++) await Promise.resolve(); };
async function tick(ms) { for (const timer of intervals.values()) if (timer.ms === ms) await timer.fn(); await settle(); }
async function publish(next) { now += 100; status = next; await tick(500); }
function keepDraft(label) {
  const name = by('Name');
  assert.equal(document.activeElement, name, label + ': focus preserved');
  assert.equal(name.disabled, false, label + ': editable draft');
  assert.equal(name.readOnly, false, label + ': editable draft');
  assert.equal(name.value, '瞿哥zh', label + ': draft preserved');
  assert.equal(name.selectionStart, 2, label + ': cursor preserved');
  assert.equal(name.selectionEnd, 2, label + ': selection preserved');
  assert.equal(name.isComposing, true, label + ': composition preserved');
}
async function rejectSubmit(label) {
  // Exercise the camera/selection guard independently from the IME guard.
  by('Name').emit('compositionend');
  by('EnrollForm').emit('submit'); await settle();
  assert.equal(requests.length, 0, label + ': submit must not enroll');
  by('Name').emit('compositionstart');
}

(async () => {
  assert.equal(by('Name').disabled, false, 'HTML draft input should be editable before the first status response');
  vm.runInNewContext(source, context, {filename: uiPath});
  await settle();
  const name = by('Name');
  name.focus(); name.type('瞿哥zh'); name.setSelectionRange(2, 2); name.emit('compositionstart');
  for (let i = 0; i < 25; i++) {
    now += 800; await tick(250);
    keepDraft('expired frame ' + i);
    assert.equal(by('Enroll').disabled, true, 'stale frame disables enrollment only');
    await publish(freshStatus());
    keepDraft('fresh frame ' + i);
  }
  now += 800; await tick(250); await rejectSubmit('stale');
  failStatus = true; await tick(500); keepDraft('disconnected');
  assert.equal(by('Enroll').disabled, true);
  await rejectSubmit('disconnected');
  failStatus = false;
  await publish(freshStatus({active: false, tracks: []})); keepDraft('stopped');
  await rejectSubmit('stopped');
  await publish(freshStatus({loading: true})); keepDraft('loading');
  await rejectSubmit('loading');
  await publish(freshStatus({error: 'camera unavailable'})); keepDraft('camera error');
  await rejectSubmit('camera error');
  await publish(freshStatus({tracks: []})); keepDraft('no selected track');
  await rejectSubmit('no selected track');
  await publish(freshStatus({tracks: [
    {track_id: 11, selected: false, bbox: [10, 20, 210, 440]},
    {track_id: 12, selected: false, bbox: [300, 20, 510, 440]}
  ]})); keepDraft('multiple unselected people');
  assert.equal(by('Target').textContent, '未选择', 'multiple people must not select themselves');
  assert.equal(by('Enroll').disabled, true, 'multiple people require explicit target choice');
  await rejectSubmit('multiple unselected people');
  await publish(freshStatus());
  by('EnrollForm').emit('submit', {isComposing: true}); await settle();
  assert.equal(requests.length, 0, 'IME confirmation must not accidentally submit enrollment');
  name.emit('compositionend'); name.setSelectionRange(0, name.value.length); name.type('瞿哥');
  holdAction = {};
  holdAction.promise = new Promise(resolve => { holdAction.resolve = resolve; });
  by('EnrollForm').emit('submit'); await settle();
  assert.deepEqual(requests, [{route: 'enroll', body: {name: '瞿哥', track_id: 11}}], 'valid explicit submit enrolls selected identity');
  assert.equal(by('Enroll').disabled, true, 'busy submit is disabled');
  assert.equal(name.disabled, false, 'request in flight must not blur input');
  assert.equal(document.activeElement, name, 'request in flight retains focus');
  name.type('草稿');
  assert.equal(requests[0].body.name, '瞿哥', 'subsequent draft edits do not mutate submitted name');
  by('EnrollForm').emit('submit'); await settle();
  assert.equal(requests.length, 1, 'busy duplicate submit is blocked');
  holdAction.resolve(); holdAction = null; await settle();

  const owner = {id: 'owner-profile', name: '主人', sample_count: 8};
  const visitor = {id: 'visitor-profile', name: '访客', sample_count: 3};
  const body = {track_id: 11, selected: true, bbox: [10, 20, 220, 440], identity: {state: 'no_face', reason: 'no_face'}, depth_valid: false};
  const targetStatus = overrides => freshStatus({profiles: [owner, visitor], tracks: [body],
    target_session: {active: true, track_id: 11, profile_id: null, motion_enabled: false}, ...overrides});
  await publish(targetStatus());
  assert.equal(by('TargetProfile').value, '', 'a registered identity must not be selected automatically');
  assert.equal(by('ConfirmTarget').disabled, true, 'profile choice is required');
  by('TargetProfile').value = owner.id; by('TargetProfile').emit('change');
  assert.equal(by('ConfirmTarget').disabled, false, 'explicit selected body can be confirmed without a face');
  const optionNodes = [...by('TargetProfile').children];
  for (let i = 0; i < 25; i++) {
    await publish(targetStatus());
    assert.equal(by('TargetProfile').value, owner.id, 'profile choice preserved across polls');
    assert.deepEqual(by('TargetProfile').children, optionNodes, 'unchanged profile options are not recreated');
    assert.equal(document.activeElement, name, 'target polling preserves name focus');
  }
  const beforeConfirm = requests.length;
  const assertConfirmBlocked = async label => {
    assert.equal(by('ConfirmTarget').disabled, true, label + ': confirmation disabled');
    by('ConfirmTarget').emit('click'); await settle();
    assert.equal(requests.length, beforeConfirm, label + ': no confirmation request');
  };
  now += 800; await tick(250); await assertConfirmBlocked('stale target');
  failStatus = true; await tick(500); await assertConfirmBlocked('disconnected'); failStatus = false;
  await publish(targetStatus({active: false})); await assertConfirmBlocked('stopped');
  await publish(targetStatus({loading: true})); await assertConfirmBlocked('loading');
  await publish(targetStatus({error: 'camera unavailable'})); await assertConfirmBlocked('camera error');
  await publish(targetStatus({enrollment: {active: true}})); await assertConfirmBlocked('enrolling');
  await publish(targetStatus({target_session: {active: false, reason: 'identity_conflict'}})); await assertConfirmBlocked('revoked target');
  assert.match(by('Session').textContent, /不一致.*重新选择/, 'conflicting identity explains reselection even while body is visible');
  await publish(targetStatus({target_session: undefined})); await assertConfirmBlocked('server without target sessions');
  await publish(targetStatus({tracks: [{...body, selected: false}]})); await assertConfirmBlocked('unselected body');
  await publish(targetStatus({tracks: [{...body, association_ambiguous: true}]})); await assertConfirmBlocked('ambiguous body');
  await publish(targetStatus({profiles: [visitor]}));
  assert.equal(by('TargetProfile').value, '', 'deleted profile choice is cleared');
  await assertConfirmBlocked('deleted profile');
  by('TargetProfile').value = 'missing-profile'; by('TargetProfile').emit('change');
  await assertConfirmBlocked('unknown profile');
  await publish(targetStatus());
  by('TargetProfile').value = owner.id; by('TargetProfile').emit('change');
  holdAction = {};
  holdAction.promise = new Promise(resolve => { holdAction.resolve = resolve; });
  by('ConfirmTarget').emit('click'); await settle();
  assert.deepEqual(requests.at(-1), {route: 'confirm-target', body: {track_id: 11, profile_id: owner.id}}, 'explicit confirmation sends selected track and exact profile');
  assert.equal(by('ConfirmTarget').disabled, true, 'busy confirmation disabled');
  by('ConfirmTarget').emit('click'); await settle();
  assert.equal(requests.length, beforeConfirm + 1, 'busy confirmation duplicate blocked');
  holdAction.resolve(); holdAction = null; await settle();

  const session = {active: true, track_id: 11, profile_id: owner.id, name: owner.name,
    confirmation_source: 'user_selection', current_face_verified: false, motion_enabled: false};
  await publish(targetStatus({target_session: session}));
  assert.match(by('Session').textContent, /本次目标：主人.*由你确认.*当前人脸未核对/, 'body target persists after looking away with truthful source');
  assert.match(by('Target').textContent, /未看到人脸/, 'live face remains unverified');
  assert.doesNotMatch(by('Target').textContent, /主人/, 'manual target name is not reported as a face match');
  await publish(targetStatus({target_session: {...session, current_face_verified: true}}));
  assert.match(by('Session').textContent, /当前人脸未核对/, 'session flag alone cannot assert a current face match');
  await publish(targetStatus({target_session: {...session, current_face_verified: true},
    tracks: [{...body, identity: {state: 'matched', id: owner.id, name: owner.name}}]}));
  assert.match(by('Session').textContent, /当前人脸已核对/, 'current matching face can corroborate session');
  await publish(targetStatus({target_session: {...session, confirmation_source: 'face_match'}}));
  assert.match(by('Session').textContent, /已通过人脸确认.*当前人脸未核对/, 'past face confirmation is distinct from current face state');
  await publish(targetStatus({target_session: {...session, track_id: 99}}));
  assert.doesNotMatch(by('Session').textContent, /本次目标：主人/, 'session from another body is not displayed');
  await publish(targetStatus({target_session: session, tracks: [{...body, association_ambiguous: true}]}));
  assert.doesNotMatch(by('Session').textContent, /本次目标：主人/, 'ambiguous body cannot preserve label');
  await publish(targetStatus({target_session: session, profiles: [visitor]}));
  assert.match(by('Session').textContent, /档案已不可用/, 'deleted identity cannot remain a target name');
  await publish(targetStatus({target_session: session}));
  now += 800; await tick(250);
  assert.doesNotMatch(by('Session').textContent, /本次目标：主人/, 'stale session clears target label locally');
  await publish(targetStatus({tracks: [], target_session: {...session, active: false, reason: 'target_lost'}}));
  assert.match(by('Session').textContent, /已丢失.*重新选择/, 'lost body asks for explicit reselection');

  const waitingSession = {...session, state: 'waiting_detection', visible: false, current_face_verified: false,
    motion_ready: false, missing_age_s: .2, hold_remaining_s: .4, reason: 'temporary_detection_miss'};
  await publish(targetStatus({target_session: session, tracks: [{...body, depth_valid: true, distance_m: 1.5}]}));
  assert.match(by('Target').textContent, /1\.50 m/, 'visible body has its current distance before the miss');
  await publish(targetStatus({target_session: waitingSession, tracks: [], selected_track_id: 11}));
  assert.match(by('Target').textContent, /短暂漏检.*等待同一目标恢复.*不会行驶/, 'short miss has a waiting state without a phantom person');
  assert.doesNotMatch(by('Target').textContent, /主人|1\.50 m/, 'waiting target neither reuses identity nor old distance as current');
  assert.match(by('Session').textContent, /上次确认的本次目标：主人.*当前未看到目标/, 'waiting session name is explicitly historical');
  assert.match(by('TargetDetails').textContent, /不沿用上一次距离/, 'waiting explains unavailable current distance');
  assert.equal(drawnBoxes.length, 0, 'missing body is not drawn from an older frame');
  assert.equal(by('Unlock').disabled, false, 'held target can be explicitly unlocked without a selected visible row');
  assert.equal(by('ConfirmTarget').disabled, true, 'held target cannot be confirmed');
  assert.equal(by('Enroll').disabled, true, 'held target cannot be enrolled');
  assert.equal(document.activeElement, name, 'short miss never interrupts draft focus');
  assert.equal(by('TargetProfile').value, '', 'hold never makes an automatic profile choice');
  const beforeHoldActions = requests.length;
  by('ConfirmTarget').emit('click'); by('EnrollForm').emit('submit'); await settle();
  assert.equal(requests.length, beforeHoldActions, 'hold guards protect confirmation and enrollment handlers');
  await publish(targetStatus({target_session: waitingSession, tracks: [], selected_track_id: 11,
    enrollment: {active: true, samples: 4, required: 3}}));
  assert.equal(by('FinishEnroll').disabled, true, 'recorded sample count cannot finish enrollment while the body is missing');
  by('FinishEnroll').emit('click'); await settle();
  assert.equal(requests.length, beforeHoldActions, 'finish handler also rejects missing target');
  await publish(targetStatus({target_session: waitingSession, tracks: [], selected_track_id: 11}));
  now += 450; await tick(250);
  assert.match(by('Session').textContent, /等待已结束/, 'local hold countdown expires before the camera freshness limit');
  assert.doesNotMatch(by('Session').textContent, /主人/, 'expired hold no longer shows a previous confirmed name');
  await publish(targetStatus({target_session: waitingSession, tracks: [], selected_track_id: 11}));
  by('Unlock').emit('click'); await settle();
  assert.deepEqual(requests.at(-1), {route: 'unlock', body: {}}, 'explicit unlock works during a fresh hold');
  await publish(targetStatus({target_session: waitingSession, tracks: [], selected_track_id: 11, profiles: [visitor]}));
  assert.doesNotMatch(by('Session').textContent, /主人/, 'missing catalog profile cannot appear even as held identity');
  await publish(targetStatus({target_session: waitingSession, tracks: [], selected_track_id: 99}));
  assert.doesNotMatch(by('Session').textContent, /主人/, 'mismatched held track id does not keep a historical label');
  await publish(targetStatus({target_session: waitingSession, tracks: [{...body, track_id: 12, selected: false}], selected_track_id: 11}));
  assert.doesNotMatch(by('Session').textContent, /主人/, 'competing body does not preserve a waiting identity in the UI');
  await publish(targetStatus({target_session: waitingSession, tracks: [], selected_track_id: 11}));
  now += 800; await tick(250);
  assert.equal(by('Unlock').disabled, true, 'stale held state cannot enable fresh-state controls');
  assert.doesNotMatch(by('Session').textContent, /主人/, 'stale held state does not preserve historical identity label');
  await publish(targetStatus({target_session: session, selected_track_id: 11}));
  assert.match(by('Session').textContent, /本次目标：主人.*持续追踪人体.*当前人脸未核对/, 'same body returning resumes target association without inventing a face match');

  const weakBody = {...body, observation_strength: 'weak', confidence: .3,
    identity: {state: 'unknown', reason: 'weak_body_detection'}};
  await publish(targetStatus({target_session: session, tracks: [weakBody], selected_track_id: 11}));
  by('TargetProfile').value = owner.id; by('TargetProfile').emit('change');
  assert.match(by('TargetDetails').textContent, /人体检测暂时较弱，正在续接原目标/, 'weak observations clearly describe continuation');
  assert.match(by('Session').textContent, /本次目标：主人.*续接原目标.*当前人脸未核对/, 'weak body preserves only prior target association');
  assert.equal(by('Tracks').children[0].disabled, true, 'weak row cannot start or restart target selection');
  assert.equal(by('ConfirmTarget').disabled, true, 'weak body cannot confirm an identity');
  assert.equal(by('Enroll').disabled, true, 'weak body cannot start enrollment');
  assert.equal(by('Unlock').disabled, false, 'weak body can still be explicitly released');
  assert.equal(document.activeElement, name, 'weak-body polling preserves name focus');
  const beforeWeakActions = requests.length;
  by('Tracks').children[0].emit('click');
  by('Canvas').emit('click', {clientX: 50, clientY: 100});
  by('ConfirmTarget').emit('click');
  by('EnrollForm').emit('submit');
  await settle();
  assert.equal(requests.length, beforeWeakActions, 'weak row, canvas, confirmation and enrollment handler guards reject actions');
  await publish(targetStatus({target_session: session, tracks: [weakBody], selected_track_id: 11,
    enrollment: {active: true, samples: 4, required: 3}}));
  assert.equal(by('FinishEnroll').disabled, true, 'weak body cannot finish enrollment even with enough saved samples');
  by('FinishEnroll').emit('click'); await settle();
  assert.equal(requests.length, beforeWeakActions, 'finish handler rejects weak-body enrollment');
  await publish(targetStatus({target_session: {...session, current_face_verified: true},
    tracks: [{...weakBody, identity: {state: 'matched', id: owner.id, name: owner.name}}], selected_track_id: 11}));
  assert.doesNotMatch(by('Target').textContent, /主人/, 'weak row cannot expose a cached face match as current');
  assert.match(by('Session').textContent, /当前人脸未核对/, 'weak observation overrides a stale face-verified session flag');
  await publish(targetStatus({target_session: session, tracks: [{...body, observation_strength: 'strong'}], selected_track_id: 11}));
  assert.equal(by('Tracks').children[0].disabled, false, 'selection returns when detection is strong');
  assert.equal(by('ConfirmTarget').disabled, false, 'identity confirmation returns for a strong current body');
  assert.equal(by('Enroll').disabled, false, 'enrollment returns for a strong current body');
  await publish(targetStatus({target_session: session, tracks: [{...body, observation_strength: 'strong'}], selected_track_id: 11,
    enrollment: {active: true, samples: 4, required: 3}}));
  assert.equal(by('FinishEnroll').disabled, false, 'a strong current body can finish an otherwise valid enrollment');

  await publish(targetStatus({target_session: session, tracks: [{...body, observation_strength: 'strong'}], selected_track_id: 11}));
  const stableRow = by('Tracks').children[0], stableRowChildren = [...stableRow.children];
  const listReplacements = by('Tracks').replaceChildrenCalls;
  stableRow.focus();
  for (let i = 0; i < 20; i++) {
    await publish(targetStatus({target_session: session, tracks: [{...body, observation_strength: 'strong',
      confidence: .55 + i / 100, distance_m: 1 + i / 100, depth_valid: i % 2 === 0,
      identity: {state: 'unknown', reason: i % 2 === 0 ? 'no_face' : 'confirming'}}], selected_track_id: 11}));
    assert.equal(by('Tracks').children[0], stableRow, 'confidence and depth polls retain the exact row button');
    assert.deepEqual(stableRow.children, stableRowChildren, 'row text changes retain child elements');
    assert.equal(document.activeElement, stableRow, 'focused track button survives changing observations');
    assert.equal(by('Tracks').replaceChildrenCalls, listReplacements, 'same ID order never rebuilds the list');
  }
  assert.match(stableRow.children[1].textContent, /距离未知/, 'stable row text still updates with current depth validity');
  const beforeRowGuards = requests.length;
  await publish(targetStatus({target_session: session, tracks: [weakBody], selected_track_id: 11}));
  assert.equal(by('Tracks').children[0], stableRow, 'weak transitions update the existing row');
  stableRow.emit('click'); await settle();
  assert.equal(requests.length, beforeRowGuards, 'reused click handler checks latest weak observation');
  await publish(targetStatus({target_session: session, tracks: [{...body, association_ambiguous: true}], selected_track_id: 11}));
  stableRow.emit('click'); await settle();
  assert.equal(requests.length, beforeRowGuards, 'reused click handler checks latest ambiguity');
  await publish(targetStatus({target_session: session, tracks: [body], selected_track_id: 11, enrollment: {active: true}}));
  stableRow.emit('click'); await settle();
  assert.equal(requests.length, beforeRowGuards, 'reused click handler checks current enrollment');
  await publish(targetStatus({target_session: session, tracks: [body], selected_track_id: 11}));
  now += 800; await tick(250); stableRow.emit('click'); await settle();
  assert.equal(requests.length, beforeRowGuards, 'reused click handler checks current camera freshness');
  await publish(targetStatus({tracks: [{...body, track_id: 12, selected: false}], selected_track_id: null}));
  stableRow.emit('click'); await settle();
  assert.equal(requests.length, beforeRowGuards, 'removed row cannot select a body that is no longer present');
  assert.notEqual(by('Tracks').children[0], stableRow, 'new track ID receives its own row');
  const currentRow = by('Tracks').children[0];
  currentRow.emit('click'); await settle();
  assert.deepEqual(requests.at(-1), {route: 'select', body: {track_id: 12}}, 'live row handler selects its current numeric ID');

  const occludedSession = {...waitingSession, state: 'waiting_occlusion', hold_remaining_s: 2.5, missing_age_s: .5};
  const unrelatedBody = {...body, track_id: 22, selected: false, bbox: [300, 30, 500, 440],
    depth_valid: true, distance_m: 2.2, identity: {state: 'matched', id: visitor.id, name: visitor.name}};
  name.focus(); name.emit('compositionstart');
  const originalDraft = name.value;
  await publish(targetStatus({target_session: occludedSession, tracks: [unrelatedBody], selected_track_id: 11}));
  assert.match(by('Target').textContent, /目标被遮挡，正在核对原目标.*剩余 2\.5 秒/, 'occlusion hold displays its remaining time');
  assert.doesNotMatch(by('Target').textContent, /主人|访客|2\.20 m/, 'another visible person is not substituted for the hidden target');
  assert.match(by('Session').textContent, /上次确认的本次目标：主人.*当前未看到目标/, 'occlusion retains the name only as historical confirmation');
  assert.equal(by('Tracks').children[0].getAttribute('aria-pressed'), 'false', 'unrelated person is not marked selected');
  assert.deepEqual(drawnBoxes, [[300, 30, 200, 410]], 'only the unrelated current box is drawn, never the hidden target');
  assert.deepEqual(drawnBoxStyles, ['#79b9f0'], 'unrelated person uses the unselected box style');
  assert.equal(by('Unlock').disabled, false, 'occluded target can be unlocked while other people remain visible');
  assert.equal(by('ConfirmTarget').disabled, true, 'occluded target cannot be confirmed');
  assert.equal(by('Enroll').disabled, true, 'occluded target cannot be enrolled');
  const occlusionRow = by('Tracks').children[0], beforeOcclusionActions = requests.length;
  const beforeOcclusionReplacement = by('Tracks').replaceChildrenCalls;
  by('ConfirmTarget').emit('click'); name.emit('compositionend'); by('EnrollForm').emit('submit'); await settle();
  assert.equal(requests.length, beforeOcclusionActions, 'occlusion action guards do not use another visible person');
  name.emit('compositionstart');
  now += 250; await tick(250);
  assert.match(by('Target').textContent, /剩余 2\.3 秒/, 'occlusion countdown advances without a new server response');
  assert.equal(by('Tracks').children[0], occlusionRow, 'countdown does not recreate unrelated rows');
  assert.equal(by('Tracks').replaceChildrenCalls, beforeOcclusionReplacement, 'countdown leaves the row list intact');
  assert.equal(document.activeElement, name, 'occlusion rendering retains draft focus');
  assert.equal(name.value, originalDraft, 'occlusion rendering retains draft text');
  assert.equal(name.isComposing, true, 'occlusion rendering retains Chinese composition');
  await publish(targetStatus({target_session: occludedSession, tracks: [{...unrelatedBody, selected: true}], selected_track_id: 11,
    enrollment: {active: true, samples: 4, required: 3}}));
  assert.equal(by('Tracks').children[0].getAttribute('aria-pressed'), 'false', 'retained selected ID prevents an unrelated selected flag taking over');
  assert.deepEqual(drawnBoxStyles, ['#79b9f0'], 'unrelated selected flag cannot paint the occluded target highlight');
  assert.equal(by('FinishEnroll').disabled, true, 'occlusion cannot finish enrollment using another person');
  by('FinishEnroll').emit('click'); await settle();
  assert.equal(requests.length, beforeOcclusionActions, 'occlusion finish handler rejects other visible people');
  await publish(targetStatus({target_session: {...occludedSession, hold_remaining_s: .1}, tracks: [unrelatedBody], selected_track_id: 11}));
  now += 150; await tick(250);
  assert.match(by('Session').textContent, /等待已结束/, 'occlusion grace expires locally while the camera is still fresh');
  assert.doesNotMatch(by('Session').textContent, /主人/, 'expired occlusion does not retain a historical target label');
  await publish(targetStatus({target_session: {...occludedSession, hold_remaining_s: 3.1}, tracks: [unrelatedBody], selected_track_id: 11}));
  assert.doesNotMatch(by('Session').textContent, /上次确认的本次目标/, 'occlusion holds beyond the three-second limit are not trusted');
  await publish(targetStatus({target_session: occludedSession, tracks: [unrelatedBody], selected_track_id: 11}));
  name.emit('compositionend'); by('Unlock').emit('click'); await settle();
  assert.deepEqual(requests.at(-1), {route: 'unlock', body: {}}, 'explicit unlock works in occlusion state');
  await publish(targetStatus({target_session: {...session, identity_basis: 'face_then_body', confirmation_source: 'face_match'},
    tracks: [body, unrelatedBody], selected_track_id: 11}));
  assert.match(by('Session').textContent, /已通过人脸确认.*当前人脸未核对/, 'recovery keeps prior face confirmation separate from fresh face evidence');
  assert.match(by('Target').textContent, /未看到人脸/, 'recovery does not invent a new face recognition');
  assert.deepEqual(drawnBoxStyles, ['#91efd0', '#79b9f0'], 'only recovered original target is highlighted');

  name.focus();
  const readyReid = {ready: true, selected_recovery_ready: true, error: null};
  await publish(targetStatus({target_session: session, selected_track_id: 11}));
  const controlsBeforeReadiness = ['Enroll', 'ConfirmTarget', 'Unlock'].map(id => by(id).disabled);
  await publish(targetStatus({target_session: session, selected_track_id: 11, appearance_reid: readyReid}));
  assert.match(by('TargetDetails').textContent, /短时遮挡找回已就绪（最多3秒）/, 'ready model and target expose recovery readiness');
  assert.deepEqual(['Enroll', 'ConfirmTarget', 'Unlock'].map(id => by(id).disabled), controlsBeforeReadiness, 'readiness hint changes no control behavior');
  assert.equal(document.activeElement, name, 'readiness hint retains name input focus');
  await publish(targetStatus({target_session: session, selected_track_id: 11,
    appearance_reid: {...readyReid, selected_recovery_ready: false}}));
  assert.match(by('TargetDetails').textContent, /请保持身体清晰可见片刻，正在准备遮挡找回/, 'ready model but unprepared target gets a preparation hint');
  await publish(targetStatus({target_session: session, selected_track_id: 11,
    appearance_reid: {ready: false, selected_recovery_ready: false, error: 'model_load_failed'}}));
  assert.match(by('TargetDetails').textContent, /短时遮挡找回暂不可用/, 'model errors show a brief unavailable hint');
  assert.doesNotMatch(by('TargetDetails').textContent, /model_load_failed/, 'model internals are not inserted into target details');
  await publish(targetStatus({target_session: session, selected_track_id: 11}));
  assert.doesNotMatch(by('TargetDetails').textContent, /遮挡找回/, 'older backends without readiness data keep existing details');
  await publish(targetStatus({target_session: session, selected_track_id: 11,
    appearance_reid: {ready: false, selected_recovery_ready: false, error: null}}));
  assert.doesNotMatch(by('TargetDetails').textContent, /遮挡找回/, 'a loading model is not described as ready');
  await publish(targetStatus({target_session: session, selected_track_id: null, tracks: [{...body, selected: false}], appearance_reid: readyReid}));
  assert.doesNotMatch(by('TargetDetails').textContent, /遮挡找回/, 'unselected body has no target readiness hint');
  await publish(targetStatus({target_session: occludedSession, selected_track_id: 11, tracks: [unrelatedBody], appearance_reid: readyReid}));
  assert.doesNotMatch(by('TargetDetails').textContent, /遮挡找回/, 'occlusion wait displays current waiting guidance only');
  await publish(targetStatus({target_session: waitingSession, selected_track_id: 11, tracks: [], appearance_reid: readyReid}));
  assert.doesNotMatch(by('TargetDetails').textContent, /遮挡找回/, 'detection wait has no readiness hint');
  await publish(targetStatus({target_session: session, selected_track_id: 11, appearance_reid: readyReid}));
  now += 800; await tick(250);
  assert.doesNotMatch(by('TargetDetails').textContent, /遮挡找回/, 'stale observations cannot claim recovery readiness');
  console.log('PASS: stable drafts/keyed rows; current-state guards; truthful face/target and bounded holds; no phantom geometry; weak observation restrictions; recovery readiness hints without control changes.');
})().catch(error => { console.error(error); process.exitCode = 1; });
