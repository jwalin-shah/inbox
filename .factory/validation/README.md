# Validation Fixtures

This directory contains tracked evidence fixtures from prior factory validation
runs. Keep these files small and deterministic so they can be reviewed in git.

Runtime output from new local runs must not be written here by default. Use one
of the ignored local output directories instead:

- `.factory/runtime/`
- `.factory/outputs/`
- `.factory/runs/`
- `.factory/missions/`

Do not delete existing evidence fixtures unless the replacement preserves the
same review value or the obsolete evidence is documented in the commit.
