# Operations runbook

## Evidence to collect

Check /health/ready for database reachability, /metrics for status/cache counts,
structured log trace IDs and matching request_audit/reservations rows. Metrics do
not carry raw prompts or tenant IDs. Do not paste secrets or corpus text into tickets.

## Failure paths

- 401: check credential rotation and the configured tenant map; do not bypass auth.
- 403: review approved model/tenant policy and deployment version consistency.
- 429: inspect estimated spent/reserved units for the UTC day. Review pending calls
  before releasing reservations; a crashed request may already have consumed tokens.
- 422 no context: check authorized classifications, corpus generation/version and
  lexical query matching. Do not expand classifications as a troubleshooting shortcut.
- 502: check upstream reachability, timeout, bounded response schema and citations.
  Avoid blind retries because a failed remote call can still have incurred cost.
- 503 readiness: check database connectivity/DNS/migrations and preserve audit data.

## Credential exposure containment

Revoke the affected key, redeploy the credential map, disable upstream access if
necessary and escalate to the incident owner. Review hashes/trace IDs without
exporting answer-cache content. This is a documented exercise; no real incident
or measured mean time to contain is claimed.

## Azure rollout prerequisites

The private-only App Service requires private operator/CI connectivity. Provision
a PostgreSQL service and reviewed private provider route, populate Key Vault
secrets outside Terraform, and use references so plaintext keys are not stored in
plan/state. Review NSG routes, DNS resolution, service platform dependencies,
remote state and restore procedures. Terraform mock validation is not Azure
runtime validation. Do not apply the example to an account without these decisions.
