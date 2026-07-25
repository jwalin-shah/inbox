# Inbox Oracle Map

Each inbox subsystem maps to orbit oracles from `~/projects/orbit/docs/research/`. The oracles provide the formal invariants and enforcement patterns that inbox should satisfy.

---

## Mapping Table

| Inbox Subsystem | Primary Oracle | Secondary Oracle | Key Principles |
|---|---|---|---|
| FastAPI server (`inbox_server.py`) | `api-design-oracle.md` | `web-platform-oracle.md` | Request ID traceability, structured errors, connection pool hygiene, timeout on long ops |
| Services layer (`services.py`) | `kernighan-plaughter-oracle.md` | `fowler-oracle.md` | Simplicity, clarity, generality; single-responsibility, deep modules |
| Connectors (`connectors/`) | `saltzer-schroeder-oracle.md` | `envoy.md` | Fail-safe defaults, economy of mechanism, least privilege; circuit breaker, retry budget |
| Connector registry (`connector_registry.py`) | `saltzer-schroeder-oracle.md` | `sicp-oracle.md` | Complete mediation, fail-safe defaults; data abstraction, narrow interfaces |
| MCP gateway (`mcp_gateway.py`) | `api-design-oracle.md` | `ousterhout-oracle.md` | Protocol conformance, session lifecycle, input validation; deep modules |
| MCP backend (`mcp_backend.py`) | `api-design-oracle.md` | `fowler-oracle.md` | HTTP client patterns, error mapping; adapter pattern |
| Message sync (`message_sync.py`) | `data-quality-oracle.md` | `lamport-tla-oracle.md` | Record identity, idempotent sync, deduplication; state machine, safety |
| Message index store (`message_index_store.py`) | `data-quality-oracle.md` | `ostep-oracle.md` | Index consistency, checkpoint integrity; persistence |
| Thread classifier (`thread_classifier.py`) | `kernighan-plaughter-oracle.md` | `tapl-oracle.md` | Clarity, generality; classification as type function |
| Approval store (`approval_store.py`) | `saltzer-schroeder-oracle.md` | `lamport-tla-oracle.md` | Complete mediation, fail-safe defaults; state machine consistency |
| Scheduler (`scheduler.py`) | `ostep-oracle.md` | `lamport-tla-oracle.md` | Persistence, state machine; safety, liveness |
| Egress audit (`egress_audit.py`) | `saltzer-schroeder-oracle.md` | `kernighan-plaughter-oracle.md` | Economy of mechanism (small allowlist), complete mediation; simplicity |
| Capture health (`capture_health.py`) | `owicki-gries-oracle.md` | `data-quality-oracle.md` | Interference freedom (thread-safe DB access); data freshness |
| Textual TUI (`inbox.py`) | `apple-platform-oracle.md` | `web-platform-oracle.md` | Responsive UI (no sync I/O in render), undo support; non-blocking updates |
| Gmail triage (`gmail_triage.py`) | `kernighan-plaughter-oracle.md` | `ousterhout-oracle.md` | Clear interface, separation of concerns; deep module for thread scoring |
| Google account resolution (`google_account_resolution.py`) | `fowler-oracle.md` | `saltzer-schroeder-oracle.md` | Adapter pattern for multi-account; fail-safe defaults |
| Memory store (`memory_store.py`) | `ostep-oracle.md` | `data-quality-oracle.md` | Persistence across restarts; data integrity |
| Services data models (`service_models.py`) | `tapl-oracle.md` | `ousterhout-oracle.md` | Type safety with `@dataclass`, pure data (no behavior); information hiding |

---

## Oracle Descriptions

### Primary Oracles

| Oracle | Source | What It Provides |
|---|---|---|
| `api-design-oracle.md` | Swagger/OpenAPI, REST best practices, GraphQL | API contract enforcement, request/response patterns, resource modeling, session lifecycle |
| `apple-platform-oracle.md` | Apple HIG, UIKit/SwiftUI, Xcode | Responsive UI contracts, undo/redo patterns, resource lifecycle, main-thread safety |
| `data-quality-oracle.md` | TFX, Model Cards, data pipeline best practices | Record identity, deduplication, schema enforcement, freshness, checkpoint integrity |
| `kernighan-plaughter-oracle.md` | Kernighan & Plaugher (1974) | Simplicity, clarity, generality, debugging, testing |
| `saltzer-schroeder-oracle.md` | Saltzer & Schroeder (1975) | 8 security design principles: economy of mechanism, fail-safe defaults, complete mediation, least privilege, separation of privilege, least common mechanism, psychological acceptability |
| `ousterhout-oracle.md` | Ousterhout (2018) | Deep modules, information hiding, strategic programming, design-it-twice |
| `fowler-oracle.md` | Fowler (1999/2002) | Refactoring catalog, code smells, enterprise patterns (adapter, strategy, observer) |
| `lamport-tla-oracle.md` | Lamport (2002) | Safety, liveness, fairness, refinement, state machine, model checking |
| `ostep-oracle.md` | Arpaci-Dusseau (2015) | Persistence, scheduling, concurrency, process/thread lifecycle |
| `owicki-gries-oracle.md` | Owicki & Gries (1976) | Sequential correctness, interference freedom for concurrent programs |
| `tapl-oracle.md` | Pierce (2002) | Type safety (progress + preservation), type function as classification |

### Secondary Oracles

| Oracle | Source | When to Use |
|---|---|---|
| `envoy.md` | Envoy proxy | Circuit breaker, retry budget, rate limiting, per-endpoint isolation |
| `sicp-oracle.md` | Abelson & Sussman | Data abstraction, higher-order procedures, metacircular evaluation patterns |

---

## How to Use This Map

1. **Identify the subsystem** you are modifying (e.g., `connector_registry.py`)
2. **Read the primary oracle** (`saltzer-schroeder-oracle.md`) for the formal invariants
3. **Consult the secondary oracle** (`sicp-oracle.md`) for the design pattern
4. **Write the invariant** as a tensor equation in `docs/invariants.md`
5. **Implement** the code against the invariant
6. **Test** with a test that exercises the invariant boundary

---

## Oracle Source Directory

All oracles live at:
```
~/projects/orbit/docs/research/
```

---