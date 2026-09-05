# LifeOps overnight improvement record — 2026-08-26

## Objective

Make LifeOps more reliable as one personal-operations surface: retrieve
evidence across the connected sources, preserve attribution, classify what
needs attention, and route consequential actions through explicit approval and
read-back verification. This record is the control document for overnight
work. It is deliberately bounded: no provider data is deleted, sent, edited,
or reorganized merely because an agent found it.

Definition of done for this cycle:

1. A client can obtain a bounded, account-scoped evidence packet.
2. The packet says what was searched, which sources answered, what is stale or
   unavailable, and where each important item came from.
3. A worker can classify attention candidates without receiving secrets,
   arbitrary host control, or provider-write authority.
4. A proposed write can be shown exactly, approved once, executed once, and
   read back against the target.
5. Every failure becomes a reproducible finding or a documented limitation;
   no worker status is accepted as completion by itself.

## Verified baseline

The following is current evidence, not an architectural aspiration:

| Surface | Evidence | Meaning | Boundary |
|---|---|---|---|
| LifeOps HTTP | `verify_lifeops_read_surface.py` exited 0 after the managed process restart; protocol `2025-06-18`, server `1.27.0`, 52 tools, direct `lifeops.context.v1` and durable-receipt checks | The read surface, account scope, source-health map, provenance shape, annotations, and receipt read-back are live | Does not prove a ChatGPT UI call or a write |
| Secure MCP Tunnel | `tunnel-client health --url-file ... --require-control-plane-poll --json` returned `result: ok`; `/healthz`, `/readyz`, and the control-plane poll all succeeded | The managed tunnel client is live and connected to the OpenAI control plane | Does not prove that ChatGPT has invoked the app |
| ChatGPT LifeOps connector read | The connected `lifeops` app completed `source_health` and a bounded `search` for `LifeOps` in the current ChatGPT context; both returned success and the search returned one result | The actual connector tool path can reach the LifeOps MCP and perform a read | This proves a bounded connector call, not provider completeness or any write/approval |
| LifeOps restricted stdio | `verify_lifeops_worker_stdio.py` exited 0; exactly `evidence_packet` and `system_audit` | DeepSeek/Pi-style workers have a narrow context path | Does not sandbox the host runtime |
| All-account context | Live unscoped `life_context` returned `all_loaded_provider_accounts` for the three loaded Google accounts and kept Master Ops/LifeOps Sheets on the canonical account | Account routing is explicit instead of silently collapsing one mailbox into the whole personal system | Does not prove exhaustive historical indexing |
| Cross-client contention | HTTP and stdio verifiers exited 0 concurrently after the process lock change | Separate clients no longer burst the shared provider session in this test | It is a contention guard, not a completeness guarantee |
| Bounded read recovery | After the timeout fix and managed-process restart, HTTP and stdio proofs exited 0 concurrently in 24.4s and 23.1s | A slow `/inbox/now` source now degrades within the triage budget instead of consuming the full verifier window | This proves the bounded verifier path, not complete provider coverage |
| DeepSeek Harness | A real bounded `evidence_packet` call returned success; all four scope booleans were false | DeepSeek Harness can consume the restricted LifeOps worker MCP | It cannot write, fetch secrets, or control workers through that MCP |
| LifeOps transport profiles | The adapter now has `full`, annotation-derived `read_only`, and exact two-tool `worker` profiles; the isolated read-only HTTP process exposes 43 tools and the live verifier proves `read_only=true`, `provider_writes=false`, `worker_control=false`, and `secret_access=false` | A remote client can be held to a separate read catalog without changing the approval-capable legacy tunnel | The platform's generic custom-action labels still say `Writes`; the actual safety proof is the server catalog/profile and live scope flags |
| Local client read-first wiring | `.mcp.json`, `.cursor/mcp.json`, and OpenClaw's `lifeops_v0` now expose an explicit `read_only` LifeOps entry; `verify_lifeops_profile_stdio.py`, config tests, and the live profile probe pass | Pi/Cursor/Claude/OpenClaw can select the same read-first LifeOps surface rather than relying on an implicit full catalog | Legacy broad OpenClaw entries remain until parity and retirement are separately proven |
| OpenClaw MCP discovery | `openclaw mcp probe lifeops_v0 --json` returned 43 tools and zero diagnostics; the discovered names are all read-only and include `life_context` and `triage_all` | OpenClaw is consuming the same annotation-derived read-first catalog, not just carrying a static config entry | This proves discovery only; an OpenClaw source-read call and host sandbox are separate proofs |
| Hermes MCP discovery | `hermes mcp test lifeops_v0_readonly` connected and discovered 43 tools from the annotation-derived `read_only` launcher | Hermes now has a named canonical read-first LifeOps surface aligned with the other local clients | The legacy six-tool surface and exact two-tool worker remain enabled for rollback/compatibility; no provider read or approval was performed |
| Full repository suite | Current run: `2043 passed in 89.11s`; focused profile/context/triage tests and runtime-verifier tests pass; receipt tests pass | The current code has broad regression coverage, including freshness, bounded-context, live-contract verifier, profile filtering, receipt persistence, and pending-proposal review invariants | The agent-safe wrapper still stops at 57 repository-wide Ruff findings; direct `INBOX_TEST_MODE=1 uv run pytest -m safe -q` passes 427 tests, but the wrapper is not green |
| Documentation gate | `prove-docs-freshness.sh` exited 0 | Machine-level operating documentation is consistent | It does not certify provider completeness |
| Orca | `orca status --json`: app running, runtime ready/reachable, version `1.4.188`; LifeOps worktree registered | Orca can host local worktrees and terminals | Terminal writability is not LifeOps authority |

