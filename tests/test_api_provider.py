import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ai_gateway.api import create_app, from_environment
from ai_gateway.contracts import Document, Question
from ai_gateway.provider import HttpProvider
from ai_gateway.retrieval import Retriever, embed

KEY = "local-testing-key-only"
HEADERS = {"Authorization": "Bearer " + KEY}


@pytest.mark.parametrize("authorization", [None, "Basic abc", "Bearer invalid"])
def test_authentication_rejects_invalid_keys(gateway, authorization):
    with TestClient(create_app(gateway, {KEY: "design"})) as client:
        headers = {} if authorization is None else {"Authorization": authorization}
        assert (
            client.post(
                "/v1/answers", json={"question": "metal review"}, headers=headers
            ).status_code
            == 401
        )


def test_authenticated_api_and_observability(gateway):
    with TestClient(create_app(gateway, {KEY: "design"})) as client:
        first = client.post("/v1/answers", json={"question": "metal review"}, headers=HEADERS)
        second = client.post("/v1/answers", json={"question": "metal review"}, headers=HEADERS)
        assert first.status_code == 200 and second.json()["cache"] == "memory"
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 200
        assert client.get("/metrics").status_code == 401
        assert (
            'gateway_requests_total{outcome="ok_miss"} 1.0'
            in client.get("/metrics", headers=HEADERS).text
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"question": "a"},
        {"question": "metal", "extra": "private"},
        {"question": "metal", "max_output_tokens": 100000},
        {"question": " "},
        {"question": "metal", "tenant": "operations"},
    ],
)
def test_input_errors_do_not_echo_submitted_values(gateway, payload):
    with TestClient(create_app(gateway, {KEY: "design"})) as client:
        result = client.post("/v1/answers", json=payload, headers=HEADERS)
        assert result.status_code == 422
        assert result.json() == {"code": "invalid_request"}


def test_readiness_fails_when_database_unavailable(gateway):
    gateway.store.healthy = lambda: (_ for _ in ()).throw(RuntimeError("secret"))
    with TestClient(create_app(gateway, {KEY: "design"})) as client:
        assert client.get("/health/ready").status_code == 503


@pytest.mark.parametrize("credentials", [{}, {"short": "design"}, {KEY: 12}, []])
def test_startup_requires_valid_credential_configuration(gateway, credentials):
    with pytest.raises(ValueError):
        create_app(gateway, credentials)


def test_http_provider_contract_uses_only_authorized_context(gateway):
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(200, json={"answer": "review metal", "citations": ["metal"]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    gateway.provider = HttpProvider("https://provider.example/v1/generate", "test-token", client)
    assert gateway.ask("design", Question(question="metal review")).answer == "review metal"
    assert captured[0]["context"] == [
        {"id": "metal", "text": "Metal materials require design review."}
    ]
    assert "tenant" not in captured[0]


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(302, headers={"Location": "https://other.example"}),
        httpx.Response(200, content=b"invalid"),
        httpx.Response(200, content=b"x" * 70000),
    ],
)
def test_http_provider_rejects_status_redirect_schema_and_size(response):
    client = httpx.Client(transport=httpx.MockTransport(lambda request: response))
    provider = HttpProvider("https://provider.example", "token", client)
    with pytest.raises((httpx.HTTPError, ValueError, ValidationError)):
        provider.generate(Question(question="metal review"), [])


@pytest.mark.parametrize(
    "endpoint,token", [("http://insecure.example", "token"), ("https://secure.example", "")]
)
def test_provider_configuration_rejects_insecure_values(endpoint, token):
    with pytest.raises(ValueError):
        HttpProvider(endpoint, token)


def test_embeddings_and_tie_order_are_deterministic():
    assert embed("METAL review") == embed("metal review")
    assert embed("") == (0.0,) * 128
    docs = [Document(id=x, tenant="design", label="internal", text="metal") for x in ["b", "a"]]
    assert [d.id for d in Retriever(docs).search("design", ["internal"], "metal")] == ["a", "b"]
    with pytest.raises(ValueError):
        Retriever(docs + [docs[0]])


def test_environment_setup_is_local_and_does_not_require_paid_api(tmp_path, monkeypatch):
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("GATEWAY_CONFIG", str(root / "config"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'env.db'}")
    gateway = from_environment()
    try:
        assert gateway.ask("design", Question(question="materials review")).cache == "miss"
    finally:
        gateway.store.engine.dispose()
