# LifeOps MCP v0

## Goal

Make ChatGPT Business the cockpit for the existing Inbox/Mac capability layer without exposing the whole Inbox REST API or weakening its write-approval invariants.

```text
ChatGPT Business
      |
      | MCP over HTTPS
      v
Secure MCP Tunnel (preferred for ChatGPT)
      |
      v
lifeops_mcp.py :9850
      |
      | authenticated localhost HTTP
      v
inbox_server.py :9849
      |
      +-- iMessage / Contacts / Notes / Reminders
      +-- Gmail / Calendar / Tasks / Drive / Docs / Sheets
      +-- Maps travel time / current location
      +-- GitHub / connector index / audit
```

The same LifeOps adapter supports two transports: Streamable HTTP for ChatGPT
Business through Secure MCP Tunnel, and local stdio for Pi, DeepSeek harnesses,
and OpenClaw. Both transports call the same authenticated Inbox server. The
stdio launcher is `scripts/run_lifeops_mcp_v0_stdio.sh`; it does not create a
second Google credential store.

The MCP adapter is intentionally smaller than Inbox. V0 proves one useful vertical slice before widening permissions.

## V0 tool surface

Read tools:

- `search` and `fetch` — cross-source evidence retrieval
- `search_indexed_messages` — fast local keyword, semantic, or hybrid search
  over captured Gmail/iMessage items while preserving source/account/thread
  identifiers and raw pointers
- `embedding_status` — read-only progress for the local semantic index
- `list_drive_files` and `list_docs` — bounded, read-only Google Drive/Docs
  metadata through Inbox; these do not download document bodies
- `document_evidence` — read one explicitly selected Google Doc body with a
  character bound, truncation flag, account, and source reference
- `search_sheets`, `sheet_metadata`, and `read_sheet_range` — bounded Google
  Sheets discovery through Inbox's existing multi-account Google integration
- `contacts_search` and `contact_profile` — unified contact evidence through
  Inbox's existing contact merger, including Google People when its runtime
  probe is healthy. Apple Contacts/AddressBook is also represented as a
  first-class read-only source in capture health and coverage, while local
  LifeOps notes and relationship claims remain separate from provider data.
- `people_search` and `person_profile` — local canonical person profiles with
  source identifiers, explicit notes, relationship claims, and linked external
  contact activity
- `message_thread` — retrieve the underlying iMessage/Gmail thread after a
  search hit identifies the conversation
- `calendar_event` — read one exact Calendar event for proposal and read-back
- `current_location` — read macOS Core Location or Inbox's configured fallback
- `life_triage` — bounded, read-only attention projection with source/account
  attribution and explicit coverage health
- `life_context` — one bounded `lifeops.context.v1` read model combining the
  existing triage, unified contacts, upcoming Calendar places, and open Google
  Tasks surfaces, plus explicit project records and contact addresses when
  Inbox has them. It also exposes explicitly captured property evidence as a
  separate top-level collection. It is a transport projection only; Inbox and
  the provider systems remain authoritative, and absent project records are reported rather
  than inferred. Explicit projects are conservatively deduplicated by a
  normalized name while retaining all memory/capture and explicitly attached
  cross-source references. When available, Inbox also contributes explicit
  rows from the canonical `Personal OS — Master Tracker` `Projects & Areas`
  tab; each row retains its spreadsheet ID, tab, account, and row number.
  Open rows from the Master Tracker's Email Action Queue may appear as
  `curated_email_action` attention items, while the Tasks Mirror remains a
  reconciliation artifact rather than a task authority.
  The `LifeOps — Persistent Context & Research` sheet also contributes
  explicit People, Actions, and Projects rows; exact-name contact matches are
  labeled, while unresolved identities remain separate.
  The context also includes bounded Drive/Docs metadata with provider IDs,
  account, modified time, parent IDs, and web links. Document bodies remain
  behind explicit follow-up reads, so metadata cannot be mistaken for complete
  document coverage.
  Actions preserve exact links back to canonical People and Project rows when
  the source text matches one canonical title; Projects preserve explicit links
  back to canonical People rows;
  weak name-fragment matches are exposed as candidates or ambiguities rather
  than silently merged. Repeated calendar/contact place observations are
  normalized into one place item with an evidence list and observed-source
  counts, so corroboration remains visible without becoming an automatically
  canonical address. Place equivalence is intentionally conservative: it only
  normalizes case, punctuation, whitespace, and common street-suffix
  abbreviations; unit/address tokens remain distinct and no geocoding is
  performed.
  Selected auxiliary LifeOps workbook tabs—Values, Captures, Interactions,
  research cache/source rows, Authority Map, Interview Queue, and Source
  Registry—are exposed as generic notes with tab and row provenance. They are
  not automatically promoted to tasks, goals, or decisions.
