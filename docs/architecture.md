# Architecture decisions

## Policy before cache

Credential identity selects the tenant. No tenant ID is accepted in Question.
Policy-denied requests cannot read cached results. Cache keys include the entire
policy, not just its human version label, to invalidate entries after a mistakenly
unversioned classification change. Corpus changes invalidate through a SHA-256
digest. Cache hits create a fresh trace and incur zero new estimated provider units.

## Reservation instead of post-call quota check

Checking usage then making a provider call would permit parallel callers to
overspend. Store.reserve creates the daily ledger row with ON CONFLICT DO NOTHING,
then conditionally increments reserved capacity only while spent+reserved+amount
fits the budget. The reservation record is stored in the same transaction.
PostgreSQL row locking and conditional updates serialize conflicting quota changes;
SQLite serializes its writes. Settlement changes a pending record once and adjusts
the ledger atomically. Provider failure charges the worst-case reservation.

This is a conservative estimate, not provider billing reconciliation. The upstream
prompt wrapper is approximated with the marker grounded-v1; tokenizer-specific
overhead is not measured. A production gateway needs actual provider usage and a
pricing-versioned accounting contract. Crash reconciliation requires operator review.

## Explicit boundary between retrieval and models

The small local index feature-hashes tokens into normalized vectors and ranks them
by dot product. Authorization filters documents before ranking. It is a tested
vector search implementation with a lexical baseline, not proof of semantic RAG
quality. The local provider extracts text. The external adapter receives only the
selected context, has a fixed administrator-configured HTTPS endpoint, disables
redirects, bounds response bytes and sets a timeout. It does not implement a vendor
SDK or claim actual commercial model integration.

## Audit and availability

Metadata audit avoids storing complete question text; hashes may still be personal
or sensitive metadata and need a retention policy. SQL cache holds actual answers.
If SQL cannot be read, the request fails before calling a provider. No cached
answer is served without an audit write. Completion is not a single transaction
with the remote provider; transient database failures may still occur after a paid
call. The service favors fail-closed policy over unconditional availability.
