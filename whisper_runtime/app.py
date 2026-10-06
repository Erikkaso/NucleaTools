"""API HTTP independente para transcricao de audio."""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Protocol

from fastapi import FastAPI, File, HTTPException, Request, UploadFile

from whisper_runtime.config import WhisperSettings
from whisper_runtime.engine import FasterWhisperEngine

ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".mp4", ".webm", ".ogg", ".flac", ".aac", ".opus"}
MEDIA_TYPE_EXTENSIONS = {
    "audio/aac": ".aac",
    "audio/flac": ".flac",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "audio/wav": ".wav",
    "audio/webm": ".webm",
}
OPTIONAL_FILE = File(default=None)


class WhisperEngine(Protocol):
    def load(self) -> None: ...

    def transcribe(self, path: Path, language: str) -> str: ...


def create_app(engine: WhisperEngine, settings: WhisperSettings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await asyncio.to_thread(engine.load)
        yield

    app = FastAPI(title="Whisper Runtime", version="1.0.0", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ready", "model": settings.model, "device": settings.device}

    @app.post("/v1/audio/transcriptions")
    async def transcriptions(
        request: Request, file: UploadFile | None = OPTIONAL_FILE, language: str | None = None
    ) -> dict[str, str]:
        if file is not None and file.filename:
            suffix = Path(file.filename).suffix.lower()
            content = await file.read()
        else:
            media_type = request.headers.get("content-type", "").split(";", maxsplit=1)[0].lower()
            suffix = MEDIA_TYPE_EXTENSIONS.get(media_type, "")
            content = await request.body()
        if not content:
            raise HTTPException(status_code=400, detail="O campo file e obrigatorio")
        if suffix not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail="Formato nao suportado")

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
            temporary.write(content)
            path = Path(temporary.name)
        try:
            selected_language = (language or settings.language).strip() or settings.language
            text = await asyncio.to_thread(engine.transcribe, path, selected_language)
            return {"text": text}
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail="Servico de transcricao indisponivel") from error
        finally:
            if file is not None:
                await file.close()
            path.unlink(missing_ok=True)

    return app


settings = WhisperSettings.from_environment()
app = create_app(FasterWhisperEngine(settings), settings)