- `identity_review` — bounded read-only review queue for LifeOps People rows
  whose contact identity is unmatched, a candidate, or ambiguous (the default
  filter), together with observed places and explicit project links. Passing
  `status=matched` is available when auditing confirmed matches. It preserves
  provenance, including exact candidate contact IDs and bounded contact
  disambiguation fields for candidate and ambiguous matches, and never
  confirms or writes a link by itself.
- `review_queue` — one bounded read-only queue combining unresolved identity
  links, action-to-project links, and stale/blocked/planned source gaps,
  ordered by review priority and retaining the exact source references needed
  for review. It returns both page counts and available counts plus a
  `offset`, pagination metadata, and a `truncated` flag, so bounded callers can
  page without mistaking a partial queue for a complete backlog. It also
  returns `complete=false` and carries relevant context/coverage failures
  forward; `truncated` only describes pagination.
- `triage_all` — sequential, read-only multi-source triage across Inbox,
  Gmail, Calendar, Tasks, iMessage, Contacts, and Sheets. It returns bounded
  evidence candidates, source/account coverage, freshness/index health, and
  validated `reply_now` / `task` / `calendar` / `waiting` / `fyi` / `archive`
  categories. Each response also carries a unique `lifeops.triage_receipt.v1`
  run ID and per-source transport trace. The trace records what this bounded
  attempt actually reached; it is not exhaustive provider coverage. The
  metadata-only receipt is persisted locally and can be read with
  `read_triage_receipt` or listed with `list_triage_receipts`; it contains no
  source-item bodies. The default model is DeepSeek V4 Pro, selected through
  `LIFEOPS_TRIAGE_MODEL`; a routed model such as `moonshotai/kimi-k3` can be
  selected for a bounded run. The model receives only titles/summaries and
  cannot fetch sources or perform writes; deterministic source guardrails
  remain in force. Kimi K3 requires TokenRouter's `reasoning_effort=low`
  option because its thinking mode cannot be disabled; successful model
  labels retain the returned model name in `classification_method`.
- `read_triage_receipt` and `list_triage_receipts` — read-only audit views over
  the local metadata-only receipt store; they never read or mutate provider
  content.
- `triage_messages` supports `offset` plus `limit` so the review queue can be
  worked through in successive read-only pages. Review threads rather than
  every individual message; each item retains its source evidence reference.
- `source_health` — provider, capture, and egress health
- `coverage_report` — versioned, read-only account/source coverage with
  indexed counts, sync timestamps, freshness policy, blockers, and planned
  source gaps. Account-scoped Google rows and unscoped local/external rows
  (such as Apple Contacts, Messages, Notes, Reminders, and GitHub) are kept
  together without inventing an account association. It is the preferred
  first call when deciding which sources can support a claim; it does not
  imply provider-side completeness beyond the recorded Inbox checkpoints.
- `calendar_events` — calendar commitments
- `travel_time` — route duration
- `multi_stop_route` — read-only ordered pickup/dropoff route with dwell
  time, per-leg evidence, and one latest safe departure time
