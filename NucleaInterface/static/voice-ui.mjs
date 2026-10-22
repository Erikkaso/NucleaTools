import { PCMPlayer, readNDJSON } from './pcm-player.mjs';

const labels = { idle: 'Pronta', listening: 'Ouvindo', thinking: 'Pensando', speaking: 'Falando', error: 'Algo deu errado' };

export function createVoiceUI({ document, window, navigator, fetch: fetcher = window.fetch.bind(window) }) {
  const app = document.getElementById('voiceApp');
  const speak = document.getElementById('speakButton');
  const symbol = document.getElementById('speakSymbol');
  const micIcon = document.getElementById('micIcon');
  const cancelButton = document.getElementById('cancelButton');
  const status = document.getElementById('voiceStatus');
  const errorBox = document.getElementById('voiceError');
  const canvas = document.getElementById('waveform');
  const pen = canvas.getContext('2d');
  const configured = Number(app.dataset.ttsPrebufferSeconds);
  const prebufferSeconds = Number.isFinite(configured) && configured >= 0 ? configured : 3;
  const configuredTimeout = Number(app.dataset.ttsAudioProgressTimeoutSeconds);
  const progressTimeoutMs = (Number.isFinite(configuredTimeout) && configuredTimeout > 0 ? configuredTimeout : 60) * 1000;
  let context, outputAnalyser, active = null, pollController = null;
  let pollEnabled = true, destroyed = false, state = 'idle', frame;
  let samples;

  function setState(next, message = '') {
    state = next;
    app.dataset.state = next;
    status.textContent = labels[next];
    errorBox.textContent = message;
    errorBox.hidden = !message;
    const recording = next === 'listening';
    const busy = !!active;
    speak.disabled = !!active?.starting;
    speak.setAttribute('aria-pressed', String(recording));
    const command = recording ? 'Parar e enviar' : busy ? 'Parar' : 'Falar';
    speak.title = command;
    speak.setAttribute('aria-label', command);
    symbol.textContent = '\u25a0';
    symbol.hidden = !busy;
    micIcon.hidden = busy;
    cancelButton.disabled = !busy;
  }

  function releaseMic(turn) {
    window.clearTimeout(turn.recordTimer);
    turn.micSource?.disconnect();
    turn.micAnalyser?.disconnect();
    turn.stream?.getTracks().forEach(track => track.stop());
    turn.stream = null;
    turn.micSource = null;
    turn.micAnalyser = null;
  }

  function dispose(turn) {
    if (!turn) return;
    window.clearTimeout(turn.progressTimer);
    turn.controller.abort();
    if (turn.recorder?.state !== 'inactive') {
      try { turn.recorder?.stop(); } catch { /* Recorder already stopped. */ }
    }
    releaseMic(turn);
    turn.player?.cancel();
    turn.chunks = [];
  }

  function cancel() {
    const turn = active;
    active = null;
    pollController?.abort();
    dispose(turn);
    setState('idle');
  }

  function fail(turn, error) {
    if (active !== turn) return;
    active = null;
    dispose(turn);
    let message = error.message || 'Falha de audio. Tente novamente.';
    if (error.name === 'NotAllowedError' || error.name === 'SecurityError') message = 'Permita o microfone nas configuracoes deste site e tente novamente.';
    if (error.name === 'NotFoundError') message = 'Conecte um microfone e tente novamente.';
    if (error.name === 'NotReadableError') message = 'Libere o microfone em outros aplicativos e tente novamente.';
    setState('error', message);
  }

  // Resume inside the gesture handler, before permission or network awaits.
  function unlockAudio() {
    if (!context) {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (!AudioContext) throw new Error('Este navegador nao suporta audio. Use um navegador atualizado.');
      context = new AudioContext();
      outputAnalyser = context.createAnalyser();
      outputAnalyser.fftSize = 1024;
      outputAnalyser.connect(context.destination);
      samples = new Float32Array(outputAnalyser.fftSize);
    }
    return context.resume();
  }

  function newTurn(kind) {
    return { kind, controller: new AbortController(), chunks: [], starting: false };
  }

  function resetProgressDeadline(turn) {
    window.clearTimeout(turn.progressTimer);
    turn.progressTimer = window.setTimeout(() => {
      fail(turn, new Error('A resposta de audio demorou demais. Verifique a conexao e tente novamente.'));
    }, progressTimeoutMs);
  }

  async function playResponse(response, turn) {
    if (!response.ok) {
      const details = await response.json().catch(() => ({}));
      throw new Error(details.error || details.message || `Falha na resposta (${response.status}). Tente novamente.`);
    }
    if (active !== turn) { await response.body?.cancel(); return; }
    const contentType = (response.headers.get('Content-Type') || '').split(';')[0].trim().toLowerCase();
    turn.player = new PCMPlayer(context, {
      prebufferSeconds, output: outputAnalyser,
      onState(next) { if (active === turn) setState(next); },
    });
    if (contentType === 'application/x-ndjson') {
      resetProgressDeadline(turn);
      for await (const event of readNDJSON(response.body, turn.controller.signal)) {
        if (active !== turn) return;
        if (event.type === 'audio') {
          resetProgressDeadline(turn);
          await turn.player.waitForCapacity(turn.controller.signal);
          if (active !== turn) return;
          turn.player.enqueue(event);
        }
        if (event.type === 'end') {
          window.clearTimeout(turn.progressTimer);
          void turn.player.finish();
        }
      }
    } else if (contentType.startsWith('audio/')) {
      const bytes = await response.arrayBuffer();
      if (active !== turn) return;
      const buffer = await context.decodeAudioData(bytes);
      if (active !== turn) return;
      await turn.player.waitForCapacity(turn.controller.signal);
      if (active !== turn) return;
      turn.player.enqueueBuffer(buffer);
    } else throw new Error('A resposta nao contem audio reproduzivel.');
    if (active !== turn) return;
    await turn.player.finish();
    if (active === turn) {
      active = null;
      dispose(turn);
      setState('idle');
    }
  }

  async function send(turn, recorder) {
    releaseMic(turn);
    if (active !== turn) return;
    try {
      const mime = recorder.mimeType || turn.chunks[0]?.type || 'audio/webm';
      const blob = new Blob(turn.chunks, { type: mime });
      turn.chunks = [];
      if (!blob.size) throw new Error('Nenhum audio capturado. Tente gravar novamente.');
      const extension = mime.includes('mp4') ? 'm4a' : mime.includes('ogg') ? 'ogg' : mime.includes('wav') ? 'wav' : 'webm';
      const form = new FormData();
      form.append('audio', blob, `voice.${extension}`);
      const response = await fetcher('/api/chat-audio', { method: 'POST', body: form, signal: turn.controller.signal });
      await playResponse(response, turn);
    } catch (error) { fail(turn, error); }
  }

  function stopAndSend(turn) {
    setState('thinking');
    const recorder = turn.recorder;
    recorder.addEventListener('stop', () => { void send(turn, recorder); }, { once: true });
    try { recorder.stop(); } catch (error) { fail(turn, error); }
    releaseMic(turn);
  }

  async function record(turn, resumed) {
    try {
      await resumed;
      if (active !== turn) return;
      if (!window.isSecureContext) throw new Error('Abra esta pagina em localhost ou HTTPS para usar o microfone.');
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error('Use um navegador atualizado com suporte a gravacao de audio.');
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (active !== turn) { stream.getTracks().forEach(track => track.stop()); return; }
      turn.stream = stream;
      const types = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus'];
      const mimeType = types.find(type => window.MediaRecorder.isTypeSupported(type));
      const recorder = new window.MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      turn.recorder = recorder;
      recorder.addEventListener('dataavailable', event => {
        if (active === turn && event.data.size) turn.chunks.push(event.data);
      });
      recorder.addEventListener('error', event => fail(turn, event.error || new Error('Falha na gravacao. Tente novamente.')));
      turn.micSource = context.createMediaStreamSource(stream);
      turn.micAnalyser = context.createAnalyser();
      turn.micAnalyser.fftSize = 1024;
      turn.micSource.connect(turn.micAnalyser);
      recorder.start(250);
      turn.recordTimer = window.setTimeout(() => {
        if (active === turn && recorder.state === 'recording') stopAndSend(turn);
      }, 60000);
      turn.starting = false;
      setState('listening');
    } catch (error) { fail(turn, error); }
  }

  function interact() {
    if (destroyed) return;
    if (active?.recorder?.state === 'recording') { stopAndSend(active); return; }
    if (active) { cancel(); return; }
    cancel();
    const turn = newTurn('browser');
    active = turn;
    turn.starting = true;
    setState('thinking');
    try { void record(turn, unlockAudio()); } catch (error) { fail(turn, error); }
  }

  async function poll() {
    if (destroyed || !pollEnabled || active || pollController || context?.state !== 'running' || document.hidden) return;
    const controller = new AbortController();
    pollController = controller;
    const timeout = window.setTimeout(() => controller.abort(), 25000);
    let turn;
    try {
      const response = await fetcher('/api/device-response', { signal: controller.signal, cache: 'no-store' });
      if (controller.signal.aborted || active || destroyed) { await response.body?.cancel(); return; }
      if (response.status === 404 || response.status === 405) { pollEnabled = false; await response.body?.cancel(); return; }
      if (response.status === 204) return;
      if (!response.ok) { await response.body?.cancel(); return; }
      window.clearTimeout(timeout);
      turn = newTurn('device');
      turn.controller = controller;
      active = turn;
      setState('thinking');
      await playResponse(response, turn);
    } catch (error) {
      if (turn && !controller.signal.aborted) fail(turn, error);
    } finally {
      window.clearTimeout(timeout);
      if (pollController === controller) pollController = null;
    }
  }

  function draw() {
    if (destroyed) return;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const width = canvas.clientWidth || 480, height = canvas.clientHeight || 180;
    if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
      canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
    }
    pen.setTransform(ratio, 0, 0, ratio, 0, 0);
    pen.clearRect(0, 0, width, height);
    const analyser = state === 'listening' ? active?.micAnalyser : state === 'speaking' ? outputAnalyser : null;
    if (analyser && samples) analyser.getFloatTimeDomainData(samples);
    let rms = 0;
    if (analyser && samples) { for (const sample of samples) rms += sample * sample; rms = Math.sqrt(rms / samples.length); }
    pen.fillStyle = state === 'listening' ? '#c94f43' : '#006b62';
    const count = 49, spacing = Math.min(9, (width - 24) / count);
    for (let i = 0; i < count; i++) {
      const envelope = Math.sin(Math.PI * (i + 1) / (count + 1));
      const amplitude = analyser ? Math.abs(samples[Math.floor(i * samples.length / count)]) : 0;
      const bar = 3 + Math.min(height - 20, (amplitude * 100 + rms * 260) * envelope);
      pen.fillRect((width - count * spacing) / 2 + i * spacing, (height - bar) / 2, 3, bar);
    }
    frame = window.requestAnimationFrame(draw);
  }

  function destroy() {
    destroyed = true;
    cancel();
    window.clearInterval(pollTimer);
    window.cancelAnimationFrame(frame);
    speak.removeEventListener('click', interact);
    cancelButton.removeEventListener('click', cancel);
    window.removeEventListener('pagehide', destroy);
    outputAnalyser?.disconnect();
    void context?.close();
  }

  speak.addEventListener('click', interact);
  cancelButton.addEventListener('click', cancel);
  window.addEventListener('pagehide', destroy);
  const pollTimer = window.setInterval(() => { void poll(); }, 1500);
  draw();
  return { cancel, destroy, poll, get state() { return state; } };
}

if (typeof document !== 'undefined') createVoiceUI({ document, window, navigator });
