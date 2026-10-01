# Requirements and executable evidence

| Requirement | Implementation | Test |
|---|---|---|
| Credential determines tenant | api.authenticate | authentication/input contract tests |
| Policy enforced before cache | Gateway.ask | policy denial and policy change tests |
| Tenant/classification filtered retrieval | Retriever.search | cross-tenant and label assertions |
| Model/corpus/policy-sensitive cache | cache key and absolute expiry | corpus, policy, TTL tests |
| Concurrent budget bounded | Store.reserve | eight-thread SQLite and PostgreSQL tests |
| Settlement performed once | Store.settle | idempotent and excessive settlement tests |
| Invalid upstream output fails closed | HttpProvider and Gateway | status, redirects, schema, size, citation tests |
| Provider failure cannot hide spent capacity | conservative settlement | failed provider ledger assertions |
| No question text in audit | Store.record | question/answer absence assertions |
| Observable readiness | API probes and counters | metrics and database failure tests |
| Private-only Azure blueprint | Terraform resources | mock plan assertions |

Tests describe implemented behavior, not production suitability or model accuracy.
