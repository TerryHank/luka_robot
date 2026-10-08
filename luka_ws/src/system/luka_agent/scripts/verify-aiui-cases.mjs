import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import Ajv from 'ajv';
import { MossAgent } from '../vendor/moss/dist/core/agent/moss-agent.js';
import { InMemorySessionStore } from '../vendor/moss/dist/core/session/session.js';
import { AiuiProvider } from '../src/providers.mjs';

const cases = [
  { text: '麻烦放一下小星星，可以吗？', expected: 'play' },
  { text: '先别放歌，告诉我现在可以去哪些地方。', expected: 'read' },
  { text: '如果我说播放小星星，你会怎么做？现在只是问问。', expected: 'none' },
  { text: '你可以帮我导航吗？我先了解一下你的能力。', expected: 'none' },
  { text: '去客厅吧。', expected: 'clarify' },
];
const results = [];
const ajv = new Ajv();
for (const item of cases) {
  const calls = [];
  const provider = new AiuiProvider({ onReply: text => console.log(JSON.stringify({ reply: text })),
    onAuthorizationReply: text => console.log(JSON.stringify({ authorization_reply: text })) });
  const agent = new MossAgent({ llmProvider: provider, model: 'aiui-v3', sessionStore: new InMemorySessionStore(),
    baseSystemPrompt: '你是露卡。业务动作只按真实用户请求执行。两个客厅分别在不同楼层，只有请求执行导航时同名目标才需要澄清；查询目的地时列出全部结果。能力询问、否定和假设应直接解释，不执行动作。',
    domainPrompt: false, includeAgentBehaviorPrompt: false, includeLanguagePolicyPrompt: false,
    enableFollowUpGuard: false, enableSteering: false,
    hooks: { async onBeforeToolExec(request) {
      if (!request.tool.metadata?.lukaMutation) return { approved: true };
      return provider.authorize({ user_request: item.text, candidate: {
        tool: request.tool.name, description: request.tool.description, arguments: request.input }, execution_results: calls,
        abortSignal: request.abortSignal });
    } } });
  for (const definition of [
    { name: 'destinations', description: '列出当前可导航目的地，有两个同名客厅', properties: {}, result: { destinations: [{ id: 'room1', name: '客厅', floor: '一楼' }, { id: 'room2', name: '客厅', floor: '二楼' }] } },
    { name: 'music_play', description: '立即播放指定歌曲，问能力、假设或否定不得执行', properties: { query: { type: 'string' } }, result: { state: 'SUCCEEDED', simulation: true } },
    { name: 'navigate', description: '导航到唯一确认的目的地ID，不能自行选择两个同名目标之一', properties: { destination_id: { type: 'string' } }, result: { state: 'SUCCEEDED', simulation: true } },
  ]) {
    const schema = { type: 'object', properties: definition.properties, required: Object.keys(definition.properties), additionalProperties: false };
    const validate = ajv.compile(schema);
    agent.tools.register({ name: definition.name, description: definition.description,
    metadata: { sideEffectClass: 'runtime_state', lukaMutation: definition.name !== 'destinations' }, inputSchema: schema,
    async execute(args) { if (!validate(args)) throw new Error('invalid_parameter_schema'); calls.push({ tool: definition.name, args }); return JSON.stringify(definition.result); } });
  }
  try {
    const answer = await agent.chat(randomUUID(), item.text, { maxTurns: 8 });
    const effects = calls.filter(call => call.tool !== 'destinations');
    if (item.expected === 'play') assert.equal(effects.filter(call => call.tool === 'music_play').length, 1);
    else assert.equal(effects.length, 0);
    if (item.expected === 'read') assert.ok(calls.some(call => call.tool === 'destinations'));
    results.push({ ...item, pass: true, calls, answer: answer.response });
  } catch (error) { results.push({ ...item, pass: false, calls, error: error.code ?? error.name }); }
  finally { await agent.close(); }
  console.log(JSON.stringify(results.at(-1)));
}
const root = '/home/sunrise/luka_data/runtime/agent/acceptance';
await mkdir(root, { recursive: true });
await writeFile(root + '/aiui_semantic_cases.json', JSON.stringify({ pass: results.every(item => item.pass), results, real_robot_commands: 0 }, null, 2));
if (results.some(item => !item.pass)) process.exitCode = 1;
