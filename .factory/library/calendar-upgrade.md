# Calendar Upgrade

## Round 1 (shipped)
- **Date range query**: `calendar_events(range_start, range_end)` replaces single-day bounds. `GET /calendar/events?start=X&end=Y` returns events in range; `?date=X` still works for backward compat.
- **Attendees**: `CalendarEvent.attendees: list[dict]` with name/email/responseStatus extracted from Google item.
- **Jump-to-date**: Ctrl+G opens date input overlay. Invalid dates show error toast.

## Round 2 (deferred — in roadmap)
- Arrow-key date navigation (left/right = prev/next day, month wrap, today badge).
- Week view (7-day columns, scrollable, v to toggle day/week/agenda) — must use range API to avoid 7 round trips.
- Agenda view (chronological list across days).
- Inline event editing (e key: title, start/end, location; Enter saves, Escape reverts).
- Multiday event rendering + attendees display in detail pane.
