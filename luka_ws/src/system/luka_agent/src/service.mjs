import net from 'node:net';
import { chmod, mkdir, readFile, writeFile, unlink, lstat } from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import Ajv from 'ajv';
import { MossAgent } from '../vendor/moss/dist/core/agent/moss-agent.js';
import { InMemorySessionStore } from '../vendor/moss/dist/core/session/session.js';
import { AiuiProvider, LocalProvider, NetworkProvider, ProviderError } from './providers.mjs';
import { BusinessBackend } from './backend.mjs';

const runtime = process.env.LUKA_AGENT_RUNTIME ?? '/home/sunrise/luka_data/runtime/agent';
const configFile = process.env.LUKA_AGENT_CONFIG ?? '/home/sunrise/.config/luka_xiaozhi/config.json';
const config = JSON.parse(await readFile(configFile, 'utf8'));
await mkdir(runtime, { recursive: true, mode: 0o700 });
const socketPath = path.join(runtime, 'moss.sock');
const lockPath = path.join(runtime, 'owner.json');
try {
  const old = JSON.parse(await readFile(lockPath, 'utf8'));
  try { process.kill(old.pid, 0); throw new Error('another Moss business owner is active'); }
  catch (error) { if (error.code !== 'ESRCH') throw error; }
  await unlink(lockPath);
} catch (error) { if (error.code !== 'ENOENT') throw error; }
await writeFile(lockPath, JSON.stringify({ pid: process.pid }), { flag: 'wx', mode: 0o600 });
try { const item = await lstat(socketPath); if (!item.isSocket()) throw new Error('socket path is occupied'); await unlink(socketPath); }
catch (error) { if (error.code !== 'ENOENT') throw error; }

const backend = new BusinessBackend({ base: process.env.LUKA_AGENT_BACKEND ?? 'http://127.0.0.1:8503' });
const sessions = new InMemorySessionStore();
const tasks = new Map();
const agents = new Map();
const callOwners = new Map();
const terminal = new Set(['completed', 'responded', 'submitted', 'failed', 'cancelled']);
const ajv = new Ajv();
const taskFile = path.join(runtime, 'tasks.json');
try {
  const previous = JSON.parse(await readFile(taskFile, 'utf8'));
  for (const task of previous) tasks.set(task.id, { ...task, phase: terminal.has(task.phase) ? task.phase : 'interrupted', peer: null });
} catch (error) { if (error.code !== 'ENOENT') throw error; }
async function persist() {
  const values = [...tasks.values()].slice(-100).map(({ controller, peer, ...task }) => task);
  const temporary = taskFile + '.tmp';
  await writeFile(temporary, JSON.stringify(values, null, 2), { mode: 0o600 });
  await import('node:fs/promises').then(fs => fs.rename(temporary, taskFile));
}
let persistence = Promise.resolve();
function save() { persistence = persistence.then(persist).catch(() => console.error('task_journal_write_failed')); }
function emit(task, type, data = {}) {
  const event = { type, task_id: task.id, session_id: task.session, phase: task.phase,
    execution_mode: 'audio_live_motion_disabled', timestamp: Date.now() / 1000, ...data };
  task.peer?.send(event); save();
}

function network(peer) {
  return Date.now() - peer.networkAt <= 3000 ? peer.network : 'unknown';
}
async function localReady(peer, signal) {
  if (signal?.aborted) throw new DOMException('cancelled', 'AbortError');
  const id = randomUUID();
  await new Promise((resolve, reject) => {
    const cancel = () => { clearTimeout(timeout); peer.local.delete(id); reject(new DOMException('cancelled', 'AbortError')); };
    const timeout = setTimeout(() => { peer.local.delete(id); signal?.removeEventListener('abort', cancel); reject(new ProviderError('local_model_not_ready')); }, 65000);
    signal?.addEventListener('abort', cancel, { once: true });
    peer.local.set(id, value => { clearTimeout(timeout); signal?.removeEventListener('abort', cancel); value.ok ? resolve() : reject(new ProviderError('local_model_start_failed')); });
    peer.send({ type: 'ensure_local', request_id: id });
  });
}

