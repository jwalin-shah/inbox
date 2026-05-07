# inbox-sym-119 risk and validation review

Date: 2026-05-07
Branch: `codex/goal-inbox-sym-119-risk-and-validation-review`
Base HEAD observed: `2805b84 Merge pull request #34 from jwalin-shah/codex/SYM-9-indexed-defaults`
Review type: `risk-and-validation-review`

## Scope and commands

This review stayed inside this repo and did not edit product code. The only intended change is this report.

Evidence commands run:
- `llm-tldr tree .`
- `git status --short --branch`
- `git log -1 --oneline`
- `rg --files docs`
- `rg --files . | rg '^\.github/'`
- `rg --files . | rg '^runs/'`
- `rg --files . | rg '^docs/overnight/'`
- `rg -n "pytestmark = pytest.mark.safe|@pytest.mark.safe|@pytest.mark.live_write|@pytest.mark.local_data|@pytest.mark.integration|@pytest.mark.slow" tests pyproject.toml docs/TESTING_FOR_AGENTS.md`
- `rg -n "def drive_upload|def sheets_format|def sheets_rename|def sheets_copy|def docs_.*text|def docs_append|def docs_insert|def docs_create|def docs_delete|def drive_create_folder|def drive_delete|def sheets_add_sheet|def sheets_delete_sheet" services.py`
- `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe --collect-only -q`

Queue validation command:
- `git status --short`

The safe pytest collection could not run in this sandbox because `uv` needed to download `rpds-py==0.30.0` and DNS/network access is unavailable. Running without `UV_CACHE_DIR=/tmp/uv-cache` also hit a sandbox permission error on `~/.cache/uv`; the service scripts already set `UV_CACHE_DIR` to `/tmp/uv-cache`, but `dev.sh` and docs commands do not.

## Concrete observations

1. `pyproject.toml:5` requires Python `>=3.12,<3.15`, and `.python-version:1` pins `3.12`; `README.md:32` still says Python 3.10+, so setup guidance can create an unsupported environment.

2. `docs/TESTING_FOR_AGENTS.md:10-12` defines the agent-safe loop as `INBOX_TEST_MODE=1 uv run pytest -m safe`, `uv run ruff check .`, and `uv run pyright`; `pyproject.toml:54-61` registers markers and adds coverage to every pytest run.

3. Only `tests/test_inbox_test_mode.py:8` and `tests/test_mcp_gateway.py:18` set `pytestmark = pytest.mark.safe`, based on repo search. Most service/server tests are unmarked, so `pytest -m safe` exercises only a small slice of the actual risk surface.

4. `inbox_test_mode.py:22-24` blocks live writes by raising `LiveWriteBlocked` when `INBOX_TEST_MODE` is enabled. `services.py:114-119` centralizes the service-side wrapper, and many write helpers call it.

5. Several external write helpers do not call the test-mode guard: `services.py:1769-1781` creates Gmail labels, `services.py:3864-3909` uploads files to Drive, `services.py:4315-4338` renames Sheets tabs, `services.py:4341-4355` sends raw Sheets `batchUpdate` formatting requests, `services.py:4358-4388` copies Sheets tabs, and `services.py:4476-4495` inserts text into Docs.

6. The HTTP endpoints route directly to those unguarded helpers: `inbox_server.py:2548-2574` handles `/drive/upload`, `inbox_server.py:2732-2758` handles Sheets tab rename/copy/format, `inbox_server.py:2978-2983` handles Docs text insertion, and `inbox_server.py:3586-3594` handles Gmail label creation.

7. `tests/test_services.py:909-951` already tests representative live-write blocking, but its coverage stops at `drive_create_folder`, `sheets_values_update`, and `docs_create`; it does not cover the missing-guard helpers above. `tests/test_drive.py:84-106` tests `drive_upload` success without checking `INBOX_TEST_MODE`.

8. `google_account_resolution.py:24-33` implements `INBOX_DEFAULT_GOOGLE_ACCOUNT` fallback, and `google_account_resolution.py:109-146` applies it to Sheets, Drive, Tasks, Docs, and Calendar service selection. Tests such as `tests/test_server.py:612-657` verify default account selection for calendar writes.

9. `CONNECTOR_ROADMAP.md:34-44` says Google writes should default to `jshah1331@gmail.com`, writes to other accounts must be explicit, and returned Google objects should include `owning_account`; `CONNECTOR_ROADMAP.md:231-240` also calls for preflight validation of destination, naming, and sharing.

10. The current preflight endpoint exists at `inbox_server.py:3009-3020`, backed by `google_account_resolution.py:160-238`, but its kind coverage is narrower than the write surface: docs, sheets, drive folders, tasks, and calendar events are modeled; uploads, Gmail labels, Sheets format/rename/copy, and Docs text mutation are not.

11. `inbox_server.py:1313-1340` protects the FastAPI backend with `INBOX_SERVER_TOKEN`, accepting Bearer and `X-API-Key`; `tests/test_server.py:376-410` covers missing, Bearer, and `X-API-Key` cases.

12. `mcp_gateway.py:32-58` protects public MCP routes with `INBOX_MCP_TOKEN` while allowing `/health`; `mcp_backend.py:19-27` forwards `INBOX_SERVER_TOKEN` to the backend. `tests/test_mcp_gateway.py:36-53` covers the public gateway auth path.

13. `scripts/run_inbox_backend.sh:7-9` and the MCP run scripts set `UV_CACHE_DIR=/tmp/uv-cache` before `uv run`, but `dev.sh:7-11` sets only port and URL before `uv run`. The docs commands in `README.md:155-157` and `docs/TESTING_FOR_AGENTS.md:10-12` omit the cache override.

