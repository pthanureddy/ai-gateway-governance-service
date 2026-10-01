# Executed verification

Verification date: 1 October 2026.

## Local host

- Python 3.12.14 in an isolated virtual environment.
- `pytest --cov=ai_gateway --cov-branch`: 45 passed; one PostgreSQL integration
  test skipped because no local PostgreSQL server was configured.
- Coverage XML: 98.71% line coverage, 92.86% branch coverage. These are separate
  measures, not a combined whole-project production quality score.
- Ruff lint and formatting passed; Python source distribution and wheel built.
- Configured uvicorn service answered health/readiness and authenticated HTTP
  retrieval; the next identical request returned a memory-cache hit.
- Terraform 1.10.4 and locked AzureRM 4.81.0: validate and three mocked plan tests
  passed. No Azure authentication, plan against a real account or apply occurred.

## Hosted CI

Implemented source commit: f719bc9c14a7ed7d5c7f03993846946d72aba55b.
Successful run: https://github.com/pthanureddy/ai-gateway-governance-service/actions/runs/36884915670

CI ran all 46 Python tests, including a real PostgreSQL 17 service-container
test for concurrent reservations, settlement, cache persistence and audit writes.
It passed the 85% branch-aware combined coverage gate, Ruff, package build,
Docker image build and a containerized authenticated answer smoke test.
The Terraform job passed formatting, initialization, validation and the three
security tests without provisioning infrastructure.

The local Docker daemon was unavailable; container execution is evidenced by the
hosted run only. The upstream HTTPS adapter was verified with mock transport.
Neither a commercial LLM call nor Azure deployment is claimed.
