"""HTTP API for the resident Chatterbox TTS engine."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from voice_runtime.engines import LocalChatterboxEngine
from voice_runtime.runtime import VoiceRuntime
from voice_runtime.streaming import StreamTickets, pcm_events

logger = logging.getLogger(__name__)


class SpeechRequest(BaseModel):
    text: str


class StreamRequest(BaseModel):
    text: str


def create_app(runtime: VoiceRuntime | None = None) -> FastAPI:
    voice_runtime = runtime if runtime is not None else VoiceRuntime(LocalChatterboxEngine())
    tickets = StreamTickets()

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

    @app.post('/v1/audio/speech/streams', status_code=202)
    async def create_stream(body: StreamRequest):
        text = body.text.strip()
        if not text or len(text) > 6000:
            raise HTTPException(422, 'Texto deve ter entre 1 e 6000 caracteres')
        if not voice_runtime.is_ready:
            raise HTTPException(503, 'Servico de sintese indisponivel')
        try:
            stream_id = tickets.create(text)
        except OverflowError as error:
            raise HTTPException(429, 'Muitas respostas aguardando reproducao') from error
        return {'stream_id': stream_id, 'format': 'pcm_s16le', 'channels': 1}

    @app.get('/v1/audio/speech/streams/{stream_id}')
    async def read_stream(stream_id: str):
        try:
            text = tickets.take(stream_id)
        except KeyError as error:
            raise HTTPException(404, 'Resposta expirada ou ja consumida') from error
        return StreamingResponse(
            pcm_events(voice_runtime, text, stream_id),
            media_type='application/x-ndjson',
            headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'},
        )

    return app


app = create_app()
