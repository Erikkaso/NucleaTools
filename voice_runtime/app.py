"""Aplicacao unica de transcricao e sintese de voz."""

from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from voice_runtime.engines import LocalChatterboxEngine, LocalWhisperEngine
from voice_runtime.runtime import VoiceRuntime

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


class SpeechRequest(BaseModel):
    text: str


def create_app(voice_runtime: VoiceRuntime) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await voice_runtime.warm_tts()
        yield

    app = FastAPI(title="Voice Runtime", version="1.0.0", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ready"}

    @app.post("/v1/audio/transcriptions")
    async def transcriptions(
        request: Request, file: UploadFile | None = OPTIONAL_FILE, language: str = "pt"
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
            return {"text": await voice_runtime.transcribe(path, language.strip() or "pt")}
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail="Servico de transcricao indisponivel") from error
        finally:
            if file is not None:
                await file.close()
            path.unlink(missing_ok=True)

    @app.post("/v1/audio/speech")
    async def speech(payload: SpeechRequest) -> Response:
        text = payload.text.strip()
        if not text:
            raise HTTPException(status_code=422, detail="texto e obrigatorio")
        try:
            audio = await voice_runtime.synthesize(text)
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail="Servico de sintese indisponivel") from error
        return Response(content=audio, media_type="audio/mpeg")

    return app


runtime = VoiceRuntime(LocalWhisperEngine(), LocalChatterboxEngine())
app = create_app(runtime)
