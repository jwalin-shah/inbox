# Readonly Profile

Name: readonly
Access: readonly

## Intent

Use this profile for analysis, inspection, dry runs, and planning where the
assistant must avoid side effects.

## Rules

- read local context before acting
- do not mutate files, services, or durable state outside local session records
- prefer reversible inspection over execution
- surface blockers instead of guessing

## Allowed Workspace

- `agents/`
