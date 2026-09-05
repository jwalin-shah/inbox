# Inbox Invariants

Tensor equations mapped to orbit oracles at `~/projects/orbit/docs/research/`.

---

## 1. Server/API Layer

Maps to: `web-platform-oracle.md`, `api-design-oracle.md` (see `docs/oracle-map.md` for mapping rationale).

### 1.1 Request ID Traceability

```
∀request: response.headers["X-Request-ID"] ≠ ""
```

**Rationale:** Every request-response pair must be traceable. Without a request ID, errors cannot be correlated to the request that caused them. The server currently has no middleware that injects `X-Request-ID` — this is a gap.

**Enforcement:** FastAPI middleware on `@app.middleware("http")` that generates a UUID and injects it into both the request state and the response headers.

**Oracle reference:** `api-design-oracle.md` — Request ID Correlation (every request gets a unique traceable ID).

### 1.2 Structured Error Responses

```
∀endpoint: (response.status_code ≥ 400) → response.body has "detail" key
```

**Rationale:** Every error response must be structured JSON with a `detail` field. Bare `500 Internal Server Error` HTML responses or unhandled exceptions that crash the connection are violations. The server uses `HTTPException` with structured JSON for most endpoints, but unhandled exceptions in route handlers can still produce bare 500s.

**Enforcement:** Global exception handler that catches unhandled `Exception` and `BaseException` and returns `JSONResponse({"detail": "Internal server error"})`.

**Oracle reference:** `api-design-oracle.md` — Structured Error Responses (all errors are JSON with a `detail` field).

### 1.3 Timeout on Long-Running Operations

```
∀long_running_op: has asyncio.wait_for(fn, timeout=deadline)
```

**Rationale:** Any operation that could block the event loop for more than a few seconds (external API calls, SQLite queries, subprocess execution) must have an explicit timeout. The server currently uses `asyncio.to_thread()` for blocking calls but does not uniformly wrap them in `asyncio.wait_for()`.

**Enforcement:** All `asyncio.to_thread()` calls that hit external services must be wrapped in `asyncio.wait_for()` with a per-operation deadline.

**Oracle reference:** `web-platform-oracle.md` — Request Timeout (every request to an external service has a timeout).

### 1.4 Connection Pool Hygiene

```
∀connection: used → (closed ∨ returned to pool)
```

**Rationale:** Every HTTP client connection, database connection, or network socket must be returned to its pool or closed after use. Leaked connections cause resource exhaustion. The server uses `httpx.Client()` and `httpx.AsyncClient()`, plus SQLite connections via `sqlite3.connect()`.

**Enforcement:** Use `contextlib.contextmanager` or `async with` for all connection-pool objects. SQLite connections in `services.py` use `with sqlite3.connect(...)` which auto-commits/closes on exit.

**Oracle reference:** `web-platform-oracle.md` — Connection Pool Hygiene (connections are returned to pool or closed).

---

## 2. Connector Layer

Maps to: `saltzer-schroeder-oracle.md`.

### 2.1 Auth Credential Check Before Use

```
∀connector: before data_access → explicit_auth_check(connector) = true
```

**Rationale:** Every connector must verify its credentials are valid before attempting data access. A connector that silently uses expired credentials should fail fast with a clear error, not hang or return empty results. The `connectors/base.py` has `AuthStatus` enum (`NEEDS_LOGIN`, `READY`, `EXPIRED`, `NEEDS_HUMAN`).

**Enforcement:** Every connector's `sync()` and `search()` methods check `AuthStatus` and raise `AuthError` if not `READY` before any data access.

**Oracle reference:** `saltzer-schroeder-oracle.md` Principle 2 (Fail-Safe Defaults): default decision is denial; failed auth check = denied access.

### 2.2 Rate Limiting (429 Backoff)

```
∀connector: (status_code == 429) → backoff(min(backoff * 2, max_backoff)) ∧ retry ≤ max_retries
```

**Rationale:** Every connector that talks to an external API must handle 429 responses with exponential backoff. The `connector_registry.py` has `DEFAULT_TIMEOUT_SECONDS = 12` but no backoff logic.

