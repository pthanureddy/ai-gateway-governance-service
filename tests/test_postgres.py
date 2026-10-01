import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from ai_gateway.contracts import GatewayError, ProviderAnswer
from ai_gateway.store import Store


@pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES_URL"), reason="Requires isolated PostgreSQL test database"
)
def test_postgres_ledger_cache_audit_and_concurrent_budget():
    store = Store(os.environ["TEST_POSTGRES_URL"])
    tenant = "ci-" + uuid.uuid4().hex[:20]

    def reserve(number):
        reservation_id = f"{tenant}-{number}"
        try:
            store.reserve(tenant, reservation_id, 50, 100, 0)
            return reservation_id
        except GatewayError:
            return None

    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            winners = [key for key in executor.map(reserve, range(8)) if key]
            assert len(winners) == 2
        store.settle(winners[0], 20)
        store.settle(winners[0], 20)
        store.settle(winners[1], 30)
        ledger = next(row for row in store.snapshot()["usage"] if row["tenant"] == tenant)
        assert ledger["reserved"] == 0 and ledger["spent"] == 50
        answer = ProviderAnswer(answer="PostgreSQL tested", citations=["doc"])
        key = uuid.uuid4().hex * 2
        store.put_cache(key, tenant, answer, 100)
        assert store.cached(key, tenant, 0)[0] == answer
        assert store.cached(key, "other", 0) is None
        store.put_cache(key, tenant, answer, 200)
        assert store.cached(key, tenant, 150)[1] == 200
        store.record(uuid.uuid4().hex, tenant, "0" * 64, "v1", "ok", "miss", 0)
        assert store.healthy()
    finally:
        store.engine.dispose()
