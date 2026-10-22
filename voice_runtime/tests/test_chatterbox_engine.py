import sys
from types import ModuleType

from voice_runtime.engines import LocalChatterboxEngine


def test_chatterbox_load_uses_only_supported_device_argument(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeChatterbox:
        @classmethod
        def from_pretrained(cls, *, device: str):
            captured["device"] = device
            return object()

    chatterbox = ModuleType("chatterbox")
    mtl_tts = ModuleType("chatterbox.mtl_tts")
    mtl_tts.ChatterboxMultilingualTTS = FakeChatterbox
    monkeypatch.setitem(sys.modules, "chatterbox", chatterbox)
    monkeypatch.setitem(sys.modules, "chatterbox.mtl_tts", mtl_tts)

    engine = LocalChatterboxEngine()
    engine.load()

    assert captured == {"device": "cuda"}


def test_warmup_uses_configured_text(monkeypatch):
    engine = LocalChatterboxEngine()
    calls = []
    monkeypatch.setenv("TTS_WARMUP_TEXT", " Bom dia. ")
    monkeypatch.setattr(engine, "synthesize", calls.append)
    engine.warmup()
    assert calls == ["Bom dia."]


def test_empty_warmup_text_skips_generation(monkeypatch):
    engine = LocalChatterboxEngine()
    calls = []
    monkeypatch.setenv("TTS_WARMUP_TEXT", "")
    monkeypatch.setattr(engine, "synthesize", calls.append)
    engine.warmup()
    assert not calls


def test_synthesis_reuses_model_and_preserves_quality_parameters(monkeypatch, caplog):
    import logging
    import numpy as np
    from voice_runtime import engines

    class Waveform:
        def squeeze(self, axis):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return np.zeros(24000, dtype=np.float32)

    class Model:
        sr = 24000

        def __init__(self):
            self.calls = []

        def generate(self, text, **kwargs):
            self.calls.append((text, kwargs))
            return Waveform()

    engine = LocalChatterboxEngine()
    engine.model = Model()
    monkeypatch.setenv("TTS_LANGUAGE_ID", "pt")
    monkeypatch.setenv("TTS_EXAGGERATION", "0.5")
    monkeypatch.setenv("TTS_CFG_WEIGHT", "0.5")
    monkeypatch.setattr(engines, "encode_mp3", lambda samples, rate: b"mp3")
    with caplog.at_level(logging.INFO):
        assert engine.synthesize("Ola") == b"mp3"
        assert engine.synthesize("Outra frase") == b"mp3"
    assert engine.model.calls == [
        (text, {"language_id": "pt", "exaggeration": 0.5, "cfg_weight": 0.5})
        for text in ("Ola", "Outra frase")
    ]
    assert "generation_ms=" in caplog.text
    assert "encoding_ms=" in caplog.text