**Enforcement:** Each connector's API call wrapper implements exponential backoff with jitter on 429 responses. Maximum retries = 3, initial backoff = 1s, max backoff = 30s.

**Oracle reference:** `saltzer-schroeder-oracle.md` Principle 7 (Least Privilege) applied to resource consumption: no connector consumes more than its fair share of rate limit.

### 2.3 Non-Blocking Sync Operations

```
∀connector: sync_operation → asyncio.to_thread(sync_operation)
```

**Rationale:** Every connector sync operation must be wrapped in `asyncio.to_thread()` to avoid blocking the event loop. The FastAPI server runs on asyncio; blocking the event loop stalls all other requests.

**Enforcement:** All sync operations registered via `connector_registry.py` are called through `asyncio.to_thread()` in the server route handlers.

**Oracle reference:** `web-platform-oracle.md` — Non-Blocking I/O (all blocking operations are offloaded to thread pool).

### 2.4 External API Call Safety

```
∀external_api_call: has(timeout + retry + circuit_breaker)
```

**Rationale:** Every call to an external API (Google, GitHub, Apple, etc.) must have three safety layers: a timeout, a retry strategy, and a circuit breaker. The `egress_audit.py` module provides host allowlisting but no circuit breaker.

**Enforcement:** Each external API call wrapper implements:
- Timeout: `asyncio.wait_for(fn, timeout=N)` where N is per-API
- Retry: exponential backoff for transient failures (429, 5xx)
- Circuit breaker: fail fast when the API is down (3 consecutive failures → open circuit for 30s)

**Oracle reference:** `saltzer-schroeder-oracle.md` Principle 2 (Fail-Safe Defaults): when the circuit is open, default is to fail fast, not hang.

---

## 3. MCP Gateway

Maps to: `api-design-oracle.md`.

### 3.1 JSON-RPC 2.0 Structure

```
∀mcp_message: has(jsonrpc == "2.0") ∧ (has("method") ⊕ has("result") ⊕ has("error"))
```

**Rationale:** Every MCP message must conform to JSON-RPC 2.0 specification. The `mcp_gateway.py` uses Starlette routes with `Mount("/mcp", app=mcp.streamable_http_app())`.

**Enforcement:** MCP message parser validates `jsonrpc` field, verifies method/result/error mutual exclusion, and rejects malformed messages with a JSON-RPC error response.

**Oracle reference:** `api-design-oracle.md` — Protocol Conformance (all messages conform to the declared protocol specification).

### 3.2 Tool Call Validation

```
∀mcp_tool_call: validated(parameters) → can_execute(parameters)
```

**Rationale:** Every MCP tool call must have its parameters validated against the tool's schema before execution. Invalid parameters should be rejected with a clear error message, not silently ignored.

**Enforcement:** MCP server validates tool call parameters against the registered tool schema (parameters JSON Schema) before dispatching to the handler.

**Oracle reference:** `api-design-oracle.md` — Input Validation (all inputs validated against schema before processing).

### 3.3 Session Lifecycle

```
∀mcp_session: has(init → use → cleanup) lifecycle
```

**Rationale:** Every MCP session must have a well-defined lifecycle. Sessions must be initialized before use and cleaned up when done. The `mcp_gateway.py` integrates with `mcp_backend.py` and `memory_store.py`.

**Enforcement:** Session lifecycle is tracked in state. Uninitialized sessions reject all calls. Sessions are cleaned up on disconnect or timeout.

**Oracle reference:** `api-design-oracle.md` — Session Lifecycle (init → use → cleanup is explicit).

### 3.4 Context Projection Provenance

```
∀context_item i: i ∈ lifeops.context.v1.sections → has(i.source_ref) ∧ read_only(context) = true
```

**Rationale:** The unified context surface is a derived transport projection,
not a second authority. Every non-empty section item must point back to the
source record that justified it, and the surface must not imply that it can
write merely because it combines multiple sources.

