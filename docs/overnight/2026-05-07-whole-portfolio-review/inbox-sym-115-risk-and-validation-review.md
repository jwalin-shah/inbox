# inbox-sym-115 risk and validation review

Queue item: `inbox-sym-115-risk-and-validation-review`
Branch: `codex/goal-inbox-sym-115-risk-and-validation-review`
Review date: 2026-05-07
Starting HEAD: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`

## Scope and validation

This was a repo-local, read-only risk and validation review. Product code was not edited. External services, deploys, pushes, PRs, and tracker updates were not used.

Required validation command:

```bash
git status --short
```

Agent-safe validation commands documented by the repo:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe
uv run ruff check .
uv run pyright
```

Prior overnight and CI artifacts checked:

```bash
rg --files -g '.github/**' -g 'docs/overnight/**' -g 'runs/**' -g 'items/**' -g '*handoff*' -g '*result.json'
rg --files docs runs .github items
```

Result: no previous `docs/overnight`, `runs`, `items`, or `.github` artifacts were present in this worktree. The second command reported missing `runs`, `.github`, and `items` directories and only found `docs/TESTING_FOR_AGENTS.md`.

## Concrete observations

1. `README.md:31-34` says Python 3.10+ is required, but `pyproject.toml:5` requires `>=3.12,<3.15`. This can send agents or setup scripts down the wrong interpreter path.

2. `pyproject.toml:53-61` configures pytest with coverage and registers `safe`, `integration`, `local_data`, `slow`, and `live_write` markers, while `docs/TESTING_FOR_AGENTS.md:9-13` tells agents to run `INBOX_TEST_MODE=1 uv run pytest -m safe`, ruff, and pyright.

3. Only `tests/test_mcp_gateway.py:18` and `tests/test_inbox_test_mode.py:8` are marked `pytest.mark.safe`, while `rg --files tests | wc -l` reports 31 test files. Many deterministic mocked tests are outside the documented safe loop.

4. `tests/conftest.py` stubs heavy ML and hardware modules such as `mlx_lm`, `mlx_whisper`, `sounddevice`, `Quartz`, and `outlines`, making broader local tests viable without real devices or ML installs.

5. `inbox_test_mode.py:22-24` blocks live writes when `INBOX_TEST_MODE` is enabled, and `services.py:114-119` centralizes the service-level hook. Write guards are present across many service functions, including Google Tasks at `services.py:3172-3221`.

6. `tests/test_services.py:934-950` verifies `INBOX_TEST_MODE` blocks extended live writes for Google Tasks, Drive, Sheets, Docs, GitHub notifications, desktop notifications, and WhatsApp. That coverage is useful but is not in the current `-m safe` loop.

7. `inbox_server.py:1313-1340` implements optional private API token auth. If `INBOX_SERVER_TOKEN` is unset, `_is_authorized` returns true for all paths, including write endpoints. Many endpoint fixtures explicitly clear the token, for example `tests/test_server.py:52-55` and `tests/test_gmail_actions.py:18-21`.

8. `.mcp.json:10-24` points both full and read-only local MCP entries at `http://127.0.0.1:9849`. `CLAUDE.md:73-76` and `MCP_SETUP.md:94-103` warn that dev worktrees must verify both `cwd` and `INBOX_SERVER_URL` or they can silently hit the primary instance.

9. `mcp_backend.py:19-27` correctly forwards `INBOX_SERVER_TOKEN` to the private backend when it is configured, and `mcp_gateway.py:36-58` protects public MCP routes with `INBOX_MCP_TOKEN` while leaving `/health` open.

10. `tools_registry.py:52-101` adds `confirm=True` gating at the MCP handler layer before dispatching to the backend. This protects MCP calls, but direct FastAPI clients can still call write endpoints with only API auth.

11. `tools_registry.py:415-480` exposes Google Task create/update/delete as confirmation-gated MCP tools, and `inbox_server.py:2028-2055` exposes the corresponding HTTP write endpoints. There is no visible server-side preflight requirement on these direct endpoints.

12. `inbox_server.py:2906-3020` provides a `GET /preflight/google-write` endpoint, and `tests/test_server.py:1521-1612` covers default account resolution plus valid/invalid folder and task-list destinations. The preflight layer exists, but write endpoints do not appear to require a recent preflight result.

13. `message_index_store.py:80-120` creates the local index with WAL mode, `sync_state`, and unique `(source, account, external_id)` items. `message_sync.py:181-269` records Gmail bootstrap progress, page tokens, errors, and final history/timestamp checkpoints.

14. `tests/test_message_sync.py:143-232` covers resumable Gmail bootstrap and history cursor recording. `tests/test_message_index_store.py:269-298` covers sync-state status and metadata persistence. These are high-value risk tests but are currently unmarked for the safe loop.

15. `inbox_server.py:3739-3853` has index-first needs-action and index sync/status endpoints. `tests/test_server.py:1816-1935` asserts `/inbox/needs-action` does not fall back to live Gmail when the index is empty, but task and calendar failures are swallowed at `inbox_server.py:3773-3793`, making operational failures easy to miss.

