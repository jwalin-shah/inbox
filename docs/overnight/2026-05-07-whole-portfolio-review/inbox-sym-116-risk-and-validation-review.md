# inbox-sym-116 Risk And Validation Review

Queue item: `inbox-sym-116-risk-and-validation-review`
Branch: `codex/goal-inbox-sym-116-risk-and-validation-review`
Baseline HEAD inspected: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`
Review date: 2026-05-07

## Scope

This was a read-only risk and validation pass. I did not edit product code, call external services, deploy, push, create PRs, or update trackers. The only intended write is this report.

Evidence inspected:

- Repository structure via `llm-tldr tree .`
- Current git state via `git status --short`, `git log --oneline -10`, and recent merge stats
- Project docs: `README.md`, `CLAUDE.md`, `DOCS_INDEX.md`, `PLAN.md`, `CONNECTOR_ROADMAP.md`, `MCP_SETUP.md`, `docs/TESTING_FOR_AGENTS.md`
- Package and validation config: `pyproject.toml`, `.pre-commit-config.yaml`, `.factory/services.yaml`
- Runtime/config/deploy surfaces: `dev.sh`, `scripts/*.sh`, `config/*.example.*`, `deploy/*.example`, `.cursor/mcp.json`
- Test and safety surfaces: `tests/`, `inbox_test_mode.py`, `tools_registry.py`, `mcp_gateway.py`, `inbox_server.py`, `google_account_resolution.py`
- Prior generated validation evidence under `.factory/validation/**`

Not present in this worktree:

- No tracked `.github/` workflows.
- No repo-local `runs/` directory with `result.json` or `handoff.md`.
- No prior `docs/overnight/` reports.

## Executive Summary

The repo has stronger-than-average local guardrails for a personal-data application: token auth exists for the HTTP backend, MCP write tools are confirmation-gated, test mode blocks many live writes, and recent index/sync work has focused tests. The main risk is not absence of tests; it is validation drift. Different repo surfaces disagree about Python version, test counts, safe test scope, and whether the default test command is the full suite.

The next executable work should make validation boring and unambiguous before expanding product behavior: align safe/full test commands, add CI or an equivalent local gate, expose the preflight write checker through the curated MCP surface, and add missing regression coverage around ambient note persistence and worktree-safe factory setup.

## Concrete Observations

1. `pyproject.toml` requires Python `>=3.12,<3.15`, while `README.md` still says Python 3.10+ is required. This can send new agents or CI jobs onto an unsupported interpreter.

2. `docs/TESTING_FOR_AGENTS.md` makes `INBOX_TEST_MODE=1 uv run pytest -m safe` the default safe command, but `rg` found `pytest.mark.safe` only in `tests/test_inbox_test_mode.py` and `tests/test_mcp_gateway.py`. Most deterministic tests are unmarked and would be deselected by that command.

3. `pyproject.toml` sets default pytest addopts to `--cov=. --cov-report=term-missing`, but there is no coverage threshold. The command reports coverage but does not prevent coverage erosion.

4. `.factory/services.yaml` defines `test: uv run pytest --ignore=tests/test_audio.py --ignore=tests/test_llm.py -x -q`. Prior validation in `.factory/validation/fix-broken-state/user-testing/flows/cli-checks.json` says the restored full suite was `uv run pytest -x -q`, including `tests/test_audio.py` and `tests/test_llm.py`.

5. `DOCS_INDEX.md` claims "Tests (736 pass)" and "All 736 tests pass", but the prior generated CLI validation reports `254 passed`. That stale claim is a high-confidence documentation drift issue.

6. `.pre-commit-config.yaml` runs Ruff, formatting, YAML/large-file/private-key hooks, and Bandit. It does not run `pyright` or `pytest`, and there is no tracked `.github/workflows` CI fallback.

7. `inbox_test_mode.py` centralizes live-write blocking with `assert_live_writes_allowed`, and `services.py` calls `_assert_live_write_allowed` across high-risk mutations including Gmail, Calendar, Reminders, Tasks, Drive, Sheets, Docs, GitHub notification writes, desktop notifications, and attendee modification.

8. `tests/test_services.py` includes representative and extended test-mode blocking coverage, and `tests/test_inbox_test_mode.py` verifies marker registration and testing docs. This is good evidence, but because most service tests are not marked `safe`, the default safe command does not exercise much of that coverage.

9. `inbox_server.py` protects the raw FastAPI backend with `INBOX_SERVER_TOKEN`, and `tests/test_server.py::TestAuth` covers unauthenticated 401 plus Bearer and `X-API-Key` success. `inbox_client.py` and `mcp_backend.py` both forward Bearer auth from the same env var.

10. `tools_registry.py` drives the curated MCP surface and marks every mutating tool as `confirm=True`; `tests/test_tools_registry.py` asserts all non-readonly tools require confirmation and that readonly registration excludes write tools.

11. `inbox_server.py` exposes `/preflight/google-write`, and `google_account_resolution.py` validates default account, Drive folder, Tasks list, and calendar destination. `tests/test_server.py` covers these cases. However, `tools_registry.py` does not expose a `preflight_google_write` MCP tool, even though `CONNECTOR_ROADMAP.md` names it as a target intent-level tool.

12. Recent sync/index work is well covered: `tests/test_message_sync.py` covers resumable Gmail bootstrap, history-cursor incremental sync, timestamp fallback, skipped iMessage row checkpoints, and scoped thread rebuilds; `tests/test_server.py` covers `/index/health`, stale checkpoints, sync errors, and compact indexed views.

13. `message_index_store.py`, `message_sync.py`, and `thread_classifier.py` now form the operational index path described in `PLAN.md`. This is implementation-ready, but the classifier remains heuristic and the plan explicitly calls classification noise a main phase risk.

14. `services.py` is 6,467 lines, `inbox.py` is 4,279 lines, and `inbox_server.py` is 3,940 lines. The test suite is broad, but these large shared modules increase change risk because small edits often cross personal-data, UI, auth, and provider boundaries.

15. `.factory/init.sh` has a bash shebang but file mode `-rw-r--r--`, matching prior generated warnings that direct execution fails with permission denied. It also `cd`s to `/Users/jwalinshah/projects/inbox` and kills port `9849`, which conflicts with the worktree isolation rules documented in `CLAUDE.md` and `MCP_SETUP.md`.

16. `inbox_server.py` now initializes `AmbientService` with `on_note=lambda raw, summary: ambient_notes.save_note(raw, summary)`, and `tests/test_ambient_notes.py` covers note writing. The server endpoint test fixtures in `tests/test_voice_pipeline.py` replace the server ambient service with a no-op callback, so there is no server-level regression test proving default ambient capture persists notes.

## Risks And Blockers

- Validation drift: agent docs, factory automation, docs index, and prior generated outputs do not agree on the authoritative validation command or expected test count.
- CI gap: there is no tracked GitHub Actions workflow or equivalent repo-local automated gate. Validation currently depends on local/manual convention.
- Safe-test gap: the documented agent-safe command currently covers only a small marked subset, which can create false confidence for personal-data write guardrails.
- MCP preflight gap: write preflight exists as an HTTP endpoint but is not available through the curated MCP tool registry, so agents may still need prompt-level routing decisions.
- Worktree safety gap: `.factory/init.sh` is not executable and hard-codes the primary checkout and port, which can disrupt the daily-driver inbox if reused from a worktree.
- Ambient persistence gap: the prior ambient no-op regression appears fixed, but there is no endpoint/runtime-level test tying `ServerState` default ambient callback to `ambient_notes.save_note`.
- External/live validation is intentionally blocked for this queue item. No Gmail, Calendar, Drive, Docs, Reminders, GitHub, notification, audio, deployment, or MCP network exercise was run.

## Exact Validation Commands

Required queue validation:

```bash
git status --short
```

Repo-documented safe loop:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe
uv run ruff check .
uv run pyright
```

Current full local validation candidates from repo/factory evidence:

```bash
uv run pytest -x -q
uv run ruff check .
uv run pyright
pre-commit run --all-files
```

Focused validation commands for the highest-risk follow-ups:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py tests/test_mcp_gateway.py -q
INBOX_TEST_MODE=1 uv run pytest tests/test_services.py::test_test_mode_blocks_representative_live_writes tests/test_services.py::test_test_mode_blocks_extended_live_writes -q
uv run pytest tests/test_tools_registry.py tests/test_api_contract.py -q
uv run pytest tests/test_message_sync.py tests/test_message_index_store.py -q
uv run pytest tests/test_voice_pipeline.py tests/test_ambient_notes.py -q
bash -n .factory/init.sh
```

## Implementation-Ready Follow-Up Tasks

### 1. Make Agent-Safe Test Selection Honest

Owned files:

- `docs/TESTING_FOR_AGENTS.md`
- `pyproject.toml`
- `tests/test_inbox_test_mode.py`
- deterministic test modules selected for `safe` coverage, starting with `tests/test_services.py`, `tests/test_tools_registry.py`, `tests/test_client.py`, `tests/test_api_contract.py`, and `tests/test_message_sync.py`

Acceptance criteria:

- The documented `INBOX_TEST_MODE=1 uv run pytest -m safe` command exercises all deterministic tests that do not touch live personal data or external write surfaces.
- Tests that mock provider SDKs, use temp SQLite files, or exercise pure routing/contract logic are marked `safe`.
- Tests that require local macOS data, real OAuth tokens, microphone/audio devices, or live provider writes remain unmarked or explicitly marked `local_data`, `integration`, or `live_write`.
- `tests/test_inbox_test_mode.py` verifies the docs contain the final safe command and marker vocabulary.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe -q
uv run pytest tests/test_inbox_test_mode.py -q
```

### 2. Reconcile Validation Docs And Factory Commands

Owned files:

- `.factory/services.yaml`
- `DOCS_INDEX.md`
- `README.md`
- `CLAUDE.md`
- `docs/TESTING_FOR_AGENTS.md`

Acceptance criteria:

- Python requirement is consistent with `pyproject.toml` (`>=3.12,<3.15`) across setup docs.
- Stale "736 tests pass" claims are removed or replaced with command-based guidance that does not hard-code a count.
- `.factory/services.yaml` stops hiding `tests/test_audio.py` and `tests/test_llm.py` behind the default test command, or clearly names the command as a reduced smoke test and adds a separate full-suite command.
- Docs name one authoritative safe loop and one authoritative full local loop.

Smallest useful validation:

```bash
uv run pytest --collect-only -q
uv run ruff check .
```

### 3. Add A Repo-Local CI Gate

Owned files:

- `.github/workflows/ci.yml`
- `README.md` or `docs/TESTING_FOR_AGENTS.md` if command names need to be referenced

Acceptance criteria:

- A tracked workflow runs on pull requests and pushes.
- The workflow installs with `uv` using a Python version allowed by `pyproject.toml`.
- The workflow runs Ruff, Pyright, and the safest practical pytest command for this macOS/personal-data repo.
- If the full suite requires macOS-only dependencies, the workflow uses a macOS runner or documents why a reduced safe suite is the CI gate and what local command covers the full suite.

Smallest useful validation:

```bash
uv run ruff check .
uv run pyright
INBOX_TEST_MODE=1 uv run pytest -m safe -q
```

### 4. Expose Google Write Preflight Through MCP

Owned files:

- `tools_registry.py`
- `tests/test_tools_registry.py`
- `tests/test_api_contract.py`
- `mcp_backend.py` only if a typed convenience wrapper is desired

Acceptance criteria:

- `preflight_google_write` is present in `TOOLS`, marked `readonly=True`, and routes to `GET /preflight/google-write`.
- Tool parameters include `kind`, `account`, `folder_id`, `list_id`, `calendar_id`, and `title`.
- The API contract test proves the tool route matches a FastAPI endpoint.
- Readonly MCP registration includes the preflight tool; write confirmation is not required because it does not mutate state.

Smallest useful validation:

```bash
uv run pytest tests/test_tools_registry.py tests/test_api_contract.py -q
```

### 5. Add Ambient Persistence Regression Coverage

Owned files:

- `tests/test_voice_pipeline.py`
- `tests/test_server_endpoints.py` or `tests/test_server.py`
- `inbox_server.py` only if tests reveal the default callback wiring needs a small seam

Acceptance criteria:

- A server/runtime test proves default `ServerState` ambient note callback calls `ambient_notes.save_note(raw, summary)`.
- Existing endpoint tests can still replace ambient/dictation services with no-op test doubles without masking default wiring.
- The test uses mocks and does not start real audio capture, microphone input, or ML inference.

Smallest useful validation:

```bash
uv run pytest tests/test_voice_pipeline.py tests/test_ambient_notes.py -q
```

## Handoff Notes

- Product code was intentionally left untouched.
- This report is the only new repo artifact expected from this worker.
- PR creation and external tracker updates were out of scope for this queue item.
