const MAX_LINE = 8 * 1024 * 1024;

export class NDJSONParser {
  constructor() {
    this.buffer = '';
    this.started = false;
    this.ended = false;
    this.sequence = 0;
    this.sampleRate = null;
  }

  push(text) {
    this.buffer += text;
    const events = [];
    let boundary;
    while ((boundary = this.buffer.indexOf('\n')) !== -1) {
      const line = this.buffer.slice(0, boundary).trim();
      this.buffer = this.buffer.slice(boundary + 1);
      if (line.length > MAX_LINE) throw new Error('Pacote de audio muito grande.');
      if (line) events.push(this.parse(line));
    }
    if (this.buffer.length > MAX_LINE) throw new Error('Pacote de audio muito grande.');
    return events;
  }

  parse(line) {
    let event;
    try { event = JSON.parse(line); } catch { throw new Error('Resposta de audio invalida.'); }
    if (!event || typeof event !== 'object' || this.ended) throw new Error('Ordem de audio invalida.');
    if (event.type === 'error') throw new Error(typeof event.message === 'string' ? event.message : 'Falha ao gerar audio.');
    if (event.type === 'ping') return event;
    if (event.type === 'start') {
      if (this.started || event.format !== 'pcm_s16le' || event.channels !== 1) throw new Error('Formato de audio invalido.');
      this.started = true;
    } else if (event.type === 'audio') {
      if (!this.started || event.seq !== this.sequence || !Number.isInteger(event.sample_rate) ||
          event.sample_rate < 3000 || event.sample_rate > 384000 ||
          (this.sampleRate !== null && event.sample_rate !== this.sampleRate)) throw new Error('Sequencia ou metadados de audio invalidos.');
      if (typeof event.data !== 'string' || !event.data.length ||
          !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(event.data)) throw new Error('PCM invalido.');
      const bytes = atob(event.data);
      if (bytes.length % 2) throw new Error('PCM incompleto.');
      const samples = new Float32Array(bytes.length / 2);
      for (let i = 0; i < samples.length; i++) {
        const value = bytes.charCodeAt(i * 2) | (bytes.charCodeAt(i * 2 + 1) << 8);
        samples[i] = (value >= 32768 ? value - 65536 : value) / 32768;
      }
      this.sampleRate = event.sample_rate;
      this.sequence++;
      return { type: 'audio', seq: event.seq, samples, sampleRate: event.sample_rate };
    } else if (event.type === 'end') {
      if (!this.started) throw new Error('Fim de audio sem inicio.');
      this.ended = true;
    } else throw new Error('Evento de audio desconhecido.');
    return event;
  }

  finish() {
    const events = this.buffer.trim() ? [this.parse(this.buffer.trim())] : [];
    this.buffer = '';
    if (!this.ended) throw new Error('Resposta interrompida: evento end ausente.');
    return events;
  }
}

export async function* readNDJSON(body, signal) {
  if (!body) throw new Error('Resposta de audio vazia.');
  const reader = body.getReader();
  const decoder = new TextDecoder('utf-8', { fatal: true });
  const parser = new NDJSONParser();
  const abort = () => { void reader.cancel().catch(() => {}); };
  let complete = false;
  try {
    signal?.throwIfAborted();
    signal?.addEventListener('abort', abort, { once: true });
    while (true) {
      const { value, done } = await reader.read();
      signal?.throwIfAborted();
      if (done) break;
      yield* parser.push(decoder.decode(value, { stream: true }));
    }
    yield* parser.push(decoder.decode());
    yield* parser.finish();
    complete = true;
  } finally {
    signal?.removeEventListener('abort', abort);
    if (!complete) await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export class PCMPlayer {
  constructor(context, { prebufferSeconds = 3, output = context.destination, onState = () => {} } = {}) {
    this.context = context;
    this.maxAheadSeconds = 12;
    this.prebufferSeconds = Number.isFinite(prebufferSeconds) ? Math.min(this.maxAheadSeconds, Math.max(0, prebufferSeconds)) : 3;
    this.output = output;
    this.onState = onState;
    this.queue = [];
    this.queuedSeconds = 0;
    this.sources = new Set();
    this.capacityWaiters = new Set();
    this.nextStartTime = 0;
    this.buffering = true;
    this.ended = false;
    this.cancelled = false;
    this.done = new Promise(resolve => { this.resolve = resolve; });
  }

  async waitForCapacity(signal) {
    signal?.throwIfAborted();
    if (this.cancelled) throw new DOMException('Reproducao cancelada.', 'AbortError');
    const hasCapacity = () => this.queuedSeconds + Math.max(0, this.nextStartTime - this.context.currentTime) < this.maxAheadSeconds;
    if (hasCapacity()) return;
    await new Promise((resolve, reject) => {
      const cleanup = () => {
        this.capacityWaiters.delete(check);
        signal?.removeEventListener('abort', abort);
      };
      const abort = () => {
        cleanup();
        reject(signal?.reason || new DOMException('Reproducao cancelada.', 'AbortError'));
      };
      const check = () => {
        if (this.cancelled || signal?.aborted) { abort(); return; }
        if (hasCapacity()) { cleanup(); resolve(); }
      };
      this.capacityWaiters.add(check);
      signal?.addEventListener('abort', abort, { once: true });
      check();
    });
  }

  enqueue({ samples, sampleRate }) {
    if (this.cancelled || this.ended) return;
    const buffer = this.context.createBuffer(1, samples.length, sampleRate);
    buffer.copyToChannel(samples, 0);
    this.enqueueBuffer(buffer);
  }

  enqueueBuffer(buffer) {
    if (this.cancelled || this.ended) return;
    this.queue.push(buffer);
    this.queuedSeconds += buffer.duration;
    this.pump();
  }

  pump() {
    if (this.cancelled) return;
    if (!this.buffering && this.context.currentTime >= this.nextStartTime) {
      this.buffering = true;
      this.onState('thinking');
    }
    if (this.buffering && !this.ended && this.queuedSeconds + 1e-6 < this.prebufferSeconds) return;
    if (this.queue.length) {
      if (this.buffering) this.nextStartTime = Math.max(this.nextStartTime, this.context.currentTime + 0.04);
      this.buffering = false;
      this.onState('speaking');
    }
    for (const buffer of this.queue) {
      const source = this.context.createBufferSource();
      source.buffer = buffer;
      source.connect(this.output);
      this.sources.add(source);
      source.onended = () => {
        source.disconnect();
        source.buffer = null;
        this.sources.delete(source);
        for (const check of this.capacityWaiters) check();
        if (!this.sources.size && !this.ended && !this.cancelled) {
          this.buffering = true;
          this.onState('thinking');
        }
        this.settle();
      };
      source.start(this.nextStartTime);
      this.nextStartTime += buffer.duration;
    }
    this.queue = [];
    this.queuedSeconds = 0;
    this.settle();
  }

  settle() {
    if (this.ended && !this.queue.length && !this.sources.size) this.resolve();
  }

  finish() {
    this.ended = true;
    this.pump();
    return this.done;
  }

  cancel() {
    this.cancelled = true;
    this.queue = [];
    this.queuedSeconds = 0;
    for (const source of this.sources) {
      source.onended = null;
      try { source.stop(); } catch { /* Source may already have ended. */ }
      source.disconnect();
      source.buffer = null;
    }
    this.sources.clear();
    for (const check of this.capacityWaiters) check();
    this.resolve();
  }
}