### Bounded triage ordering hardening

The Inbox message triage projection now preserves category priority while
ordering each category newest-first. This keeps the first bounded review page
focused on the freshest evidence. The change is read-only and does not alter
the index, event log, provider state, or task queue. It is covered by
`tests/test_triage_projection.py::test_message_triage_shows_freshest_item_first_within_category`;
the focused triage suite passed (`10 passed`). The managed Inbox process was
restarted and returned HTTP 200 on `/health`, reporting the three configured
Gmail, Calendar, Drive, and Sheets accounts; the Secure MCP Tunnel remained
healthy afterward.

### Review-queue completeness hardening

`review_queue` now propagates relevant context and coverage failures, exposes a
separate `complete`/`completeness` result, and keeps `truncated` reserved for
pagination. A source failure can therefore no longer appear to be a complete
review merely because the returned page was not clipped. The regression test
`tests/test_lifeops_identity_review.py::test_review_queue_marks_partial_context_without_conflating_pagination`
passes, and the focused identity-review suite passes (`7 passed`).

The Business workspace now has two LifeOps app records: the legacy `lifeops`
app remains untouched, and `lifeops-read-only` is published against the
separate `lifeops-readonly` secure tunnel (`tunnel_6a8f1ed22d908191a4f3402d6cc5e74a`).
The latter imported 43 tools and excludes proposal, approval, and execution
tools. Its app ID is `asdk_app_6a8f20a754d081918f4e6828cc1b6fa9`; publication
proves catalog delivery, not a fresh ChatGPT conversation call.

**Secure MCP discovery compatibility (2026-08-26):** The tunnel validator
probes `server/discover` before importing an app's action catalog. FastMCP
1.27's legacy Streamable HTTP handler returned an invalid-parameters error for
that probe, which left publication stuck even though `initialize` and
`tools/list` worked. LifeOps now intercepts that probe with an honest
2025-06-18 discovery card and delegates all other requests to FastMCP. A local
probe returned HTTP 200 with `supportedVersions=["2025-06-18"]`.

The first post-fix live revalidation passed for both HTTP and restricted stdio
clients. Before the deadline fix, both had timed out at 90 seconds; the
stalled `/inbox/now` read was the first bounded source failure. `triage_all`
now applies an 8-second per-read limit and a 45-second total triage deadline,
returning the affected source in `read_errors` rather than hanging the packet.
The sync-state freshness fix also passed its focused regression: a running or
failed attempt preserves the prior `last_success_at` instead of making stale
indexed data appear current.
The context route now has the same bounded failure behavior: supplemental
reads are capped at 8 seconds each and 120 seconds total, with source errors
returned in `source_health` and `limitations`.

