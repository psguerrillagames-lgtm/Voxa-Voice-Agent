# Runbook: High p99 latency

## Triage
Check which service the latency originates in. Gateway latency is usually a symptom:
compare api-gateway p99 against each upstream (checkout, payments, inventory). The
service whose latency rose first and furthest is the likely origin.

## Recent deploy correlation
If latency stepped up within 15 minutes of a deploy to the originating service, treat
the deploy as the prime suspect. Look for new errors that only appear after the deploy
timestamp. Preferred remediation: rollback_deploy on that service. Do not restart, as a
restart keeps the bad version running.

## Load-driven latency
If rps and cpu rose together and there was no deploy, the service is saturated. Logs
show queue depth and CPU throttling. Remediation: scale_service to roughly
current_replicas * (current_rps / baseline_rps), capped at 20.
