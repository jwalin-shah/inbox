# Inbox Invariants

## 0. Triage Reply Boundary

```
needs_reply = 1 → actionability = "reply" ∧ latest_sender ≠ "Me"
```

Reviewing an opportunity, newsletter, or other candidate is not evidence that
the user owes the sender a response. The index classifier and downstream model
refinement must preserve this boundary; model output may not create a reply
obligation from a non-reply source projection.

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

### 1.5 Bounded Memory Projection Reads

```
∀memory_read: 1 ≤ returned_count(memory_read) ≤ min(requested_limit, 500)
```

**Rationale:** Explicit LifeOps memory records are a derived local read model
that must remain bounded when exposed through the Inbox gateway. The route must
not become an unbounded dump of personal context or a second write authority.

**Enforcement:** `GET /memory` clamps the requested limit to 500 and delegates
to the existing `MemoryStore.query_entries` read path. It never mutates memory,
provider data, or the append-only evidence log.

**Oracle reference:** `api-design-oracle.md` — Pagination and bounded list
responses.

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

## 8. Gas Optimization Layer

Maps to: `kernighan-plaughter-oracle.md` (determinism, simplicity) with
`saltzer-schroeder-oracle.md` (fail-safe defaults, complete mediation) for the
provider/egress boundary and `api-design-oracle.md` for the HTTP surface.

New modules: `gas_models.py` (pure data), `gas_providers.py` (station/route
adapters + composite merge), `gas_context.py` (EIA regional average),
`gas_optimizer.py` (deterministic scorer). Exposed as one MCP tool
`find_best_gas` routed server-side through `services.py` → `inbox_server.py`.

Provider status: Google Places (New) + Routes are live. GasBuddy is intentionally
NOT integrated — its GraphQL endpoint sits behind Cloudflare/CSRF and the
maintained client requires a FlareSolverr bypass, so a clean fail-closed adapter
is not possible without a ToS-violating, break-prone scraper. A regional-average
context is available behind `INBOX_EIA_API_KEY`.

### 8.1 Deterministic Recommendation

```
∀ gas_query q: find_best_gas(q, providers, now) = find_best_gas(q, providers, now)
```

**Rationale:** The recommendation must be a pure, deterministic function of
its inputs. No LLM and no source of nondeterminism (ranking uses a total order
with a stable terminal tie-break on `provider_id`). This is what lets Inbox
answer "why did it send me there yesterday?" with a reproducible trace.

**Enforcement:** `select_best` sorts on `(effective_cost, preferred, price, provider_id)`;
all randomness-free. Test: `test_find_best_gas_deterministic`.

### 8.2 Fail-Closed Credential Gating

```
∀ provider_instance: api_key = ∅ → nearby_stations(…) = [] ∧ route(…) = None
```

**Rationale:** Providers must return empty/None *before* touching the network
when no API key is configured, rather than raising or fabricating a price.

**Enforcement:** `GooglePlacesFuelProvider` / `GoogleRoutesProvider` short-circuit
on an empty key. Tests: `test_nearby_stations_no_key_returns_empty`,
`test_routes_provider_no_key_returns_none`.

### 8.3 Normalized Data Boundary

```
∀ google_response: consumers(google_response) ⊆ {GasStation, FuelPrice, RouteLeg}
```

**Rationale:** Nothing above the provider layer may see Google's wire shape
(`fuelOptions`, `units`/`nanos`, proto enums, field-mask JSON). Restricting the
blast radius lets providers be swapped without touching the scorer or MCP tool.

**Enforcement:** Google parsing lives only in `gas_providers.py`; the scorer and
`find_best_gas` consume `gas_models.py` types. Test:
`test_nearby_stations_normalize_google_response`.

### 8.4 Freshness Policy

```
∀ station s, fuel_type f: age(s.price[f].updated_at) > max_price_age → s ∉ recommendation
default max_price_age = 72h (config/env-tunable)
```

**Rationale:** A price older than the acceptable age must not anchor the primary
recommendation (it is still listed as an alternative, with its age surfaced in
`price_age_minutes`). Real Places data refreshes roughly daily, so the default
was relaxed from the design's 24h to 72h and made tunable
(`INBOX_GAS_MAX_PRICE_AGE_HOURS` / `config/gas.json` →
`GasPreferences.max_price_age_hours`).