- `departure_times` — leave-time calculation for located events
- `tasks` — current Google Tasks
- `gmail_normalization` — per-account indexed Gmail coverage, sync freshness,
  and action counts
- `todo_candidates` — stable, attributable action candidates without writes
- `task_reconciliation` — compare existing Google Tasks with candidates,
  including unmatched tasks and conservative same-account duplicate or
  near-duplicate title groups; this is report-only and never deletes tasks
- `property_evidence` — read explicitly captured property photos, measurements,
  parcel records, and sun/shadow observations from the append-only evidence
  log; this does not infer surveyed geometry
- `evidence_packet` — bounded, ephemeral context for a named worker. It carries
  selected LifeOps sections, source health, limitations, and provenance, while
  explicitly carrying no provider-write, secret, or terminal authority. Notes
  and document metadata are excluded unless requested. Use
  `scripts/run_lifeops_mcp_v0_worker_stdio.sh` when the worker should see only
  this packet and `system_audit`; that restricted profile also rejects notes
  and document metadata.
- `system_audit` — read-only readiness summary for the observed LifeOps
  surfaces. It reports coverage, task-duplicate findings, property-evidence
  state, embedding freshness, the approval policy, and known gaps such as
  worker dispatch. A `ready` result means the observed reads responded; it
  does not mean every provider, account, file, message, or Mac capability has
  been exhaustively connected.

Governed work-item seam:

- `create_work_item` — durably records a bounded proposal for a named worker
  with an idempotency key, scope, evidence references, budget, and acceptance
  checks. This is local metadata only: it does not launch a process, call a
  provider, inject credentials, or execute a terminal command. Repeating the
  same idempotency key returns the same proposal; reusing it with different
  content fails closed.
- `get_work_item` and `list_work_items` — read the durable proposal, its
  append-only metadata events, and its receipt. New proposals remain
  `status=proposed` and `dispatch_status=not_admitted` until a future adapter
  proves Bridge admission, exact scope/tree binding, and independent
  verification. This deliberate gap is visible in `system_audit` rather than
  represented as a fake running state.

The work-item store is separate from the triage receipt store and lives under
the same owner-only LifeOps application-support directory by default. It uses
SQLite WAL plus a materialized current row and an append-only event table. It
stores metadata and source references only; source bodies, secrets, commands,
and environment values are rejected at the MCP boundary.

Bounded write workflow:

- `propose_create_task`
- `propose_task_from_candidate` — bind one reviewed candidate to the existing
  message-linked task workflow
- `propose_update_calendar_event`
- `propose_person_note`
- `propose_person_relationship`
- `propose_person_identity_link` — persist a confirmed local link between a
  canonical LifeOps person and a source contact; it does not edit provider
  Contacts
- `pending_actions` — show the exact supported pending proposals for review;
  this is read-only and does not approve or execute anything
- `approve_pending_action`
- `execute_approved_action`
- `verify_approved_action` — re-read the target and return a bounded
  verification receipt; duplicate or unsupported matches are reported as
  `ambiguous`/`unsupported`, never as success

Person-profile and identity-link writes are local-only; they do not modify
Apple/Google Contacts. Identity links are read back from Inbox before the
context projection treats the link as a durable match.
No MCP tool can send messages, delete data, run arbitrary shell commands, or
execute arbitrary Inbox endpoints in v0.

### Runtime profiles

The adapter supports three explicit transport profiles:

- `full` (the default) exposes the complete v0 catalog, including the
  proposal/approval/execute tools described above. Those writes remain
  payload-bound and lease-gated; `full` does not mean arbitrary Inbox access.
- `read_only` removes every tool whose MCP annotation is not explicitly
  `read_only_hint=true`. It currently exposes the read catalog only and is
  the preferred profile for a first remote ChatGPT read proof.
- `worker` exposes exactly `evidence_packet` and `system_audit`, with the
  additional account allowlist enforced by `evidence_packet`.

