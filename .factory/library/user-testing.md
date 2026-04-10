# User Testing

Testing surface, required testing skills/tools, and resource cost classification.

## Validation Surface

### Surface 1: REST API (curl)
- **URL**: http://localhost:9849
- **How**: `curl` commands against server endpoints
- **Setup**: Start server with `uv run python inbox_server.py`
- **Teardown**: `lsof -ti :9849 | xargs kill`
- **Capabilities**: All CRUD operations, health checks, data retrieval

### Surface 2: TUI (tuistory)
- **Launch**: `uv run python inbox.py` (auto-starts server)
- **How**: tuistory skill — launch terminal app, capture snapshots, send keyboard inputs
- **Capabilities**: Visual validation of widget rendering, tab navigation, keybindings, data display
- **Limitations**: Cannot test macOS-level notifications (only TUI indicator). Server must be running.

### Surface 3: TUI (Textual Pilot — headless)
- **How**: `async with InboxApp().run_test() as pilot:` in pytest
- **Capabilities**: Headless UI testing — press keys, click widgets, query DOM, assert on widget state
- **Limitations**: Requires mocking InboxClient (no real server)

## Validation Concurrency

**Machine specs**: 8GB RAM, 8 CPU cores, Apple Silicon (M-series)

### tuistory surface
- Each tuistory instance: ~200MB (terminal + app process)
- Server: ~100MB
- **Max concurrent validators: 2** (server shared, 2 terminal instances fit in headroom)
- Rationale: 8GB total, ~5GB baseline usage, ~3GB headroom * 0.7 = 2.1GB. Each instance ~200MB + shared server ~100MB = 500MB for 2 instances.

### curl surface
- Lightweight, shares server with tuistory
- **Max concurrent validators: 5** (negligible memory per curl process)

## Testing Skills Required
- `tuistory` — for TUI visual validation
- `curl` — for API endpoint validation (built-in, no special skill needed)

## Known Limitations
- macOS desktop notifications cannot be validated programmatically via tuistory; only the in-TUI bell indicator can be checked
- Audio capture (ambient/dictation) requires real microphone hardware; tests must mock audio input
- LLM model loading takes 5-30 seconds; tests with real models need longer timeouts
