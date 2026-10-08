import test from 'node:test';
import assert from 'node:assert/strict';
import { MossAgent } from '../vendor/moss/dist/core/agent/moss-agent.js';
import { InMemorySessionStore } from '../vendor/moss/dist/core/session/session.js';

test('Moss re-reads changing operation state and consumes the new result', async () => {
  let turns = 0, polls = 0;
  const provider = {
    id: 'fixture', displayName: 'fixture', capabilities: { streaming: true },
    async complete() {
      turns++;
      return turns < 3 ? { stopReason: 'tool_use', content: [{ type: 'tool_use', id: 'call' + turns, name: 'operation_status', input: { id: 'op1' } }] }
        : { stopReason: 'end_turn', content: [{ type: 'text', text: 'done' }] };
    },
    async stream(options, event) {
      const reply = await this.complete(options);
      event({ type: 'message_start' });
      for (const item of reply.content) {
        event({ type: 'content_block_start', ...(item.type === 'tool_use' ? { toolUse: { id: item.id, name: item.name } } : {}) });
        event(item.type === 'tool_use' ? { type: 'content_block_delta', partialJson: JSON.stringify(item.input) } : { type: 'content_block_delta', text: item.text });
        event({ type: 'content_block_stop' });
      }
      event({ type: 'message_delta', stopReason: reply.stopReason }); event({ type: 'message_stop' }); return reply;
    },
  };
  const agent = new MossAgent({ llmProvider: provider, sessionStore: new InMemorySessionStore(), domainPrompt: false,
    includeAgentBehaviorPrompt: false, enableSteering: false, enableFollowUpGuard: false });
  agent.tools.register({ name: 'operation_status', description: 'Read changing task status',
    metadata: { sideEffectClass: 'runtime_state' }, inputSchema: { type: 'object', properties: { id: { type: 'string' } } },
    async execute() { return JSON.stringify({ state: ++polls === 1 ? 'RUNNING' : 'SUCCEEDED' }); } });
  try { await agent.chat('live-state-test', 'Wait for the task'); assert.equal(polls, 2); }
  finally { await agent.close(); }
});
