"""Deterministic feature-hashed embeddings; no semantic quality claims."""

import hashlib
import math
import re

from ai_gateway.contracts import Document


def embed(text: str, dimensions: int = 128) -> tuple[float, ...]:
    values = [0.0] * dimensions
    for token in re.findall(r"[a-z0-9]+", text.lower()):
        digest = hashlib.sha256(token.encode()).digest()
        values[int.from_bytes(digest[:4], "big") % dimensions] += 1.0
    norm = math.sqrt(sum(value * value for value in values))
    return tuple(value / norm if norm else 0.0 for value in values)


class Retriever:
    def __init__(self, documents: list[Document]):
        if len(documents) > 1000:
            raise ValueError("Corpus exceeds local index bound")
        if len({(doc.tenant, doc.id) for doc in documents}) != len(documents):
            raise ValueError("Duplicate tenant document id")
        self.documents = documents
        self.vectors = {id(doc): embed(doc.text) for doc in documents}
        canonical = [doc.model_dump() for doc in documents]
        import json

        self.version = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()

    def search(self, tenant: str, labels: list[str], question: str) -> list[Document]:
        query = embed(question)
        scored = []
        for doc in self.documents:
            if doc.tenant != tenant or doc.label not in labels:
                continue
            score = sum(a * b for a, b in zip(query, self.vectors[id(doc)], strict=True))
            if score > 0:
                scored.append((score, doc.id, doc))
        scored.sort(key=lambda row: (-row[0], row[1]))
        return [doc for _, _, doc in scored[:3]]
