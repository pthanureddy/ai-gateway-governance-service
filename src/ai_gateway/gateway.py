import hashlib
import json
import logging
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable

from ai_gateway.contracts import GatewayError, Policy, ProviderAnswer, Question, Result
from ai_gateway.provider import Provider
from ai_gateway.retrieval import Retriever
from ai_gateway.store import Store

log = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    """Character heuristic, not provider tokenizer or billable usage."""
    return (len(text) + 3) // 4


class Gateway:
    def __init__(
        self,
        policy: Policy,
        retriever: Retriever,
        store: Store,
        provider: Provider,
        clock: Callable[[], float] = time.time,
    ):
        self.policy = policy
        self.retriever = retriever
        self.store = store
        self.provider = provider
        self.clock = clock
        self.memory: OrderedDict[str, tuple[ProviderAnswer, float]] = OrderedDict()
        self.lock = threading.RLock()

    def ask(self, tenant: str, question: Question) -> Result:
        trace_id = str(uuid.uuid4())
        digest = hashlib.sha256(question.question.encode()).hexdigest()
        policy = self.policy.tenants.get(tenant)
        if policy is None or question.model not in policy.models:
            self.store.record(
                trace_id, tenant, digest, self.policy.version, "policy_denied", "none", 0
            )
            raise GatewayError(403, "model_or_tenant_not_allowed")
        # Include the entire policy content: changing a label/budget cannot reuse a stale entry.
        key = hashlib.sha256(
            json.dumps(
                {
                    "tenant": tenant,
                    "request": question.model_dump(),
                    "policy": self.policy.model_dump(),
                    "corpus": self.retriever.version,
                    "prompt": "grounded-v1",
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        now = self.clock()
        with self.lock:
            entry = self.memory.get(key)
            if entry and entry[1] > now:
                self.memory.move_to_end(key)
                return self._cached_result(trace_id, tenant, digest, entry[0], "memory")
            self.memory.pop(key, None)
        stored = self.store.cached(key, tenant, now)
        if stored:
            self._remember(key, *stored)
            return self._cached_result(trace_id, tenant, digest, stored[0], "database")
        documents = self.retriever.search(tenant, policy.labels, question.question)
        if not documents:
            self.store.record(
                trace_id, tenant, digest, self.policy.version, "no_context", "none", 0
            )
            raise GatewayError(422, "no_authorized_context")
        input_tokens = estimate_tokens(
            question.question + " ".join(doc.text for doc in documents) + "grounded-v1"
        )
        reserved = input_tokens + question.max_output_tokens
        try:
            self.store.reserve(tenant, trace_id, reserved, policy.daily_token_budget, now)
        except GatewayError:
            self.store.record(
                trace_id, tenant, digest, self.policy.version, "budget_denied", "none", 0
            )
            raise
        try:
            answer = self.provider.generate(question, documents)
            if not set(answer.citations).issubset({doc.id for doc in documents}):
                raise ValueError("Provider cites unauthorized context")
            output_tokens = estimate_tokens(answer.answer)
            if output_tokens > question.max_output_tokens:
                raise ValueError("Provider output exceeds reserved bound")
        except Exception:
            # Charge the reservation conservatively: a failing upstream may already have spent tokens.
            self.store.settle(trace_id, reserved)
            self.store.record(
                trace_id, tenant, digest, self.policy.version, "provider_failed", "none", reserved
            )
            log.warning("gateway provider failure trace_id=%s", trace_id)
            raise GatewayError(502, "provider_failed") from None
        spent = input_tokens + output_tokens
        self.store.settle(trace_id, spent)
        expires = self.clock() + self.policy.cache_ttl_seconds
        self.store.put_cache(key, tenant, answer, expires)
        self._remember(key, answer, expires)
        self.store.record(trace_id, tenant, digest, self.policy.version, "ok", "miss", spent)
        log.info("gateway request completed trace_id=%s cache=miss", trace_id)
        return Result(
            **answer.model_dump(),
            trace_id=trace_id,
            cache="miss",
            policy_version=self.policy.version,
            estimated_tokens=spent,
        )

    def _remember(self, key: str, answer: ProviderAnswer, expires: float):
        with self.lock:
            self.memory[key] = answer, expires
            self.memory.move_to_end(key)
            while len(self.memory) > 128:
                self.memory.popitem(last=False)

    def _cached_result(
        self, trace_id: str, tenant: str, digest: str, answer: ProviderAnswer, layer: str
    ):
        self.store.record(trace_id, tenant, digest, self.policy.version, "ok", layer, 0)
        return Result(
            **answer.model_dump(),
            trace_id=trace_id,
            cache=layer,
            policy_version=self.policy.version,
            estimated_tokens=0,
        )
