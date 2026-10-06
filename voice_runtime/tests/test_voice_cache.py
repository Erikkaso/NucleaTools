from pathlib import Path

from voice_runtime.voice_cache import cache_path_for_voice, load_or_prepare


class FakeConditionals:
    def __init__(self, payload: str) -> None:
        self.payload = payload

    def save(self, path: Path) -> None:
        path.write_text(self.payload, encoding="utf-8")

    def to(self, device: str) -> "FakeConditionals":
        assert device == "cuda"
        return self


class FakeModel:
    device = "cuda"

    def __init__(self) -> None:
        self.conds: FakeConditionals | None = None
        self.prepared = 0

    def prepare_conditionals(self, reference: str, exaggeration: float) -> None:
        assert Path(reference).is_file()
        assert exaggeration == 0.5
        self.prepared += 1
        self.conds = FakeConditionals("prepared")


def test_cache_key_changes_when_voice_reference_changes(tmp_path: Path) -> None:
    reference = tmp_path / "eric.wav"
    reference.write_bytes(b"first")
    first = cache_path_for_voice("eric", reference, tmp_path / "cache", "v3", 0.5)
    reference.write_bytes(b"second")
    second = cache_path_for_voice("eric", reference, tmp_path / "cache", "v3", 0.5)

    assert first != second


def test_prepare_creates_cache_for_later_warm_load(tmp_path: Path, monkeypatch) -> None:
    reference = tmp_path / "eric.wav"
    reference.write_bytes(b"voice")
    cache_path = tmp_path / "cache" / "eric.pt"
    prepared = FakeModel()

    assert load_or_prepare(prepared, reference, cache_path, 0.5) is False
    assert prepared.prepared == 1
    assert cache_path.read_text(encoding="utf-8") == "prepared"

    class Loader:
        @staticmethod
        def load(path: Path, map_location: str) -> FakeConditionals:
            assert path == cache_path
            assert map_location == "cpu"
            return FakeConditionals(path.read_text(encoding="utf-8"))

    monkeypatch.setattr("voice_runtime.voice_cache._load_conditionals", lambda: Loader)
    restored = FakeModel()

    assert load_or_prepare(restored, reference, cache_path, 0.5) is True
    assert restored.prepared == 0
    assert restored.conds is not None
    assert restored.conds.payload == "prepared"
