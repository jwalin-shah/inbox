# inbox-sym-117 Risk And Validation Review

Queue item: `inbox-sym-117-risk-and-validation-review`
Branch: `codex/goal-inbox-sym-117-risk-and-validation-review`
Review date: 2026-05-07
HEAD reviewed: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`

## Scope

This is a read-only risk and validation review for the `inbox-sym-117` repo. No product code was edited. External services, deploys, pushes, PR creation, destructive cleanup, and tracker updates were treated as out of scope.

Repo-local previous overnight outputs were checked with `fd -H -t f 'overnight|handoff|result\.json|CODEX_WORKPAD|ISSUE|runs' .`; no prior overnight reports, handoffs, or run result files were present in this worktree before this report.

Current git state at the start of review was clean on `codex/goal-inbox-sym-117-risk-and-validation-review`.

## Concrete File Evidence

1. `CLAUDE.md:3-13` defines Inbox as a local Python/Textual/FastAPI personal-data app and documents `INBOX_SERVER_PORT`/`INBOX_SERVER_URL`; this makes wrong-port validation a real risk because the daily driver defaults to port `9849`.
2. `CLAUDE.md:53-76` explicitly warns that macOS data paths are shared across worktrees and that an MCP client pointed at `9849` can appear to work while reading primary data instead of a dev worktree.
3. `docs/TESTING_FOR_AGENTS.md:7-13` declares the agent-safe loop as `INBOX_TEST_MODE=1 uv run pytest -m safe`, `uv run ruff check .`, and `uv run pyright`.
4. `pyproject.toml:53-62` registers pytest markers and coverage defaults, but only `tests/test_inbox_test_mode.py:8` and `tests/test_mcp_gateway.py:18` currently apply the `safe` marker. A grep count found 864 test functions and only two `safe` marker sites.
5. `tests/conftest.py:15-35` stubs ML and hardware dependencies such as `mlx_lm`, `mlx_whisper`, `sounddevice`, `outlines`, and `Quartz`, so many deterministic tests appear eligible for safe marking after review.
6. `inbox_test_mode.py:18-24` implements `INBOX_TEST_MODE` and `assert_live_writes_allowed`; `services.py:114-119` wires service mutations through that helper.
7. `services.py:420-4455`, `services.py:5511`, and `services.py:6270` show broad live-write guards for Google auth, Gmail, iMessage, Calendar, Reminders, Tasks, Drive, Sheets, Docs, GitHub notifications, desktop notifications, WhatsApp, and calendar attendee mutation.
8. `services.py:5429-5480`, `services.py:5560-5584`, and `services.py:6090-6118` write notification, favorite, and voice config files under `~/.config/inbox` outside test mode; `tests/test_inbox_test_mode.py:29-46` verifies these paths move under `INBOX_TEST_DATA_DIR` only when services is imported in test mode.
9. `inbox_server.py:1313-1340` requires `INBOX_SERVER_TOKEN` only when that env var is set; `tests/test_server.py:371-410` covers unset, bearer, and `X-API-Key` behavior.
10. `mcp_gateway.py:32-45` and `mcp_gateway.py:48-58` allow all non-health HTTP MCP requests when `INBOX_MCP_TOKEN` is unset; `tests/test_mcp_gateway.py:36-53` tests rejection only when the token is configured.
11. `MCP_SETUP.md:252-313` says the backend should never be internet-facing, MCP should be exposed instead of the raw API, and remote MCP should require `INBOX_MCP_TOKEN`; `scripts/run_inbox_mcp_http.sh:1-9` and `scripts/run_inbox_mcp_http_readonly.sh:1-9` start HTTP MCP without checking that token.
12. `.pre-commit-config.yaml:1-23` covers Ruff, formatting, basic file hygiene, private-key detection, and Bandit; no `.github/workflows` directory or other CI workflow file exists in this worktree.
13. `.factory/services.yaml:1-16` defines local install, test, typecheck, lint, format, and an inbox server healthcheck; its test command excludes audio and LLM tests but does not use `INBOX_TEST_MODE=1`.
14. `README.md:31-34` claims Python `3.10+`, while `pyproject.toml:5` requires `>=3.12,<3.15`; this is a stale setup claim that can send workers into the wrong interpreter.
15. `batch/batch-runner.sh:56-65` initializes state and auth headers, `batch/batch-runner.sh:74-80` constructs a JSON payload with shell interpolation, and `batch/batch-runner.sh:92-101` updates a shared state TSV without locking while `batch/batch-runner.sh:135-160` can run workers in parallel.
16. `message_sync.py:638-655` exposes local index bootstrap, incremental, rebuild, and summary CLI modes; `inbox_server.py:3844-3853` exposes bootstrap and incremental sync as API POST endpoints.

## Risks And Blockers

1. Safe validation is too narrow. The documented agent-safe command currently covers only the safe-marked files, while high-value deterministic tests for server auth, preflight, index health, message sync, client routing, and live-write blocking are unmarked. This can let risky changes pass the default overnight loop.
2. There is no repo CI workflow. Local commands are documented, pre-commit exists, and `.factory/services.yaml` has useful commands, but there is no checked-in workflow proving that the safe loop, lint, and typecheck run on PRs.
3. HTTP MCP auth is fail-open when `INBOX_MCP_TOKEN` is absent. The server binds to loopback in `mcp_server.py` and `inbox_mcp_readonly.py`, and deployment docs say to use env files, but the runtime middleware and scripts do not fail closed. A misconfigured service can expose tools unauthenticated behind whatever reverse proxy is in front of it.
4. Worktree routing remains fragile. The docs correctly warn about primary-vs-dev confusion, but there is no validation command that proves `cwd`, `INBOX_SERVER_URL`, server port, and MCP backend routing all point at the intended worktree before testing mutations.
5. Batch archive parallelism can corrupt local state. Parallel workers update `batch/archive-state.tsv` with a read-rewrite-move sequence and no lock, even though `.gitignore:45-49` reserves a batch lock file path. The curl JSON is also shell-built from TSV values.
6. Setup docs are stale around Python version and test safety. README's Python requirement and unqualified `uv run pytest` recommendation conflict with pyproject and agent-safe testing guidance.
7. Index sync endpoints can read large live personal data sources and mutate the local `.inbox_index.sqlite3` state. They are valid product functionality, but they should not be part of default agent validation unless a test-data DB or explicit local-data opt-in is present.
8. External/live validation is intentionally blocked for this review. Gmail, Calendar, Drive, Docs, Sheets, Tasks, iMessage, Notes, Reminders, GitHub, microphone, notification, and OAuth paths require credentials or local personal data and should stay mocked or explicitly opted in.

## Exact Validation Commands

Required queue validation:

```bash
git status --short
```

Agent-safe default loop from repo docs:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe
uv run ruff check .
uv run pyright
```