Select a profile with `LIFEOPS_MCP_PROFILE`. For example, a local read-only
process can be started with:

```bash
LIFEOPS_MCP_PROFILE=read_only uv run python lifeops_mcp.py
```

The existing `lifeops` Business tunnel remains on the default `full` profile
for the already-published legacy app. The new `lifeops-readonly` Business
tunnel runs a separate port and LaunchAgent with `LIFEOPS_MCP_PROFILE=read_only`.
The published `lifeops-read-only` app is bound to that second tunnel and
imports the 43-tool read catalog. Keeping the transports separate prevents a
read-only app from silently inheriting approval-capable tools. The profile is
an additional defense-in-depth boundary, not a replacement for the Inbox
approval lease or the ChatGPT confirmation.

### Repeatable live read-surface verification

After starting LifeOps, run this sanitized verifier to prove the local MCP
handshake, required read tools, read-only annotations, and one bounded
account-scoped evidence call:

```bash
export LIFEOPS_VERIFY_ACCOUNT='your-account@example.com'
uv run python scripts/verify_lifeops_read_surface.py
```

It refuses an unscoped account, never calls a write tool, and prints only
protocol/server metadata, tool counts, annotations, schema, scope flags,
selected-account scope, source-health entries, provenance count, and
section names. Set `LIFEOPS_MCP_URL` for another endpoint or
`LIFEOPS_MCP_AUTH_TOKEN` when the endpoint requires bearer authentication.
This proves the MCP target and bounded read contract; it does not by itself
prove a ChatGPT Business UI call or grant a host agent shell/filesystem
permissions.

`triage_all` is intentionally bounded. It is an attention-candidate projection,
not an assertion that every historical email body or every Sheet cell has been
read. Source coverage and read errors are returned with every run; callers must
not treat a run with non-empty `read_errors` as complete.
Each source read is capped at 8 seconds and the sequential triage run has a
45-second total deadline. A timed-out source is returned as an explicit
`read_errors` entry so a slow provider cannot consume the entire MCP request
window or be mistaken for a complete empty result.

`life_context` is the stable read contract for clients that need one current
snapshot rather than several tool-specific calls. Its `people`, `places`,
`projects`, and `commitments` sections are built from existing Inbox read
endpoints and retain provider, capture, or tracker-row identifiers. Its `goals`, `decisions`,
and `notes` sections stay empty unless this adapter receives explicit records
for them; it does not infer durable state from a message title or model output.
Its supplemental reads have an 8-second per-read limit and a 120-second total
route deadline; unavailable sources remain visible in `source_health` and
`limitations` instead of making the snapshot appear complete.
Supplemental reads are explicitly scheduled in sequence because they share
provider/session objects and a cross-process lock; Google Sheets-backed
projections remain additionally serialized because they share the provider
session. The live
snapshot remains source-health annotated; a partial read is reported as a
limitation rather than silently presented as complete.
The projection retries one transport-level failure per read within this
read-only boundary; approval and provider-write paths do not use that retry
behavior.
Reads are also coordinated across LifeOps MCP processes with a per-user,
owner-only lock file. This prevents separate stdio and HTTP clients from
bursting the shared Inbox/provider session at the same time; it does not
serialize approval or provider-write paths and does not make a partial read
complete.

The canonical LifeOps, Master Ops, and project-tracker Sheets are user-scoped
personal-operations sources, not per-mailbox data. `life_context` therefore
reads them through the explicit `LIFEOPS_CANONICAL_GOOGLE_ACCOUNT` source
account even when its `account` argument selects another Gmail/Calendar
mailbox. The current Mac deployment uses `jshah1331@gmail.com`; deployments
for another owner must set that environment variable explicitly. The returned
source health records the canonical source account so this routing is visible
and auditable.

