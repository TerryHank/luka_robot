import { randomUUID } from 'node:crypto';

export class BackendError extends Error {
  constructor(code) { super(String(code).replace(/https?:\/\/\S+/g, '[url]')); this.code = code; }
}

export class BusinessBackend {
  constructor({ base = 'http://127.0.0.1:8503', fetchImpl = fetch } = {}) {
    if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw new BackendError('backend_must_be_local');
    this.base = base; this.fetch = fetchImpl;
  }

  async request(route, body, signal, timeout = 30000) {
    const combined = signal ? AbortSignal.any([signal, AbortSignal.timeout(timeout)]) : AbortSignal.timeout(timeout);
    let response;
    try { response = await this.fetch(this.base + route, { signal: combined, method: body === undefined ? 'GET' : 'POST',
      headers: { 'Content-Type': 'application/json' }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) }); }
    catch (error) { if (signal?.aborted) throw error; throw new BackendError('backend_response_unknown'); }
    const value = await response.json();
    if (!response.ok) throw new BackendError(value.error ?? 'backend_rejected');
    return value;
  }

  async catalog(signal) { return this.request('/api/assistant/tools', undefined, signal, 5000); }

  async execute(name, args, task, signal) {
    const operationId = randomUUID();
    const body = { tool: name, arguments: args, source: task.text, generation: task.generation,
      task_id: task.id, operation_id: operationId };
    try {
      const response = await this.request('/api/assistant/execute', body, signal);
      return response.operation;
    } catch (error) {
      if (error.code !== 'backend_response_unknown') throw error;
      // The mutation may have been accepted. Query this exact operation, never resubmit it.
      try { return await this.request('/api/assistant/operations/' + operationId, undefined, signal, 5000); }
      catch { throw new BackendError('operation_unconfirmed:' + operationId); }
    }
  }

  async cancel(taskId) { return this.request('/api/assistant/cancel-task', { task_id: taskId }, undefined, 10000); }
}
