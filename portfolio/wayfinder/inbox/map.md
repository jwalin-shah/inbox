# Inbox OAuth gateway

## Destination

Connect the inbox MCP server to Gemini Spark with a supported OAuth path, then
prove a live read handshake under `jshah1331@gmail.com`.

## Findings

- Public HTTPS, MCP discovery, protected-resource metadata, DCR, scoped bearer
  validation, and approval-gated writes are implemented.
- The brokered Google exchange needs a separate PKCE pair from Gemini's PKCE
  pair.
- Gemini has completed discovery and DCR in live tests but has not consistently
  advanced to authorization; a pre-registered-client fallback is required.

## Decisions

- Keep Google OAuth credentials server-side only.
- Add a separate static Gemini client ID/secret configured through environment
  variables and accepted by the gateway without weakening DCR validation.
- Preserve `inbox.read` and `inbox.write` scope checks and the existing write
  approval lease.

## Not yet specified

- Whether Gemini Spark will complete the static-client flow for this account;
  this must be proven with a live authorization and token exchange.

## Out of scope

- Exposing Google client secrets to Gemini.
- Broadening MCP access or bypassing approval leases.
