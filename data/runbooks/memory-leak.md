# Runbook: Memory leak / OOMKilled

## Symptoms
memory_pct climbs steadily over 30-60 minutes (a ramp, not a step), long GC pauses,
then OOMKilled container restarts and OutOfMemoryError in logs. Latency rises as GC
pauses grow.

## Remediation
Immediate: restart_service to reclaim memory and buy time (hours).
If a deploy in the last 24h touched the service, also schedule a rollback review.
If no recent deploy, open a ticket to capture a heap dump on the next occurrence.