When `account` is blank, `life_context` first reads Inbox's account inventory
and fans out account-scoped Docs, Calendar, Drive, and Tasks reads across the
loaded accounts. When `account` is supplied, those reads use only that exact
account. If account discovery fails, the route keeps a default fallback but
  labels it as incomplete instead of claiming all-account coverage.

A live unscoped `life_context` proof confirmed the three loaded Google
provider accounts are enumerated for Calendar, Tasks, Drive, and Docs, while
the canonical Master Ops and LifeOps Sheets remain routed to
`jshah1331@gmail.com`. This is account-routing evidence, not proof that every
historical item in every provider has been indexed.

`property_evidence` is likewise limited to explicitly captured append-only
observations; an empty collection means property evidence has not yet been
captured, not that the property has been surveyed and found empty.

`coverage_report` is the companion freshness contract. It joins the source
registry policy with per-account provider/capture status and the local Gmail
normalization/index checkpoints. `status=ready` means Inbox has a current
readability proof for the observed account/source; it does not mean the remote
provider has been exhaustively compared with the local index. Planned or
blocked sources remain explicit in `completeness.reasons`.

The index's `last_success_at` is deliberately a commit timestamp: starting a
sync or updating progress does not advance it, and an error preserves the last
successful value. A source that has only a running or failed attempt therefore
remains stale/unverified instead of appearing fresh because work began.

Document bodies are intentionally not bulk-loaded into `life_context`.
`document_evidence` is the explicit follow-up path when a metadata item is
relevant. It returns only the requested bounded prefix and records whether the
body was truncated.

The local message index is the fast retrieval layer, not a second authority.
Inbox preserves raw observations and provider identifiers; SQLite FTS5 provides
immediate exact search, and a resumable local BGE embedding build adds semantic
ranking without sending message bodies to an external embedding service. Use
`search_indexed_messages` in keyword mode even while embeddings are building.
Semantic and hybrid modes report progress and fall back to keyword results if
the local model is unavailable.

Provider index syncs now trigger a bounded local embedding refresh as a best-effort
follow-up. The background scheduler performs this after its periodic incremental
sync, and the manual bootstrap/incremental endpoints do the same. This keeps new
messages searchable without making provider capture depend on the optional model;
if the model is unavailable, the response reports `embedding_error` and keyword
search remains usable.

From the Inbox checkout, build the derived vectors explicitly when bootstrapping
or catching up a large backlog:

```bash
uv run python scripts/build_message_embeddings.py --batch-size 8
```

The builder is resumable and does not run inside server startup. It writes only
derived vectors to `.inbox_index.sqlite3`; rerunning it fills new or changed
items. Routine syncs process a bounded batch so the server stays responsive;
completion is proved only when `embedding_status` reports `pending: 0` for the
configured model.

When `life_context` reports `embedding_index.pending: 0`, semantic retrieval is
complete for the current indexed item set at that model checkpoint. A later
provider sync can create new pending work; callers must use the returned status
and checked-at timestamp rather than assuming permanent completeness.

## Authority and agent runtimes

Google Drive, Docs, and Sheets remain the source systems. Inbox is the single
personal-data gateway and LifeOps is the single governed MCP surface. ChatGPT's
native Google Drive app may be used as a convenience UI, but it is not a second
LifeOps database or an alternative writer. Pi, DeepSeek, and OpenClaw should use
the local stdio transport; ChatGPT Business should use the HTTP transport. A
CLI such as `gog` is an adapter or diagnostic fallback only, not a parallel
credential or data authority.

For worker runtimes, use `scripts/run_lifeops_mcp_v0_worker_stdio.sh`. Its MCP
catalog contains only `evidence_packet` and `system_audit`; the packet itself
uses the same Inbox-backed read models but cannot expose provider writes,
secrets, notes, document metadata, or terminal control. DeepSeek Harness can
consume `docs/lifeops-mcp-v0-deepseek-worker.cordis.yml` through its generic
stdio MCP client, and Hermes can
register the same launcher as a separate MCP server. A worker connection is
proven only after its client completes MCP initialization and lists exactly
those two tools.

