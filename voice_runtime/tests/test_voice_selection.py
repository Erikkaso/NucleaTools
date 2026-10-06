from pathlib import Path

from voice_runtime.config import select_voice


def test_existing_named_voice_is_selected(tmp_path: Path) -> None:
    (tmp_path / "eric.wav").write_bytes(b"wav")

    selection = select_voice("eric", tmp_path)

    assert selection.name == "eric"
    assert selection.reference == tmp_path / "eric.wav"
    assert selection.used_fallback is False


def test_missing_named_voice_falls_back_to_default(tmp_path: Path) -> None:
    selection = select_voice("julio", tmp_path)

    assert selection.name == "default"
    assert selection.reference is None
    assert selection.used_fallback is True


def test_invalid_voice_name_falls_back_to_default(tmp_path: Path) -> None:
    selection = select_voice("../secret", tmp_path)

    assert selection.name == "default"
    assert selection.used_fallback is True
