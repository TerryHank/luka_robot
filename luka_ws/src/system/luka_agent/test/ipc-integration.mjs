// Linux-only integration: real service + Moss SDK, local model/backend fixtures.
import assert from 'node:assert/strict';
import http from 'node:http';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { mkdtemp, writeFile, stat, rm } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
if (process.platform !== 'linux') throw new Error('Run this Unix socket fixture on Linux');
const folder = await mkdtemp(path.join(os.tmpdir(), 'luka-moss-ipc-'));
const operations = new Map(); let effects = 0;
const reply = (response, data) => { response.writeHead(200, { 'Content-Type': 'application/json' }); response.end(JSON.stringify(data)); };
const server = http.createServer(async (request, response) => {
  let bytes = ''; for await (const data of request) bytes += data;
  const body = bytes ? JSON.parse(bytes) : {};
  if (request.url === '/api/assistant/tools') return reply(response, { generation: 1, capabilities: [{ name: 'music_play', description: 'Play test audio', ready: true, mutation: true,
    input_schema: { type: 'object', properties: { query: { type: 'string' } }, required: ['query'], additionalProperties: false } }] });
  if (request.url === '/api/assistant/execute') {
    effects++; const operation = { operation_id: body.operation_id, task_id: body.task_id, tool: body.tool, state: 'SUCCEEDED', result: { state: 'SUCCEEDED', message: 'fixture played' } };
    operations.set(body.operation_id, operation); return reply(response, { operation });
  }
  if (request.url === '/api/assistant/cancel-task') return reply(response, { state: 'CANCEL_REQUESTED' });
  if (request.url.startsWith('/api/assistant/operations/')) return reply(response, operations.get(request.url.split('/').at(-1)));
  if (request.url === '/model') {
    const system = body.messages?.[0]?.content ?? '';
    if (system.startsWith('判断用户是否授权')) return reply(response, { choices: [{ message: { content: '{"approved":true,"reason":"fixture"}' } }] });
    const question = body.messages.find(message => message.role === 'user')?.content ?? '';
    if (question === 'slow') { setTimeout(() => reply(response, { choices: [{ message: { content: 'slow response' } }] }), 5000); return; }
    if (body.messages.some(message => message.role === 'tool')) return reply(response, { choices: [{ message: { content: 'fixture done' } }] });
    return reply(response, { choices: [{ message: { content: null, tool_calls: [{ id: 'fixture-call', type: 'function', function: { name: 'music_play', arguments: '{"query":"fixture"}' } }] } }] });
  }
  response.writeHead(404); response.end();
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const port = server.address().port;
const config = path.join(folder, 'config.json');
await writeFile(config, JSON.stringify({ local_llm: { url: `http://127.0.0.1:${port}/model`, model: 'fixture' } }), { mode: 0o600 });
const child = spawn(process.execPath, [path.join(root, 'src/service.mjs')], { env: { ...process.env,
  LUKA_AGENT_CONFIG: config, LUKA_AGENT_RUNTIME: path.join(folder, 'runtime'), LUKA_AGENT_BACKEND: `http://127.0.0.1:${port}` }, stdio: ['ignore', 'pipe', 'pipe'] });
let logs = ''; child.stdout.on('data', data => { logs += data; }); child.stderr.on('data', data => { logs += data; });
let socket;
try {
  const deadline = Date.now() + 10000;
  while (!logs.includes('MOSS_BUSINESS_READY') && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 50));
  assert.match(logs, /MOSS_BUSINESS_READY/);
  const file = path.join(folder, 'runtime/moss.sock');
  assert.equal((await stat(file)).mode & 0o777, 0o600);
  socket = net.createConnection(file); await new Promise(resolve => socket.once('connect', resolve));
  let buffer = ''; const events = [];
  const send = value => socket.write(JSON.stringify(value) + '\n');
  socket.on('data', data => {
    buffer += data;
    while (buffer.includes('\n')) {
      const end = buffer.indexOf('\n'), event = JSON.parse(buffer.slice(0, end)); buffer = buffer.slice(end + 1);
      events.push(event);
      if (event.type === 'ensure_local') send({ type: 'local_ready', request_id: event.request_id, ok: true });
    }
  });
  const heartbeat = setInterval(() => send({ type: 'network', state: 'offline', timestamp: Date.now() / 1000 }), 200);
  try {
    send({ type: 'network', state: 'offline', timestamp: Date.now() / 1000 });
    send({ type: 'create_task', task_id: 'task1', session_id: 'fixture', text: 'play fixture' });
    const wait = async (predicate, seconds = 15) => {
      const until = Date.now() + seconds * 1000;
      while (!predicate() && Date.now() < until) await new Promise(resolve => setTimeout(resolve, 30));
      assert.ok(predicate(), JSON.stringify(events));
    };
    await wait(() => events.some(event => event.type === 'answer' && event.task_id === 'task1'));
    assert.equal(effects, 1);
    assert.equal(events.find(event => event.type === 'answer').text, 'fixture done');
    send({ type: 'create_task', task_id: 'task2', session_id: 'fixture2', text: 'slow' });
    await wait(() => events.some(event => event.task_id === 'task2' && event.phase === 'planning'));
    send({ type: 'cancel_task', task_id: 'task2' });
    await wait(() => events.some(event => event.type === 'cancelled' && event.task_id === 'task2'));
    assert.equal(effects, 1);
    console.log(JSON.stringify({ pass: true, real_moss_service: true, unix_socket_mode: '600', task1_effects: 1, cancelled_task2_effects: 0, model_and_backend: 'fixtures', real_robot_commands: 0 }));
  } finally { clearInterval(heartbeat); }
} finally {
  socket?.destroy(); child.kill('SIGTERM');
  await new Promise(resolve => { if (child.exitCode !== null) resolve(); else child.once('exit', resolve); });
  server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  await rm(folder, { recursive: true, force: true });
}
