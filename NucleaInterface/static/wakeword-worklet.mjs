class WakewordCaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const samples = inputs[0]?.[0];
    if (samples?.length) {
      const copied = samples.slice();
      this.port.postMessage(copied.buffer, [copied.buffer]);
    }
    return true;
  }
}

registerProcessor('wakeword-capture', WakewordCaptureProcessor);
