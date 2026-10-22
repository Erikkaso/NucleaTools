import test from 'node:test';
import assert from 'node:assert/strict';
import { createVoiceUI } from './voice-ui.mjs';

const tick = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };

function harness({ permission, secure = true, fetcher, progressTimeout } = {}) {
  const calls = [], sources = [], tracks = [], timers = new Map();
  let now = 0, audioContext;
  class Element extends EventTarget {
    dataset = { ttsPrebufferSeconds: '0' };
    setAttribute(name, value) { this[name] = value; }
    click() { this.dispatchEvent(new Event('click')); }
    getContext() { return { setTransform() {}, clearRect() {}, fillRect() {} }; }
  }
  const elements = Object.fromEntries(['voiceApp', 'speakButton', 'speakSymbol', 'micIcon', 'cancelButton', 'voiceStatus', 'voiceError', 'waveform'].map(id => [id, new Element()]));
  const document = { hidden: false, getElementById: id => elements[id] };
  if (progressTimeout !== undefined) elements.voiceApp.dataset.ttsAudioProgressTimeoutSeconds = String(progressTimeout);
  const stream = () => {
    const track = { stopped: false, stop() { this.stopped = true; } };
    tracks.push(track);
    return { getTracks: () => [track] };
  };
  class Context {
    constructor() { audioContext = this; }
    currentTime = 0; state = 'suspended'; destination = {};
    resume() { calls.push('resume'); this.state = 'running'; return Promise.resolve(); }
    close() { return Promise.resolve(); }
    createAnalyser() { return { fftSize: 1024, connect() {}, disconnect() {}, getFloatTimeDomainData(data) { data.fill(0.1); } }; }
    createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
    createBuffer(ch, length, rate) { return { duration: length / rate, copyToChannel() {} }; }
    async decodeAudioData() { return { duration: 1 }; }
    createBufferSource() {
      const source = { connect() {}, disconnect() {}, start(at) { this.at = at; }, stop() { this.stopped = true; } };
      sources.push(source); return source;
    }
  }
  class Recorder extends EventTarget {
    static isTypeSupported(type) { return type.includes('webm'); }
    state = 'inactive'; mimeType = 'audio/webm';
    start() { this.state = 'recording'; }
    stop() {
      this.state = 'inactive';
      queueMicrotask(() => {
        const event = new Event('dataavailable'); event.data = new Blob(['voice'], { type: this.mimeType });
        this.dispatchEvent(event); this.dispatchEvent(new Event('stop'));
      });
    }
  }
  const window = Object.assign(new EventTarget(), {
    AudioContext: Context, MediaRecorder: Recorder, isSecureContext: secure,
    setInterval: () => 1, clearInterval() {},
    setTimeout(fn, delay) { const id = Symbol(); timers.set(id, { fn, delay, at: now + delay }); return id; },
    clearTimeout(id) { timers.delete(id); },
    requestAnimationFrame: () => 3, cancelAnimationFrame() {},
  });
  const navigator = { mediaDevices: { getUserMedia() { calls.push('permission'); return permission ? permission.promise : Promise.resolve(stream()); } } };
  const requests = [];
  const fetch = async (url, options) => {
    requests.push({ url, options });
    return fetcher ? fetcher(url, options) : new Response(null, { status: 204 });
  };
  const ui = createVoiceUI({ document, window, navigator, fetch });
  async function advance(ms) {
    const target = now + ms;
    while (true) {
      const due = [...timers].filter(([, timer]) => timer.at <= target).sort((a, b) => a[1].at - b[1].at)[0];
      if (!due) break;
      timers.delete(due[0]); now = due[1].at; due[1].fn(); await tick();
    }
    now = target; await tick();
  }
  return { ui, elements, calls, sources, tracks, requests, stream, timers, advance, get context() { return audioContext; } };
}

function ndjson({ end = true } = {}) {
  const events = [{ type: 'start', format: 'pcm_s16le', channels: 1 }, { type: 'audio', seq: 0, sample_rate: 24000, data: 'AID/fw==' }];
  if (end) events.push({ type: 'end' });
  return new Response(events.map(e => JSON.stringify(e) + '\n').join(''), { headers: { 'Content-Type': 'application/x-ndjson' } });
}

test('first gesture resumes audio before requesting permission; cancellation stops late mic', async () => {
  const permission = deferred(); const h = harness({ permission });
  assert.deepEqual(h.calls, []);
  h.elements.speakButton.click();
  assert.deepEqual(h.calls, ['resume']);
  await tick();
  assert.deepEqual(h.calls, ['resume', 'permission']);
  h.ui.cancel();
  permission.resolve(h.stream());
  await tick();
  assert.equal(h.ui.state, 'idle');
  assert.equal(h.tracks[0].stopped, true);
  assert.equal(h.requests.length, 0);
  h.ui.destroy();
});

