# AI Gateway Governance Service

A Python/FastAPI portfolio service demonstrating policy-governed retrieval access,
transactional estimated-token budgets, two-layer tenant-isolated caching and
metadata-only request auditing. Includes a private Azure App Service Terraform
blueprint. It is independent work, not a Pandora product or an operated enterprise
platform. Example documents and tenant identities are fictional.

## What it implements

- Server-side credentials map to tenants; requests cannot choose another tenant.
- Allowlisted models and document classifications are checked before cache lookup.
- Deterministic 128-dimensional feature-hashed embeddings and cosine vector search
  retrieve up to three authorized documents. This is lexical retrieval, not a
  learned semantic embedding model; hash collisions and irrelevant matches are possible.
- A fixed provider contract supplies a cited answer. The default provider extracts
  context locally and **is not an LLM**. An HTTPS adapter supports an upstream
  implementing this repository's JSON contract; no commercial LLM was called.
- Conditional SQL updates reserve capacity before upstream calls. Concurrent
  reservations cannot exceed the tenant's UTC-day budget. Successful calls settle
  the estimate; failed calls conservatively charge the full reservation because
  an upstream may already have consumed resources.
- A bounded process-memory L1 cache and SQL L2 cache use keys containing tenant,
  full policy content, corpus digest, prompt version and complete request. Both
  layers honor the original absolute expiry; policy changes invalidate entries.
- Audit rows contain question hashes, policy versions, outcomes and estimated
  units, rather than prompt or answer text. Cache rows do contain answer text.
- Health/readiness and authenticated Prometheus request-outcome metrics support
  triage. Error responses do not expose provider credentials or validation values.

## Setup and reproducible verification

Python 3.11+ is required. No Azure account or paid model key is needed for tests.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -c constraints.txt -e ".[dev]"
python -m ruff check .
python -m ruff format --check .
python -m pytest --cov=ai_gateway --cov-branch --cov-report=term-missing
python -m build
$env:GATEWAY_KEYS_JSON = '{"local-development-key-only":"design"}'
uvicorn ai_gateway.api:create_app --factory --host 127.0.0.1 --port 8080
```

On Linux/macOS activate with `source .venv/bin/activate` and set the environment
with `export GATEWAY_KEYS_JSON='{"local-development-key-only":"design"}'`.
The published local credential above is for synthetic development only.

```bash
curl -X POST http://127.0.0.1:8080/v1/answers \
  -H 'Authorization: Bearer local-development-key-only' \
  -H 'Content-Type: application/json' \
  -d '{"question":"What materials require design review?"}'
```

The result contains `answer`, `citations`, `trace_id`, `cache`, `policy_version`
and `estimated_tokens`. Repeat it for a `memory` cache hit. Restart the service
within the TTL for a `database` hit. Unknown models return 403; exhausted budgets
return 429; missing authorized context returns 422; upstream failures return 502.

## Configuration

| Variable | Purpose |
|---|---|
| `GATEWAY_KEYS_JSON` | Secret credential-to-tenant mapping; no default credentials |
| `GATEWAY_CONFIG` | Directory containing validated policy.json and corpus.json |
| `DATABASE_URL` | Default `sqlite:///gateway.db`; PostgreSQL `postgresql+psycopg://...` supported |
| `PROVIDER_ENDPOINT` | Optional fixed HTTPS endpoint implementing docs/provider-contract.md |
| `PROVIDER_TOKEN` | Required only for the HTTPS provider |
| `TEST_POSTGRES_URL` | Isolated test database used by PostgreSQL integration test |

Policy and corpus are loaded once per process. Restart to apply changes; service
operators must keep versions consistent across replicas. SQLite suits local use;
the Azure blueprint requires a separately provisioned private PostgreSQL database.

## Architecture, controls and trade-offs

```text
Authenticated REST request -> tenant/model policy -> L1 / SQL L2 cache
                                      |
                                authorized retrieval
                                      |
                           SQL budget reservation -> provider
                                      |
                      validate citations/output -> settle + audit + cache
```

See [architecture decisions](docs/architecture.md),
[provider contract](docs/provider-contract.md),
[operations](docs/operations.md), [requirements](docs/requirements.md) and
[AI-assisted development](docs/ai-assisted-development.md).

## Azure infrastructure verification

```bash
terraform -chdir=infra/azure fmt -check
terraform -chdir=infra/azure init -backend=false
terraform -chdir=infra/azure validate
terraform -chdir=infra/azure test
```

Terraform mock plan tests need no Azure authentication. The blueprint defines
separate integration/private-endpoint subnets, an NSG, private-only Linux App
Service, managed identity, Key Vault secret references, a private endpoint and
private DNS linkage. It is not applied to an Azure subscription. Production
deployment needs a reviewed PostgreSQL endpoint, provider connectivity, remote
state, private CI access, secret creation/rotation and network policy approval.

GitHub Actions runs Python lint/tests/coverage and wheel build, a real PostgreSQL
service-container integration test, Docker image build, and Terraform validation
plus mock policy tests. Docker is verified in hosted CI, not by the unavailable
local Docker daemon.

## Deliberate limitations

- No production history, load-test result, technical leadership or incident MTTC
  improvement is claimed. No MLflow or Databricks execution is included.
- Token units use `ceil(characters/4)`, not a provider tokenizer. They are not
  billed-token accounting or an exact financial cost limit.
- Citation allowlisting proves document IDs are authorized, not answer faithfulness
  or resistance to prompt injection. Learned retrieval and model evals are future work.
- Authentication uses static keys; add enterprise identity, key rotation, role
  separation and authorization for operations before deployment.
- Duplicate concurrent cache misses can call the provider more than once; their
  reservations remain budget-bounded. There is no distributed single-flight or
  automatic retry. A crash may leave a pending reservation; fail-closed capacity
  remains reserved until the UTC day changes or an operator reconciles it.
- Database tables are created at startup for tests. Use migrations for deployment.
  Expired cache rows are removed when read; add retention jobs and encryption.
- The REST interface limits fields but has no streaming whole-body size limiter;
  enforce ingress body/rate limits. Public health endpoints expose status only.
- The Terraform NSG restricts outbound to approved private destination CIDRs; the
  full App Service platform dependency paths still need environment validation.
