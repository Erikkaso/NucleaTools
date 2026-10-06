import {
  AUTOMATIC_SILENCE_MS,
  shouldStopVoiceCapture,
} from './voice-activity.mjs';

export { AUTOMATIC_SILENCE_MS, shouldStopVoiceCapture };

const MODEL_URL = '/static/wakeword/nuclea_int8.tflite';
const WASM_URL = '/static/vendor/tfjs-tflite/wasm/';
const SAMPLE_RATE = 16000;
const WINDOW_SAMPLES = 16000;
const FRAME_LENGTH = 400;
const FRAME_STEP = 320;
const FFT_LENGTH = 512;
const MEL_BANDS = 40;
const MFCC_COUNT = 13;
const FRAME_COUNT = 49;
const INPUT_SCALE = 3.1064834594726562;
const INPUT_ZERO_POINT = 76;
const OUTPUT_SCALE = 0.00390625;
const OUTPUT_ZERO_POINT = -128;
const THRESHOLD = 0.75;
const INFERENCE_INTERVAL_MS = 250;
const COOLDOWN_MS = 2000;

export function quantizeMfcc(values, scale = INPUT_SCALE, zeroPoint = INPUT_ZERO_POINT) {
  const output = new Int8Array(values.length);
  for (let index = 0; index < values.length; index += 1) {
    const quantized = Math.round(values[index] / scale) + zeroPoint;
    output[index] = Math.max(-128, Math.min(127, quantized));
  }
  return output;
}

export function shouldTriggerWake(scores, threshold = THRESHOLD) {
  if (scores.length < 3) return false;
  return scores.slice(-3).filter((score) => score >= threshold).length >= 2;
}

function periodicHann(length) {
  const values = new Float64Array(length);
  for (let index = 0; index < length; index += 1) {
    values[index] = 0.5 - (0.5 * Math.cos((2 * Math.PI * index) / length));
  }
  return values;
}

function hzToSlaneyMel(hz) {
  const frequencySpacing = 200 / 3;
  const minimumLogHz = 1000;
  const minimumLogMel = minimumLogHz / frequencySpacing;
  const logStep = Math.log(6.4) / 27;
  return hz < minimumLogHz
    ? hz / frequencySpacing
    : minimumLogMel + (Math.log(hz / minimumLogHz) / logStep);
}

function slaneyMelToHz(mel) {
  const frequencySpacing = 200 / 3;
  const minimumLogHz = 1000;
  const minimumLogMel = minimumLogHz / frequencySpacing;
  const logStep = Math.log(6.4) / 27;
  return mel < minimumLogMel
    ? mel * frequencySpacing
    : minimumLogHz * Math.exp(logStep * (mel - minimumLogMel));
}

function createMelFilterBank() {
  const bins = (FFT_LENGTH / 2) + 1;
  const minimumMel = hzToSlaneyMel(20);
  const maximumMel = hzToSlaneyMel(7600);
  const melPoints = new Float64Array(MEL_BANDS + 2);
  for (let index = 0; index < melPoints.length; index += 1) {
    melPoints[index] = slaneyMelToHz(
      minimumMel + ((maximumMel - minimumMel) * index / (MEL_BANDS + 1)),
    );
  }

  const weights = new Float64Array(MEL_BANDS * bins);
  for (let mel = 0; mel < MEL_BANDS; mel += 1) {
    const left = melPoints[mel];
    const center = melPoints[mel + 1];
    const right = melPoints[mel + 2];
    const normalization = 2 / (right - left);
    for (let bin = 0; bin < bins; bin += 1) {
      const frequency = (SAMPLE_RATE * bin) / FFT_LENGTH;
      const lower = (frequency - left) / (center - left);
      const upper = (right - frequency) / (right - center);
      weights[(mel * bins) + bin] = Math.max(0, Math.min(lower, upper)) * normalization;
    }
  }
  return weights;
}

export function fftPower(frame, hann) {
  const real = new Float64Array(FFT_LENGTH);
  const imaginary = new Float64Array(FFT_LENGTH);
  for (let index = 0; index < FRAME_LENGTH; index += 1) real[index] = frame[index] * hann[index];

  for (let index = 1, reversed = 0; index < FFT_LENGTH; index += 1) {
    let bit = FFT_LENGTH >> 1;
    while (reversed & bit) {
      reversed ^= bit;
      bit >>= 1;
    }
    reversed ^= bit;
    if (index < reversed) {
      [real[index], real[reversed]] = [real[reversed], real[index]];
      [imaginary[index], imaginary[reversed]] = [imaginary[reversed], imaginary[index]];
    }
  }

  for (let length = 2; length <= FFT_LENGTH; length <<= 1) {
    const angle = (-2 * Math.PI) / length;
    const half = length >> 1;
    for (let offset = 0; offset < FFT_LENGTH; offset += length) {
      for (let index = 0; index < half; index += 1) {
        const cosine = Math.cos(angle * index);
        const sine = Math.sin(angle * index);
        const even = offset + index;
        const odd = even + half;
        const transformedReal = (real[odd] * cosine) - (imaginary[odd] * sine);
        const transformedImaginary = (real[odd] * sine) + (imaginary[odd] * cosine);
        real[odd] = real[even] - transformedReal;
        imaginary[odd] = imaginary[even] - transformedImaginary;
        real[even] += transformedReal;
        imaginary[even] += transformedImaginary;
      }
    }
  }

  const power = new Float64Array((FFT_LENGTH / 2) + 1);
  for (let index = 0; index < power.length; index += 1) {
    power[index] = real[index] ** 2 + imaginary[index] ** 2;
  }
  return power;
}

