import test from 'node:test';
import assert from 'node:assert/strict';
import { parseToolReply, protocolJson, aiuiPacket, aiuiSignedUrl, aiuiConversation, decodeAiuiFrame, NetworkProvider, openaiMessages } from '../src/providers.mjs';

test('dynamic tool names and values do not depend on trigger phrases', () => {
  const reply = parseToolReply('{"type":"tools","calls":[{"name":"plugin_319","arguments":{"level":37}}]}', [{ name: 'plugin_319' }]);
  assert.equal(reply.content[0].name, 'plugin_319');
  assert.equal(reply.content[0].input.level, 37);
});
test('plain prose, undeclared calls and malformed arguments cannot execute', () => {
  for (const value of ['已播放', '{"type":"tools","calls":[{"name":"shell","arguments":{}}]}', '{"type":"tools","calls":[{"name":"x","arguments":[]}]}']) {
    assert.throws(() => parseToolReply(value, [{ name: 'x' }]));
  }
});
test('AIUI request uses documented prompt, full conversation and numeric request id', () => {
  const packet = aiuiPacket({ appid: 'fake', sn: 'fake', requestId: '123456', prompt: 'tools', messages: [{ role: 'user', content: '到了再放歌' }] });
  assert.equal(packet.parameter.nlp.prompt, 'tools');
  assert.equal(packet.parameter.nlp.new_session, 'true');
  assert.match(Buffer.from(packet.payload.text.text, 'base64').toString(), /到了再放歌/);
  assert.match(aiuiSignedUrl('fake', 'fake'), /^wss:\/\/aiui\.xf-yun\.com\/v3\/aiint\/sos\?/);
});
test('online provider failures do not invoke local inference', async () => {
  let local = 0;
  const provider = new NetworkProvider({ network: () => 'online', online: { complete: async () => { throw new Error('cloud'); } }, offline: { complete: async () => { local++; } } });
  await assert.rejects(provider.complete({}), /cloud/); assert.equal(local, 0);
});
test('unknown connectivity blocks both providers', async () => {
  const provider = new NetworkProvider({ network: () => 'unknown', online: { complete: () => assert.fail() }, offline: { complete: () => assert.fail() } });
  await assert.rejects(provider.complete({}), /network_unknown/);
});
test('confirmed offline prepares the local model before inference', async () => {
  const calls = [];
  const provider = new NetworkProvider({ network: () => 'offline', online: { complete: () => assert.fail() }, ensureLocal: async () => calls.push('start'), offline: { complete: async () => calls.push('infer') } });
  await provider.complete({}); assert.deepEqual(calls, ['start', 'infer']);
});
test('tool results retain call ids for local model multi-step continuation', () => {
  const messages = openaiMessages({ systemPrompt: 'luka', messages: [
    { role: 'assistant', content: [{ type: 'tool_use', id: 'nav1', name: 'navigate', input: { id: 'living' } }] },
    { role: 'user', content: [{ type: 'tool_result', tool_use_id: 'nav1', content: '{"state":"SUCCEEDED"}' }] },
  ] });
  assert.equal(messages[1].tool_calls[0].id, 'nav1');
  assert.deepEqual(messages[2], { role: 'tool', tool_call_id: 'nav1', content: '{"state":"SUCCEEDED"}' });
});
test('AIUI binary websocket messages are decoded as UTF8 JSON', () => {
  const frame = { header: { status: 2, code: 0 } };
  const bytes = new TextEncoder().encode(JSON.stringify(frame));
  assert.deepEqual(decodeAiuiFrame(bytes.buffer), frame);
  assert.deepEqual(decodeAiuiFrame(JSON.stringify(frame)), frame);
});
test('flat AIUI protocol preserves dynamic tool arguments and final responses', () => {
  const result = parseToolReply('{"tool":"dynamic_nav","args":{"id":"room_82"}}', [{ name: 'dynamic_nav' }]);
  assert.deepEqual(result.content[0].input, { id: 'room_82' });
  assert.equal(parseToolReply('{"answer":"完成"}').content[0].text, '完成');
  assert.equal(parseToolReply('{"clarify":"哪个客厅？"}').content[0].text, '哪个客厅？');
});
test('AIUI transcript exposes actual result IDs without nested JSON string escaping', () => {
  const text = aiuiConversation([{ role: 'user', content: [{ type: 'tool_result', tool_use_id: 'call1', content: '{"operation_id":"op_73","state":"ACCEPTED"}' }] }]);
  assert.match(text, /"operation_id":"op_73"/);
  assert.equal(text.includes('\\"'), false);
});
test('a Moss tool-result user message does not replace the actual user goal', () => {
  const packet = aiuiPacket({ appid: 'fake', sn: 'fake', requestId: '1', prompt: 'fake', messages: [
    { role: 'user', content: '到了之后播放小星星' },
    { role: 'user', content: [{ type: 'tool_result', tool_use_id: '1', content: '{"state":"SUCCEEDED"}' }] },
  ] });
  assert.match(Buffer.from(packet.payload.text.text, 'base64').toString(), /^当前真实用户任务："到了之后播放小星星"/);
});
test('complete JSON with transport punctuation keeps exact values; broken bodies and multiple objects fail', () => {
  assert.deepEqual(protocolJson('{"tool":"x","args":{"id":"room } 7"}}</'), { tool: 'x', args: { id: 'room } 7' } });
  for (const bad of ['{"tool":"x","args":{"id":"y"}]}}', '{"tool":"x","args":{}} {"tool":"y","args":{}}']) {
    assert.throws(() => protocolJson(bad));
  }
});