**Enforcement:** `_is_stale(age, prefs.max_price_age_minutes)` excludes anything
over the tunable threshold from `eligible`. Tests:
`test_stale_price_excluded_from_recommendation`,
`test_all_stale_returns_no_price_data`,
`test_price_within_72h_is_eligible_by_default`,
`test_custom_max_age_hours_still_enforced`.

### 8.5 Price Validity Gate

```
∀ station s: (price ≤ 0 ∨ ¬exists(fuel_type)) → s excluded from ranking
```

**Rationale:** A missing or non-positive price cannot be optimized over; it is
excluded (and counted in `metadata.missing_price`), never treated as free.

**Enforcement:** `_parse_fuel_price` drops `price ≤ 0`; `find_best_gas` skips
stations with no matching `fuel_type`. Tests: `test_missing_regular_excluded`,
`test_find_best_gas_no_price_data`.

### 8.6 Detour-Aware Cost Function

```
effective_cost = price·g + (detour_miles/mpg)·price + detour_minutes·(time_value/60)
```

**Rationale:** The recommendation minimizes total effective cost — fuel fill
plus the fuel/time cost of the detour — not raw price. This is what makes Inbox
better than a price-sorted list.

**Enforcement:** `_score_candidate`; `select_best` picks `min(effective_cost)`.
Test: `test_slightly_more_expensive_wins_when_detour_large`.

### 8.7 Egress Mediation for New Hosts

```
places.googleapis.com, routes.googleapis.com ∈ allowed_hosts()
```

**Rationale:** The feature adds two Google API hosts outside the legacy
`maps.googleapis.com`. Under the allowlist (invariant 7.2), they must be
explicitly permitted or every live call fails 403/RequestError.

**Enforcement:** `DEFAULT_ALLOWED_HOSTS` includes both; outbound calls go through
`egress_audit.post`. Test coverage in `test_invariant_p0_host_allowlist.py`.

### 8.8 Freshest-Wins Composite Merge

```
∀ providers P, co-located stations s, fuel_type f:
  merged.price[f] = max_fresh(∪_{p∈P} p.price[f])     # ties → cheaper; missing ts never wins
  merge is deterministic given provider order
```