An independent runtime review during this cycle also identified two open gaps:
OpenClaw currently has narrow LifeOps reads alongside broader `inbox_full`,
approval-capable Inbox, and broad LifeOps profiles; and the restricted MCP
worker contract does not sandbox a worker's own shell, filesystem, or process
tools. These are findings, not silently accepted claims of security.

## Decisions made and why

### 1. Inbox remains personal-data authority; LifeOps remains the governed MCP
surface

This prevents ChatGPT, Claude, Pi, DeepSeek, Orca, Agy, and Cursor from each
becoming a competing database or writer. Inbox owns provider reads and existing
approval machinery. LifeOps exposes bounded projections and exact action
workflows. Bridge remains the future work-authority handoff, not an accidental
second personal-data store.

**How it works:** every projection carries source identifiers, account scope,
freshness, and limitations. A worker consumes a packet or read tool; it does
not receive the Inbox token.

**Acceptance test:** a packet must prove `read_only=true` and
`provider_writes=false`, `worker_control=false`, `secret_access=false`, and
`raw_event_mutation=false`.

### 2. One context contract, with explicit account semantics

`life_context` is the stable read model for a current bounded snapshot. A
blank account means all loaded provider accounts for account-scoped Google
reads. An exact account selects only that account. The canonical LifeOps/Master
Ops/project-tracker Sheets remain one user-scoped source routed through the
explicit canonical account (`jshah1331@gmail.com` in the current deployment).

**Why:** this fixes the prior failure mode where one mailbox was silently
presented as the whole personal system, while also avoiding three fake copies
of the canonical personal graph.

**Acceptance test:** all-account calls report the account inventory and source
scope; selected-account calls do not fan out; canonical Sheet reads identify
their source account; inventory failure is labelled incomplete.

### 3. Workers get evidence, not authority

DeepSeek Harness, Pi, and other worker runtimes may classify or summarize a
bounded packet. The restricted worker profile exposes only `evidence_packet`
and `system_audit`. DeepSeek's current LifeOps classifier receives bounded
titles/summaries, not unrestricted mailbox bodies.

Claude should be maximized for high-value review, synthesis, adversarial
checking, and implementation proposals in isolated Orca worktrees. It should
not be used as a hidden always-on writer. The useful unit of work is a small
review with explicit inputs, expected evidence, and a stop condition.

**Acceptance test:** a worker report names the evidence it used, lists
uncertainties, and produces no provider mutation. A host-agent permission is
never described as an MCP permission.

The remaining OpenClaw profile work is a P1 retirement item. The default
`lifeops_v0` path now exposes the verified read-only surface; full Inbox,
approval-capable Inbox, and legacy broad LifeOps entries remain available until
parity and the actual channel workflow are tested, after which they can be
made explicit captain-only profiles. This record does not silently revoke
those older paths.

The same distinction applies to Pi, DeepSeek Harness, Claude, Agy, and Cursor:
MCP filtering limits what they can call through LifeOps, but it does not remove
their independent host tools. Any worker treated as untrusted must be launched
through Bridge/OS isolation with no inherited credential environment and no
unrestricted home-directory access.

### 4. Exact approval remains mandatory for real-world writes

LifeOps may propose a Google Task or Calendar update, but the action payload
must be shown exactly, approved explicitly, leased once, executed once, and
verified by re-reading the target. This applies even when a model is highly
confident. No worker, tunnel, or API key bypasses this sequence.

**Acceptance test:** the first write slice is the street-play Calendar update;
the final record includes proposal ID, approval/lease identity, execution
result, and target read-back. No write is attempted during this overnight
review without a separate user approval.

### 5. Pending proposals must be inspectable without being executable

LifeOps now exposes `pending_actions` as a read-only review surface. It returns
the exact supported method, path, body, account/resource binding, and payload
hash for pending proposals, while omitting unsupported guarded routes. Listing
does not mint a lease, approve a request, or execute a provider action.

**Why:** a user cannot safely approve an action they cannot inspect. A broad
“approve everything” control would also break the payload-bound lease model.

**Acceptance test:** the unit regression proves that a supported proposal is
returned verbatim as review data, an unsupported route is omitted, and the
only call made is `GET /approvals?state=pending`; no decision endpoint is
called.

### 6. Preserve raw evidence; derive state separately

