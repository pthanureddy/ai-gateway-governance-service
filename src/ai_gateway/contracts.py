from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Question(StrictModel):
    question: str = Field(min_length=3, max_length=2000)
    model: str = Field(default="local-grounded-v1", pattern=r"^[a-z0-9-]{1,60}$")
    max_output_tokens: int = Field(default=256, ge=16, le=1024)


class Document(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9-]{1,60}$")
    tenant: str = Field(pattern=r"^[a-z0-9-]{1,40}$")
    label: Literal["internal", "restricted"]
    text: str = Field(min_length=1, max_length=4000)


class TenantPolicy(StrictModel):
    models: list[str] = Field(min_length=1, max_length=20)
    labels: list[Literal["internal", "restricted"]] = Field(min_length=1, max_length=2)
    daily_token_budget: int = Field(ge=1, le=10000000)


class Policy(StrictModel):
    version: str = Field(pattern=r"^[a-z0-9-]{1,40}$")
    tenants: dict[str, TenantPolicy]
    cache_ttl_seconds: int = Field(default=60, ge=1, le=3600)


class ProviderAnswer(StrictModel):
    answer: str = Field(min_length=1, max_length=8192)
    citations: list[str] = Field(min_length=1, max_length=3)


class Result(ProviderAnswer):
    trace_id: str
    cache: Literal["miss", "memory", "database"]
    policy_version: str
    estimated_tokens: int


class GatewayError(Exception):
    def __init__(self, status: int, code: str):
        self.status = status
        self.code = code
        super().__init__(code)