function resampleToWakewordRate(samples, inputRate) {
  const output = new Float32Array(WINDOW_SAMPLES);
  const scale = (samples.length - 1) / (WINDOW_SAMPLES - 1);
  for (let index = 0; index < WINDOW_SAMPLES; index += 1) {
    const position = index * scale;
    const before = Math.floor(position);
    const after = Math.min(before + 1, samples.length - 1);
    output[index] = samples[before] + ((samples[after] - samples[before]) * (position - before));
  }
  return output;
}

const hann = periodicHann(FRAME_LENGTH);
const melFilterBank = createMelFilterBank();

function mfccFromPcm(samples) {
  const bins = (FFT_LENGTH / 2) + 1;
  const melSpectrogram = new Float64Array(MEL_BANDS * FRAME_COUNT);
  let maximumDb = -Infinity;

  for (let frame = 0; frame < FRAME_COUNT; frame += 1) {
    const start = frame * FRAME_STEP;
    const power = fftPower(samples.subarray(start, start + FRAME_LENGTH), hann);
    for (let mel = 0; mel < MEL_BANDS; mel += 1) {
      let energy = 0;
      for (let bin = 0; bin < bins; bin += 1) energy += power[bin] * melFilterBank[(mel * bins) + bin];
      const db = 10 * Math.log10(Math.max(1e-10, energy));
      melSpectrogram[(mel * FRAME_COUNT) + frame] = db;
      maximumDb = Math.max(maximumDb, db);
    }
  }

  const output = new Float32Array(MFCC_COUNT * FRAME_COUNT);
  for (let frame = 0; frame < FRAME_COUNT; frame += 1) {
    for (let coefficient = 0; coefficient < MFCC_COUNT; coefficient += 1) {
      let total = 0;
      for (let mel = 0; mel < MEL_BANDS; mel += 1) {
        const db = Math.max(melSpectrogram[(mel * FRAME_COUNT) + frame], maximumDb - 80);
        total += db * Math.cos((Math.PI * coefficient * (mel + 0.5)) / MEL_BANDS);
      }
      output[(coefficient * FRAME_COUNT) + frame] = total * (
        coefficient === 0 ? 1 / Math.sqrt(MEL_BANDS) : Math.sqrt(2 / MEL_BANDS)
      );
    }
  }
  return output;
}

function appendSamples(existing, incoming, maximumLength) {
  const retained = Math.min(existing.length, Math.max(0, maximumLength - incoming.length));
  const output = new Float32Array(retained + incoming.length);
  if (retained) output.set(existing.subarray(existing.length - retained));
  output.set(incoming, retained);
  return output;
}

export class WakewordListener {
  constructor({ onStatus, onScore, onWake, onError }) {
    this.onStatus = onStatus;
    this.onScore = onScore;
    this.onWake = onWake;
    this.onError = onError;
    this.context = null;
    this.stream = null;
    this.model = null;
    this.buffer = new Float32Array();
    this.scores = [];
    this.lastInference = 0;
    this.lastWake = 0;
    this.inferenceRunning = false;
  }

  async start() {
    if (this.context) return;
    if (!globalThis.tf || !globalThis.tflite) throw new Error('Runtime TensorFlow Lite indisponivel');

    globalThis.tflite.setWasmPath(WASM_URL);
    await globalThis.tf.ready();
    this.onStatus('carregando modelo');
    this.model = await globalThis.tflite.loadTFLiteModel(MODEL_URL, { numThreads: 1 });

    this.onStatus('solicitando microfone');
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    this.context = new AudioContext();
    await this.context.audioWorklet.addModule('/static/wakeword-worklet.mjs');
    const source = this.context.createMediaStreamSource(this.stream);
    const processor = new AudioWorkletNode(this.context, 'wakeword-capture');
    const silent = this.context.createGain();
    silent.gain.value = 0;
    processor.port.onmessage = ({ data }) => this.receiveSamples(new Float32Array(data));
    source.connect(processor);
    processor.connect(silent);
    silent.connect(this.context.destination);
    await this.context.resume();
    this.onStatus('escutando');
  }

  async resume() {
    if (this.context?.state === 'suspended') await this.context.resume();
  }

  stop() {
    this.stream?.getTracks().forEach((track) => track.stop());
    this.context?.close();
    this.stream = null;
    this.context = null;
    this.model = null;
    this.buffer = new Float32Array();
    this.scores = [];
  }

  receiveSamples(samples) {
    if (!this.context || this.inferenceRunning) return;
    const maximumLength = Math.ceil(this.context.sampleRate * 1.25);
    this.buffer = appendSamples(this.buffer, samples, maximumLength);
    const now = performance.now();
    if (this.buffer.length < this.context.sampleRate || now - this.lastInference < INFERENCE_INTERVAL_MS) return;
    this.lastInference = now;
    this.inferenceRunning = true;
    this.scoreLatestWindow(now).catch(this.onError).finally(() => {
      this.inferenceRunning = false;
    });
  }

  async scoreLatestWindow(now) {
    const nativeWindow = this.buffer.subarray(this.buffer.length - Math.round(this.context.sampleRate));
    const pcm = resampleToWakewordRate(nativeWindow, this.context.sampleRate);
    const quantized = quantizeMfcc(mfccFromPcm(pcm));
    const input = globalThis.tf.tensor4d(Int32Array.from(quantized), [1, MFCC_COUNT, FRAME_COUNT, 1], 'int32');
    const output = this.model.predict(input);
    const rawScores = await output.data();
    const score = (rawScores[1] - OUTPUT_ZERO_POINT) * OUTPUT_SCALE;
    input.dispose();
    output.dispose();

    this.scores.push(score);
    if (this.scores.length > 3) this.scores.shift();
    this.onScore(score);
    if (shouldTriggerWake(this.scores) && now - this.lastWake >= COOLDOWN_MS) {
      this.lastWake = now;
      this.onWake(score);
    }
  }
}
