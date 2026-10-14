# Runbook: Third-party dependency outage

## Symptoms
Errors referencing an external host (e.g. bank-gateway.partner.com) returning 5xx,
no deploy or config change on our side, callers of the affected service show
secondary errors.

## Remediation
There is nothing to roll back or restart. Escalate: page the vendor through the
partner status page and the payments on-call. Consider enabling the degraded-mode
banner. Do not restart our services; it only adds load during recovery.
