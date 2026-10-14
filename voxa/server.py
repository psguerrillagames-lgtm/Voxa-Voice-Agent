"""FastAPI app: alert webhook, voice call endpoints and a live event stream.

    POST /alerts                     alert webhook -> Voxa investigates and "calls" you
    POST /scenarios/{name}/trigger   demo: inject a fault and fire its alert
    POST /incidents/{id}/reply       engineer reply as text, or audio (ElevenLabs STT)
    GET  /incidents/{id}/speech      Voxa's latest line as streamed MP3 (ElevenLabs TTS)
    WS   /ws                         live agent trace for the dashboard
"""

from __future__ import annotations

import asyncio
import itertools
from pathlib import Path
from typing import Annotated

import anthropic
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse

from voxa.agents.orchestrator import Orchestrator
from voxa.config import settings
from voxa.guardrails import Policy
from voxa.llm import ClaudeLLM, LLMClient
from voxa.memory import IncidentMemory
from voxa.observability import Tracer
from voxa.rag import DATA_DIR, KnowledgeBase
from voxa.session import IncidentSession
from voxa.sim import SCENARIOS, Infra
from voxa.tools import action_tools
from voxa.voice import ElevenLabsVoice

WEB = Path(__file__).resolve().parent.parent / "web"


class Hub:
    """Fans tracer events out to every connected dashboard."""

    def __init__(self) -> None:
        self.queues: set[asyncio.Queue] = set()

    def publish(self, event: dict) -> None:
        for q in self.queues:
            q.put_nowait(event)


def create_app(llm_factory=None, memory: IncidentMemory | None = None,
               voice_key: str | None = None) -> FastAPI:
    app = FastAPI(title="Voxa", version="0.1.0")
    hub = Hub()
    kb = KnowledgeBase.from_dir()
    memory = memory or IncidentMemory(settings.memory_db or DATA_DIR / "memory.db")
    sessions: dict[int, IncidentSession] = {}
    ids = itertools.count(1)

    def new_session(infra: Infra, incident_id: int) -> IncidentSession:
        tracer = Tracer()
        tracer.subscribe(lambda e: hub.publish({"incident": incident_id, **e}))
        llm: LLMClient = llm_factory(tracer) if llm_factory else ClaudeLLM(tracer)
        orch = Orchestrator(llm, infra, kb, memory, tracer)
        policy = Policy({t.name: t for t in action_tools(infra)}, dry_run=settings.dry_run)
        return IncidentSession(llm, infra, orch, policy, memory, tracer)

    def voice_for(session: IncidentSession) -> ElevenLabsVoice:
        key = settings.elevenlabs_api_key if voice_key is None else voice_key
        return ElevenLabsVoice(session.tracer, api_key=key)

    def get(incident_id: int) -> IncidentSession:
        if incident_id not in sessions:
            raise HTTPException(404, "unknown incident")
        return sessions[incident_id]

    def view(incident_id: int, s: IncidentSession) -> dict:
        inv = s.investigation
        return {
            "id": incident_id, "state": s.state,
            "transcript": [{"speaker": t.speaker, "text": t.text} for t in s.transcript],
            "diagnosis": inv.diagnosis.model_dump() if inv else None,
            "proposed_action": s.proposed.model_dump() if s.proposed else None,
            "audit": s.policy.audit, "metrics": s.tracer.summary(),
            "voice": voice_for(s).enabled,
        }

    async def open_incident(alert: dict, infra: Infra) -> dict:
        incident_id = next(ids)
        session = new_session(infra, incident_id)
        sessions[incident_id] = session
        try:
            await session.start(alert)
        except anthropic.AuthenticationError as exc:
            raise HTTPException(503, "Anthropic rejected the API key. Check ANTHROPIC_API_KEY "
                                     "in .env and restart the server.") from exc
        except TypeError as exc:
            if "authentication" not in str(exc):
                raise
            raise HTTPException(503, "No Anthropic API key. Put ANTHROPIC_API_KEY=... in .env "
                                     "next to pyproject.toml and restart the server.") from exc
        return view(incident_id, session)

    @app.get("/")
    async def index():
        return FileResponse(WEB / "index.html")

    @app.get("/health")
    async def health():
        return {"ok": True, "model": settings.model, "dry_run": settings.dry_run}

    @app.get("/scenarios")
    async def scenarios():
        return [{"name": s.name, "alert": s.alert, "description": s.description}
                for s in SCENARIOS.values()]

    @app.post("/scenarios/{name}/trigger")
    async def trigger(name: str):
        if name not in SCENARIOS:
            raise HTTPException(404, "unknown scenario")
        scenario = SCENARIOS[name]
        return await open_incident(scenario.alert, scenario.build())

    @app.post("/alerts")
    async def alert_webhook(alert: dict):
        # Real alerts run against the live (here: baseline simulated) environment.
        return await open_incident(alert, Infra())

    @app.get("/incidents/{incident_id}")
    async def incident(incident_id: int):
        return view(incident_id, get(incident_id))

    @app.post("/incidents/{incident_id}/reply")
    async def reply(incident_id: int, text: Annotated[str | None, Form()] = None,
                    audio: Annotated[UploadFile | None, File()] = None):
        session = get(incident_id)
        if audio is not None:
            data = await audio.read()
            text = await voice_for(session).transcribe(
                data, audio.filename or "reply.webm", audio.content_type or "audio/webm")
        if not text:
            raise HTTPException(400, "send text or audio")
        await session.reply(text)
        return view(incident_id, session) | {"heard": text}

    @app.get("/incidents/{incident_id}/speech")
    async def speech(incident_id: int):
        session = get(incident_id)
        voice = voice_for(session)
        if not voice.enabled:
            raise HTTPException(503, "ELEVENLABS_API_KEY not configured")
        line = next((t.text for t in reversed(session.transcript) if t.speaker == "voxa"), "")
        return StreamingResponse(voice.stream_speech(line), media_type="audio/mpeg")

    @app.get("/memory")
    async def memory_view():
        return memory.all()

    @app.websocket("/ws")
    async def ws(socket: WebSocket):
        await socket.accept()
        queue: asyncio.Queue = asyncio.Queue()
        hub.queues.add(queue)
        try:
            while True:
                await socket.send_json(await queue.get())
        except WebSocketDisconnect:
            pass
        finally:
            hub.queues.discard(queue)

    return app


app = create_app()
