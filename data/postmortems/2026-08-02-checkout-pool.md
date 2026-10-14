# Postmortem 2026-08-02: checkout outage after DB client refactor

Deploy v2.1.0 of checkout replaced the DB client and defaulted pool size to 5. Under
evening load the pool exhausted within 10 minutes, p99 rose 4x and gateway alarms
fired first, which sent the responder to the gateway. Time to mitigate: 42 minutes.
Fix: rollback of checkout. Lesson: gateway latency alerts are usually downstream
symptoms; check deploys on upstream services first.
