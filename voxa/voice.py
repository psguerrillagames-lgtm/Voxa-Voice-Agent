"""ElevenLabs speech: text-to-speech for Voxa's voice, speech-to-text for replies.

Uses the REST API directly over httpx (async). When no API key is configured the
functions degrade gracefully so the text-only flow and tests still work.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from voxa.config import settings
from voxa.observability import Tracer

API = "https://api.elevenlabs.io/v1"


class VoiceUnavailable(RuntimeError):
    pass


class ElevenLabsVoice:
    def __init__(self, tracer: Tracer, api_key: str = settings.elevenlabs_api_key,
                 voice_id: str = settings.voice_id, tts_model: str = settings.tts_model,
                 stt_model: str = settings.stt_model,
                 client: httpx.AsyncClient | None = None):
        self.tracer = tracer
        self.api_key = api_key
        self.voice_id = voice_id
        self.tts_model = tts_model
        self.stt_model = stt_model
        self.client = client or httpx.AsyncClient(timeout=30)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict:
        if not self.api_key:
            raise VoiceUnavailable("ELEVENLABS_API_KEY is not set")
        return {"xi-api-key": self.api_key}

    async def stream_speech(self, text: str) -> AsyncIterator[bytes]:
        """Stream MP3 audio chunks as ElevenLabs generates them (low time-to-first-audio)."""
        url = f"{API}/text-to-speech/{self.voice_id}/stream"
        body = {"text": text, "model_id": self.tts_model,
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}
        with self.tracer.span("voice", "tts", agent="voice", chars=len(text)) as span:
            async with self.client.stream("POST", url, headers=self._headers(), json=body,
                                          params={"output_format": "mp3_44100_128"}) as resp:
                resp.raise_for_status()
                first = True
                async for chunk in resp.aiter_bytes():
                    if first:
                        span.data["first_chunk_ms"] = span.ms_so_far()
                        first = False
                    yield chunk

    async def speak(self, text: str) -> bytes:
        return b"".join([chunk async for chunk in self.stream_speech(text)])

    async def transcribe(self, audio: bytes, filename: str = "reply.webm",
                         content_type: str = "audio/webm") -> str:
        with self.tracer.span("voice", "stt", agent="voice", bytes=len(audio)) as span:
            resp = await self.client.post(
                f"{API}/speech-to-text", headers=self._headers(),
                data={"model_id": self.stt_model},
                files={"file": (filename, audio, content_type)})
            resp.raise_for_status()
            text = resp.json().get("text", "").strip()
            span.data["transcript"] = text
            return text
