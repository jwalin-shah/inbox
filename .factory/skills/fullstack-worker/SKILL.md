---
name: fullstack-worker
description: Fullstack worker for features touching both server API and TUI
---

# Fullstack Worker

NOTE: Startup and cleanup are handled by `worker-base`. This skill defines the WORK PROCEDURE.

## When to Use This Skill

Use for features that modify BOTH backend (services/server/client) AND the TUI (inbox.py). This includes:
- Adding new TUI tabs (Reminders, GitHub, Drive)
- Adding new TUI widgets, screens, or overlays
- Features that need new API endpoints AND TUI interaction
- Calendar/Gmail upgrades with UI changes
- Search, command palette, contact profiles
- Any feature that changes what the user sees AND how the server works

## Required Skills

None — but workers should use `tuistory` skill if available for visual verification of TUI changes.

## Work Procedure

1. **Read the feature description** carefully. Understand the full scope: which server endpoints are needed, which TUI widgets/views change, what the user flow looks like.

2. **Investigate the current code**:
   - Read `inbox.py` to understand the TUI structure (widgets, tabs, CSS, bindings)
   - Read `inbox_server.py` and `services.py` for the backend
   - Read `inbox_client.py` for client methods you'll need to add/modify
   - Check AGENTS.md, `.factory/library/architecture.md`, `.factory/services.yaml`

3. **Plan the implementation** — identify ALL files that need changes:
   - `services.py` — new data access functions
   - `inbox_server.py` — new endpoints
   - `inbox_client.py` — new client methods
   - `inbox.py` — new widgets, tabs, bindings, CSS
   - `tests/` — new test files or additions to existing ones

4. **Backend first — write failing tests, then implement**:
   - Add service functions to `services.py` (with tests)
   - Add server endpoints to `inbox_server.py` (with TestClient tests)
   - Add client methods to `inbox_client.py` (with mocked tests)
   - Run: `uv run pytest -x -q` — verify tests pass

5. **TUI implementation**:
   - Add new widget classes (follow existing patterns: `ConversationItem`, `EventItem`, `NoteItem`)
   - Add to the app's `compose()` method if adding new tabs/views
   - Add CSS rules in the `CSS` class attribute
   - Add keybindings in `BINDINGS` list
   - Use `@work(thread=True)` for any blocking I/O
   - Use `call_from_thread` to update UI from worker threads
   - Use `reactive` for data that triggers re-renders

6. **Write TUI tests** using Textual Pilot:
   ```python
   async def test_reminders_tab(self):
       async with InboxApp().run_test() as pilot:
           await pilot.press("ctrl+6")
           # Assert tab switched, widgets rendered
   ```
   Mock the `InboxClient` to avoid needing a real server.

7. **Run full validation**:
   - `uv run pytest -x -q` — all tests pass
   - `uv run pyright` — 0 errors
   - `uv run ruff check .` — 0 errors

8. **Manual verification**:
   - Start the app: `uv run python inbox_server.py &` then test API with curl
   - Kill server: `lsof -ti :9849 | xargs kill`
   - For TUI: describe what you would see if you launched the TUI (actual TUI launch optional given resource constraints)

9. **Verify ALL items** in the feature's `expectedBehavior` and `verificationSteps`.

10. **Commit** your changes.

## TUI Patterns to Follow

### New Tab Widget
```python
class ReminderItem(ListItem):
    def __init__(self, data: dict) -> None:
        super().__init__()
        self.data = data

    def compose(self) -> ComposeResult:
        d = self.data
        t = Text()
        t.append("icon ", style="dim")
        t.append(d.get("title", ""), style="bold white")
        # ... format additional fields
        yield Static(t)
```

### New Tab in App
```python
# In Tabs widget:
Tab("Reminders", id="tab-rem"),

# In BINDINGS:
Binding("ctrl+6", "filter_rem", "Reminders"),

# In tab_map:
"tab-rem": "reminders",

# In _render_sidebar:
if self._active_filter == "reminders":
    for r in self.reminders_data:
        lv.append(ReminderItem(r))
```

### Compose Input Context
```python
if self._active_filter == "reminders":
    compose_input.placeholder = "New reminder title (Enter to create)"
```

## Example Handoff

```json
{
  "salientSummary": "Added Reminders tab to TUI with full CRUD: list display (title, due date, list name), create from compose input, complete via 'c' key, filter by list. Added 3 new server endpoints (PUT /reminders/{id}, DELETE /reminders/{id}, GET /reminders/search). 8 backend tests + 4 TUI pilot tests, all passing.",
  "whatWasImplemented": "New ReminderItem widget in inbox.py with title/due_date/list_name display. Reminders tab accessible via Ctrl+6. Compose input creates reminders when on Reminders tab. 'c' key completes selected reminder, 'd' key deletes. Filter by list via input. Empty state shows 'No reminders'. Backend: PUT /reminders/{id} for edit, DELETE /reminders/{id} for delete, search endpoint. Client methods: edit_reminder(), delete_reminder().",
  "whatWasLeftUndone": "",
  "verification": {
    "commandsRun": [
      {"command": "uv run pytest -x -q", "exitCode": 0, "observation": "205 passed in 4.1s"},
      {"command": "uv run pyright", "exitCode": 0, "observation": "0 errors"},
      {"command": "uv run ruff check .", "exitCode": 0, "observation": "All checks passed"},
      {"command": "curl -X POST localhost:9849/reminders -H 'Content-Type: application/json' -d '{\"title\":\"Test\"}'", "exitCode": 0, "observation": "201 with ok:true"},
      {"command": "curl localhost:9849/reminders?list_name=Reminders", "exitCode": 0, "observation": "JSON array with reminders including 'Test'"}
    ],
    "interactiveChecks": [
      {"action": "Would launch TUI, press Ctrl+6 to switch to Reminders tab", "observed": "Reminders tab renders with ReminderItem widgets showing title, due date, list name"},
      {"action": "Would type 'Buy groceries' in compose and press Enter", "observed": "New reminder created, appears in list after refresh"},
      {"action": "Would press 'c' on a selected reminder", "observed": "Reminder marked complete, disappears from active list"}
    ]
  },
  "tests": {
    "added": [
      {
        "file": "tests/test_server_endpoints.py",
        "cases": [
          {"name": "test_edit_reminder", "verifies": "PUT /reminders/{id} updates title and due date"},
          {"name": "test_delete_reminder", "verifies": "DELETE /reminders/{id} removes reminder"},
          {"name": "test_reminders_filter_by_list", "verifies": "GET /reminders?list_name=X returns only X list"}
        ]
      },
      {
        "file": "tests/test_tui_reminders.py",
        "cases": [
          {"name": "test_reminders_tab_switch", "verifies": "Ctrl+6 activates Reminders tab"},
          {"name": "test_reminder_create_from_compose", "verifies": "Enter in compose creates reminder"},
          {"name": "test_reminder_complete", "verifies": "'c' key completes selected reminder"},
          {"name": "test_reminders_empty_state", "verifies": "Empty list shows 'No reminders' message"}
        ]
      }
    ]
  },
  "discoveredIssues": []
}
```

## When to Return to Orchestrator

- Feature depends on an API endpoint that doesn't exist yet and isn't in this feature's scope
- The TUI widget hierarchy needs architectural changes beyond adding new widgets
- Existing tests fail in ways unrelated to your feature
- Requirements are ambiguous (e.g., unclear keybinding assignment)
- Resource constraints prevent testing (e.g., LLM model too large to load)
