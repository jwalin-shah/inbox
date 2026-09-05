# LifeOps council v0

## Purpose

The council is a queue and routing layer above existing provider surfaces. It
does not recreate Perplexity, ChatGPT, OpenClaw, TokenRouter, browser control,
OAuth, or Bridge. It records which worker should do a round of work, why that
surface is economically attractive, and what evidence the worker returned.

```text
LifeOps council job
  -> ranked subscription/API/local surfaces
  -> worker claims one job
  -> independent result + evidence
  -> disagreement flag / later synthesis
  -> append-only local event log
```

## Subscription economics

Each surface records:

- provider and surface name
- capabilities
- marginal cost and whether a subscription is already sunk
- quota and reset fields, which remain `null` until account-specific proof
- rate-limit type, quality, latency, automation level, and best use
- availability and the source/time of the last verification
- whether the surface is allowed in the automatic lane; policy-disabled
  surfaces remain available only as explicit interactive handoffs

Unknown quota is not treated as unlimited. Unknown availability is not treated
as an unattended execution route. Subscription surfaces rank ahead of local or
API routes when their availability is actually proven; until then they remain
interactive handoff candidates.

`council quota-sync` reads the local, redacted `quota-axi --json` report. In
the current machine proof, Codex reports a fresh Plus plan with 95% remaining
in its weekly window; Claude, Copilot, Grok, Kimi, and ZAI report
`auth_required`. This updates only the matching Codex surface. Perplexity is
not exposed by this local quota probe, so its availability remains `unknown`.
Quota readiness still does not make Codex executable: the surface remains
`availability: unknown` until a harmless execution handshake is proved.

`chatgpt/sol` is intentionally `automatic_enabled: false`. LifeOps does not
use ChatGPT Work as an unattended worker. It may remain a manual consultation
surface, but it cannot become an automatic council route merely because an
account probe later reports it available. Codex is tracked separately and is
also not automatic until its execution handshake is proved.

`perplexity/mac-local-mcp` represents the preferred no-API Perplexity path:
the signed-in Perplexity Mac app invokes a curated local MCP server. The app
and connector must be installed and handshaken before this surface can be
considered usable. It remains manual-only because the Mac app is a user-facing
conversation surface, not an unattended daemon.

## Commands

```sh
scripts/lifeops council surfaces
PATH=/opt/homebrew/bin:/Users/jwalinshah/bin:$PATH scripts/lifeops council quota-sync
scripts/lifeops council routes research.search
scripts/lifeops council create --question "Should we pursue this idea?"
scripts/lifeops council claim --worker firstmate --surface perplexity/best
scripts/lifeops council show <job_id>
scripts/lifeops council result <job_id> \
  --worker firstmate --surface perplexity/best \
  --summary "..." \
  --evidence-json '[{"url":"https://example.com","title":"Example"}]'
scripts/lifeops council status
```

The first proof is local queue creation, priority ordering, claim identity, and
readback. It does not call a consumer subscription UI or scrape provider
output. Provider execution is a separate adapter and requires a real,
account-specific connector/API/interactive handoff proof.

## Boundaries and next live proofs

1. Probe the actual Perplexity connector/API surface available to this account;
   do not infer it from a help page or subscription name.
2. Probe the actual ChatGPT/Codex account surface separately; a consumer
   subscription is not itself an API credential.
3. If cloud workers must call LifeOps, expose only a reviewed authenticated
   HTTPS council endpoint. The local Inbox listener is not a public endpoint.
4. Store provider response IDs, citations, and readback evidence in result
   records. For consequential actions, Bridge remains the execution and
   verification boundary.

## Grill result

**Pass with explicit unknowns.** The queue, economic fields, deterministic
ranking, and claim/result identity are testable locally. The design does not
claim that Perplexity or ChatGPT subscription automation is live: those
surfaces are `availability: unknown` until their current account-specific
connector or API capability is probed. This prevents the most dangerous
failure mode here—mistaking a paid plan or a catalog entry for an executable,
authorized worker.