test('insecure context shows actionable error only after a click', async () => {
  const h = harness({ secure: false });
  assert.equal(h.ui.state, 'idle');
  h.elements.speakButton.click(); await tick();
  assert.equal(h.ui.state, 'error');
  assert.match(h.elements.voiceError.textContent, /localhost.*HTTPS/);
  assert.deepEqual(h.calls, ['resume']);
  h.ui.destroy();
});

test('record toggle sends multipart audio, waits for playback and blocks device polling', async () => {
  const h = harness({ fetcher: () => ndjson() });
  h.elements.speakButton.click(); await tick();
  assert.equal(h.ui.state, 'listening');
  await h.ui.poll(); assert.equal(h.requests.length, 0);
  h.elements.speakButton.click(); await tick();
  assert.equal(h.requests[0].url, '/api/chat-audio');
  assert.equal(h.requests[0].options.body.get('audio').type, 'audio/webm');
  assert.equal(h.tracks[0].stopped, true);
  assert.equal(h.ui.state, 'speaking');
  await h.ui.poll(); assert.equal(h.requests.length, 1);
  h.sources[0].onended(); await tick();
  assert.equal(h.ui.state, 'idle');
  assert.equal(h.sources[0].buffer, null);
  h.ui.destroy();
});

test('cancel aborts request and playback without a stale state change', async () => {
  const h = harness({ fetcher: () => ndjson() });
  h.elements.speakButton.click(); await tick();
  h.elements.speakButton.click(); await tick();
  h.elements.cancelButton.click(); await tick();
  assert.equal(h.requests[0].options.signal.aborted, true);
  assert.equal(h.sources[0].stopped, true);
  assert.equal(h.ui.state, 'idle');
  h.ui.destroy();
});

test('legacy audio plays and truncated NDJSON fails with cleanup', async () => {
  for (const legacy of [true, false]) {
    const h = harness({ fetcher: () => legacy ? new Response('audio', { headers: { 'Content-Type': 'audio/mpeg' } }) : ndjson({ end: false }) });
    h.elements.speakButton.click(); await tick(); h.elements.speakButton.click(); await tick();
    assert.equal(h.ui.state, legacy ? 'speaking' : 'error');
    if (legacy) { h.sources[0].onended(); await tick(); assert.equal(h.ui.state, 'idle'); }
    else { assert.match(h.elements.voiceError.textContent, /end/); assert.equal(h.sources[0].stopped, true); }
    h.ui.destroy();
  }
});

test('device polling waits for unlock, supports 204 and cannot overwrite a browser turn', async () => {
  const response = deferred();
  const h = harness({ fetcher: () => response.promise });
  await h.ui.poll(); assert.equal(h.requests.length, 0);
  h.elements.speakButton.click(); await tick(); h.ui.cancel();
  const polling = h.ui.poll();
  assert.equal(h.requests[0].url, '/api/device-response');
  h.elements.speakButton.click(); await tick();
  response.resolve(ndjson()); await polling;
  assert.equal(h.requests[0].options.signal.aborted, true);
  assert.equal(h.ui.state, 'listening');
  assert.equal(h.sources.length, 0);
  h.ui.destroy();
  const empty = harness();
  empty.elements.speakButton.click(); await tick(); empty.ui.cancel();
  await empty.ui.poll(); assert.equal(empty.ui.state, 'idle');
  empty.ui.destroy();
});

test('device playback stays active until the final source ends', async () => {
  const h = harness({ fetcher: () => ndjson() });
  h.elements.speakButton.click(); await tick(); h.ui.cancel();
  const polling = h.ui.poll(); await tick();
  assert.equal(h.ui.state, 'speaking');
  await h.ui.poll(); assert.equal(h.requests.length, 1);
  h.sources[0].onended(); await polling;
  assert.equal(h.ui.state, 'idle');
  h.ui.destroy();
});

test('main button stops device playback', async () => {
  const h = harness({ fetcher: () => ndjson() });
  h.elements.speakButton.click(); await tick(); h.ui.cancel();
  const polling = h.ui.poll(); await tick();
  h.elements.speakButton.click(); await polling; await tick();
  assert.equal(h.ui.state, 'idle');
  assert.equal(h.sources[0].stopped, true);
  h.ui.destroy();
});