16. `DOCS_INDEX.md` states `uv run pytest` has "736 pass" and "All 736 tests pass", but the review did not find a current CI artifact or prior overnight report proving that claim in this checkout.

## Primary risks and blockers

1. The documented safe validation loop is too narrow. It currently exercises only two safe-marked test files, leaving mocked server, service, sync, and index tests outside the command agents are told to run.

2. Token/auth behavior is under-specified for test and deployment. The private API intentionally becomes open when `INBOX_SERVER_TOKEN` is unset, but write endpoints are large in number and endpoint fixtures often clear the token. That is acceptable for local development only if deployment scripts and tests make the boundary explicit.

3. Write safety is split across MCP confirmation, optional API auth, service-level test-mode guards, and an advisory preflight endpoint. There is no single server-side contract proving that direct HTTP writes are preflighted or mapped to clear blocked-write errors under `INBOX_TEST_MODE`.

4. Dev worktree routing can hit the primary inbox. The docs call this out, but `.mcp.json` hardcodes port 9849 and there is no automated check that the MCP backend URL matches the active worktree intent.

5. Documentation has stale or conflicting claims: Python 3.10+ vs `pyproject.toml` requiring 3.12+, a test-count pass claim without current local evidence, and an older MCP v1 plan that no longer matches the broader registry write surface.

6. CI evidence is missing in this worktree. No `.github` workflow or prior `runs/*/result.json` / `handoff.md` files were available locally, so the next work wave should not assume remote validation exists.

No stop condition was hit. The main blocker is evidence quality: before launching broad implementation work, make the agent-safe validation lane representative enough to catch regressions.

## Implementation-ready follow-up tasks

### 1. Expand the safe test marker set

Owned files:
- `tests/test_server.py`
- `tests/test_server_endpoints.py`
- `tests/test_services.py`
- `tests/test_message_sync.py`
- `tests/test_message_index_store.py`
- `tests/test_api_contract.py`
- `tests/test_conversations_latency.py`
- `pyproject.toml` only if marker descriptions need tightening

Acceptance criteria:
- Deterministic, mocked tests that do not touch live local data or external writes are marked `safe`.
- Tests requiring local macOS data, live provider data, or externally visible writes are explicitly marked `local_data`, `integration`, or `live_write`.
- `INBOX_TEST_MODE=1 uv run pytest -m safe --collect-only -q` includes server, service write-guard, sync, index, and API contract tests, not only MCP/test-mode tests.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe --collect-only -q
INBOX_TEST_MODE=1 uv run pytest -m safe tests/test_inbox_test_mode.py tests/test_mcp_gateway.py tests/test_api_contract.py -q
```

### 2. Add private API auth contract tests

Owned files:
- `tests/test_server_auth.py` or `tests/test_server.py`
- `inbox_server.py` only if behavior needs correction

Acceptance criteria:
- With `INBOX_SERVER_TOKEN` set, missing and invalid credentials return 401 for at least one read endpoint and one write endpoint.
- Valid `Authorization: Bearer ...` and `x-api-key` both work.
- The test documents whether `/health` should require the private token when auth is enabled, then locks that behavior.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_server_auth.py -q
```

### 3. Make direct HTTP write blocking explicit under test mode

Owned files:
- `tests/test_server_write_guards.py` or `tests/test_server.py`
- `inbox_server.py`
- `services.py` only if a missing guard is found

Acceptance criteria:
- Representative direct HTTP writes for Gmail, Reminders, Google Tasks, Drive, Docs, Sheets, GitHub notification read, and desktop notification are covered with `INBOX_TEST_MODE=1`.
- A blocked write returns a clear 4xx response instead of an unstructured 500.
- The tests use fake services that would fail if the service-level guard did not run.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_server_write_guards.py -q
```

### 4. Reconcile stale docs and validation claims

Owned files:
- `README.md`
- `DOCS_INDEX.md`
- `MCP_V1_PLAN.md`
- `docs/TESTING_FOR_AGENTS.md`

Acceptance criteria:
- README Python requirement matches `pyproject.toml`.
- Unverified fixed test-count claims are removed or replaced with the exact command used to generate them.
- MCP docs distinguish current registry behavior from historical v1 scope.
- Agent testing docs explain that `-m safe` is the default deterministic lane and that live provider tests require opt-in.

Smallest useful validation:

```bash
rg "Python 3.10|736 pass|All 736 tests pass|deletes stay out of scope" README.md DOCS_INDEX.md MCP_V1_PLAN.md docs/TESTING_FOR_AGENTS.md
git diff --check
```

### 5. Add a worktree routing self-check for MCP/dev use

Owned files:
- `mcp_backend.py`
- `mcp_gateway.py`
- `MCP_SETUP.md`
- `.mcp.json` or `config/codex.inbox.example.toml` if examples are updated
- `tests/test_mcp_gateway.py`

Acceptance criteria:
- A local health or diagnostic path reports the effective backend URL and whether backend auth is enabled without exposing tokens.
- Tests cover `INBOX_SERVER_URL` override behavior so worktree clients can prove they are not hitting primary port 9849 by accident.
- Docs tell agents to run the self-check before exercising a dev worktree.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_mcp_gateway.py -q
```