**Rationale:** When two providers report the same physical pump, the composite
keeps the freshest price per fuel type (a 35-minute-old GasBuddy price beats
Google's 23-hour-old price for the same station), directly attacking the
staleness gap. A provider missing a timestamp never outranks a stamped one.

**Enforcement:** `CompositeFuelPriceProvider` merges on a coordinate bucket
(`_merge_key`); `_fresher` breaks same-freshness ties by price and provider
order is the stable source priority. Tests: `test_composite_fresher_wins`,
`test_composite_cheaper_wins_on_same_freshness`,
`test_composite_missing_timestamp_never_beats_stamped`, `test_composite_deterministic`.

### 8.9 Fail-Closed Regional-Average Context

```
∀ eia_call: api_key = ∅ ∨ response ∉ sane($/gal band) → context omitted (never fabricated)
```

**Rationale:** The EIA weekly average is advisory context, never a replacement for
a station price. It must be omitted (not guessed) when the key is absent or the
response is malformed/implausible, and it must pass the egress allowlist.

**Enforcement:** `RegionalFuelPriceContext` fails closed; `_parse_eia_series`
drops points outside `[_MIN_USD_PER_GALLON, _MAX_USD_PER_GALLON]` and keeps the
newest period; `api.eia.gov` is allowlisted. Tests:
`test_weekly_average_no_key_returns_none`, `test_weekly_average_fails_closed`,
`test_parse_eia_series_skips_invalid_and_out_of_range`.

### 8.10 Bounded Route-Scoring Budget

```
∀ query: scored(E) = cheapest(K) ∪ nearest(M) ⊆ E        # K=8, M=5, straight-line order
  ⇒ |route_calls| ≤ K+M and E \ scored are surfaced without a detour score
```

**Rationale:** Google Routes is the per-query cost multiplier (one call per
scored station). Only a cheap or nearby station can win the effective-cost
ranking, so routing is bounded to the K cheapest plus M nearest (by
straight-line miles), and the rest are surfaced without a detour score (they
cannot be recommended). This keeps the bill independent of the Places result
count.

**Enforcement:** `_pick_route_candidates` returns the bounded union and the
caller routes only `to_route`, reporting `metadata.routes_skipped_by_budget` and
appending skipped stations to `alternatives` with a "Not route-scored" reason.
Tests: `test_pick_route_candidates_keeps_far_cheap_and_near_expensive`,
`test_find_best_gas_routes_bounded_subset_and_surfaces_skipped`.

## 9. Bridge source/capture adapter

### 9.1 Stable event identity and ownership

```
∀ normalized_record r: emit(r) → event_id(r) ≠ "" ∧ owner(r) is unchanged
```

The Bridge adapter is a projection of an existing Inbox record. It must not
create a second personal-data authority or silently replace the record's
canonical owner.

### 9.2 Provider-neutral envelope

```
∀ emitted_event e: e.version = "bridge.contracts.v1" ∧ has(e.id, e.kind, e.source, e.payload.text)
```

Legacy `role`, `model`, `provider`, and `verify` fields are not interpreted by
the source adapter. Execution policy belongs to Bridge's typed ticket and
approval path.

### 9.3 Intake is not execution

```
∀ e: accepted_for_intake(e) → ¬execution_authority(e) ∧ ¬verification_receipt(e)
```

Bridge intake acceptance only proves schema validation and durable intake
recording. It does not prove worker execution, code verification, or Git
delivery.

## 10. Canonical LifeOps project projection

### 10.1 Explicit rows only

```
∀ project_record p: p.project ≠ "" ∧ p.source_ref.source = "google_sheets"
```

The `/project-records` route reads the configured `Personal OS — Master
Tracker` project tab. It does not infer projects from arbitrary Drive or
message text. Every record retains the spreadsheet ID, tab, account, and row
number so the context layer can explain where the project came from.

### 10.2 Bounded and read-only

```
∀ project_read: 1 ≤ returned_count(project_read) ≤ min(requested_limit, 200)
∧ project_read.read_only = true
```

Project discovery is a bounded read model. Any later task or calendar action
must use its own approval-gated action path and must not mutate the tracker as
a side effect of discovery.

### 10.3 Tracker queues are projections, not authorities

```
∀ queue_record q: q.source_ref.source = "google_sheets"
∧ read(master_ops_queues) → ¬create_task(q) ∧ ¬send_message(q)
```

The Email Action Queue, Capture Inbox, and Google Tasks Mirror are read-only
reconciliation artifacts. Google Tasks, Gmail, and the original capture source
remain authoritative; queue discovery must not silently create or modify
provider state.

### 10.4 Persistent LifeOps sheet is explicit normalized evidence

```
∀ row r ∈ lifeops_sheet_projection: r.source_ref.source = "google_sheets"
∧ read(lifeops_sheet_projection) → ¬provider_mutation
```

The Canonical Context & LifeOps Registry (`10XAlrmI7tMvXADyrHVK7hLYGcDV6V-IxZhihtxsh5m8`,
tabs `04_PEOPLE` / `05_ACTIONS` / `03_PROJECTS`) may supply explicit people,
actions, and projects records with confidence and relationship fields. It
enriches the read model, but it does not replace Gmail, Calendar, Google Tasks,
Contacts, or source-native project authorities. The LEGACY Persistent Context
workbook is non-authoritative.

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
| 8.1     | Deterministic recommendation | P1 | Yes | High |
| 8.2     | Fail-closed credential gating | P0 | Yes | High |
| 8.3     | Normalized data boundary | P1 | Yes | High |
| 8.4     | Freshness policy | P1 | Yes | High |
| 8.5     | Price validity gate | P1 | Yes | High |
| 8.6     | Detour-aware cost function | P1 | Yes | High |
| 8.7     | Egress mediation for new hosts | P0 | Yes | High |
| 8.8     | Freshest-wins composite merge | P1 | Yes | High |
| 8.9     | Fail-closed regional-average context | P1 | Yes | Medium |
| 8.10    | Bounded route-scoring budget | P1 | Yes | High |

**Key:** P0 = safety/security/data-loss invariant (hard block). P1 = provable correctness invariant. P2 = style/design preference.

---
