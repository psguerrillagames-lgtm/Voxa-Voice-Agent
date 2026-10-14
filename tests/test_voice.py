import httpx
import pytest

from voxa.observability import Tracer
from voxa.voice import ElevenLabsVoice, VoiceUnavailable


def _voice(handler) -> ElevenLabsVoice:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return ElevenLabsVoice(Tracer(), api_key="test-key", voice_id="v1", client=client)


async def test_tts_streams_audio_with_auth_header():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers["xi-api-key"]
        return httpx.Response(200, content=b"ID3fake-mp3")

    audio = await _voice(handler).speak("Hello, checkout is down.")
    assert audio == b"ID3fake-mp3"
    assert "/text-to-speech/v1/stream" in seen["url"] and seen["key"] == "test-key"


async def test_stt_returns_transcript():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/speech-to-text"
        assert b"scribe_v1" in request.content
        return httpx.Response(200, json={"text": " Yes, roll it back. "})

    assert await _voice(handler).transcribe(b"audio") == "Yes, roll it back."


async def test_missing_key_raises():
    voice = ElevenLabsVoice(Tracer(), api_key="")
    assert not voice.enabled
    with pytest.raises(VoiceUnavailable):
        await voice.speak("hi")