**Enforcement:** `life_context` only admits items with stable provider or
Inbox references, returns `schema_version = lifeops.context.v1`, and marks the
whole response `read_only = true`. Unavailable source reads become explicit
health/limitation entries rather than empty-success claims.

Property observations follow the same rule: `life_context.property_evidence`
may contain only explicitly captured append-only events with an event
reference. An empty property collection is an explicit not-captured state; it
must not be presented as a surveyed or complete property model.

**Oracle reference:** `api-design-oracle.md` — resource modeling, structured
responses, and explicit versioning.

### 3.5 Approved Writes Require Read-Back Verification

```
∀approved_write a: execute(a) → read_back(a) ∧ (verified(a) ∨ explicit_nonverification(a))
```

**Rationale:** A provider's successful HTTP response is not sufficient proof
that the intended durable state exists. The LifeOps adapter must re-read the
target using the exact approved account/resource scope and return the evidence
and mismatches used for the conclusion. Ambiguous duplicate matches are not
reported as verified.

**Enforcement:** `execute_approved_action` returns a structured verification
receipt. `verify_approved_action` repeats the read-only check. The current
contracts cover Google Task creation, Calendar event updates, and local person
notes/relationship claims; unsupported action classes return `unsupported`.

**Oracle reference:** `api-design-oracle.md` — observable postconditions and
structured responses.

### 3.6 Project Evidence Preservation

```
∀ project p: evidence_count(p) ≥ 1 ∧ every(p.evidence_refs) is source-linked
```

**Rationale:** Project deduplication must not erase the captures or source
records that justified the merge. The adapter may combine explicit project
records under a conservative normalized name, but it must never infer a
project from arbitrary message text.

**Enforcement:** `life_context` emits `project_key`, preserves every memory,
capture, and explicit canonical-tracker row reference in `evidence_refs` or
`linked_source_refs`, and accepts cross-source links only when they are already
present in project metadata or the Inbox tracker projection.

### 3.7 Master Tracker Queue Projection

```
∀ q ∈ context.attention:
  q.attention_class = "curated_email_action" → q.source_ref.source = "google_sheets"
```

The Email Action Queue is a curated review surface, not a replacement for
Gmail. The Google Tasks Mirror is reconciliation evidence, not a second task
authority. Both are exposed only through Inbox's bounded read-only queue
projection.

### 3.8 Persistent LifeOps Identity Resolution

```
∀ p from LifeOps People: p.identity_resolution.status ∈ {matched, unmatched, ambiguous}
```

Exact-name matching is only a labeled candidate link. The adapter preserves
the source row and does not silently merge ambiguous people or accounts.

**Oracle reference:** `data-quality-oracle.md` — record identity,
deduplication, and provenance preservation.

### 3.9 Document Metadata Is Not Document Content

```
∀d ∈ context.documents: has(d.source_ref) ∧ read_only(d) = true
```

Drive and Docs metadata may be included in the unified context, but a file
listing is not evidence that its body was read. Body reads remain explicit,
bounded follow-up operations through `document_evidence` and must retain the
provider file/document ID, account, truncation state, and retrieval timestamp.

### 3.10 Semantic Index Freshness

```
context.embedding_index.pending = 0 → semantic coverage complete at checkpoint
```

The local embedding status is a freshness checkpoint for the current indexed
item set, not a permanent guarantee. A later provider sync may create pending
work again; the context must expose the model, item counts, pending count, and
read timestamp so callers can decide whether semantic retrieval is sufficient.

### 3.11 Conservative Cross-Source Identity and Place Linking

```
∀ link: exact_or_explicit_alias → matched
       weak_fragment → candidate
       multiple_candidates → ambiguous
```

LifeOps People rows may carry explicit links into Actions and Projects. Contact
resolution only upgrades to `matched` for an exact name or explicit
parenthetical alias. A weaker unique one-word or explicit-alias fragment
remains a review candidate; ordinary fragments from multi-word names, such as
a shared surname, are not used as matches. Repeated place observations are
merged only by normalized displayed address while preserving each source
reference and per-source observation counts.

