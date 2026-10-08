// Real AIUI + real Moss loop. Every executor below is an in-memory simulation.
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import Ajv from 'ajv';
import { MossAgent } from '../vendor/moss/dist/core/agent/moss-agent.js';
import { InMemorySessionStore } from '../vendor/moss/dist/core/session/session.js';
import { AiuiProvider } from '../src/providers.mjs';

const evidenceRoot = process.env.LUKA_AGENT_EVIDENCE ?? '/home/sunrise/luka_data/runtime/agent/acceptance';
await mkdir(evidenceRoot, { recursive: true });
const replies = [];
const provider = new AiuiProvider({ onReply(text) { replies.push(text); console.log(JSON.stringify({ gate_model_reply: text })); } });
const trace = [];
const destinationId = 'room_' + randomUUID().slice(0, 8);
let navigationStarted = false;
let arrived = false;
let statusPolls = 0;
let musicPlayed = false;
const agent = new MossAgent({
  llmProvider: provider, model: 'aiui-v3', sessionStore: new InMemorySessionStore(),
  baseSystemPrompt: '你是露卡。在模拟验收中按用户要求编排任务，使用工具反馈判断执行状态。',
  domainPrompt: false, enableSteering: false, enableFollowUpGuard: false,
  includeAgentBehaviorPrompt: false, includeLanguagePolicyPrompt: false,
  hooks: { onToolResult(call, result) {
    const event = { tool: call.name, error: Boolean(result.isError) };
    trace.push(event); console.log(JSON.stringify({ gate_tool: event }));
  } },
});
const ajv = new Ajv();
function register(name, description, properties, execute, { required = Object.keys(properties), sideEffectClass = 'runtime_state' } = {}) {
  const schema = { type: 'object', properties, required, additionalProperties: false };
  const validate = ajv.compile(schema);
  agent.tools.register({ name, description, metadata: { sideEffectClass }, inputSchema: schema,
    async execute(input) {
      if (!validate(input)) throw new Error('tool parameters do not match schema');
      console.log(JSON.stringify({ gate_request: name, input }));
      const value = await execute(input);
      console.log(JSON.stringify({ gate_result: name, value }));
      return JSON.stringify(value);
    } });
}
register('destinations', '查询当前有效目的地及其稳定ID，可选query用于搜索。导航必须使用查询到的ID。', { query: { type: 'string' } }, () => ({ destinations: [{ id: destinationId, name: '客厅' }] }), { required: [], sideEffectClass: 'readonly' });
register('navigation_start', '模拟提交导航。返回ACCEPTED仅表示受理，必须查询navigation_status确认到达。', { destination_id: { type: 'string' } }, input => {
  assert.equal(input.destination_id, destinationId); assert.equal(navigationStarted, false);
  navigationStarted = true; return { operation_id: 'nav_gate', state: 'ACCEPTED', simulation: true };
});
register('navigation_status', '查询模拟导航的实际进度。RUNNING需要继续等待，SUCCEEDED才表示到达。', { operation_id: { type: 'string' } }, input => {
  assert.equal(input.operation_id, 'nav_gate'); assert.equal(navigationStarted, true);
  statusPolls++; arrived = statusPolls >= 2;
  return { operation_id: 'nav_gate', state: arrived ? 'SUCCEEDED' : 'RUNNING', simulation: true };
});
register('music_play', '模拟播放指定歌曲。只在用户要求的前置任务已成功后执行。', { query: { type: 'string' } }, input => {
  assert.equal(arrived, true, 'music cannot start before confirmed arrival');
  assert.ok(input.query.includes('小星星')); assert.equal(musicPlayed, false);
  musicPlayed = true; return { state: 'SUCCEEDED', playing: '小星星', simulation: true };
});
const evidence = { started: new Date().toISOString(), provider: 'aiui', moss_commit: 'e0f163d8fa18dd8913854d6ccb6acbd0e084d15c', real_robot_commands: 0 };
try {
  const result = await agent.chat('gate-' + randomUUID(), '请带我去客厅，到了之后再播放小星星。', { maxTurns: 12 });
  assert.equal(arrived, true); assert.equal(musicPlayed, true);
  assert.ok(trace.filter(t => t.tool === 'navigation_status').length >= 2);
  assert.equal(trace.filter(t => t.error).length, 0);
  evidence.pass = true; evidence.answer = result.response; evidence.trace = trace;
  console.log(JSON.stringify({ pass: true, trace, answer: result.response, real_robot_commands: 0 }));
} catch (error) {
  evidence.pass = false; evidence.error = error.code ?? error.name; evidence.trace = trace; evidence.model_replies = replies;
  console.log(JSON.stringify({ pass: false, error: evidence.error, trace, real_robot_commands: 0 }));
  process.exitCode = 1;
} finally {
  await agent.close();
  await writeFile(path.join(evidenceRoot, `aiui_moss_gate_${Date.now()}.json`), JSON.stringify(evidence, null, 2), { mode: 0o600 });
  await writeFile(path.join(evidenceRoot, 'aiui_moss_gate.json'), JSON.stringify(evidence, null, 2), { mode: 0o600 });
}