Useful focused validations for the follow-up tasks below:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py tests/test_mcp_gateway.py -q
INBOX_TEST_MODE=1 uv run pytest tests/test_server.py::TestAuth tests/test_server.py::TestPreflight -q
INBOX_TEST_MODE=1 uv run pytest tests/test_message_sync.py tests/test_message_index_store.py -q
bash -n batch/batch-runner.sh
uv run ruff check .
uv run pyright
```

## Implementation-Ready Follow-Up Tasks

### 1. Expand The Safe Test Marker Set

Owned files:
- `tests/test_message_sync.py`
- `tests/test_message_index_store.py`
- `tests/test_server.py`
- `tests/test_services.py`
- `tests/test_client.py`
- `docs/TESTING_FOR_AGENTS.md`

Acceptance criteria:
- Deterministic tests that use mocks/temp paths and do not touch live personal data are marked `safe`.
- `INBOX_TEST_MODE=1 uv run pytest -m safe -q` exercises server auth, Google preflight, index health, message sync checkpointing, client auth headers, and representative live-write blocking.
- Tests that require local user stores, OAuth, provider APIs, microphone input, or visible writes remain unmarked or explicitly marked `local_data`, `integration`, `slow`, or `live_write`.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe tests/test_inbox_test_mode.py tests/test_mcp_gateway.py tests/test_server.py tests/test_message_sync.py tests/test_message_index_store.py tests/test_services.py tests/test_client.py -q
```

