# Runbook: Database connection pool exhaustion

## Symptoms
Errors like "connection pool exhausted" or "waited 3000ms for connection", error rate
and latency spike together on one service.

## Causes
1. A deploy changed pool size or connection handling (most common, check the deploy
   summary for "pool", "DB client", "connection").
2. A slow query holds connections (check the database service, not the caller).

## Remediation
Cause 1: rollback_deploy the service. Then file a bug against the deploy author.
Cause 2: escalate to the database on-call.
Never raise DB_POOL_SIZE above 100 without DBA approval.