14. No `.github/` workflow files are present in the worktree. `.pre-commit-config.yaml:1-23` provides local ruff, formatting, basic hooks, and bandit, but there is no checked-in CI evidence for the validation loop.

15. `SHEETS_CHANGELOG.md:38` and `SHEETS_CHANGELOG.md:114` claim "All 736 tests pass", but this review could not reproduce any pytest collection because dependency sync requires network access from a fresh sandbox.

16. `config/inbox.env.example:1-6` separates `INBOX_SERVER_TOKEN` and `INBOX_MCP_TOKEN`, which matches the backend/gateway split, but missing env propagation remains a known runtime risk because the MCP backend silently sends no Authorization header when `INBOX_SERVER_TOKEN` is unset.

## Key risks and blockers

Risk 1: Test mode is incomplete for live external writes.

The highest-impact finding is that several Google/Gmail/Drive/Docs/Sheets mutation helpers bypass `_assert_live_write_allowed`. This can let agent-safe tests or local probes touch real external resources if they call `drive_upload`, `gmail_label_create`, `sheets_rename_sheet`, `sheets_format`, `sheets_copy_to`, or `docs_insert_text` while live credentials are present.

Risk 2: The documented safe pytest loop is too narrow.

Only two test files are marked `safe`, so the default agent-safe command does not cover most server/service behavior. This creates false confidence, especially around personal-data integrations.

Risk 3: Fresh sandbox validation is blocked by dependency download and cache defaults.

`UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe --collect-only -q` failed because the environment cannot resolve PyPI. Running without `UV_CACHE_DIR` failed earlier due `~/.cache/uv` sandbox permissions. The run scripts mitigate this for services, but docs/dev commands do not.

Risk 4: Preflight exists but does not cover the full write surface.

`/preflight/google-write` models only a subset of write kinds. Raw Sheets formatting is explicitly documented as a flexible write surface, but it currently has neither test-mode guard nor preflight kind.

Risk 5: No CI workflow is checked in.

Local pre-commit exists, but there is no repository CI file proving ruff, pyright, and the safe pytest suite run outside a developer machine.

## Implementation-ready follow-up tasks

### 1. Close live-write guard gaps in service helpers

Owned files:
- `services.py`
- `tests/test_services.py`

Acceptance criteria:
- `gmail_label_create`, `drive_upload`, `sheets_rename_sheet`, `sheets_format`, `sheets_copy_to`, and `docs_insert_text` call `_assert_live_write_allowed(...)` before touching provider service objects.
- Add tests using `_WriteShouldNotRun` with `INBOX_TEST_MODE=1` that prove each helper raises `LiveWriteBlocked` before service access.
- Existing representative live-write tests still pass.

Smallest validation:
- `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_services.py::test_test_mode_blocks_extended_live_writes -q`

### 2. Make the safe marker set match the documented agent-safe loop

Owned files:
- `tests/test_services.py`
- `tests/test_server.py`
- `tests/test_gmail_actions.py`
- `tests/test_drive.py`
- `docs/TESTING_FOR_AGENTS.md`

Acceptance criteria:
- Mark deterministic, mocked tests for test-mode guards, auth middleware, account routing, and mocked Google write endpoints as `safe`.
- Do not mark local-data, live-write, microphone, OAuth, or provider-backed integration tests as `safe`.
- `pytest -m safe --collect-only -q` collects the guard/auth/account-routing tests, not only `test_inbox_test_mode.py` and `test_mcp_gateway.py`.

Smallest validation:
- `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe --collect-only -q`

### 3. Standardize sandbox-safe uv cache usage

Owned files:
- `dev.sh`
- `docs/TESTING_FOR_AGENTS.md`
- `README.md`
- `CLAUDE.md`

Acceptance criteria:
- `dev.sh` exports `UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"`, matching `scripts/run_inbox_backend.sh`.
- Agent testing docs and README validation commands either set `UV_CACHE_DIR=/tmp/uv-cache` inline or explain the requirement for sandboxed agents.
- README Python requirement is aligned with `pyproject.toml` and `.python-version`.

Smallest validation:
- `UV_CACHE_DIR=/tmp/uv-cache uv run python --version`
- `rg -n "Python 3.10|UV_CACHE_DIR" README.md docs/TESTING_FOR_AGENTS.md CLAUDE.md dev.sh`

### 4. Expand write preflight to the missing mutation kinds

Owned files:
- `google_account_resolution.py`
- `inbox_server.py`
- `tests/test_server.py`

Acceptance criteria:
- `/preflight/google-write` supports explicit kinds for `drive_upload`, `gmail_label`, `sheet_format`, `sheet_tab_rename`, `sheet_tab_copy`, and `doc_text_insert`.
- Each new kind resolves the same account that the matching endpoint will use.
- Tests cover valid and invalid destination/account cases where applicable.

Smallest validation:
- `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_server.py -k "Preflight or default_account" -q`

### 5. Add repository CI for the agent-safe loop

Owned files:
- `.github/workflows/ci.yml`
- `docs/TESTING_FOR_AGENTS.md`

Acceptance criteria:
- CI installs with `uv` on Python 3.12.
- CI runs `uv run ruff check .`, `uv run pyright`, and `INBOX_TEST_MODE=1 uv run pytest -m safe`.
- CI sets `INBOX_TEST_MODE=1`, avoids live credentials, and does not require macOS-only personal data stores for the safe suite.

Smallest validation:
- `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .`
- `UV_CACHE_DIR=/tmp/uv-cache uv run pyright`
- `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe -q`

## Handoff notes

No external services were called intentionally, no tracker was updated, no PR was created, and no product code was edited. The only blocker encountered was local validation dependency resolution in a network-restricted sandbox.