async function runTask(task) {
  const peer = task.peer;
  let provider;
  try {
    const catalog = await backend.catalog(task.controller.signal);
    task.generation = catalog.generation;
    task.phase = 'planning'; emit(task, 'task_event');
    provider = new NetworkProvider({ network: () => network(peer), online: new AiuiProvider(config),
      offline: new LocalProvider(config.local_llm), ensureLocal: signal => localReady(peer, signal) });
    let entry = agents.get(task.session);
    if (!entry) {
      const agent = new MossAgent({ llmProvider: provider, model: 'luka-dynamic', sessionStore: sessions,
        workspaceDir: path.join(runtime, 'moss'), baseSystemPrompt: '你是露卡，帮助用户完成机器人业务任务。运动能力尚未完成实车验收，未就绪时说明原因。根据真实结果回复，允许任务组合、同义表达和上下文指代。',
        domainPrompt: false, includeAgentBehaviorPrompt: false, includeLanguagePolicyPrompt: false,
        enableFollowUpGuard: false, enableSteering: false, toolTimeoutMs: 35000, maxAgentTurns: 20,
        hooks: { async onBeforeToolExec(request) {
          const active = tasks.get(request.runId);
          if (!active || active.controller.signal.aborted) return { approved: false, reason: 'task_cancelled' };
          callOwners.set(request.toolCallId, active.id);
          if (!request.tool.metadata?.lukaMutation) return { approved: true };
          return entry.provider.authorize({ user_request: active.text, candidate: {
            tool: request.tool.name, description: request.tool.description, arguments: request.input },
            execution_results: active.operations, session_context: [...tasks.values()].filter(item => item.session === active.session && item.id !== active.id).slice(-4)
              .map(item => ({ user_request: item.text, phase: item.phase, operations: item.operations })), abortSignal: request.abortSignal });
        }, onToolResult(call, result) {
          const active = tasks.get(callOwners.get(call.id));
          if (!active) return;
          active.trace.push({ name: call.name, error: Boolean(result.isError) });
          emit(active, 'task_event', { tool: call.name, tool_failed: Boolean(result.isError) });
        } },
      });
      entry = { agent, active: task, provider, registered: new Set() }; agents.set(task.session, entry);
    } else {
      if (entry.active && !terminal.has(entry.active.phase)) throw new ProviderError('session_busy');
      entry.provider.network = () => network(peer);
      entry.provider.ensureLocal = signal => localReady(peer, signal);
      entry.active = task;
    }
    task.provider = network(peer) === 'offline' ? 'local_qwen' : 'aiui';
    for (const name of entry.registered) entry.agent.tools.remove(name);
    entry.registered.clear();
    for (const item of catalog.capabilities ?? []) {
      const validate = ajv.compile(item.input_schema);
      entry.agent.tools.register({ name: item.name, description: item.description + (item.ready ? '' : '。当前未就绪：' + item.reason),
        inputSchema: item.input_schema, metadata: { sideEffectClass: 'runtime_state', timeoutMs: 65000, lukaMutation: item.mutation },
        async execute(args, toolContext) {
          const active = tasks.get(toolContext.runId);
          if (!active || active.controller.signal.aborted) throw new Error('task_cancelled');
          if (!validate(args)) throw new Error('invalid_tool_parameters');
          if (item.mutation && !item.cancel && (await backend.catalog(active.controller.signal)).generation !== active.generation) {
            throw new Error('task_invalidated_by_takeover');
          }
          active.phase = 'executing'; emit(active, 'task_event', { tool: item.name });
          const operation = await backend.execute(item.name, args, active, active.controller.signal);
          active.operations.push(operation);
          emit(active, 'task_event', { tool: item.name, operation_id: operation.operation_id, operation_state: operation.state });
          return JSON.stringify({ ...(operation.result?.result && typeof operation.result.result === 'object' ? operation.result.result : {}),
            ...operation.result, state: operation.state, operation_id: operation.result?.operation_id ?? operation.operation_id });
        },
      });
      entry.registered.add(item.name);
    }
    const result = await entry.agent.chat(task.session, task.text, { abortSignal: task.controller.signal, maxTurns: 20, runId: task.id });
    if (task.controller.signal.aborted) return;
    const pending = task.operations.some(operation => ['ACCEPTED', 'RUNNING', 'UNKNOWN', 'CANCEL_REQUESTED'].includes(operation.state));
    task.phase = task.trace.some(item => item.error) ? 'failed' : pending ? 'submitted' : task.operations.length ? 'completed' : 'responded';
    task.answer = result.response;
    emit(task, 'answer', { text: task.answer, provider: task.provider, trace: task.trace });
  } catch (error) {
    if (task.controller.signal.aborted) return;
    task.phase = 'failed'; task.error = error.code ?? error.name;
    emit(task, 'error', { error: task.error });
  }
}

