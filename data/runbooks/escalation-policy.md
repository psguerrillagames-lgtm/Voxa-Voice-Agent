# Escalation policy

- Severity critical + customer-facing checkout/payments: page the on-call within 5 min.
- Destructive actions (rollback) require explicit on-call approval.
- WRITE actions (restart, scale, config change) require approval during business hours
  and for any payments service change.
- When confidence in a root cause is below 0.6, escalate instead of acting.
