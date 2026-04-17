# Write Profile

Name: write
Access: write

## Intent

Use this profile for local implementation tasks where the assistant may write
within approved workspace boundaries.

## Rules

- keep edits scoped to the requested task
- record meaningful session events
- prefer simple standard-library solutions first
- do not assume ownership outside explicitly approved paths

## Allowed Workspace

- `agents/`
