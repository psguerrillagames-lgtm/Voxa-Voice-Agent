# Runbook: Bad runtime configuration

## Symptoms
Service enters crashloop or error rate jumps right after a "config reloaded" log line,
with no code deploy. Errors mention a config key, unresolvable host, or invalid value.

## Diagnosis
Use get_config to read current values. Compare against known-good hosts:
redis-prod.internal:6379, postgres-prod.internal:5432. Typos in hostnames are the
most common cause.

## Remediation
set_config the offending key back to its known-good value. Rolling back the code
deploy will NOT help because config is loaded separately from config-service.
