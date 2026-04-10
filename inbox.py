"""
Unified inbox TUI — iMessage + Gmail + Calendar + Notes
Thin client that connects to inbox_server.py via HTTP.
Auto-starts the server on launch.
"""

from __future__ import annotations

import os
import time
from datetime import datetime

import httpx
from rich.align import Align
from rich.panel import Panel
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import (
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
    Tab,
    Tabs,
)

from inbox_client import InboxClient

DEFAULT_POLL_INTERVAL = 10.0


def _poll_interval_from_env() -> float:
    raw_value = os.environ.get("INBOX_POLL_INTERVAL", str(DEFAULT_POLL_INTERVAL)).strip()
    try:
        interval = float(raw_value)
    except ValueError:
        return DEFAULT_POLL_INTERVAL
    return interval if interval > 0 else DEFAULT_POLL_INTERVAL


def _format_request_error(action: str, exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        return f"{action} failed (HTTP {status_code})"
    if isinstance(exc, httpx.RequestError):
        return "Server unreachable — press Ctrl+R to retry"
    return f"{action} failed: {exc}"


# ── UI Widgets ───────────────────────────────────────────────────────────────


class ConversationItem(ListItem):
    def __init__(self, data: dict) -> None:
        super().__init__()
        self.data = data

    def compose(self) -> ComposeResult:
        d = self.data
        source = d.get("source", "")
        source_icon = "󰍦" if source == "imessage" else "󰊫"
        t = Text()
        t.append(f"{source_icon} ", style="dim")

        if source == "gmail":
            snippet = d.get("snippet", "")
            if d.get("unread"):
                t.append(snippet[:40] or "(no subject)", style="bold white")
                t.append(" ●", style="bold yellow")
            else:
                t.append(snippet[:40] or "(no subject)", style="white")
            ts = d.get("last_ts", "")
            try:
                dt = datetime.fromisoformat(ts)
                time_str = dt.strftime("%b %d %H:%M")
            except (ValueError, TypeError):
                time_str = ""
            name = d.get("name", "")[:20]
            t.append(f"\n  {name}", style="dim")
            acct = d.get("gmail_account", "")
            if acct:
                t.append(f" · {acct.split('@')[0]}", style="dim italic")
            if time_str:
                t.append(f"  {time_str}", style="dim")
        else:
            name = d.get("name", "?")
            if d.get("unread"):
                t.append(name, style="bold white")
                t.append(" ●", style="bold yellow")
            else:
                t.append(name, style="white")
            ts = d.get("last_ts", "")
            try:
                dt = datetime.fromisoformat(ts)
                time_str = dt.strftime("%H:%M")
            except (ValueError, TypeError):
                time_str = ""
            snippet = d.get("snippet", "")[:38]
            line2 = f"{time_str}  {snippet}" if time_str else snippet
            t.append(f"\n  {line2}", style="dim")

        yield Static(t)


class EventItem(ListItem):
    def __init__(self, data: dict) -> None:
        super().__init__()
        self.data = data

    def compose(self) -> ComposeResult:
        d = self.data
        t = Text()
        t.append("󰃮 ", style="dim")
        if d.get("all_day"):
            t.append("All day", style="cyan")
        else:
            try:
                start = datetime.fromisoformat(d["start"]).strftime("%H:%M")
                end = datetime.fromisoformat(d["end"]).strftime("%H:%M")
                t.append(f"{start}–{end}", style="cyan")
            except (ValueError, KeyError):
                t.append("???", style="cyan")
        t.append(f"  {d.get('summary', '?')}", style="bold white")
        loc = d.get("location", "")
        if loc:
            t.append(f"\n  📍 {loc}", style="dim")
        yield Static(t)


class NoteItem(ListItem):
    def __init__(self, data: dict) -> None:
        super().__init__()
        self.data = data

    def compose(self) -> ComposeResult:
        d = self.data
        t = Text()
        t.append("󰎞 ", style="dim")
        t.append(d.get("title", "Untitled"), style="bold white")
        snippet = d.get("snippet", "")[:40]
        folder = d.get("folder", "")
        line2 = ""
        if folder:
            line2 = f"{folder} · "
        line2 += snippet
        if line2:
            t.append(f"\n  {line2}", style="dim")
        yield Static(t)


class MessageView(Static):
    DEFAULT_CSS = """
    MessageView {
        padding: 1 2;
        overflow-y: auto;
    }
    """
    messages: reactive[list[dict]] = reactive([], recompose=True)

    def compose(self) -> ComposeResult:
        if not self.messages:
            yield Label("[dim]Select a conversation[/]")
            return
        for msg in self.messages:
            body = msg.get("body", "").strip()
            if not body:
                continue
            try:
                ts = datetime.fromisoformat(msg["ts"]).strftime("%H:%M")
            except (ValueError, KeyError):
                ts = ""
            body_text = Text(body)
            is_me = msg.get("is_me", False)
            if is_me:
                panel = Panel(
                    Align.right(body_text),
                    title=f"[dim]{ts}[/]",
                    title_align="right",
                    border_style="cyan",
                    padding=(0, 1),
                )
                yield Static(Align.right(panel))
            else:
                sender = msg.get("sender", "?")
                panel = Panel(
                    body_text,
                    title=f"[bold green]{sender}[/]  [dim]{ts}[/]",
                    title_align="left",
                    border_style="green",
                    padding=(0, 1),
                )
                yield Static(panel)

    def watch_messages(self) -> None:
        self.call_later(self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> None:
        self.scroll_end(animate=False)


class DetailView(Static):
    DEFAULT_CSS = """
    DetailView {
        padding: 1 2;
        overflow-y: auto;
    }
    """
    detail: reactive[dict | None] = reactive(None, recompose=True)

    def compose(self) -> ComposeResult:
        if not self.detail:
            yield Label("[dim]Select an item[/]")
            return
        d = self.detail
        t = Text()

        if "summary" in d:
            # Calendar event
            t.append(f"{d['summary']}\n", style="bold white")
            t.append("─" * 40 + "\n", style="dim")
            if d.get("all_day"):
                t.append("All day\n", style="cyan")
            else:
                try:
                    start = datetime.fromisoformat(d["start"]).strftime("%H:%M")
                    end = datetime.fromisoformat(d["end"]).strftime("%H:%M")
                    t.append(f"{start} – {end}\n", style="cyan")
                except (ValueError, KeyError):
                    pass
            if d.get("location"):
                t.append(f"\n📍 {d['location']}\n", style="green")
            if d.get("description"):
                t.append(f"\n{d['description']}\n", style="white")
            if d.get("account"):
                t.append(f"\n[{d['account']}]", style="dim italic")

        elif "title" in d:
            # Note
            t.append(f"{d['title']}\n", style="bold white")
            t.append("─" * 40 + "\n", style="dim")
            if d.get("folder"):
                t.append(f"📁 {d['folder']}\n", style="dim")
            if d.get("modified"):
                try:
                    mod = datetime.fromisoformat(d["modified"]).strftime("%b %d, %Y %H:%M")
                    t.append(f"Modified: {mod}\n", style="dim")
                except (ValueError, KeyError):
                    pass
            body = d.get("body", d.get("snippet", ""))
            if body:
                t.append(f"\n{body}\n", style="white")

        yield Static(t)


# ── Main App ─────────────────────────────────────────────────────────────────


class InboxApp(App):
    CSS = """
    Screen { layout: vertical; }
    #main { layout: horizontal; height: 1fr; }
    #sidebar {
        width: 32;
        border-right: solid $primary-darken-2;
        layout: vertical;
    }
    #tabs { height: 3; }
    Tabs { height: 3; }
    Tab { padding: 0 2; }
    #contact-list { height: 1fr; }
    #content { width: 1fr; layout: vertical; }
    #messages {
        height: 1fr;
        border-bottom: solid $primary-darken-2;
        overflow-y: auto;
        padding: 1 2;
    }
    #detail-view {
        height: 1fr;
        border-bottom: solid $primary-darken-2;
        overflow-y: auto;
        padding: 1 2;
    }
    #compose-area { height: 3; layout: horizontal; padding: 0 1; }
    #compose { width: 1fr; }
    #status { height: 1; padding: 0 1; color: $text-muted; }
    .hidden { display: none; }
    """

    BINDINGS = [
        Binding("ctrl+r", "refresh", "Refresh"),
        Binding("ctrl+1", "filter_all", "All"),
        Binding("ctrl+2", "filter_imsg", "iMessage"),
        Binding("ctrl+3", "filter_gmail", "Gmail"),
        Binding("ctrl+4", "filter_cal", "Calendar"),
        Binding("ctrl+5", "filter_notes", "Notes"),
        Binding("ctrl+6", "filter_rem", "Reminders"),
        Binding("ctrl+7", "filter_gh", "GitHub"),
        Binding("ctrl+8", "filter_drv", "Drive"),
        Binding("ctrl+shift+6", "toggle_ambient", "Ambient"),
        Binding("ctrl+a", "add_account", "Add Account"),
        Binding("ctrl+shift+a", "reauth_account", "Re-auth"),
        Binding("ctrl+n", "new_event", "New Event"),
        Binding("ctrl+d", "delete_event", "Delete Event"),
        Binding("escape", "clear_compose", "Clear"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    POLL_INTERVAL = _poll_interval_from_env()

    # After this many consecutive poll errors, show a persistent outage message
    _SUSTAINED_OUTAGE_THRESHOLD = 3

    def __init__(self) -> None:
        super().__init__()
        # Use longer timeout for first requests (data loading can be slow)
        self.client = InboxClient(timeout=60)
        self.conversations: list[dict] = []
        self.events: list[dict] = []
        self.notes_data: list[dict] = []
        self.active_conv: dict | None = None
        self.active_event: dict | None = None
        self._active_filter: str = "all"
        self._poll_timer = None
        self._client_closed = False
        self._poll_had_error = False
        self._consecutive_errors = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main"):
            with Vertical(id="sidebar"):
                yield Tabs(
                    Tab("All", id="tab-all"),
                    Tab("iMessage", id="tab-imsg"),
                    Tab("Gmail", id="tab-gmail"),
                    Tab("Calendar", id="tab-cal"),
                    Tab("Notes", id="tab-notes"),
                    Tab("Reminders", id="tab-rem"),
                    Tab("GitHub", id="tab-gh"),
                    Tab("Drive", id="tab-drv"),
                    id="tabs",
                )
                yield ListView(id="contact-list")
            with Vertical(id="content"):
                yield Static(id="status")
                yield MessageView(id="messages")
                yield DetailView(id="detail-view", classes="hidden")
                with Horizontal(id="compose-area"):
                    yield Input(
                        placeholder="Reply… (Enter to send)",
                        id="compose",
                    )
        yield Footer()

    # ── Tab switching ────────────────────────────────────────────────────

    @on(Tabs.TabActivated, "#tabs")
    def on_tab_activated(self, event: Tabs.TabActivated) -> None:
        tab_map = {
            "tab-all": "all",
            "tab-imsg": "imessage",
            "tab-gmail": "gmail",
            "tab-cal": "calendar",
            "tab-notes": "notes",
            "tab-rem": "reminders",
            "tab-gh": "github",
            "tab-drv": "drive",
        }
        self._active_filter = tab_map.get(event.tab.id or "", "all")
        self._render_sidebar()
        self._toggle_views()

    def _toggle_views(self) -> None:
        is_detail = self._active_filter in (
            "calendar",
            "notes",
            "reminders",
            "github",
            "drive",
        )
        msg_view = self.query_one("#messages", MessageView)
        det_view = self.query_one("#detail-view", DetailView)
        compose_input = self.query_one("#compose", Input)

        if is_detail:
            msg_view.add_class("hidden")
            det_view.remove_class("hidden")
            if self._active_filter == "calendar":
                compose_input.placeholder = "New event: Title 2pm-3pm @ Location (Enter)"
            elif self._active_filter == "reminders":
                compose_input.placeholder = "New reminder (Enter to create)"
            else:
                compose_input.placeholder = ""
        else:
            msg_view.remove_class("hidden")
            det_view.add_class("hidden")
            compose_input.placeholder = "Reply… (Enter to send)"

    def _render_sidebar(self) -> None:
        lv = self.query_one("#contact-list", ListView)
        lv.clear()

        if self._active_filter == "calendar":
            for e in self.events:
                lv.append(EventItem(e))
            n_accts = len(set(e.get("account", "") for e in self.events if e.get("account")))
            status = f"[cyan]{len(self.events)} events today[/]"
            if n_accts:
                status += f"  [dim]{n_accts} account{'s' if n_accts > 1 else ''}[/]"
            elif not self.events:
                status += "  [yellow]ctrl+a to add account[/]"
            self.query_one("#status", Static).update(status)
            return

        if self._active_filter == "notes":
            for n in self.notes_data:
                lv.append(NoteItem(n))
            status = f"[magenta]{len(self.notes_data)} notes[/]"
            self.query_one("#status", Static).update(status)
            return

        if self._active_filter == "reminders":
            self.query_one("#status", Static).update("[dim]Reminders[/]")
            return

        if self._active_filter == "github":
            self.query_one("#status", Static).update("[dim]GitHub Notifications[/]")
            return

        if self._active_filter == "drive":
            self.query_one("#status", Static).update("[dim]Google Drive[/]")
            return

        if self._active_filter == "all":
            shown = self.conversations
        else:
            shown = [c for c in self.conversations if c.get("source") == self._active_filter]

        for c in shown:
            lv.append(ConversationItem(c))

        unread = sum(c.get("unread", 0) for c in shown)
        tab_label = {
            "all": "All",
            "imessage": "iMessage",
            "gmail": "Gmail",
        }.get(self._active_filter, "")
        status = f"[green]{len(shown)} conversations[/]"
        if unread:
            status += f"  [yellow]{unread} unread[/]"
        status += f"  [dim]{tab_label}[/]"
        self.query_one("#status", Static).update(status)

    # ── Tab shortcuts ────────────────────────────────────────────────────

    def action_filter_all(self) -> None:
        self.query_one("#tabs", Tabs).active = "tab-all"

    def action_filter_imsg(self) -> None:
        self.query_one("#tabs", Tabs).active = "tab-imsg"

    def action_filter_gmail(self) -> None:
        self.query_one("#tabs", Tabs).active = "tab-gmail"

    def action_filter_cal(self) -> None:
        self.query_one("#tabs", Tabs).active = "tab-cal"

    def action_filter_notes(self) -> None:
        self.query_one("#tabs", Tabs).active = "tab-notes"

    def action_filter_rem(self) -> None:
        self.query_one("#tabs", Tabs).active = "tab-rem"

    def action_filter_gh(self) -> None:
        self.query_one("#tabs", Tabs).active = "tab-gh"

    def action_filter_drv(self) -> None:
        self.query_one("#tabs", Tabs).active = "tab-drv"

    def action_toggle_ambient(self) -> None:
        """Toggle ambient listening on/off."""
        self._do_toggle_ambient()

    @work(thread=True, exit_on_error=False)
    def _do_toggle_ambient(self) -> None:
        try:
            status = self.client.ambient_status()
            if status.get("ambient"):
                self.client.ambient_stop()
                self.call_from_thread(
                    self.query_one("#status", Static).update,
                    "[yellow]Ambient listening stopped[/]",
                )
            else:
                self.client.ambient_start()
                self.call_from_thread(
                    self.query_one("#status", Static).update,
                    "[green]Ambient listening started[/]",
                )
        except Exception as e:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[red]{_format_request_error('Ambient toggle', e)}[/]",
            )

    # ── Boot & refresh ───────────────────────────────────────────────────

    def on_mount(self) -> None:
        self.query_one("#status", Static).update("[dim]Starting server...[/]")
        self.boot()

    @work(thread=True, exit_on_error=False)
    def boot(self) -> None:
        try:
            self.client.ensure_server()
        except RuntimeError as e:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[red]{e}[/]",
            )
            # Start polling even if server boot fails — polling will keep
            # trying so the TUI recovers automatically when the server
            # comes back.
            self.call_from_thread(self._start_polling)
            return
        self.call_from_thread(
            self.query_one("#status", Static).update,
            "[dim]Server ready — loading...[/]",
        )
        self._do_refresh()
        self.call_from_thread(self._start_polling)

    def _start_polling(self) -> None:
        """Start the auto-refresh timer."""
        self._poll_timer = self.set_interval(self.POLL_INTERVAL, self._poll_refresh)

    def _poll_refresh(self) -> None:
        """Background poll — only refreshes if data changed."""
        self._bg_poll()

    def action_refresh(self) -> None:
        # Manual refresh resets outage counters so the user's explicit
        # retry always tries fresh, regardless of prior poll failures.
        self._consecutive_errors = 0
        self._bg_refresh()

    @work(thread=True, exit_on_error=False)
    def _bg_refresh(self) -> None:
        try:
            self._do_refresh()
        except Exception as exc:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[red]{_format_request_error('Refresh', exc)}[/]",
            )

    @work(thread=True, exit_on_error=False)
    def _bg_poll(self) -> None:
        """Lightweight poll — updates data without disrupting UI if unchanged."""
        try:
            convos, events, notes, status_override, changed = self._collect_poll_data()
        except Exception as exc:
            # Unhandled exception in poll data collection — keep the TUI alive
            self._consecutive_errors += 1
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[red]{_format_request_error('Auto-refresh', exc)}[/]",
            )
            return

        if status_override:
            self._consecutive_errors += 1
            self._poll_had_error = True
            if self._consecutive_errors >= self._SUSTAINED_OUTAGE_THRESHOLD:
                # Show persistent outage message that reminds user about retry
                status_override = "[red]Server unreachable — press Ctrl+R to retry[/]"
            if changed:
                self.call_from_thread(self._populate, convos, events, notes, status_override)
                return
            self.conversations = convos
            self.call_from_thread(self.query_one("#status", Static).update, status_override)
            return

        # Success path — reset counters
        self._consecutive_errors = 0
        if changed:
            self._poll_had_error = False
            self.call_from_thread(self._populate, convos, events, notes, status_override)
            return

        self.conversations = convos
        if self._poll_had_error:
            self._poll_had_error = False
            self.call_from_thread(self._render_sidebar)

    def _do_refresh(self) -> None:
        """Fetch all data from the server (runs in worker thread)."""
        convos, events, notes, status_override = self._collect_refresh_data()
        self.call_from_thread(self._populate, convos, events, notes, status_override)

    def _populate(
        self,
        convos: list[dict],
        events: list[dict],
        notes: list[dict],
        status_override: str | None = None,
    ) -> None:
        self.conversations = convos
        self.events = events
        self.notes_data = notes
        self._render_sidebar()
        if status_override:
            self.query_one("#status", Static).update(status_override)

    def _merge_status_errors(self, errors: list[str]) -> str | None:
        unique_errors = list(dict.fromkeys(errors))
        if not unique_errors:
            return None
        return f"[red]{' · '.join(unique_errors)}[/]"

    def _collect_auxiliary_data(self) -> tuple[list[dict], list[dict], list[str]]:
        events = self.events
        notes = self.notes_data
        errors: list[str] = []

        try:
            events = self.client.calendar_events()
        except Exception as exc:
            errors.append(_format_request_error("Calendar refresh", exc))

        try:
            notes = self.client.notes(limit=50)
        except Exception as exc:
            errors.append(_format_request_error("Notes refresh", exc))

        return events, notes, errors

    def _collect_refresh_data(self) -> tuple[list[dict], list[dict], list[dict], str | None]:
        convos = self.conversations
        errors: list[str] = []

        try:
            convos = self.client.conversations(limit=100)
        except Exception as exc:
            errors.append(_format_request_error("Conversation refresh", exc))

        events, notes, aux_errors = self._collect_auxiliary_data()
        errors.extend(aux_errors)
        return convos, events, notes, self._merge_status_errors(errors)

    def _collect_poll_data(self) -> tuple[list[dict], list[dict], list[dict], str | None, bool]:
        try:
            convos = self.client.conversations(limit=100)
        except Exception as exc:
            return (
                self.conversations,
                self.events,
                self.notes_data,
                self._merge_status_errors([_format_request_error("Auto-refresh", exc)]),
                False,
            )

        # Check if unread counts changed
        old_unread = sum(c.get("unread", 0) for c in self.conversations)
        new_unread = sum(c.get("unread", 0) for c in convos)
        old_ids = {c.get("id") for c in self.conversations}
        new_ids = {c.get("id") for c in convos}

        changed = (
            old_unread != new_unread or old_ids != new_ids or len(self.conversations) != len(convos)
        )

        if not changed:
            return convos, self.events, self.notes_data, None, False

        events, notes, errors = self._collect_auxiliary_data()
        return convos, events, notes, self._merge_status_errors(errors), True

    # ── Selection ────────────────────────────────────────────────────────

    @on(ListView.Selected, "#contact-list")
    def on_item_selected(self, event: ListView.Selected) -> None:
        item = event.item

        if isinstance(item, EventItem):
            self.active_event = item.data
            self.query_one("#detail-view", DetailView).detail = item.data
            return

        if isinstance(item, NoteItem):
            self.active_event = None
            self._load_note(item.data)
            return

        if isinstance(item, ConversationItem):
            self.active_conv = item.data
            self.active_event = None
            self._load_thread(item.data)

    @work(thread=True, exit_on_error=False)
    def _load_thread(self, conv: dict) -> None:
        try:
            msgs = self.client.messages(
                source=conv["source"],
                conv_id=conv["id"],
                thread_id=conv.get("thread_id", ""),
            )
        except Exception as e:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[red]{_format_request_error('Thread load', e)}[/]",
            )
            return
        self.call_from_thread(self._show_thread, msgs, conv)

    def _show_thread(self, msgs: list[dict], conv: dict) -> None:
        mv = self.query_one("#messages", MessageView)
        mv.messages = msgs
        mv.call_later(mv._scroll_to_bottom)
        name = conv.get("name", "?")
        source = conv.get("source", "")
        acct = conv.get("gmail_account", "")
        acct_tag = f" [{acct}]" if acct else ""
        if conv.get("is_group") and conv.get("members"):
            members = ", ".join(conv["members"][:5])
            if len(conv["members"]) > 5:
                members += f" +{len(conv['members']) - 5}"
            status = f"[bold]{name}[/]  [dim]Group · {members}[/]"
        else:
            status = f"[bold]{name}[/]  [dim]{source}{acct_tag}[/]"
        self.query_one("#status", Static).update(status)
        self.query_one("#compose", Input).focus()

    @work(thread=True, exit_on_error=False)
    def _load_note(self, note_data: dict) -> None:
        status_override = None
        try:
            full = self.client.note(note_data["id"])
        except Exception as exc:
            status_override = f"[red]{_format_request_error('Note load', exc)}[/]"
            full = note_data
        self.call_from_thread(self._show_note, full, status_override)

    def _show_note(self, note: dict, status_override: str | None = None) -> None:
        self.query_one("#detail-view", DetailView).detail = note
        if status_override:
            self.query_one("#status", Static).update(status_override)
            return
        title = note.get("title", "?")
        self.query_one("#status", Static).update(f"[bold]{title}[/]  [dim]note[/]")

    # ── Send / create ────────────────────────────────────────────────────

    @on(Input.Submitted, "#compose")
    def on_send(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        self.query_one("#compose", Input).clear()

        if self._active_filter == "calendar":
            self._create_quick_event(text)
            return

        if not self.active_conv:
            return

        # Optimistic UI
        mv = self.query_one("#messages", MessageView)
        optimistic = {
            "sender": "Me",
            "body": text,
            "ts": datetime.now().isoformat(),
            "is_me": True,
            "source": self.active_conv.get("source", ""),
        }
        mv.messages = [*mv.messages, optimistic]
        self._do_send(self.active_conv, text)

    @work(thread=True, exit_on_error=False)
    def _do_send(self, conv: dict, text: str) -> None:
        status = "[red]Failed to send[/]"
        try:
            ok = self.client.send(
                conv_id=conv["id"],
                source=conv["source"],
                text=text,
            )
        except Exception as exc:
            ok = False
            status = f"[red]{_format_request_error('Send', exc)}[/]"
        else:
            if ok:
                status = "[green]Sent[/]"
        self.call_from_thread(self.query_one("#status", Static).update, status)
        if ok and conv["source"] == "imessage":
            self._reload_after_send(conv, text)

    def _reload_after_send(self, conv: dict, sent_text: str) -> None:
        """Retry thread reload until the sent message appears in the DB."""

        for delay in (1.0, 2.0, 3.0):
            time.sleep(delay)
            try:
                msgs = self.client.messages(
                    source=conv["source"],
                    conv_id=conv["id"],
                    thread_id=conv.get("thread_id", ""),
                )
            except Exception:
                continue
            # Check if the DB has our sent message
            if any(
                m.get("is_me") and m.get("body", "").strip() == sent_text.strip() for m in msgs[-5:]
            ):
                self.call_from_thread(self._show_thread, msgs, conv)
                return

        # DB never caught up — keep the optimistic message visible,
        # just update status so the user knows
        self.call_from_thread(
            self.query_one("#status", Static).update,
            "[green]Sent[/] [dim](DB sync pending)[/]",
        )

    @work(thread=True, exit_on_error=False)
    def _create_quick_event(self, text: str) -> None:
        status_override = None
        try:
            result = self.client.create_quick_event(text)
            ok = result.get("ok", False)
        except Exception as exc:
            status_override = f"[red]{_format_request_error('Event creation', exc)}[/]"
            ok = False

        if ok:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                "[green]Event created[/]",
            )
            self._do_refresh()
        else:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                status_override or "[red]Failed to create event[/]",
            )

    # ── Calendar actions ─────────────────────────────────────────────────

    def action_new_event(self) -> None:
        if self._active_filter != "calendar":
            self.query_one("#tabs", Tabs).active = "tab-cal"
        self.query_one("#compose", Input).focus()

    def action_delete_event(self) -> None:
        if not self.active_event or not self.active_event.get("event_id"):
            self.query_one("#status", Static).update("[yellow]No event selected[/]")
            return
        self.query_one("#status", Static).update(
            f"[yellow]Deleting '{self.active_event.get('summary')}'...[/]"
        )
        self._do_delete_event(self.active_event)

    @work(thread=True, exit_on_error=False)
    def _do_delete_event(self, event: dict) -> None:
        status_override = None
        try:
            ok = self.client.delete_event(
                event_id=event["event_id"],
                calendar_id=event.get("calendar_id", "primary"),
                account=event.get("account", ""),
            )
        except Exception as exc:
            status_override = f"[red]{_format_request_error('Delete event', exc)}[/]"
            ok = False

        if ok:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[green]Deleted '{event.get('summary')}'[/]",
            )
            self._do_refresh()
        else:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                status_override or "[red]Failed to delete[/]",
            )

    # ── Account actions ──────────────────────────────────────────────────

    def action_add_account(self) -> None:
        self.query_one("#status", Static).update("[yellow]Opening browser for auth...[/]")
        self._do_add_account()

    @work(thread=True, exit_on_error=False)
    def _do_add_account(self) -> None:
        try:
            result = self.client.add_account()
            email = result.get("email", "")
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[green]Added {email} — refreshing...[/]",
            )
            self._do_refresh()
        except Exception as e:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[red]{_format_request_error('Auth', e)}[/]",
            )

    def action_reauth_account(self) -> None:
        email = ""
        if self.active_conv and self.active_conv.get("gmail_account"):
            email = self.active_conv["gmail_account"]
        if not email:
            try:
                accts = self.client.accounts()
                gmail_accts = accts.get("gmail", [])
                if gmail_accts:
                    email = gmail_accts[0]
            except Exception:
                pass
        if not email:
            self.query_one("#status", Static).update(
                "[yellow]No account to re-auth — ctrl+a to add[/]"
            )
            return
        self.query_one("#status", Static).update(f"[yellow]Re-authing {email}...[/]")
        self._do_reauth(email)

    @work(thread=True, exit_on_error=False)
    def _do_reauth(self, email: str) -> None:
        try:
            result = self.client.reauth_account(email)
            new_email = result.get("email", email)
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[green]Re-authed {new_email} — refreshing...[/]",
            )
            self._do_refresh()
        except Exception as e:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[red]{_format_request_error('Re-auth', e)}[/]",
            )

    # ── Misc ─────────────────────────────────────────────────────────────

    def _update_status_from_thread(self, message: str) -> None:
        """Safely update the status bar from a worker thread."""
        self.call_from_thread(self.query_one("#status", Static).update, message)

    def action_clear_compose(self) -> None:
        self.query_one("#compose", Input).clear()

    def _cleanup_resources(self) -> None:
        if self._poll_timer is not None:
            self._poll_timer.stop()
            self._poll_timer = None
        if not self._client_closed:
            self.client.close()
            self._client_closed = True

    def action_quit(self) -> None:
        self._cleanup_resources()
        self.exit()

    def on_unmount(self) -> None:
        self._cleanup_resources()


if __name__ == "__main__":
    app = InboxApp()
    app.run()
