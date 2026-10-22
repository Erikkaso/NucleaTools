"""HTTP API for the resident Chatterbox TTS engine."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from voice_runtime.engines import LocalChatterboxEngine
from voice_runtime.runtime import VoiceRuntime

logger = logging.getLogger(__name__)


class SpeechRequest(BaseModel):
    text: str


def create_app(runtime: VoiceRuntime | None = None) -> FastAPI:
    voice_runtime = runtime if runtime is not None else VoiceRuntime(LocalChatterboxEngine())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logging.basicConfig(level=logging.INFO)
        await voice_runtime.warm_tts()
        try:
            yield
        finally:
            await voice_runtime.close()

    app = FastAPI(title="Voice Runtime TTS", version="2.0.0", lifespan=lifespan)

    @app.get("/health")
    async def health():
        ready = voice_runtime.is_ready
        return JSONResponse(
            {"status": "ready" if ready else "starting", "service": "tts"},
            status_code=200 if ready else 503,
        )

    @app.post("/v1/audio/speech")
    async def speech(body: SpeechRequest):
        text = body.text.strip()
        if not text:
            raise HTTPException(status_code=422, detail="Texto nao pode ser vazio")
        try:
            audio = await voice_runtime.synthesize(text)
        except RuntimeError as error:
            logger.exception("tts_request_failed")
            raise HTTPException(status_code=503, detail="Servico de sintese indisponivel") from error
        return Response(content=audio, media_type="audio/mpeg")

    return app


app = create_app()
