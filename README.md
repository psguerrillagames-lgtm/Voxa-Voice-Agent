# Voxa — Voice-First Multi-Agent SRE

When a production alert fires, **Voxa calls you first**:

> "Hi, checkout latency jumped 40% in the last ten minutes. It started right after deploy v2.3.
> The logs show connection-pool timeouts. Want me to roll back?"

You answer by voice. A team of Claude agents investigates logs, metrics and deploys, checks
its own diagnosis, and only takes risky actions after your spoken approval.

## Stack

- **Claude** (Anthropic API): planner, specialist agents, critic
- **ElevenLabs**: text-to-speech for the call, speech-to-text for your replies
- **Python / FastAPI** backend, plain-JS web dashboard

## Status

Work in progress. See commit history.
