import concurrent.futures
import threading

import pytest
from sqlalchemy import select

from ai_gateway.contracts import GatewayError, ProviderAnswer, Question
from ai_gateway.gateway import estimate_tokens
from ai_gateway.store import reservations


def query(text="metal review", **kwargs):
    return Question(question=text, **kwargs)


def test_authorized_retrieval_and_memory_cache(gateway):
    first = gateway.ask("design", query())
    second = gateway.ask("design", query())
    assert first.citations == ["metal"]
    assert first.cache == "miss"
    assert second.cache == "memory"
    assert second.estimated_tokens == 0
    assert first.trace_id != second.trace_id
    assert "confidential" not in first.answer
    assert gateway.store.snapshot()["usage"][0]["reserved"] == 0


def test_database_cache_after_process_memory_reset(gateway):
    first = gateway.ask("design", query())
    gateway.memory.clear()
    result = gateway.ask("design", query())
    assert result.cache == "database"
    assert first.answer == result.answer


@pytest.mark.parametrize(
    "tenant,model", [("unknown", "local-grounded-v1"), ("design", "unapproved-model")]
)
def test_policy_denies_before_cache(gateway, tenant, model):
    gateway.ask("design", query())
    with pytest.raises(GatewayError) as error:
        gateway.ask(tenant, query(model=model))
    assert error.value.status == 403
    assert gateway.store.snapshot()["audit"][-1]["status"] == "policy_denied"


def test_cross_tenant_corpus_cannot_be_returned(gateway):
    result = gateway.ask("operations", query("metal operations review"))
    assert result.citations == ["stock"]
    assert "Metal" not in result.answer
    assert result.cache == "miss"


def test_no_authorized_context_is_explicit(gateway):
    with pytest.raises(GatewayError) as error:
        gateway.ask("design", query("zzzzzzzzzzzzzzzzzzzzzzzz"))
    assert error.value.code == "no_authorized_context"
    assert gateway.store.snapshot()["usage"] == []


def test_policy_change_invalidates_both_cache_layers(gateway):
    gateway.ask("design", query())
    gateway.policy.tenants["design"].labels.append("restricted")
    result = gateway.ask("design", query())
    assert result.cache == "miss"
    assert "secret" in result.citations


def test_corpus_change_invalidates_cache(gateway):
    from ai_gateway.contracts import Document
    from ai_gateway.retrieval import Retriever

    gateway.ask("design", query())
    gateway.retriever = Retriever(
        [Document(id="new", tenant="design", label="internal", text="Metal review policy changed.")]
    )
    assert gateway.ask("design", query()).citations == ["new"]


def test_absolute_ttl_is_not_extended_by_database_hit(gateway):
    now = [1000000.0]
    gateway.clock = lambda: now[0]
    gateway.ask("design", query())
    now[0] += 20
    gateway.memory.clear()
    assert gateway.ask("design", query()).cache == "database"
    now[0] += 11
    assert gateway.ask("design", query()).cache == "miss"


def test_memory_cache_is_bounded(gateway):
    answer = ProviderAnswer(answer="ok", citations=["metal"])
    for number in range(140):
        gateway._remember(str(number), answer, 99999999999)
    assert len(gateway.memory) == 128
    assert "0" not in gateway.memory


def test_budget_denial_does_not_create_reservation(gateway):
    gateway.policy.tenants["design"].daily_token_budget = 1
    with pytest.raises(GatewayError) as error:
        gateway.ask("design", query())
    assert error.value.status == 429
    with gateway.store.engine.connect() as connection:
        assert connection.execute(select(reservations)).all() == []


def test_budget_is_scoped_by_utc_day(gateway):
    gateway.store.reserve("design", "r1", 100, 100, 0)
    gateway.store.settle("r1", 100)
    with pytest.raises(GatewayError):
        gateway.store.reserve("design", "r2", 1, 100, 0)
    gateway.store.reserve("design", "r3", 100, 100, 86400)
    assert len(gateway.store.snapshot()["usage"]) == 2


def test_settlement_is_idempotent_and_cannot_overspend(gateway):
    gateway.store.reserve("design", "r1", 100, 100, 0)
    with pytest.raises(ValueError):
        gateway.store.settle("r1", 101)
    gateway.store.settle("r1", 30)
    gateway.store.settle("r1", 30)
    row = gateway.store.snapshot()["usage"][0]
    assert row["spent"] == 30 and row["reserved"] == 0


def test_concurrent_reservations_cannot_exceed_limit(gateway):
    start = threading.Barrier(8)

    def reserve(number):
        start.wait()
        try:
            gateway.store.reserve("design", str(number), 50, 100, 0)
            return 1
        except GatewayError:
            return 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(reserve, range(8))) == 2
    assert gateway.store.snapshot()["usage"][0]["reserved"] == 100


@pytest.mark.parametrize("failure", ["exception", "citation", "oversized"])
def test_provider_failures_are_bounded_and_charge_reservation(gateway, failure):
    class BrokenProvider:
        def generate(self, question, documents):
            if failure == "exception":
                raise RuntimeError("secret credentials should not appear")
            if failure == "citation":
                return ProviderAnswer(answer="invalid", citations=["unauthorized"])
            return ProviderAnswer(answer="x" * 5000, citations=["metal"])

    gateway.provider = BrokenProvider()
    with pytest.raises(GatewayError) as error:
        gateway.ask("design", query())
    assert error.value.code == "provider_failed"
    row = gateway.store.snapshot()["usage"][0]
    assert row["reserved"] == 0 and row["spent"] > 0
    assert not gateway.memory
    assert "secret" not in str(error.value)


def test_audit_does_not_store_question_or_answer(gateway):
    result = gateway.ask("design", query("metal review private wording"))
    audit = gateway.store.snapshot()["audit"][0]
    assert "private wording" not in str(audit)
    assert result.answer not in str(audit)
    assert len(audit["question_digest"]) == 64


@pytest.mark.parametrize("text,result", [("", 0), ("1234", 1), ("12345", 2)])
def test_estimation_is_character_heuristic(text, result):
    assert estimate_tokens(text) == result


def test_database_failure_propagates_without_provider_call(gateway):
    calls = []

    class Provider:
        def generate(self, question, documents):
            calls.append(1)

    gateway.provider = Provider()
    gateway.store.cached = lambda *args: (_ for _ in ()).throw(RuntimeError("database down"))
    with pytest.raises(RuntimeError):
        gateway.ask("design", query())
    assert calls == []