Action-to-project links use the same conservative rule: only one exact
canonical project title may produce a `matched` reference. A unique shorthand
inside one title is labeled `candidate` without creating a reference; partial
or ambiguous project text remains unresolved.

Auxiliary workbook rows remain generic notes until a separate explicit rule
promotes them. A value, research record, or interview question must not become
an actionable commitment merely because it was read into the context.

### 3.12 Coverage Claims Must Be Account- and Freshness-Bounded

```
∀coverage_claim c: c.account_scoped ∧ c.has_checked_at ∧ c.has_freshness_basis
```

**Rationale:** A provider-level “configured” flag cannot prove that every
account is readable or that the local index is current. Coverage must retain
the account, source, checkpoint timestamps, freshness policy, and explicit
blockers or planned gaps.

**Enforcement:** `coverage_report` joins provider health, capture health,
Gmail normalization, embeddings, and the source registry into
`lifeops.coverage.v1`. It reports provider-side completeness limits instead of
promoting a successful probe into an exhaustive-sync claim.

**Oracle reference:** `data-quality-oracle.md` — freshness, completeness, and
lineage-aware reporting.

### 3.13 Identity Review Is Not Identity Mutation

```
∀review_item r: surfaced_candidate(r) → ¬canonical_merge(r)
```

**Rationale:** A review queue may collect unresolved people, places, and
project links, but surfacing a likely match must not silently rewrite the
contact graph or source records.

**Enforcement:** `identity_review` is read-only, retains the originating
references, exact candidate contact IDs, and bounded disambiguation fields,
and only exposes candidate/ambiguous/unmatched status. Any future confirmation
must use an explicit, payload-bound approval action.

`review_queue` may combine identity, project, and source-health review items for
orchestration, but it is also read-only and cannot promote a candidate, create
a link, or claim a planned source is connected.

The durable confirmation path is `propose_person_identity_link` followed by
explicit approval, exact execution, and a read-back from `/identity/links`.
The resulting local link is then used by `life_context` as
`method=approved_identity_link`; provider Contacts remain unchanged.

### 3.14 System Audit Is Observational

```
system_audit() → read_only = true
```

**Rationale:** A readiness report must not mutate provider data, approve an
action, start a worker, inspect arbitrary Mac files, or read secrets. It is a
bounded summary of existing read contracts and must preserve known gaps
instead of converting missing evidence into a success claim.

**Enforcement:** `system_audit` delegates only to bounded read-only
projections, returns explicit issue codes and limitations, and reports the
write policy as proposal → explicit approval → single-use lease → execute →
read-back. Worker-control, provider-write, secret-access, and raw-event
mutation scope remain false until separately implemented and verified.

### 3.15 Worker Evidence Packets Are Scoped

```
∀ packet p: p.read_only = true ∧
           p.scope.provider_writes = false ∧
           p.scope.worker_control = false ∧
           p.scope.secret_access = false
```

**Rationale:** External workers need useful context, but they must not become
an alternate personal-data authority or inherit Inbox credentials. A packet
is an ephemeral projection with an explicit consumer, purpose, section
allowlist, account scope, item bound, source health, and limitations.

**Enforcement:** `evidence_packet` delegates to `life_context` with model
execution disabled, validates requested sections, bounds each list, and
returns only read-model data and provenance. The restricted worker stdio
profile exposes only `evidence_packet` and `system_audit`; provider writes,
arbitrary Inbox tools, secrets, terminal control, notes, and document metadata
are not exposed.

### 3.16 Place Resolution Is Conservative

```
place_key(a) = place_key(b) => only presentation-equivalent address strings
                              are merged; every source observation is retained
```

**Rationale:** Calendar locations and contact addresses often differ only by
punctuation or a street-suffix abbreviation. Merging those observations helps
cross-source context while geocoding or fuzzy matching could incorrectly join
distinct places.

**Enforcement:** The `life_context` place projection normalizes case,
punctuation, whitespace, and a bounded list of common street suffixes. It does
not drop unit/address tokens, geocode, or promote a merged place to a canonical
address; all original evidence references remain attached.