Messages, calendar rows, contact records, Sheet rows, and documents remain
source evidence. Triage labels, person links, project links, and “needs me”
items are derived state and can be corrected without rewriting history.

**Why:** it makes wrong interpretations recoverable and lets reviewers answer
“why does LifeOps believe this?” instead of trusting an opaque summary.

**Acceptance test:** every derived attention item retains its source/account/
thread or row reference and observed time, or is explicitly marked as lacking
that evidence.

### 7. Coordination is bounded and observable

The in-process gates and per-user cross-process lock protect the shared Inbox
provider session. They prevent concurrent clients from creating artificial
timeouts, while bounded reads and explicit truncation prevent a giant “capture
everything” request from pretending to be complete.

**Acceptance test:** concurrent HTTP and stdio read proofs exit 0; partial or
timed-out reads remain visible as limitations; approval/write paths do not use
the read retry behavior.

### 8. Sync freshness advances only on a successful commit

`sync_state.last_success_at` now changes only when a sync records the
successful `idle` state. Starting a sync or recording progress leaves the
previous successful timestamp intact; a new source that has never completed a
sync remains visibly unverified rather than appearing fresh merely because a
run started.

**Why:** a running or failed synchronization is not evidence that the indexed
data is current. Freshness must describe the last successful observation, not
the latest attempt.

**Acceptance test:** the store regression proves the timestamp is empty for a
new running sync, populated after the idle commit, and unchanged during the
next running/progress state.

### 9. Every triage response must identify its read attempt

`triage_all` now returns a unique `lifeops.triage_receipt.v1` run ID, the
requested account scope, and a per-source transport trace with status, attempt
count, timing, and bounded error text. This lets a downstream reviewer
distinguish “the tool returned” from “every source answered.”

**Why:** a multi-source summary without a run identity makes it too easy to
reuse an old result or mistake a partial read for a complete one.

**Acceptance test:** the timeout regression checks that the receipt records a
deadline-exceeded source and marks `transport_complete=false`.

**Durability:** the metadata-only receipt is also persisted in the local
LifeOps read-receipt database with owner-only permissions. The new read-back
and list tools expose the audit record without storing source-item bodies or
changing provider data. A persistence failure is surfaced in the receipt and
does not turn a successful provider read into a false failure.

### 10. The unified context route must fail within a bounded window

`life_context` now applies an 8-second limit to each supplemental Inbox read
and a 120-second total route deadline, including account fan-out and gate wait.
Timed-out or unavailable sources are retained as source-health errors and
limitations while the rest of the bounded projection is returned.

The reads are scheduled explicitly in sequence because they share provider
session objects and a cross-process lock. This makes each per-read timeout
measure the read itself rather than time queued behind another read.

**Why:** protecting only the initial triage call still allowed the follow-up
people, project, document, calendar, and task reads to hang the one-surface
context request.

**Acceptance test:** the context regression uses a hanging provider request and
proves that the route returns an unavailable Calendar source with an explicit
`life_context_*` error.

## Overnight work queue

Work proceeds in this order. A later item must not be used to imply an earlier
one is complete.

### P0 — prove the one user-facing read path

1. In the ChatGPT Business Work composer with `lifeops` selected, run one
   read-only `life_context`/`evidence_packet` check for the exact account
   `jwalinshah13@gmail.com`.
2. Record the returned schema, account scope, source-health result, freshness,
   and limitations.
3. Compare the response with the direct LifeOps verifier. Flag any mismatch;
   do not “repair” it by widening permissions.

**Blocked until:** the user performs the action-time confirmation in the
ChatGPT UI. This is a deliberate user gate, not a technical failure.

### P1 — make triage useful without making it authoritative

1. Run a bounded triage page across Gmail, iMessage, Calendar, Tasks, Contacts,
   and the canonical Sheets.
2. Produce categories: `reply_now`, `task`, `calendar`, `waiting`, `fyi`, and
   `archive`, with evidence references and confidence.
3. Reconcile candidates against existing Google Tasks in report-only mode.
4. Surface identity candidates for review rather than silently merging people.

**Acceptance test:** every proposed task has a source reference and dedupe
reason; no task is created automatically.

### P1 — use Claude as a reviewer, not a parallel authority

The Orca Claude review should answer only:

