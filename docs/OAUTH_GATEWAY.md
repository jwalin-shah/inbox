# OAuth gateway

The public MCP gateway exposes OAuth 2.0 authorization-code flow for Gemini.
Discovery is `/.well-known/oauth-authorization-server`; clients register at
`/oauth/register`. Authorization requires S256 PKCE and binds the callback to
the server-side state record. The callback exchanges the Google authorization
code at Google's token endpoint, then issues a short-lived, gateway-signed
scoped bearer token.

Tokens require `inbox.read` for MCP reads. A client must additionally send
`X-Inbox-Write: true` and hold `inbox.write` for write calls. This scope check
does not replace the existing per-action approval lease: guarded provider
writes still fail unless the exact `x-inbox-approval-lease` is present.

Set `INBOX_OAUTH_SECRET` and `INBOX_OAUTH_DB` in deployment. Configure
`GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` for the Google code
exchange. The default development signing secret must not be used in a
deployed gateway.

For Gemini Spark's static-client fallback, the launcher loads the dedicated
MCP client pair from `$HOME/.config/inbox/gemini_mcp_static_client.json`.
Enter that pair in Gemini Advanced Settings. These credentials identify
Gemini to this MCP gateway; they are not the Google OAuth client credentials
used by the gateway for the upstream Google login.