The same restricted launcher is registered as `lifeops-worker` in the checked-in
`.mcp.json` and `.cursor/mcp.json` examples. Pi also has a project-local
`.pi/mcp.json` override: it disables the broader `inbox` and `inbox-readonly`
entries and exposes only `evidence_packet` and `system_audit` directly from
`lifeops-worker`. This makes the safe context surface available to Pi after
installing `pi-mcp-adapter` without allowing Pi to fall back to the older
write-capable Inbox entry. The shared files remain available to other clients;
the Pi override does not modify them.
Before starting that restricted launcher, set
`LIFEOPS_WORKER_ACCOUNT_ALLOWLIST` to a comma-separated list of exact account
identities. The worker rejects an omitted or empty account scope rather than
silently exposing all observed mailboxes; each packet call must name one
allowlisted account. This account selector scopes provider reads wherever the
underlying source supports account routing. It does not split the canonical
local personal graph: Apple Contacts, approved identity links, local memory,
and explicitly captured property observations are user-scoped by design and
are labeled that way in the packet contract.

Hermes has a separate `lifeops_v0_readonly` entry that starts
`scripts/run_lifeops_mcp_v0_stdio.sh` with `LIFEOPS_MCP_PROFILE=read_only`.
That entry is the canonical Hermes read surface and currently discovers 43
annotation-approved read tools. The older `lifeops_readonly` entry and the
two-tool `lifeops_v0_worker` entry remain available for rollback and worker
compatibility; they are not proof that the older broad surface has been
retired. A Hermes MCP test proves initialization and tool discovery only; it
does not perform provider reads or grant approval authority.

Antigravity has the same restricted launcher registered through its native
`agy mcp` registry with the same account allowlist. Its registry and tool-schema
discovery are confirmed, but a headless `agy --print` invocation still requires
an interactive MCP permission grant; a denied headless call is not counted as a
LifeOps tool-call proof. Do not use `--dangerously-skip-permissions` as the
normal operating mode. A live Agy call remains an explicit follow-up proof,
not an assumed capability.

Orca now tracks this v0 checkout as a worktree, and an Orca-managed Pi
terminal has completed a bounded `lifeops-worker_evidence_packet` call for an
allowlisted account. The returned packet was `lifeops.evidence_packet.v1`,
`read_only=true`, with provider writes, worker control, secret access, and raw
event mutation all false. This proves Orca/Pi read consumption only; it does
not grant Orca execution, filesystem, provider-write, or Bridge-delivery
authority.

The worker MCP boundary is not an operating-system sandbox. Pi, Agy, and other
host runtimes retain their own local tools and process permissions. A worker
cannot use MCP to call an Inbox write or retrieve the Inbox token, but a host
agent with shell access could still inspect its own runtime environment. Use a
separate OS/container sandbox if a worker must be treated as hostile or
untrusted; do not claim that MCP registration alone provides that isolation.

On 2026-08-26, three consecutive bounded live `life_context` calls for an
allowlisted account completed with `lifeops.context.v1`, `read_only=true`,
and no unavailable-source limitations after the concurrency/retry hardening.
The standard-library read-surface verifier also passed against the running
HTTP endpoint. This proves local runtime reliability for the bounded read
slice, not completeness of every provider or a ChatGPT UI action.

The repeatable `scripts/verify_lifeops_worker_stdio.py` check performs the
same contract proof over the local worker transport: it requires the exact
two-tool set (`evidence_packet` and `system_audit`), read-only annotations,
the `2025-06-18` handshake, and a bounded account-scoped packet whose
provider-write, worker-control, secret-access, and raw-event-mutation flags
are all false. On 2026-08-26 it passed against the active worker launcher.

