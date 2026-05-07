# inbox-sym-118 risk and validation review

Date: 2026-05-07
Branch: `codex/goal-inbox-sym-118-risk-and-validation-review`
HEAD: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`
Queue item: `inbox-sym-118-risk-and-validation-review`

## Scope

This is a repo-local risk and validation pass for `inbox-sym-118`. I reviewed local docs, package metadata, tests, scripts, deployment examples, factory validation outputs, and git state. I did not edit product code, call external services, push, open a PR, or update trackers.

The queue item referenced `items/inbox-sym-118-risk-and-validation-review/ISSUE.md`, but that file is absent in this worktree. I used the Goal Pack issue text supplied in the worker prompt as the task contract.

## Concrete observations

1. `README.md` describes a privacy-first local TUI/API spanning iMessage, Gmail, Calendar, Sheets, Notes, Reminders, GitHub, Drive, ambient audio, dictation, and autocomplete; the stated runtime surface is much broader than a normal web app and includes personal data plus live write integrations.
2. `pyproject.toml:5` requires Python `>=3.12,<3.15`, while `README.md` says Python 3.10+. That mismatch can send agents or CI to the wrong interpreter before any tests run.
3. `pyproject.toml:53-62` registers pytest markers for `safe`, `integration`, `local_data`, `slow`, and `live_write`, and `docs/TESTING_FOR_AGENTS.md:9-18` documents the safe command loop. This is a strong base for agent-safe validation.
4. `docs/TESTING_FOR_AGENTS.md:23-43` explicitly requires `INBOX_TEST_MODE=1` and forbids live-write, local-data, and provider-specific integration tests unless opted in. Any future validation task should preserve that contract.
5. `inbox_test_mode.py:9-24` centralizes safe-mode environment handling and raises `LiveWriteBlocked`; `services.py:114-119` routes service-level live-write guards through that helper.
6. `tests/test_services.py:909-951` covers representative write blockers for Gmail, Calendar, Apple Reminders, Google Tasks, Drive, Sheets, Docs, GitHub notifications, desktop notifications, and WhatsApp. This is the main regression fence for accidental live writes during agent runs.
7. `services.py:65-80` redirects token files and local macOS databases into `INBOX_TEST_DATA_DIR` only when test mode is active. Without `INBOX_TEST_MODE=1`, importing or starting the server can reach real `~/Library` data paths and repo-local token paths.
8. `services.py:88-98` requests broad Google OAuth scopes including Gmail modify/send, Calendar, Drive, Sheets, Docs, and Tasks. The repo needs tight validation around account resolution and write confirmation because a single token has many mutation powers.
9. `services.py:330-416` builds all Google services from every token in `tokens/`, refreshes expired credentials, renames token files to account emails, and logs failures. This is operationally useful but increases startup side effects and makes offline validation sensitive to cached credentials and network availability.
10. `inbox_server.py:1198-1285` starts contacts, Google auth, optional conversation prewarm, ambient audio autostart, and the scheduler in lifespan. Tests can inject a runtime, but the default app startup path is side-effectful unless a test or runner disables those pieces.
11. `inbox_server.py:1313-1340` makes backend auth optional: if `INBOX_SERVER_TOKEN` is absent, all REST requests are accepted. This is reasonable for loopback-only local use, but deployment validation must prove the raw backend stays private.
12. `mcp_gateway.py:36-58` makes HTTP MCP auth optional in the same way and exempts `/health`; `config/inbox.env.example:1-9` documents separate backend and MCP tokens. Remote deployment checks should fail closed when a token is missing.
13. `tools_registry.py:52-78` adds `confirm=True` handling to generated MCP handlers, and `tools_registry.py:110-119` filters readonly tools for the readonly MCP server. That central registry is the right place to add mutation-surface regression tests.
14. `inbox_mcp_readonly.py:44-77` still exposes sensitive read capabilities such as daily note reads and memory queries, even though it excludes mutation tools. "Read-only" should be treated as lower-risk, not public-safe.
15. `.gitignore:12-25` ignores OAuth credentials, tokens, keys, secrets, env files, and local token dirs; `.gitignore:40-43` also ignores local MCP memory and scheduler SQLite files. Secret hygiene is present at the repo boundary.
16. `.pre-commit-config.yaml:1-23` configures ruff, formatting, basic file checks, private-key detection, and Bandit, but `fd -H '^workflows$|\\.yml$|\\.yaml$' .github .` found no `.github/workflows` files. There is local validation config but no visible GitHub Actions workflow in this worktree.
17. `.factory/services.yaml:1-8` defines `test`, `test_all`, `typecheck`, and `lint`, but the default `test` command excludes `tests/test_audio.py` and `tests/test_llm.py`. This is also called out as already documented in `.factory/validation/fix-broken-state/scrutiny/synthesis.json:31-35`.
18. `.factory/validation/architecture-hardening/scrutiny/synthesis.json:41-57` records a systemic `Permission denied` issue for direct `.factory/init.sh` execution, and `ls -l .factory/init.sh` confirms the file is not executable (`-rw-r--r--`). This can break repeated agent setup.
19. `.factory/validation/reminders-tab/scrutiny/synthesis.json:30-35` records a blocking reminder correctness issue: duplicate incomplete reminders with the same title and list can cause AppleScript to mutate the wrong reminder. The same file includes an orchestrator override at lines 46-52, so this is accepted risk, not resolved risk.
20. `.factory/validation/voice-pipeline/scrutiny/synthesis.json:5-22` records a passing `uv run pytest -x -q`, `uv run pyright`, and `uv run ruff check .` validation set with 563 tests run. `DOCS_INDEX.md:40-45` still claims `uv run pytest` has "736 pass", which is a stale or at least unverified count in current local evidence.
21. `.factory/services.yaml:12-14` hardcodes the service start path to `/Users/jwalinshah/projects/inbox` and port `9849`, while `CLAUDE.md` says worktrees should run on alternate ports. Factory service validation can accidentally target the daily-driver checkout instead of this isolated worktree.
22. `scripts/run_inbox_backend.sh:1-9` uses `UV_CACHE_DIR=/tmp/uv-cache` before `uv run python inbox_server.py`. That cache override is necessary in this sandbox: plain `uv run` attempted to use `~/.cache/uv` and failed with `Operation not permitted`.

## Risks and blockers

- Required issue file missing: `items/inbox-sym-118-risk-and-validation-review/ISSUE.md` is not present. The prompt supplied the issue body, so the review could continue, but future workers should not depend on the missing path.
- Offline validation is not currently guaranteed in a fresh sandbox. `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py -q` tried to download `hf-xet` through the `mlx-whisper` dependency chain and failed because network is unavailable.
- There is no visible `.github/workflows` CI in this worktree. Local validation commands exist, but PR-level enforcement cannot be confirmed from repo-local files.
- The default factory `test` command skips audio and LLM tests. That may be reasonable for speed, but the repo needs an explicit policy for when skipped domains must run.
- Default server startup has real-data and background-process touchpoints: contacts, Google auth, optional ambient audio, scheduler, and optional prewarm.
- Auth is opt-in for both the private backend and public MCP gateway. Deployment evidence must prove exposed surfaces always set tokens and bind the backend privately.
- The readonly MCP gateway still exposes private notes and memory reads. It should be reviewed as a personal-data exfiltration surface, not just as a non-mutating API.
- The Reminders duplicate-title mutation risk remains accepted by override rather than technically eliminated.
- Documentation contains stale validation claims, especially the `DOCS_INDEX.md` test count.

## Validation commands

Commands run during this review:

```bash
git status --short --branch
```

Result before edits: clean branch output only, `## codex/goal-inbox-sym-118-risk-and-validation-review`.

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py -q
```

Result: failed before tests because sandboxed `uv` could not open `/Users/jwalinshah/.cache/uv/sdists-v9/.git`.

```bash
UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py -q
```

Result: failed before tests because dependency setup attempted to download `hf-xet==1.4.3` via the `mlx-whisper -> huggingface-hub -> hf-xet` chain, and DNS/network access is unavailable.

Required queue validation:

```bash
git status --short
```

Result after writing this report: exit code 0, output:

```text
?? docs/overnight/
```

## Implementation-ready follow-up tasks

1. Make the agent-safe smoke test runnable offline.
   Owned files: `pyproject.toml`, `uv.lock`, `docs/TESTING_FOR_AGENTS.md`, `tests/conftest.py`.
   Acceptance criteria: a fresh sandbox can run the documented focused safe test without downloading ML/audio transitive dependencies; heavy ML/audio packages remain available for full local installs; docs explain the exact offline-safe command.
   Smallest useful validation: `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py -q`.

2. Add PR CI for the safe validation contract.
   Owned files: `.github/workflows/safe-validation.yml`, `docs/TESTING_FOR_AGENTS.md`.
   Acceptance criteria: CI runs `INBOX_TEST_MODE=1 uv run pytest -m safe`, `uv run ruff check .`, and `uv run pyright`; the workflow does not require local personal data, provider credentials, microphone access, or live writes; README or testing docs link to the CI contract.
   Smallest useful validation: `git diff --check .github/workflows/safe-validation.yml docs/TESTING_FOR_AGENTS.md` plus `INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py -q` in an environment with dependencies available.

3. Align factory validation commands with the safe-test policy.
   Owned files: `.factory/services.yaml`, `.factory/library/architecture-hardening.md`, `docs/TESTING_FOR_AGENTS.md`.
   Acceptance criteria: `.factory/services.yaml` has distinct commands for safe smoke, default repo test, full test including audio/LLM, typecheck, and lint; skipped audio/LLM coverage is explicitly named rather than hidden; worktree service start commands do not hardcode the daily-driver checkout.
   Smallest useful validation: `python -c "import yaml, pathlib; print(yaml.safe_load(pathlib.Path('.factory/services.yaml').read_text())['commands'].keys())"` or an equivalent repo-available YAML parse, then `git diff --check .factory/services.yaml docs/TESTING_FOR_AGENTS.md`.

4. Add MCP mutation-surface regression tests.
   Owned files: `tools_registry.py`, `tests/test_tools_registry.py`, `tests/test_mcp_gateway.py`, `tests/test_mcp_readonly.py` if created.
   Acceptance criteria: every non-readonly registry tool is confirmation-gated; readonly MCP registration excludes all non-readonly tools; sensitive "read-only" tools are enumerated in tests so new personal-data read surfaces are intentional; full MCP memory and note write tools still require confirmation.
   Smallest useful validation: `INBOX_TEST_MODE=1 uv run pytest tests/test_tools_registry.py tests/test_mcp_gateway.py -q`.

5. Revisit Reminders mutation targeting or document the accepted limit at the API boundary.
   Owned files: `services.py`, `tests/test_reminders.py`, `CLAUDE.md`, `docs/TESTING_FOR_AGENTS.md` if new opt-in validation is needed.
   Acceptance criteria: duplicate-title same-list reminder mutations either fail with an explicit ambiguity error before AppleScript execution or have a documented EventKit-backed design issue; tests cover duplicate incomplete reminders with identical titles in one list; public API docs describe the behavior.
   Smallest useful validation: `INBOX_TEST_MODE=1 uv run pytest tests/test_reminders.py -q`.

## Handoff

Changed files: `docs/overnight/2026-05-07-whole-portfolio-review/inbox-sym-118-risk-and-validation-review.md`.
Commit SHA: no commit created; current HEAD is `2805b8400519da188ca7d3f6e39b19a8ca42b05a`.
PR URL: none; external pushes and PR creation are out of scope for this worker.
Blockers: missing queue `ISSUE.md`; safe pytest smoke blocked by sandbox cache permissions without `UV_CACHE_DIR` and then by restricted network while resolving `hf-xet`.
