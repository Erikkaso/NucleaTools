from pathlib import Path
import array
import math

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_stop_cue_matches_start_rms_without_clipping():
    levels = []
    for name in ("onsfx", "offsfx"):
        samples = array.array("h", (ROOT / "main" / "assets" / f"{name}.pcm").read_bytes())
        assert max(abs(sample) for sample in samples) < 32700
        levels.append(math.sqrt(sum(sample * sample for sample in samples) / len(samples)))
    assert abs(20 * math.log10(levels[1] / levels[0])) < 1.0


@pytest.mark.parametrize("name", ["onsfx", "offsfx"])
def test_embedded_cue_is_short_non_silent_pcm16(name):
    pcm = (ROOT / "main" / "assets" / f"{name}.pcm").read_bytes()
    assert pcm and len(pcm) % 2 == 0
    assert not pcm.startswith(b"RIFF")
    assert 0.1 < len(pcm) / 48000 < 1.2
    samples = array.array("h", pcm)
    assert max(abs(sample) for sample in samples) > 1000


def test_cues_are_embedded_only_when_enabled():
    cmake = (ROOT / "main" / "CMakeLists.txt").read_text()
    assert "if(CONFIG_NUCLEA_RECORDING_SFX_ENABLED)" in cmake
    assert "assets/onsfx.pcm" in cmake
    assert "assets/offsfx.pcm" in cmake


def test_sfx_job_uses_same_serial_worker_as_tts():
    worker = (ROOT / "main" / "audio_upload_worker.cc").read_text()
    assert "PlayRecordingCue(self->speaker_, job.cue)" in worker
    assert worker.index("PlayRecordingCue(self->speaker_, RecordingCue::kOff)") < worker.index("uploader.Upload")
    assert "job.url[0]" in worker


def test_capture_is_drained_and_start_cue_is_excluded_from_recording():
    app = (ROOT / "main" / "app_main.cc").read_text()
    assert "upload_worker.StartCue(RecordingCue::kOn)" in app
    assert "upload_worker.PollCue" in app
    assert app.index("capture.ReadPcm16") < app.index("if (upload_worker.Busy() && !upload_worker.Interruptible()) continue;")
    assert "capture.LastTimestampMs() < recording_start_at" in app
    assert "recorder.Start(chunk, 0" in app
