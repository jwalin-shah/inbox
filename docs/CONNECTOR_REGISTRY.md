# Connector Registry

Inbox uses local connector CLIs as adapters, while Inbox remains the product layer.

## Sources

| Connector | CLI | Scope | Storage | Writes |
| --- | --- | --- | --- | --- |
| Google Workspace | `gog` | Gmail, Calendar, Drive, Docs, Sheets, Contacts | `~/Library/Application Support/gogcli` | Yes, confirm first |
| WhatsApp | `wacli` | WhatsApp chats/history | `~/.wacli` | Yes, confirm first |
| iMessage/SMS | Inbox native reader; optional `imsg` CLI | Messages.app history | `~/Library/Messages/chat.db` | Yes, confirm first |
| LinkedIn | `python3 scripts/linkedin_web_scanner.py` | LinkedIn Messaging export/scanner DB | `~/.openhuman/**/linkedin_data.db` | No |
| Discord | `discrawl` | Discord archive/search | `~/Library/Application Support/discrawl/discrawl.db` | No |
| X/Twitter | `birdclaw` | Local X/Twitter archive | `~/.birdclaw` | Yes, confirm first |

## API

- `GET /connectors/status` reports install/auth/storage health.
- `POST /connectors/search` searches connector CLIs directly.
- `POST /connectors/{connector_id}/sync` returns a dry-run sync plan by default.
- `POST /search` can opt into connector sources explicitly:
  - `["connector:whatsapp"]`
  - `["connector:imessage"]`
  - `["connector:discord"]`
  - `["connector:twitter"]`
  - `["connector:google"]`
  - `["connector:linkedin"]`
  - `["connectors"]`

`/search` with `["all"]`, `["imessage"]`, or `["gmail"]` keeps the existing built-in Inbox behavior and does not automatically call external connector CLIs. Connector status reports that native path separately from optional CLI installation.

## Account Substrate

Each connector status row includes scoped account metadata:

- `accounts[].id`: stable local account scope, such as `google:workspace` or `whatsapp:local`.
- `accounts[].subject_ref`: the connector-owned account identity reference, not a raw credential.
- `accounts[].read_scopes`: read capabilities Inbox may use for search/status/sync planning.
- `accounts[].write_scopes`: write capabilities known to the connector, exposed as metadata only.
- `accounts[].credential_refs`: encrypted credential references only.

Credential material follows an encrypted-reference envelope. The registry may report `infisical://`, `keychain://`, or encrypted local `file://` references, but it must not store or return plaintext OAuth tokens, refresh tokens, session cookies, passwords, private keys, or provider API keys.

## Safety

- Passive Google status intentionally avoids Keychain reads.
- Connector status probes are read-only doctor/auth commands and command previews.
- Sync defaults to dry-run; `{"execute": true}` is still denied unless a per-action approval lease is present.
- Live sync execution requires a per-action approval lease at the registry boundary.
- Sending/posting/deleting/calendar writing is outside this registry and must require explicit user confirmation through the Inbox approval gate before any provider helper can run.
- The registry exposes only `auth`, `search`, and `sync` command slots; it does not expose `send`, `delete`, or `calendar_write` commands.
- Connector command output is normalized into source/id/title/snippet/timestamp/metadata for read-only use.

Every status row includes `action_policy`:

- `read` and `search`: allowed without approval.
- `sync_execute`: approval required.
- `send`, `delete`, and `calendar_write`: approval required and executed outside `connector_registry.py`.

## Readiness Checklist

- Google Workspace: `gog` on PATH, OAuth status command succeeds, Gmail/Calendar/Sheets scopes are present, and dry-run sync command is reviewable.
- iMessage/SMS native Inbox path: `~/Library/Messages/chat.db` exists/readable by the Inbox process and the required macOS permission is granted. `imsg` is optional for external CLI/search workflows; it is not required for Inbox's built-in reader.
- WhatsApp: `wacli` on PATH, `wacli doctor --json` succeeds, and sync is reviewed through dry-run before any execute path.
- LinkedIn: scanner module imports, LinkedIn export/scanner `linkedin_data.db` exists/readable, and scanner use remains opt-in with `INBOX_ENABLE_LINKEDIN_SCRAPER=1`.
- Job outreach: Gmail and LinkedIn sources are both readable so recruiter email history and LinkedIn message history are available.
