# Agents Control Plane

This directory is an isolated Milestone 1 scaffold for a local personal
assistant control plane. It is intentionally small and does not integrate with
the rest of the repo yet.

## Layout

- `profiles/`: human-readable execution profiles
- `prompts/`: reusable prompt templates
- `runner/`: small Python package for profile loading, session persistence, and
  supervisor orchestration
- `sessions/`: local JSON session state, ignored by git
- `logs/`: local runtime logs, ignored by git

## Milestone 1 Scope

Milestone 1 provides:

- two execution profiles: `readonly` and `write`
- prompt assembly from local templates and profile files
- a JSON-backed session store rooted in `agents/sessions/`
- typed result objects for supervisor flow
- a minimal supervisor that can start, record, and finish sessions

## Non-Goals

Milestone 1 does not include:

- subprocess execution
- model integration
- repo-wide wiring
- auth, policy engines, or remote coordination

## Example

```python
from agents.runner import SessionStore, Supervisor

store = SessionStore()
supervisor = Supervisor(store=store)

record = supervisor.start_session(profile_name="readonly", goal="Inspect inbox state")
supervisor.record_step(record.session_id, summary="Loaded profile and initialized session")
supervisor.finish_session(record.session_id, success=True, final_message="Scaffold ready")
```
