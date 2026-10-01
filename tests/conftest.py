import time

import pytest

from ai_gateway.contracts import Document, Policy
from ai_gateway.gateway import Gateway
from ai_gateway.provider import LocalProvider
from ai_gateway.retrieval import Retriever
from ai_gateway.store import Store


@pytest.fixture
def gateway(tmp_path):
    policy = Policy.model_validate(
        {
            "version": "v1",
            "cache_ttl_seconds": 30,
            "tenants": {
                "design": {
                    "models": ["local-grounded-v1"],
                    "labels": ["internal"],
                    "daily_token_budget": 5000,
                },
                "operations": {
                    "models": ["local-grounded-v1"],
                    "labels": ["internal", "restricted"],
                    "daily_token_budget": 5000,
                },
            },
        }
    )
    docs = [
        Document(
            id="metal",
            tenant="design",
            label="internal",
            text="Metal materials require design review.",
        ),
        Document(
            id="secret",
            tenant="design",
            label="restricted",
            text="Metal design budget is confidential.",
        ),
        Document(
            id="stock",
            tenant="operations",
            label="internal",
            text="Stock transfer requires an operations review.",
        ),
    ]
    store = Store(f"sqlite:///{tmp_path / 'test.db'}")
    yield Gateway(policy, Retriever(docs), store, LocalProvider(), time.time)
    store.engine.dispose()
