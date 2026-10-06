import sys
from types import ModuleType

from voice_runtime.engines import LocalWhisperEngine


def test_whisper_load_uses_cpu_settings_from_environment(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeWhisperModel:
        def __init__(self, model: str, *, device: str, compute_type: str) -> None:
            captured.update(model=model, device=device, compute_type=compute_type)

    faster_whisper = ModuleType("faster_whisper")
    faster_whisper.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", faster_whisper)
    monkeypatch.setenv("WHISPER_MODEL", "small")
    monkeypatch.setenv("WHISPER_DEVICE", "cpu")
    monkeypatch.setenv("WHISPER_COMPUTE_TYPE", "int8")

    engine = LocalWhisperEngine()
    engine.load()

    assert captured == {"model": "small", "device": "cpu", "compute_type": "int8"}


def test_whisper_load_defaults_to_cuda_turbo_model(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeWhisperModel:
        def __init__(self, model: str, *, device: str, compute_type: str) -> None:
            captured.update(model=model, device=device, compute_type=compute_type)

    faster_whisper = ModuleType("faster_whisper")
    faster_whisper.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", faster_whisper)
    monkeypatch.delenv("WHISPER_MODEL", raising=False)
    monkeypatch.delenv("WHISPER_DEVICE", raising=False)
    monkeypatch.delenv("WHISPER_COMPUTE_TYPE", raising=False)

    engine = LocalWhisperEngine()
    engine.load()

    assert captured == {"model": "large-v3-turbo", "device": "cuda", "compute_type": "int8_float16"}