- Which claims in this document are actually proven?
- Which gaps are most likely to cause a false “done” report?
- Which next test gives the highest information gain with the least privilege?
- Which existing capability should be reused instead of rebuilt?

Claude's output becomes an input to this document only after the coordinator
checks its claims against current files, logs, and live proofs. An isolated
Orca worktree is used so review cannot alter the LifeOps checkout.

The current Claude run is paused at Orca's explicit folder-trust prompt. I am
not accepting that prompt implicitly: it grants Claude read, edit, and execute
access to the isolated review checkout. Once the user trusts that specific
worktree, Claude can continue with the bounded review. Native `ca` and
TokenRouter-backed `ct` are separate routes; a version string or account
metadata is not a model-request proof, and `ct` must remain inside a
Bridge-admitted sandbox if it uses permissive host flags.

### P2 — prepare, but do not yet widen, the next adapters

Keep these as explicit backlog items:

- Agy/Cursor host adapter with the same restricted worker contract.
- Bridge reference-only evidence binding after its typed contract is
  implemented and verified.
- Apple Shortcuts/Siri notification delivery for approved commitments and
  departure times.
- Additional source adapters only after a source registry entry, freshness
  policy, provenance mapping, and read proof exist.

No direct LifeOps-to-DeepSeek secret handoff, unrestricted Orca shell bridge,
or “full Inbox permissions” bundle is part of this cycle.

## Learning loop: how the same mistake becomes structurally harder to repeat

Every overnight task follows this record:

```text
question
  -> current attempt identity
  -> smallest reproducible check
  -> observed result
  -> decision and reason
  -> bounded implementation
  -> live verification
  -> read-back / receipt
  -> limitation or lesson
```

The coordinator must reject these common false completions:

- “The app is installed” presented as “the tool call worked.”
- “The worker has a writable terminal” presented as “the worker has provider
  permission.”
- “One account answered” presented as “all accounts are connected.”
- “A model classified an item” presented as “a task or calendar change exists.”
- “A test passed” presented as “the Mac permission or remote tunnel works.”
- “A source appears in a registry” presented as “its historical corpus is
  complete.”

When one of these appears, add a regression test or a source-health/limitation
field before adding another integration. This is the structural response to
the recurring problem: separate authority, evidence, permissions, freshness,
and completion receipts instead of relying on agent confidence.

## User gates still required

Only two human decisions are needed for the next vertical slice:

1. Confirm the pending read-only LifeOps check in the ChatGPT Business chat.
2. Later, separately approve the exact street-play Calendar update after the
   proposal is displayed.

If Claude is to continue in Orca, trust only the isolated review worktree shown
by Orca's prompt. That grants Claude access to that checkout's files and
commands; it does not grant LifeOps, Inbox, Google, Infisical, Keeper, or
provider-write authority.

## Current honest status

The read architecture is substantially operational and the worker boundary is
proven. A bounded read through the connected ChatGPT LifeOps app is now proven;
the first approved write/read-back proof remains open. OpenClaw's read-first
discovery is proven, but legacy profile retirement is not. Bridge delivery,
Agy/Cursor execution, complete mailbox coverage, Apple notification
automation, and property evidence remain unproven. Overnight work should
reduce those specific uncertainties, not hide them behind a larger tool list.

The completed independent review did not edit files, access secrets, or perform
provider writes. Its findings are included here as open hardening work, not as
new runtime proof.

### Triage reply-boundary correction (2026-08-26)

The source classifier previously set `needs_reply=1` for both `reply` and
`review`. That turned opportunity/newsletter review candidates into false
reply obligations. The classifier now requires explicit `reply` actionability
before setting `needs_reply`, and the LifeOps model join cannot promote a
source-derived non-reply candidate to `reply_now`.

The existing Inbox derived index was backed up to
`.inbox_index.sqlite3.pre-triage-fix-20260826` and rebuilt locally using the
existing `message_sync.py rebuild` operation. The live index went from 503
`review + needs_reply` rows to zero; the 163 explicit `reply + needs_reply`
rows remained. Raw messages and provider systems were not mutated.

Focused regression tests pass in both the LifeOps and Inbox checkouts. This
fix improves semantic precision; it does not prove that every mailbox history
has been indexed or that a model can safely create tasks without review.