test('recording cap sends at 60 seconds and clears timer on cancel', async () => {
  const h = harness({ fetcher: () => ndjson() });
  h.elements.speakButton.click(); await tick();
  assert.equal(h.elements.micIcon.hidden, true);
  const cap = [...h.timers.values()].find(t => t.delay === 60000);
  assert.ok(cap);
  cap.fn(); await tick();
  assert.equal(h.requests.length, 1);
  assert.equal(h.ui.state, 'speaking');
  assert.equal(h.timers.size, 0);
  h.ui.cancel();
  h.elements.speakButton.click(); await tick();
  h.ui.cancel();
  assert.equal(h.timers.size, 0);
  assert.equal(h.elements.micIcon.hidden, false);
  assert.equal(h.elements.speakSymbol.hidden, true);
  h.ui.destroy();
});

function streamingResponse() {
  let streamController, cancelled = false;
  const body = new ReadableStream({
    start(controller) { streamController = controller; },
    cancel() { cancelled = true; },
  });
  return {
    response: new Response(body, { headers: { 'Content-Type': 'application/x-ndjson' } }),
    emit(event) { streamController.enqueue(new TextEncoder().encode(JSON.stringify(event) + '\n')); },
    close() { streamController.close(); },
    get cancelled() { return cancelled; },
  };
}

test('audio progress deadline begins at headers and pings cannot extend default 60 seconds', async () => {
  const stream = streamingResponse(); const h = harness({ fetcher: () => stream.response });
  h.elements.speakButton.click(); await tick(); h.elements.speakButton.click(); await tick();
  for (let i = 0; i < 5; i++) {
    await h.advance(10000); stream.emit({ type: 'ping' }); await tick();
  }
  assert.equal(h.ui.state, 'thinking');
  await h.advance(10000);
  assert.equal(h.ui.state, 'error');
  assert.match(h.elements.voiceError.textContent, /audio.*Tente novamente/i);
  assert.equal(h.requests[0].options.signal.aborted, true);
  assert.equal(stream.cancelled, true);
  assert.equal(h.timers.size, 0);
  h.ui.destroy();
});

test('only audio resets configured progress timeout; end and cancel clear it', async () => {
  const stream = streamingResponse(); const h = harness({ fetcher: () => stream.response, progressTimeout: 2 });
  h.elements.speakButton.click(); await tick(); h.elements.speakButton.click(); await tick();
  await h.advance(1500);
  stream.emit({ type: 'start', format: 'pcm_s16le', channels: 1 });
  stream.emit({ type: 'audio', seq: 0, sample_rate: 24000, data: 'AID/fw==' }); await tick();
  await h.advance(1500);
  assert.equal(h.ui.state, 'speaking');
  stream.emit({ type: 'ping' }); await tick();
  await h.advance(500);
  assert.equal(h.ui.state, 'error');
  assert.equal(h.sources[0].stopped, true);
  h.ui.destroy();

  for (const end of [true, false]) {
    const pending = streamingResponse(); const other = harness({ fetcher: () => pending.response });
    other.elements.speakButton.click(); await tick(); other.elements.speakButton.click(); await tick();
    pending.emit({ type: 'start', format: 'pcm_s16le', channels: 1 });
    pending.emit({ type: 'audio', seq: 0, sample_rate: 24000, data: 'AID/fw==' }); await tick();
    if (end) { pending.emit({ type: 'end' }); pending.close(); await tick(); }
    else other.ui.cancel();
    assert.equal(other.timers.size, 0);
    await other.advance(120000);
    assert.equal(other.ui.state, end ? 'speaking' : 'idle');
    other.ui.destroy();
  }
});

test('UI backpressure stops reading body and cancel releases the reader', async () => {
  let reads = 0, cancelled = false;
  const events = [{ type: 'start', format: 'pcm_s16le', channels: 1 }];
  for (let i = 0; i < 200; i++) events.push({ type: 'audio', seq: i, sample_rate: 24000, data: Buffer.alloc(4800).toString('base64') });
  const body = new ReadableStream({
    pull(controller) { reads++; controller.enqueue(new TextEncoder().encode(JSON.stringify(events.shift()) + '\n')); },
    cancel() { cancelled = true; },
  }, { highWaterMark: 0 });
  const h = harness({ fetcher: () => new Response(body, { headers: { 'Content-Type': 'application/x-ndjson' } }) });
  h.elements.speakButton.click(); await tick(); h.elements.speakButton.click(); await tick();
  const before = reads;
  assert.ok(before >= 120 && before <= 123, before);
  await tick(); assert.equal(reads, before);
  h.context.currentTime = 1; h.sources[0].onended(); await tick();
  assert.ok(reads > before);
  assert.ok(h.sources.at(-1).at + 0.1 - h.context.currentTime <= 12.100001);
  h.ui.cancel(); await tick();
  assert.equal(cancelled, true);
  assert.equal(body.locked, false);
  assert.equal(h.timers.size, 0);
  h.ui.destroy();
});