The checked-in `.mcp.json` and `.cursor/mcp.json` now provide a named
`lifeops-readonly` entry using the annotation-derived profile; the existing
worker entry remains the narrower two-tool contract. OpenClaw's `lifeops_v0`
entry is likewise started with `LIFEOPS_MCP_PROFILE=read_only` and its
client-side list covers the complete read catalog. Older `inbox_full`,
approval-capable Inbox, and legacy LifeOps entries remain present until their
replacement paths are separately proven and deliberately retired. The full
`scripts/run_lifeops_mcp_v0_stdio.sh` launcher remains available for the
approved LifeOps cockpit. Client-side allowlists must still exclude write
tools unless that client is the approved cockpit.

Run `scripts/verify_lifeops_profile_stdio.py` to prove the read-only profile
over stdio without calling a source-read tool. It requires the core context,
search, evidence, system-audit, and triage tools, rejects all proposal,
approval, capture, and execute tools, and requires a read-only annotation on
every discovered tool.

`task_duplicate_review` is a narrower read-only view over the task
reconciliation report. It returns deterministic review IDs, preserves the
source task IDs and accounts, labels exact-title versus conservative
near-duplicate groups, and explicitly never deletes, merges, or edits a task.

### Lindy, Gemini Spark, and Workspace Studio

These products fit behind LifeOps rather than beside it:

- Lindy is a cloud workflow and agent runtime. Its Gmail and Google Calendar
  integrations can read and write, and its HTTP/webhook actions can reach
  arbitrary APIs. It should therefore receive only a brokered, typed adapter
  with scoped capabilities. Never give a Lindy workflow the Inbox bearer token
  or a generic Inbox REST proxy.
- Gemini Spark is Google's personal/Workspace agent surface. Google Workspace
  Studio is the separate flow-builder surface for Workspace-native automation.
  They can be useful for Gmail/Drive/Calendar-local work, but their native
  actions must not become a second LifeOps task or commitment authority.
- If Spark, Workspace Studio, or Lindy discovers a personal action that spans
  email, messages, contacts, calendar, and travel, the durable path is:
  observation -> LifeOps evidence -> deduplicated proposal -> approval ->
  provider execution -> read-back.
- Apple Calendar and Reminders remain delivery surfaces. They can provide
  device-native notifications for an approved canonical commitment, while
  LifeOps owns the cross-source reasoning and deduplication.

No Lindy or Google-agent adapter is currently configured in this checkout. The
safe next step is a typed broker that accepts signed observations and proposal
requests, not a generic webhook-to-REST bridge.

## Why writes are not direct

Inbox already has a stronger invariant than a generic confirmation dialog: each guarded action is approved through a single-use lease bound to the exact HTTP method, path, provider, operation, account/resource, item count, query hash, payload hash, and expiry.

The MCP layer preserves that sequence:

```text
propose -> pending approval -> explicit confirmation -> lease -> exact execution -> read-back verification
```

`execute_approved_action` performs the read-back automatically and returns both
`verified` and a structured `verification` receipt. The receipt is currently
bounded to Google Task creation, Calendar event updates, and local person notes
or relationship claims. Calendar verification compares timestamps by instant;
task creation requires one exact match on title, notes, and due time; person
records are matched by the identifier returned by the local write. A successful
HTTP response without a matching read-back is not treated as completion.
`verify_approved_action` can repeat the read-only check when a provider is
eventually consistent.

Do not add a generic `request(method, path, body)` tool and do not bypass the Inbox approval middleware.

## Local startup

Checkout the branch and install the existing project dependencies:

```bash
git checkout lifeops-mcp-v0
uv sync
```

Use a strong existing Inbox token or generate a new random one. Never commit it:

```bash
export INBOX_SERVER_TOKEN='<strong-random-token>'
```

Start both local services:

```bash
bash scripts/run_lifeops_mcp_v0.sh
```

Defaults:

- Inbox REST: `http://127.0.0.1:9849`
- LifeOps MCP: `http://127.0.0.1:9850/mcp`
- automatic departure-task creation: OFF during validation

