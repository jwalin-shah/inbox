# MAX-250 Workpad

## Issue

- Linear: `MAX-250`
- Title: Inbox: require explicit API auth for personal-data and write endpoints
- Repo: `/Users/jwalinshah/projects/inbox`
- Worktree: `/Users/jwalinshah/projects/inbox-MAX-250`
- Branch: `codex/MAX-250-inbox-api-auth-fail-closed`
- Base: `origin/main` at `1327e97`

## Plan

- Make `/health` the only unauthenticated endpoint by default.
- Require `INBOX_SERVER_TOKEN` for all non-health endpoints unless an explicit dev/test bypass is enabled.
- Add `INBOX_SERVER_ALLOW_UNAUTHENTICATED=1` as the named bypass for isolated development and tests.
- Update auth tests to prove fail-closed, token success, X-API-Key success, and explicit dev bypass behavior.
- Update README/CLAUDE/config docs for the new default.

## Validation

```bash
uv run pytest tests/test_server.py::TestAuth -q --no-cov
```

Result: passed, 7 passed.

```bash
uv run pytest tests/test_server.py tests/test_server_endpoints.py tests/test_api_contract.py -q --no-cov
```

Result: passed, 186 passed.

```bash
uv run ruff check inbox_server.py tests/conftest.py tests/test_server.py
```

Result: passed.

```bash
git diff --check
```

Result: passed.

```bash
scripts/validate_agent_safe.sh
```

Result: passed. Ruff passed, Bandit completed with existing warnings only, and safe pytest passed with 11 passed and 874 deselected.

Review rerun after PR #43 landed:

```bash
uv lock --check
```

Result: passed.

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_server.py -q --no-cov
```

Result: passed, 126 passed.

```bash
scripts/validate_agent_safe.sh
```

Result: passed. Ruff passed, Bandit completed with existing warnings only, and safe pytest passed with 11 passed and 874 deselected.

```bash
git diff --check
```

Result: passed.

## Handoff

Pending PR.

## Connector Registry Split PR - 2026-05-13

Source preservation branch: `codex/inbox-preservation-split-review`.
Implementation branch: `codex/inbox-connector-registry-preservation`.
Base: `origin/main` at `0cc9391`.

Scope:

- Add `connector_registry.py` as the read-only local connector registry module.
- Add `/connectors/status`, `/connectors/search`, and
  `/connectors/{connector_id}/sync` endpoints.
- Let `/search` opt into connector sources explicitly without changing
  `["all"]` built-in search behavior.
- Add `InboxClient` connector helpers.
- Add `docs/CONNECTOR_REGISTRY.md` and focused connector endpoint tests.

Out of scope for this PR:

- WhatsApp/OpenHuman local-store indexing.
- Google auth diagnostics and Gmail filter audit.
- Calendar dedupe and classifier quality fixes.
- Generated `.agent-stack-review/` and `docs/architecture/` artifacts.

Validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_connector_registry.py tests/test_server.py::TestConnectorEndpoints -q --no-cov
```

Result: passed, `9 passed in 3.67s`.

```bash
uv run ruff check connector_registry.py inbox_server.py inbox_client.py tests/test_connector_registry.py tests/test_server.py
```

Result: passed.

```bash
git diff --check
```

Result: passed.

Gemini secondary review:

- Ran in read-only plan mode against the clean worktree diff.
- Decision: reviewable as the first split PR.
- Required fixes before commit: none.
