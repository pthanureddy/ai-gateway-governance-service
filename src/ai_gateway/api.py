import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from prometheus_client import CollectorRegistry, Counter, generate_latest

from ai_gateway.contracts import Document, GatewayError, Policy, Question, Result
from ai_gateway.gateway import Gateway
from ai_gateway.provider import HttpProvider, LocalProvider
from ai_gateway.retrieval import Retriever
from ai_gateway.store import Store


def from_environment() -> Gateway:
    root = Path(os.environ.get("GATEWAY_CONFIG", "config"))
    policy = Policy.model_validate_json((root / "policy.json").read_text())
    documents = [
        Document.model_validate(row) for row in json.loads((root / "corpus.json").read_text())
    ]
    store = Store(os.environ.get("DATABASE_URL", "sqlite:///gateway.db"))
    endpoint = os.environ.get("PROVIDER_ENDPOINT")
    provider = (
        HttpProvider(endpoint, os.environ.get("PROVIDER_TOKEN", ""))
        if endpoint
        else LocalProvider()
    )
    return Gateway(policy, Retriever(documents), store, provider)


def create_app(gateway: Gateway | None = None, credentials: dict[str, str] | None = None):
    registry = CollectorRegistry()
    requests = Counter(
        "gateway_requests_total", "Requests by outcome", ["outcome"], registry=registry
    )
    credential_map = (
        credentials
        if credentials is not None
        else json.loads(os.environ.get("GATEWAY_KEYS_JSON", "{}"))
    )
    if (
        not isinstance(credential_map, dict)
        or not credential_map
        or any(
            not isinstance(k, str) or len(k) < 16 or not isinstance(v, str)
            for k, v in credential_map.items()
        )
    ):
        raise ValueError(
            "Configure GATEWAY_KEYS_JSON with keys of at least 16 characters and tenant values"
        )
    keys = [
        (hashlib.sha256(key.encode()).digest(), tenant) for key, tenant in credential_map.items()
    ]

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.gateway = gateway or from_environment()
        yield
        if gateway is None:
            app.state.gateway.store.engine.dispose()

    app = FastAPI(title="AI Gateway Governance Service", lifespan=lifespan)

    def authenticate(authorization: str | None = Header(default=None)) -> str:
        if authorization is None or not authorization.startswith("Bearer "):
            raise GatewayError(401, "authentication_required")
        digest = hashlib.sha256(authorization[7:].encode()).digest()
        tenant = next(
            (tenant for stored, tenant in keys if hmac.compare_digest(digest, stored)), None
        )
        if tenant is None:
            raise GatewayError(401, "invalid_credentials")
        return tenant

    @app.exception_handler(GatewayError)
    async def domain_error(request: Request, exception: GatewayError):
        requests.labels(exception.code).inc()
        return JSONResponse({"code": exception.code}, status_code=exception.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, exception: RequestValidationError):
        requests.labels("invalid_input").inc()
        return JSONResponse({"code": "invalid_request"}, status_code=422)

    @app.post("/v1/answers", response_model=Result)
    def ask(question: Question, request: Request, tenant: str = Depends(authenticate)):
        result = request.app.state.gateway.ask(tenant, question)
        requests.labels("ok_" + result.cache).inc()
        return result

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready(request: Request):
        try:
            request.app.state.gateway.store.healthy()
            return {"status": "ok"}
        except Exception:
            return JSONResponse({"status": "unavailable"}, status_code=503)

    @app.get("/metrics")
    def metrics(tenant: str = Depends(authenticate)):
        return Response(generate_latest(registry), media_type="text/plain; version=0.0.4")

    return app