### 3.17 Worker Account Scope Is Explicit

```
profile(worker) => account != "" ∧ account ∈ configured_allowlist
```

**Rationale:** A worker should receive only the account context required for
its task. Treating an omitted account as every observed mailbox defeats data
minimization even when the tool is read-only.

**Enforcement:** The restricted launcher requires
`LIFEOPS_WORKER_ACCOUNT_ALLOWLIST`, and `evidence_packet` rejects missing or
non-allowlisted account values before calling `life_context`.

---

## 4. Data Integrity

Maps to: `data-quality-oracle.md` (see `docs/oracle-map.md` for mapping rationale).

### 4.1 Unique Message ID

```
∀message: has(unique_id) ∧ ¬∃message2: (message2.unique_id == message.unique_id) ∧ (message2 ≠ message)
```

**Rationale:** Every message across all sources must have a unique ID. The `service_models.py` `Msg` has `message_id` for Gmail (empty for iMessage). The `message_sync.py` uses `message_id` for Gmail dedup and `rowid` for iMessage.

**Enforcement:** Message index store enforces uniqueness constraint on message IDs. Duplicate IDs are rejected or merged.

**Oracle reference:** `data-quality-oracle.md` — Record Identity (every record must have a unique, stable identifier).

### 4.2 No Sync Duplicates

```
∀sync_operation: count(messages after sync) - count(messages before sync) = count(new messages)
```

**Rationale:** After any sync operation, no duplicate messages should exist. The `message_sync.py` uses `GMAIL_HISTORY_CURSOR` and `GMAIL_TIMESTAMP_CURSOR` for incremental sync and deduplicates via `seen` sets.

**Enforcement:** Sync operations verify that the resulting message count delta equals the number of new messages fetched. Any discrepancy is logged as a data integrity violation.

**Oracle reference:** `data-quality-oracle.md` — Idempotent Sync (re-running sync produces the same result as running it once).

### 4.3 Approval Store Consistency

```
∀approval_store_operation: (state before → operation → state after) is consistent
- state.approved → lease exists
- state.denied → no lease exists
- state.pending → no lease exists
```

**Rationale:** The `approval_store.py` manages approval requests through a lifecycle: `pending` → `approved` (with lease) or `denied`. Every transition must be recorded and consistent. The store also logs every event to `audit_log`.

**Enforcement:** Approval store enforces state machine transitions. Approving a request that is already decided raises `HTTPException(409)`. Every state change is logged to the audit log.

**Oracle reference:** `data-quality-oracle.md` — State Machine Consistency (every state transition produces a valid and consistent next state).

---

## 5. TUI Layer

Maps to: `apple-platform-oracle.md` patterns, `web-platform-oracle.md`.

### 5.1 Non-Blocking TUI Updates

```
∀tui_update: (I/O in render) → @work(thread=True, exit_on_error=False)
```

**Rationale:** Every TUI update that involves I/O (network requests, file reads, database queries) must be non-blocking. The `inbox.py` TUI uses Textual's `@work(thread=True, exit_on_error=False)` decorator for all network calls (confirmed: 20+ occurrences of this pattern).

**Enforcement:** All network calls in the TUI are wrapped in `@work(thread=True)` methods. Direct synchronous I/O in the render path is a violation.

**Oracle reference:** `apple-platform-oracle.md` — Responsive UI (the main thread never blocks on I/O).

### 5.2 Undo Capability

```
∀user_action: is_destructive → has(undo) ∨ has(confirmation)
```

**Rationale:** Every destructive user action (delete, archive, send) must have either an undo capability or a confirmation dialog. The TUI currently has no explicit undo mechanism for most operations.

**Enforcement:** Destructive operations (delete, archive, unsubcribe) require user confirmation before execution. Future: implement undo stack for reversible operations.

**Oracle reference:** `apple-platform-oracle.md` — Undo Support (destructive operations are reversible or confirmed).

---

## 6. Scheduler Layer

Maps to: `lamport-tla-oracle.md`, `ostep-oracle.md`.

### 6.1 Task State Machine

