"""Runtime settings, read once from the environment (and .env if present)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class Settings:
    model: str = os.getenv("VOXA_MODEL", "claude-opus-5-5")
    # Voice needs fast turns; specialists are cheap read-only investigators.
    effort: str = os.getenv("VOXA_EFFORT", "low")
    dry_run: bool = _bool("VOXA_DRY_RUN", True)
    elevenlabs_api_key: str = os.getenv("ELEVENLABS_API_KEY", "")
    voice_id: str = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
    tts_model: str = os.getenv("ELEVENLABS_TTS_MODEL", "eleven_flash_v2_5")
    stt_model: str = os.getenv("ELEVENLABS_STT_MODEL", "scribe_v1")


settings = Settings()
