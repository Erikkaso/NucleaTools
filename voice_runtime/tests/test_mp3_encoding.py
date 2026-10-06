import numpy as np

from voice_runtime.engines import encode_mp3


def test_encode_mp3_returns_mpeg_bytes() -> None:
    waveform = np.zeros(24_000, dtype=np.float32)

    audio = encode_mp3(waveform, sample_rate=24_000)

    assert len(audio) > 0
    assert audio[:2] in {b"\xff\xf3", b"\xff\xfb"}