```
∀scheduled_message: status ∈ {"pending", "sent", "cancelled", "failed"}
∀followup_reminder: status ∈ {"active", "fired", "cancelled", "replied"}
```

**Rationale:** The `scheduler.py` defines `ScheduledMessage` and `FollowupReminder` with explicit state machines. Each state transition must be valid and recorded.

**Enforcement:** State transitions are validated. Transitions to invalid states (e.g., `pending` → `fired`) are rejected.

**Oracle reference:** `lamport-tla-oracle.md` — State Machine (every state transition is explicitly defined and validated).

### 6.2 Task Persistence

```
∀scheduled_task: created → survives(server_restart)
```

**Rationale:** All scheduled tasks must survive server restarts. The scheduler uses SQLite storage (`.inbox_scheduler.sqlite3`) for persistence.

**Enforcement:** Scheduler re-reads pending tasks from SQLite on startup. No in-memory-only scheduling.

**Oracle reference:** `ostep-oracle.md` — Persistence (data survives process restart).

---

## 7. Egress Audit Layer

Maps to: `saltzer-schroeder-oracle.md`.

### 7.1 All Outbound Traffic Audited

```
∀outbound_request: logged_to(egress_audit_db)
```

**Rationale:** Every outbound HTTP request to external hosts must be logged to the egress audit database. The `egress_audit.py` module provides an allowlist (`INBOX_EGRESS_ALLOWLIST`) and auto-logs outbound traffic.

**Enforcement:** The egress_audit middleware intercepts all outbound HTTP requests via `httpx.AsyncClient` event hooks and logs them to `.inbox_egress_audit.sqlite3`.

**Oracle reference:** `saltzer-schroeder-oracle.md` Principle 6 (Complete Mediation): every access to every external resource must be checked for authority and logged.

### 7.2 Host Allowlist Enforcement

```
∀outbound_request: host ∈ allowlist ∨ host ∈ loopback
```

**Rationale:** Outbound traffic is restricted to explicitly allowed hosts (default: `api.github.com`, `maps.googleapis.com`) and loopback addresses. The `egress_audit.py` enforces this via `_is_local_host()` and `_ALLOWED_HOSTS`.

**Enforcement:** `EgressAuditMiddleware` blocks requests to hosts not in the allowlist with a 403 response. The allowlist is configurable via `INBOX_EGRESS_ALLOWLIST`.

**Oracle reference:** `saltzer-schroeder-oracle.md` Principle 1 (Economy of Mechanism): the allowlist is a small, explicit set of permitted hosts; everything else is denied by default.

---

## Invariant Classification

| Section | Invariant | P0/P1/P2 | Has Test? | Priority |
|---------|-----------|----------|-----------|----------|
| 1.1     | X-Request-ID | P1 | No | Medium |
| 1.2     | Structured errors | P1 | No | High |
| 1.3     | Timeout on long ops | P1 | No | High |
| 1.4     | Connection pool hygiene | P1 | No | Medium |
| 2.1     | Auth check before use | P0 | No | High |
| 2.2     | 429 backoff | P1 | No | Medium |
| 2.3     | Non-blocking sync | P1 | No | High |
| 2.4     | External API safety | P1 | No | High |
| 3.1     | JSON-RPC structure | P1 | No | Medium |
| 3.2     | Tool call validation | P1 | No | High |
| 3.3     | Session lifecycle | P1 | No | Medium |
| 4.1     | Unique message ID | P0 | No | High |
| 4.2     | No sync duplicates | P1 | No | High |
| 4.3     | Approval store consistency | P0 | No | High |
| 5.1     | Non-blocking TUI | P1 | No | Medium |
| 5.2     | Undo capability | P2 | No | Low |
| 6.1     | Task state machine | P1 | No | Low |
| 6.2     | Task persistence | P1 | No | Medium |
| 7.1     | Outbound audited | P1 | No | High |
| 7.2     | Host allowlist | P0 | No | High |

**Key:** P0 = safety/security/data-loss invariant (hard block). P1 = provable correctness invariant. P2 = style/design preference.

---