The MCP process binds only to loopback. The tunnel is the only intended remote ingress.

## ChatGPT Business connection — preferred

ChatGPT cannot connect directly to localhost. For the actual Business connection, use OpenAI Secure MCP Tunnel so the MCP server stays private rather than placing it directly on the public internet.

In ChatGPT Business on web:

1. As a workspace admin/owner, open Workspace Settings -> Apps -> Create and enable Developer Mode for yourself if needed.
2. Choose the private/local MCP connection flow and Secure MCP Tunnel.
3. Point the tunnel's local target at `http://127.0.0.1:9850/mcp`.
4. Let ChatGPT scan the tools.
5. Keep the app in developer/draft mode while the tool surface is changing.
6. Test the acceptance sequence below before publishing it to the workspace.

Follow the current Secure MCP Tunnel instructions presented by ChatGPT/OpenAI for the tunnel client rather than copying a stale tunnel command into this repository.

## ngrok — useful dev path, not the default trust boundary

For a quick network/MCP smoke test, ngrok can forward an HTTPS endpoint to the local MCP port:

```bash
brew install ngrok
ngrok config add-authtoken '<YOUR_NGROK_AUTHTOKEN>'
ngrok http 9850
```

That produces a public HTTPS endpoint whose MCP URL is approximately:

```text
https://<assigned-host>/mcp
```

Important: **do not connect a bare public ngrok endpoint to personal-data/write tools.** `INBOX_SERVER_TOKEN` protects LifeOps -> Inbox; it does not authenticate Internet -> LifeOps MCP. If ngrok is used beyond a disposable smoke test, add a ChatGPT-compatible MCP authentication layer or verified edge policy first. For the normal ChatGPT Business setup, prefer Secure MCP Tunnel.

## First acceptance test: Street play practice

Do not broaden the connector until this works end to end.

1. `source_health()` shows iMessage/Calendar/Tasks usable; `current_location()` is available (or an explicit origin is supplied), and `travel_time()` succeeds before any write is proposed.
2. Search for `street play practice`, `45738 Bridgeport`, or the relevant contact; retrieve the source messages with `message_thread` as evidence.
3. Read the event date and identify the exact `Street play practice` event with `calendar_event`.
4. Read `current_location` and use `multi_stop_route` for the known legs, including pickup and practice destination.
5. Propose updating the exact Calendar event location to the evidence-backed practice address.
6. Show the exact proposed change to the user. Do not approve it implicitly.
7. After explicit user approval, approve and execute the recorded action.
8. Re-read the exact event with `calendar_event` and verify the location changed.
9. Run `departure_times` and verify a sensible leave time can now be produced.

If `current_location()` reports `available: false`, grant Location Services to
the launch process or configure `INBOX_HOME_ADDRESS` in the owner-only Inbox
runtime environment. The current Mac setup has that fallback configured from
the verified local Home contact record; it remains a read-only origin for
travel calculations and is not written back to Contacts. If `travel_time()` returns
502, the Maps key is present but not authorized for the Distance Matrix API;
fix that provider permission before treating departure calculations as proved.

A later `prepare_travel` tool may compose these primitives once the behavior is proven. Do not build it first.

## Expansion rule

Add a new MCP write tool only when a real workflow is blocked without it. The next likely candidates are:

- complete/update Google Task
- draft/send or reply to a message
- local notification / Apple Shortcut invocation
- GitHub actions

Each must map to a typed Inbox capability and preserve the same propose/approve/execute/verify discipline where consequences warrant it.

## Non-goals for v0

- no generic shell
- no unrestricted filesystem access
- no arbitrary REST proxy
- no automatic deletion
- no direct messaging writes
- no World Monitor integration
- no Perplexity UI automation
- no Postgres migration
- no new user interface

Those are backlog items, not prerequisites for proving the cockpit.
