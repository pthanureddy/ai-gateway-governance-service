"""Transactional usage reservations, cached answers and metadata-only audit."""

from datetime import UTC, datetime

from sqlalchemy import (
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ai_gateway.contracts import GatewayError, ProviderAnswer

metadata = MetaData()
usage = Table(
    "usage_ledger",
    metadata,
    Column("tenant", String(40), primary_key=True),
    Column("day", String(10), primary_key=True),
    Column("reserved", Integer, nullable=False),
    Column("spent", Integer, nullable=False),
)
reservations = Table(
    "reservations",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("tenant", String(40), nullable=False),
    Column("day", String(10), nullable=False),
    Column("amount", Integer, nullable=False),
    Column("state", String(20), nullable=False),
)
cache = Table(
    "answer_cache",
    metadata,
    Column("key", String(64), primary_key=True),
    Column("tenant", String(40), nullable=False),
    Column("expires", Float, nullable=False),
    Column("body", Text, nullable=False),
)
audit = Table(
    "request_audit",
    metadata,
    Column("trace_id", String(36), primary_key=True),
    Column("tenant", String(40), nullable=False),
    Column("question_digest", String(64), nullable=False),
    Column("policy_version", String(40), nullable=False),
    Column("status", String(40), nullable=False),
    Column("cache_layer", String(20), nullable=False),
    Column("estimated_tokens", Integer, nullable=False),
)


class Store:
    def __init__(self, database_url: str):
        connect_args = (
            {"check_same_thread": False, "timeout": 15} if database_url.startswith("sqlite") else {}
        )
        self.engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)
        if self.engine.dialect.name not in {"sqlite", "postgresql"}:
            raise ValueError("Only SQLite and PostgreSQL are supported")
        metadata.create_all(self.engine)
        self.insert = pg_insert if self.engine.dialect.name == "postgresql" else sqlite_insert

    def healthy(self) -> bool:
        with self.engine.connect() as connection:
            connection.execute(select(1))
        return True

    def reserve(self, tenant: str, trace_id: str, amount: int, budget: int, now: float):
        day = datetime.fromtimestamp(now, UTC).date().isoformat()
        with self.engine.begin() as connection:
            connection.execute(
                self.insert(usage)
                .values(tenant=tenant, day=day, reserved=0, spent=0)
                .on_conflict_do_nothing()
            )
            result = connection.execute(
                update(usage)
                .where(
                    usage.c.tenant == tenant,
                    usage.c.day == day,
                    usage.c.reserved + usage.c.spent + amount <= budget,
                )
                .values(reserved=usage.c.reserved + amount)
            )
            if result.rowcount != 1:
                raise GatewayError(429, "estimated_token_budget_exceeded")
            connection.execute(
                reservations.insert().values(
                    id=trace_id, tenant=tenant, day=day, amount=amount, state="pending"
                )
            )

    def settle(self, trace_id: str, spent: int):
        with self.engine.begin() as connection:
            statement = select(reservations).where(reservations.c.id == trace_id)
            if self.engine.dialect.name == "postgresql":
                statement = statement.with_for_update()
            row = connection.execute(statement).mappings().one()
            if spent < 0 or spent > row["amount"]:
                raise ValueError("Settlement exceeds reservation")
            result = connection.execute(
                update(reservations)
                .where(reservations.c.id == trace_id, reservations.c.state == "pending")
                .values(state="settled")
            )
            if result.rowcount == 1:
                connection.execute(
                    update(usage)
                    .where(usage.c.tenant == row["tenant"], usage.c.day == row["day"])
                    .values(reserved=usage.c.reserved - row["amount"], spent=usage.c.spent + spent)
                )

    def cached(self, key: str, tenant: str, now: float):
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    select(cache).where(cache.c.key == key, cache.c.tenant == tenant)
                )
                .mappings()
                .first()
            )
            if row and row["expires"] > now:
                return ProviderAnswer.model_validate_json(row["body"]), row["expires"]
            if row:
                connection.execute(delete(cache).where(cache.c.key == key))
        return None

    def put_cache(self, key: str, tenant: str, answer: ProviderAnswer, expires: float):
        with self.engine.begin() as connection:
            values = dict(key=key, tenant=tenant, expires=expires, body=answer.model_dump_json())
            connection.execute(
                self.insert(cache)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[cache.c.key], set_={"body": values["body"], "expires": expires}
                )
            )

    def record(
        self,
        trace_id: str,
        tenant: str,
        digest: str,
        version: str,
        status: str,
        layer: str,
        tokens: int,
    ):
        with self.engine.begin() as connection:
            connection.execute(
                audit.insert().values(
                    trace_id=trace_id,
                    tenant=tenant,
                    question_digest=digest,
                    policy_version=version,
                    status=status,
                    cache_layer=layer,
                    estimated_tokens=tokens,
                )
            )

    def snapshot(self):
        with self.engine.connect() as connection:
            return {
                "usage": [dict(row) for row in connection.execute(select(usage)).mappings()],
                "audit": [dict(row) for row in connection.execute(select(audit)).mappings()],
            }
