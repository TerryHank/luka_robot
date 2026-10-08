import test from 'node:test';
import assert from 'node:assert/strict';
import { BusinessBackend } from '../src/backend.mjs';

test('lost mutation response queries the same operation and never sends it twice', async () => {
  const calls = [];
  let id;
  const backend = new BusinessBackend({ fetchImpl: async (url, request) => {
    calls.push({ url, method: request.method });
    if (request.method === 'POST') { id = JSON.parse(request.body).operation_id; throw new Error('reply lost'); }
    assert.equal(url.endsWith('/' + id), true);
    return { ok: true, json: async () => ({ operation_id: id, state: 'ACCEPTED' }) };
  } });
  const result = await backend.execute('plugin_effect', {}, { id: 'task', text: 'an arbitrary request', generation: 1 });
  assert.equal(result.state, 'ACCEPTED'); assert.equal(calls.filter(call => call.method === 'POST').length, 1);
});
test('backend cannot target a remote URL', () => {
  assert.throws(() => new BusinessBackend({ base: 'http://example.com' }), /backend_must_be_local/);
});