### 2. Add Checked-In CI For The Agent-Safe Loop

Owned files:
- `.github/workflows/ci.yml`
- `.factory/services.yaml`
- `docs/TESTING_FOR_AGENTS.md`

Acceptance criteria:
- CI installs with `uv sync --group dev` or the repo's accepted equivalent.
- CI runs `INBOX_TEST_MODE=1 uv run pytest -m safe`, `uv run ruff check .`, and `uv run pyright`.
- `.factory/services.yaml` uses the same safe test command as agent docs, or explicitly distinguishes "safe" from "broader local" test commands.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe -q
uv run ruff check .
uv run pyright
```

### 3. Fail Closed For HTTP MCP When Token Is Missing

Owned files:
- `mcp_gateway.py`
- `mcp_server.py`
- `inbox_mcp_readonly.py`
- `scripts/run_inbox_mcp_http.sh`
- `scripts/run_inbox_mcp_http_readonly.sh`
- `tests/test_mcp_gateway.py`
- `MCP_SETUP.md`

Acceptance criteria:
- HTTP MCP startup fails or refuses `/mcp` when `INBOX_MCP_TOKEN` is unset, unless an explicit local-development override is set.
- `/health` still reports whether auth is enabled without exposing protected tools.
- Stdio MCP behavior remains unchanged for trusted local clients.
- Tests cover missing token, invalid token, valid token, `/health`, and the local override path.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_mcp_gateway.py -q
bash -n scripts/run_inbox_mcp_http.sh scripts/run_inbox_mcp_http_readonly.sh
```

### 4. Harden Batch Archive State And Payload Handling

Owned files:
- `batch/batch-runner.sh`
- `tests/test_batch_runner.py` or a new focused shell-test wrapper under `tests/`
- `.gitignore`

Acceptance criteria:
- Parallel batch workers serialize updates to `batch/archive-state.tsv` using `batch/.batch-state.lock` or an equivalent lock.
- JSON request payloads are built with a proper encoder instead of raw shell interpolation.
- Thread IDs and source values are validated before use in log filenames, TSV writes, and curl payloads.
- `--dry-run` remains read-only and does not create or mutate state beyond any explicitly documented temp setup.

Smallest useful validation:

```bash
bash -n batch/batch-runner.sh
INBOX_TEST_MODE=1 uv run pytest tests/test_batch_runner.py -q
```

### 5. Align Setup Docs With Runtime And Safe Validation

Owned files:
- `README.md`
- `CLAUDE.md`
- `DOCS_INDEX.md`
- `docs/TESTING_FOR_AGENTS.md`
- `pyproject.toml`

Acceptance criteria:
- Python version guidance consistently says `>=3.12,<3.15` or the project intentionally lowers `pyproject.toml`.
- README development commands distinguish safe agent validation from full local validation.
- Docs consistently mention `INBOX_TEST_MODE=1` for agent-run tests and reserve live/local-data verification for explicit opt-in.
- `pyproject.toml` project metadata no longer has placeholder description text.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py -q
uv run ruff check README.md CLAUDE.md DOCS_INDEX.md docs/TESTING_FOR_AGENTS.md pyproject.toml
```

## Handoff Notes

- Report file written: `docs/overnight/2026-05-07-whole-portfolio-review/inbox-sym-117-risk-and-validation-review.md`
- Product code edited: no
- External trackers updated: no
- PR created: no
- Known blockers: live/provider validation requires credentials, local personal data, or explicit approval; this review stayed inside repo-local evidence and the queue validation command.
