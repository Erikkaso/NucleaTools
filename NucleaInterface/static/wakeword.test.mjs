import assert from 'node:assert/strict';
import test from 'node:test';

import { fftPower, quantizeMfcc, shouldTriggerWake } from './wakeword.mjs';
import {
  AUTOMATIC_SILENCE_MS,
  shouldStopVoiceCapture,
} from './voice-activity.mjs';

test('quantizes MFCC values using the model input scale and zero point', () => {
  const input = new Float32Array([-3.1064834594726562, 0, 3.1064834594726562, 500]);

  assert.deepEqual(
    Array.from(quantizeMfcc(input)),
    [75, 76, 77, 127],
  );
});

test('requires two of the latest three scores to trigger a wake', () => {
  assert.equal(shouldTriggerWake([0.76, 0.2, 0.75]), true);
  assert.equal(shouldTriggerWake([0.76, 0.2, 0.74]), false);
  assert.equal(shouldTriggerWake([0.91]), false);
});

test('ends an automatic recording after sustained silence or its maximum duration', () => {
  const options = { silenceMs: AUTOMATIC_SILENCE_MS, maximumMs: 20000 };
  const state = { startedAt: 1000, lastSpeechAt: 3000 };

  assert.equal(AUTOMATIC_SILENCE_MS, 5000);
  assert.equal(shouldStopVoiceCapture(state, 7999, options), false);
  assert.equal(shouldStopVoiceCapture(state, 8000, options), true);
  assert.equal(shouldStopVoiceCapture(state, 21000, options), true);
});

test('keeps FFT power on the scale used by the MFCC training pipeline', () => {
  const frame = new Float32Array(400);
  const hann = new Float64Array(400).fill(1);
  frame[200] = 1;

  assert.equal(fftPower(frame, hann)[0], 1);
});