const server = net.createServer(socket => {
  const peer = { network: 'unknown', networkAt: 0, local: new Map(), buffer: '', send: value => {
    if (!socket.destroyed) socket.write(JSON.stringify(value) + '\n');
  } };
  socket.setEncoding('utf8');
  socket.on('data', bytes => {
    peer.buffer += bytes;
    if (peer.buffer.length > 262144) return socket.destroy();
    while (peer.buffer.includes('\n')) {
      const end = peer.buffer.indexOf('\n'), line = peer.buffer.slice(0, end); peer.buffer = peer.buffer.slice(end + 1);
      let request;
      try { request = JSON.parse(line); } catch { socket.destroy(); return; }
      if (request.type === 'network' && ['online', 'offline', 'unknown'].includes(request.state)) {
        if (Math.abs(Date.now() / 1000 - request.timestamp) <= 3) { peer.network = request.state; peer.networkAt = Date.now(); }
      } else if (request.type === 'local_ready') {
        peer.local.get(request.request_id)?.(request); peer.local.delete(request.request_id);
      } else if (request.type === 'create_task') {
        if (typeof request.text !== 'string' || !request.text.trim() || request.text.length > 4000 || typeof request.session_id !== 'string') {
          peer.send({ type: 'error', error: 'invalid_task' }); continue;
        }
        const task = { id: request.task_id ?? randomUUID(), session: request.session_id, text: request.text,
          phase: 'queued', peer, trace: [], operations: [], controller: new AbortController() };
        if (tasks.has(task.id)) { peer.send({ type: 'error', task_id: task.id, error: 'duplicate_task' }); continue; }
        tasks.set(task.id, task); emit(task, 'task_event'); void runTask(task);
      } else if (request.type === 'cancel_task') {
        const task = tasks.get(request.task_id);
        if (!task || task.peer !== peer) { peer.send({ type: 'error', error: 'unknown_task' }); continue; }
        task.controller.abort(); task.phase = 'cancel_requested';
        void backend.cancel(task.id).then(result => {
          task.phase = 'cancelled'; emit(task, 'cancelled', { stop_confirmation: result.state });
        }).catch(() => emit(task, 'cancelled', { stop_confirmation: 'UNKNOWN' }));
      } else if (request.type === 'hello') peer.send({ type: 'hello', runtime: 'moss', motion_enabled: false });
    }
  });
  socket.on('error', () => {});
  socket.on('close', () => {
    for (const task of tasks.values()) if (task.peer === peer && !terminal.has(task.phase)) {
      task.controller.abort(); task.phase = 'interrupted'; save(); void backend.cancel(task.id).catch(() => {});
    }
  });
});
server.listen(socketPath, async () => { await chmod(socketPath, 0o600); console.log('MOSS_BUSINESS_READY'); });
let closing = false;
async function close() {
  if (closing) return; closing = true;
  for (const task of tasks.values()) task.controller?.abort();
  for (const entry of agents.values()) await entry.agent.close();
  save(); await persistence; server.close();
  await unlink(socketPath).catch(() => {}); await unlink(lockPath).catch(() => {}); process.exit(0);
}
process.on('SIGTERM', () => void close()); process.on('SIGINT', () => void close());
