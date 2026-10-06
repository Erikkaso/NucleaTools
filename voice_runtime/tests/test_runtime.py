import asyncio
from pathlib import Path

from voice_runtime.runtime import VoiceRuntime


class FakeWhisper:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def load(self) -> None:
        self.calls.append("load:whisper")

    def unload(self) -> None:
        self.calls.append("unload:whisper")

    def transcribe(self, path: Path, language: str) -> str:
        self.calls.append(f"transcribe:{path.name}:{language}")
        return "onde estao os teclados"


class FakeTts:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def load(self) -> None:
        self.calls.append("load:tts")

    def unload(self) -> None:
        self.calls.append("unload:tts")

    def synthesize(self, text: str) -> bytes:
        self.calls.append(f"speech:{text}")
        return b"ID3"


def test_transcription_releases_whisper_and_warms_tts() -> None:
    calls: list[str] = []
    runtime = VoiceRuntime(FakeWhisper(calls), FakeTts(calls))

    async def run() -> str:
        text = await runtime.transcribe(Path("voice.webm"), "pt")
        await runtime.join()
        return text

    assert asyncio.run(run()) == "onde estao os teclados"
    assert calls == [
        "load:whisper",
        "transcribe:voice.webm:pt",
        "unload:whisper",
        "load:tts",
    ]


def test_speech_reuses_warmed_tts() -> None:
    calls: list[str] = []
    runtime = VoiceRuntime(FakeWhisper(calls), FakeTts(calls))

    async def run() -> bytes:
        await runtime.warm_tts()
        return await runtime.synthesize("Resposta curta.")

    assert asyncio.run(run()) == b"ID3"
    assert calls == ["load:tts", "speech:Resposta curta."]
