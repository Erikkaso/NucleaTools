# Firmware speaker contract

`CONFIG_NUCLEA_SPEAKER_ENABLED=y` requests multipart `responseMode=speaker`
on the existing `/api/device-audio` POST. Disabled builds omit the field and
retain browser delivery. There is no retry, replay, second request or token auth.

Public menu options (Nuclea device audio):

| Symbol (CONFIG_ prefix omitted) | Default |
| --- | --- |
| NUCLEA_SPEAKER_ENABLED | y |
| NUCLEA_SPEAKER_BCLK_GPIO | 14 |
| NUCLEA_SPEAKER_WS_GPIO | 21 |
| NUCLEA_SPEAKER_DIN_GPIO | 13 |
| NUCLEA_SPEAKER_VOLUME_PERCENT | 10 (range 0..100) |

MAX98357A uses I2S1 TX, Philips stereo 16-bit at 24000 Hz, with the scaled
mono sample duplicated into both slots. SD tied to 3V3 selects the left slot;
VIN is 5V and grounds are common. Microphone remains I2S0 RX on BCLK41/WS42/SD40.
Pin assertions reject conflicts with microphone, enabled display and reserved pins.

The same POST response must have a 2xx status and `application/x-ndjson`
(parameters accepted), followed by LF- or CRLF-terminated JSON objects:

1. `{"type":"start","format":"pcm_s16le","channels":1}` exactly once.
2. One or more `audio` objects with `seq` starting at zero, incrementing by one,
   `sample_rate:24000`, and `data` containing base64 PCM16LE mono. Decoded
   lengths must be positive, even, and at most 4800 bytes (100 ms).
3. `ping` may occur between start and end without advancing audio progress.
4. `{"type":"end"}` is mandatory. No objects may follow it.

An `error` event always fails the response and stops playback. Malformed JSON,
duplicate keys, excessive nesting, invalid base64, wrong format/rate/sequence,
unterminated lines, missing end, transport errors and wrong MIME also fail.
JSON error bodies are never sent to I2S as PCM. Lines occupy at most 8191 bytes
excluding LF and including any CR. The 8192-byte line and 4800-byte decoded PCM
buffers are explicitly allocated in PSRAM, not internal RAM shared with TLS.
JSON metadata still uses the normal cJSON allocator; global hooks are unchanged.

The persistent consumer task owns I2S. Its static FreeRTOS queue uses 192800
bytes of PSRAM for up to four seconds of PCM. Playback starts/rebuffers around
48000 queued PCM bytes (one second). A heap-resident producer coalesces PCM
across event boundaries into 480-byte queue frames, retaining a partial frame
until EOF; two-byte events consume queue capacity at the same PCM rate as full
events. Valid EOF flushes the partial frame and responses shorter than
one second. Backpressure is bounded; network reads never run on the speaker task.
The DMA ring is four 10 ms descriptors with automatic clearing after callbacks.
Success waits for a full ring of silence and another 50 ms before disabling TX.
Abort disables TX and resets the queue before acknowledging session completion;
every new playback preloads all DMA descriptors with zeros.

Network operations have a 220 second ceiling within a 240 second request budget.
Body reads use the IDF chunk decoder. Before each read and on each ON_DATA
callback, the owner thread shrinks the next internal transport timeout to the
minimum of one second and the remaining absolute/audio progress budget (one
millisecond once expired). Expiry is latched, and returned data is rejected
before parsing when expired. Only accepted PCM renews progress, never raw data
or pings. This bounds slow body-data trickles without per-byte socket reads or
reentrant close/cancel calls. IDF partial headers, chunk extensions and trailers
do not emit ON_DATA: these metadata trickles can still extend the SDK call past
the budget. There is no SDK patch enforcing a hard wall-clock deadline there.
No audio
for 220 seconds before the first event or 90 seconds afterwards fails even if
pings continue. A queue push waits at most six seconds; final playback waits
at most eight seconds, abort acknowledgement at most two seconds. These local
waits can extend past the HTTP budget. Buffer/task allocation is persistent at
startup; per-response JSON/decoder memory is released when the upload returns.

Worker Busy includes playback and DMA drain. Playing is atomic; the app shows
green while playing, drains microphone capture throughout Busy, then resets the
inference window and drains capture for another two seconds before inference.

## Focused checks

`tools/speaker_stream_tests.cc` uses compile-time assertions and is included in
the firmware CMake sources. It also needs only a C++17 compiler, without IDF,
cJSON, mbedTLS or hardware:

```sh
clang++ -std=c++17 -Wall -Wextra -Werror -Imain -fsyntax-only tools/speaker_stream_tests.cc
```

It exercises arbitrary splits, bytewise framing, CRLF, exact line capacity,
overflow, embedded NUL, truncation, failed consumers, event order, sequence,
rate, decoded-length constraints, terminal end, tiny-event coalescing, every
even PCM split, partial-frame flush/reset and slow-trickle deadline arithmetic.
cJSON/mbedTLS decoding,
FreeRTOS concurrency, I2S timing and acoustic echo still need target execution.
Verify short replies, replies longer than the buffer, underrun/rebuffer, a
disconnect during playback, malformed/error events followed by a good request,
and a build with speaker disabled. Do not flash hardware as part of these checks.

## Troubleshooting

The ESP explicitly requests `Accept-Encoding: identity`; gzip/Brotli response
bodies are rejected before playback. Disable forced compression in the public
gateway's Ingress. HTTP 200 with `PCM_bytes=0` and `aborted=1` means the uploader
cancelled playback before I2S wrote any samples; it is not proof of amplifier
failure. Headers now log content encoding and the gateway's request ID. Body
failures distinguish transport error, premature EOF, overlong lines, binary/NUL
content, blank lines and rejected JSON events. Correlate the request ID with
gateway logs, without logging raw base64 or speech.
Early JSON failures now report envelope/parse stage, byte offset, expected
packet sequence and available/largest internal memory block. Other event
failures distinguish metadata, base64, sequence/size, speaker queue and state.
An HTTP 200 and one accepted PCM packet exclude neither later JSON failure nor
memory pressure: the whole response must reach a valid terminal `end` event.

`Playback ended` also reports input RMS in dBFS, near-full-scale sample count
(`clipped`) and queue rebuffer count. Rebuffering counts software queue starvation,
not measured DMA underflows. Low input RMS can explain quiet speech; repeated
rebuffering explains pauses. Clean PCM with distorted sound still requires
checking amplifier power and wiring; do not increase gain without measuring.
For a 4-ohm, 3W speaker, keep VIN stable at 5V under load, grounds common, and
the speaker connected only between OUT+ and OUT-, never between output and GND.
