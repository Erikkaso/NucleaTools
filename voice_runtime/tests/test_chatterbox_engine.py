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
