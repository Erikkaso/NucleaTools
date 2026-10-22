import test from 'node:test';
import assert from 'node:assert/strict';
import { NDJSONParser, PCMPlayer, readNDJSON } from './pcm-player.mjs';

const start = { type: 'start', format: 'pcm_s16le', channels: 1 };
const packet = (seq = 0) => ({ type: 'audio', seq, sample_rate: 24000, data: 'AID/fw==' });
const line = (v) => JSON.stringify(v) + '\n';

test('parser buffers arbitrary chunks, CRLF, ping and final line without newline', () => {
  const parser = new NDJSONParser();
  const input = line(start) + line({ type: 'ping' }) + line(packet()).replace('\n', '\r\n') + JSON.stringify({ type: 'end' });
  const events = [];
  for (const char of input) events.push(...parser.push(char));
  events.push(...parser.finish());
  assert.deepEqual(events.map(e => e.type), ['start', 'ping', 'audio', 'end']);
});

test('rejects invalid ordering, metadata, PCM, sequence and truncated streams', () => {
  for (const events of [
    [packet()], [start, packet(1)], [start, { ...packet(), sample_rate: 0 }],
    [{ ...start, channels: 2 }], [start, { ...packet(), data: 'AA==' }],
    [start, { ...packet(), data: '!!!!' }], [start, start],
    [start, { type: 'end' }, packet()], [start, packet(), { ...packet(1), sample_rate: 16000 }],
  ]) {
    assert.throws(() => new NDJSONParser().push(events.map(line).join('')));
  }
  const parser = new NDJSONParser();
  parser.push(line(start) + line(packet()));
  assert.throws(() => parser.finish(), /end|interromp/i);
  assert.throws(() => new NDJSONParser().push(line({ type: 'error', message: 'Falha remota' })), /Falha remota/);
});

test('stream decoder preserves split UTF-8 and releases reader on error', async () => {
  const bytes = new TextEncoder().encode(line({ type: 'error', message: 'Permiss\u00e3o' }));
  const body = new ReadableStream({ start(c) { for (const b of bytes) c.enqueue(Uint8Array.of(b)); c.close(); } });
  await assert.rejects(async () => { for await (const e of readNDJSON(body)) void e; }, /Permiss\u00e3o/);
  assert.equal(body.locked, false);
});

function context() {
  return {
    currentTime: 0, destination: {}, sources: [],
    createBuffer(channels, length, rate) {
      return { duration: length / rate, copyToChannel(data) { this.samples = data; } };
    },
    createBufferSource() {
      const source = { connect() {}, disconnect() { this.disconnected = true; }, start(at) { this.at = at; }, stop() { this.stopped = true; } };
      this.sources.push(source);
      return source;
    },
  };
}
const pcm = (seconds = 1) => ({ samples: new Float32Array(seconds * 24000), sampleRate: 24000 });

test('prebuffers then schedules packets in monotonic order before end', () => {
  const ctx = context();
  const player = new PCMPlayer(ctx, { prebufferSeconds: 3 });
  player.enqueue(pcm()); player.enqueue(pcm());
  assert.equal(ctx.sources.length, 0);
  player.enqueue(pcm());
  assert.equal(ctx.sources.length, 3);
  assert.deepEqual(ctx.sources.map(s => s.at), [0.04, 1.04, 2.04]);
});

test('end flushes short response and resolves only after playback, freeing sources', async () => {
  const ctx = context(); const player = new PCMPlayer(ctx);
  player.enqueue(pcm());
  const finished = player.finish();
  assert.equal(ctx.sources.length, 1);
  ctx.currentTime = 2;
  ctx.sources[0].onended();
  await finished;
  assert.equal(player.sources.size, 0);
  assert.equal(ctx.sources[0].buffer, null);
});

test('underrun requires another prebuffer and resumes at current time', () => {
  const ctx = context(); const player = new PCMPlayer(ctx, { prebufferSeconds: 2 });
  player.enqueue(pcm(2));
  ctx.currentTime = 3;
  ctx.sources[0].onended();
  player.enqueue(pcm());
  assert.equal(ctx.sources.length, 1);
  player.enqueue(pcm());
  assert.equal(ctx.sources[1].at, 3.04);
  assert.equal(ctx.sources[2].at, 4.04);
});

test('cancel stops active audio, drops queued data and settles completion', async () => {
  const ctx = context(); const player = new PCMPlayer(ctx, { prebufferSeconds: 0 });
  player.enqueue(pcm());
  const done = player.finish(); player.cancel();
  await done;
  assert.equal(ctx.sources[0].stopped, true);
  assert.equal(ctx.sources[0].buffer, null);
  assert.equal(player.sources.size, 0);
  player.enqueue(pcm());
  assert.equal(ctx.sources.length, 1);
});

test('packet arriving 20ms before prior end remains contiguous without another lead', () => {
  const ctx = context(); const player = new PCMPlayer(ctx, { prebufferSeconds: 0 });
  player.enqueue(pcm(0.1));
  assert.equal(ctx.sources[0].at, 0.04);
  ctx.currentTime = 0.120;
  player.enqueue(pcm(0.1));
  assert.equal(ctx.sources[1].at, 0.140);
  player.cancel();
});

test('capacity stalls consumption until playback advances; scheduled audio stays bounded', async () => {
  const ctx = context(); const player = new PCMPlayer(ctx, { prebufferSeconds: 0 });
  let consumed = 0;
  const controller = new AbortController();
  const consuming = (async () => {
    for (let i = 0; i < 200; i++) {
      await player.waitForCapacity(controller.signal);
      player.enqueue(pcm(0.1));
      consumed++;
    }
  })();
  const rejected = assert.rejects(consuming, { name: 'AbortError' });
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(consumed >= 119 && consumed <= 121, consumed);
  assert.ok(player.nextStartTime - ctx.currentTime <= 12.100001);
  const before = consumed;
  ctx.currentTime = 1;
  ctx.sources[0].onended();
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(consumed > before);
  assert.ok(player.nextStartTime - ctx.currentTime <= 12.100001);
  controller.abort(); await rejected;
  player.cancel();
});

test('capacity includes prebuffer and clamps oversized prebuffer to avoid deadlock', async () => {
  const ctx = context(); const player = new PCMPlayer(ctx, { prebufferSeconds: 90 });
  for (let i = 0; i < 120; i++) {
    await player.waitForCapacity();
    player.enqueue(pcm(0.1));
  }
  assert.equal(player.queue.length, 0);
  assert.equal(ctx.sources.length, 120);
  player.cancel();
});

test('capacity cancellation releases all waiters, including an already aborted signal', async () => {
  const ctx = context(); const player = new PCMPlayer(ctx, { prebufferSeconds: 0 });
  await player.waitForCapacity();
  player.enqueueBuffer({ duration: 40 }); // A single legacy buffer must be accepted.
  const a = assert.rejects(player.waitForCapacity(), { name: 'AbortError' });
  const b = assert.rejects(player.waitForCapacity(), { name: 'AbortError' });
  player.cancel(); await Promise.all([a, b]);
  const controller = new AbortController(); controller.abort();
  await assert.rejects(new PCMPlayer(ctx).waitForCapacity(controller.signal), { name: 'AbortError' });
});
