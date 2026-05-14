# Connector Registry

Inbox uses local connector CLIs as adapters, but Inbox remains the product layer.

## Sources

| Connector | CLI | Scope | Storage | Writes |
| --- | --- | --- | --- | --- |
| Google Workspace | `gog` | Gmail, Calendar, Drive, Docs, Sheets, Contacts | `~/Library/Application Support/gogcli` | Yes, confirm first |
| WhatsApp | `wacli` | WhatsApp chats/history | `~/.wacli` | Yes, confirm first |
| iMessage/SMS | `imsg` | Messages.app history | `~/Library/Messages/chat.db` | Yes, confirm first |
| Discord | `discrawl` | Discord archive/search | `~/Library/Application Support/discrawl/discrawl.db` | No |
| X/Twitter | `birdclaw` | Local X/Twitter archive/search | `~/.birdclaw` | Yes, confirm first |

## API

- `GET /connectors/status` reports install/auth/storage health.
- `POST /connectors/search` searches connector CLIs directly.
- `POST /connectors/{connector_id}/sync` returns a dry-run sync plan by default.
- `POST /search` can opt into connector sources explicitly:
  - `["whatsapp"]`
  - `["imessage"]`
  - `["discord"]`
  - `["twitter"]`
  - `["google"]`
  - `["connectors"]`

`/search` with `["all"]` keeps the existing built-in Inbox behavior and does not automatically call external connector CLIs.

## Safety

- Passive Google status intentionally avoids Keychain reads.
- Sync defaults to dry-run unless `{"execute": true}` is passed.
- Sending/posting/writing is outside this registry and must require explicit user confirmation.
- Connector command output is normalized into source/id/title/snippet/timestamp/metadata for read-only use.
