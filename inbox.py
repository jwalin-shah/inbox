"""
Unified inbox TUI — iMessage + Gmail + Calendar + Notes
Thin client that connects to inbox_server.py via HTTP.
Auto-starts the server on launch.
"""

from __future__ import annotations

import os
import time
import webbrowser
from datetime import date, datetime, timedelta

import httpx
from rich.align import Align
from rich.panel import Panel
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.reactive import reactive
from textual.screen import Screen
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
        if d.get("_favorite"):
            t.append("⭐ ", style="bold yellow")

        if source == "gmail":
            snippet = d.get("snippet", "")
            if d.get("_starred"):
                t.append("★ ", style="bold yellow")
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


class ReminderItem(ListItem):
    def __init__(self, data: dict) -> None:
        super().__init__()
        self.data = data

    def compose(self) -> ComposeResult:
        d = self.data
        t = Text()
        t.append("☐ ", style="yellow")
        t.append(d.get("title", "Untitled"), style="bold white")
        due = d.get("due_date", "")
        list_name = d.get("list_name", "")
        line2_parts: list[str] = []
        if due:
            try:
                dt = datetime.fromisoformat(due)
                line2_parts.append(dt.strftime("%b %d"))
            except (ValueError, TypeError):
                line2_parts.append(due)
        else:
            line2_parts.append("No date")
        if list_name:
            line2_parts.append(list_name)
        line2 = " · ".join(line2_parts)
        if d.get("flagged"):
            t.append(" 🏴", style="red")
        if d.get("priority", 0) > 0:
            t.append(" ❗", style="yellow")
        if line2:
            t.append(f"\n  {line2}", style="dim")
        if d.get("notes"):
            snippet = d["notes"][:40]
            t.append(f"\n  {snippet}", style="dim italic")
        yield Static(t)


class DriveItem(ListItem):
    """Widget for a Google Drive file/folder in the sidebar."""

    _MIME_ICONS: dict[str, str] = {
        "application/vnd.google-apps.folder": "📁",
        "application/vnd.google-apps.document": "📝",
        "application/vnd.google-apps.spreadsheet": "📊",
        "application/vnd.google-apps.presentation": "📽️",
        "application/pdf": "📄",
        "image/": "🖼️",
        "video/": "🎬",
        "audio/": "🎵",
        "text/": "📄",
    }

    def __init__(self, data: dict) -> None:
        super().__init__()
        self.data = data

    @staticmethod
    def _icon_for_mime(mime: str) -> str:
        if mime in DriveItem._MIME_ICONS:
            return DriveItem._MIME_ICONS[mime]
        for prefix, icon in DriveItem._MIME_ICONS.items():
            if "/" in prefix and mime.startswith(prefix):
                return icon
        return "📄"

    @staticmethod
    def _human_size(size: int) -> str:
        if size <= 0:
            return ""
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.1f} {unit}" if unit != "B" else f"{size} {unit}"
            size /= 1024  # type: ignore[assignment]
        return f"{size:.1f} TB"

    def compose(self) -> ComposeResult:
        d = self.data
        mime = d.get("mime_type", "")
        t = Text()
        t.append(f"{self._icon_for_mime(mime)} ", style="dim")
        t.append(d.get("name", "Untitled"), style="bold white")

        line2_parts: list[str] = []
        mod = d.get("modified", "")
        if mod:
            try:
                dt = datetime.fromisoformat(mod)
                line2_parts.append(dt.strftime("%b %d %H:%M"))
            except (ValueError, TypeError):
                pass
        size = d.get("size", 0)
        human = self._human_size(size)
        if human:
            line2_parts.append(human)
        acct = d.get("account", "")
        if acct:
            line2_parts.append(acct.split("@")[0])
        if line2_parts:
            t.append(f"\n  {' · '.join(line2_parts)}", style="dim")
        yield Static(t)


class NotificationItem(ListItem):
    def __init__(self, data: dict) -> None:
        super().__init__()
        self.data = data

    def compose(self) -> ComposeResult:
        d = self.data
        t = Text()
        reason = d.get("reason", "")
        ntype = d.get("type", "")
        is_pr_review = reason == "review_requested" or ntype == "PullRequest"

        if is_pr_review:
            t.append("🔀 ", style="magenta bold")
        elif ntype == "Issue":
            t.append("🐛 ", style="dim")
        elif ntype == "Release":
            t.append("📦 ", style="dim")
        else:
            t.append("🔔 ", style="dim")

        # Title
        if d.get("unread"):
            t.append(d.get("title", "Untitled"), style="bold white")
        else:
            t.append(d.get("title", "Untitled"), style="white")

        if d.get("unread"):
            t.append(" ●", style="bold yellow")

        # Repo name + reason on line 2
        repo = d.get("repo", "")
        line2_parts: list[str] = []
        if repo:
            line2_parts.append(repo)
        if reason:
            # Make reason more human-readable
            reason_display = reason.replace("_", " ")
            line2_parts.append(reason_display)
        line2 = " · ".join(line2_parts)
        if line2:
            t.append(f"\n  {line2}", style="dim")

        # Timestamp on line 3
        ts = d.get("updated_at", "")
        if ts:
            try:
                dt = datetime.fromisoformat(ts)
                time_str = dt.strftime("%b %d %H:%M")
                t.append(f"\n  {time_str}", style="dim")
            except (ValueError, TypeError):
                pass

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
            # Append attachment metadata if present
            atts = msg.get("attachments", [])
            if atts:
                att_parts = []
                for att in atts:
                    fname = att.get("filename", "file")
                    size = att.get("size", 0)
                    if size >= 1024 * 1024:
                        size_str = f"{size / (1024 * 1024):.1f} MB"
                    elif size >= 1024:
                        size_str = f"{size / 1024:.1f} KB"
                    else:
                        size_str = f"{size} B"
                    att_parts.append(f"📎 {fname} ({size_str})")
                body = body + "\n" + "\n".join(att_parts)

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
            # Attendees
            attendees = d.get("attendees", [])
            if attendees:
                t.append("\n👥 Attendees\n", style="bold")
                for att in attendees:
                    name = att.get("name") or att.get("email", "?")
                    email = att.get("email", "")
                    status = att.get("responseStatus", "")
                    icon = {
                        "accepted": "✅",
                        "declined": "❌",
                        "tentative": "❓",
                        "needsAction": "⏳",
                    }.get(status, "•")
                    label = name
                    if email and email != name:
                        label += f" ({email})"
                    t.append(f"  {icon} {label}\n", style="white")
            if d.get("account"):
                t.append(f"\n[{d['account']}]", style="dim italic")

        elif d.get("completed") is not None and "list_name" in d:
            # Reminder — identified by completed field + list_name
            t.append(f"{d['title']}\n", style="bold white")
            t.append("─" * 40 + "\n", style="dim")
            if d.get("completed"):
                t.append("✅ Completed\n", style="green")
            else:
                t.append("☐ Incomplete\n", style="yellow")
            if d.get("due_date"):
                try:
                    dt = datetime.fromisoformat(d["due_date"])
                    t.append(f"📅 Due: {dt.strftime('%b %d, %Y %H:%M')}\n", style="cyan")
                except (ValueError, KeyError):
                    t.append(f"📅 Due: {d['due_date']}\n", style="cyan")
            else:
                t.append("📅 No due date\n", style="dim")
            if d.get("list_name"):
                t.append(f"📋 List: {d['list_name']}\n", style="dim")
            if d.get("priority", 0) > 0:
                t.append(f"❗ Priority: {d['priority']}\n", style="yellow")
            if d.get("flagged"):
                t.append("🏴 Flagged\n", style="red")
            if d.get("notes"):
                t.append(f"\n{d['notes']}\n", style="white")

        elif "reason" in d and "repo" in d:
            # GitHub notification — identified by reason + repo fields
            is_pr_review = d.get("reason") == "review_requested" or d.get("type") == "PullRequest"
            if is_pr_review:
                t.append("🔀 ", style="magenta bold")
            else:
                t.append("🔔 ", style="dim")
            t.append(f"{d.get('title', 'Untitled')}\n", style="bold white")
            t.append("─" * 40 + "\n", style="dim")
            t.append(f"📦 {d.get('repo', '?')}\n", style="cyan")
            reason = d.get("reason", "").replace("_", " ")
            t.append(f"📌 {reason}\n", style="yellow" if is_pr_review else "dim")
            ntype = d.get("type", "")
            if ntype:
                t.append(f"🏷  {ntype}\n", style="dim")
            if d.get("unread"):
                t.append("● Unread\n", style="bold yellow")
            else:
                t.append("  Read\n", style="dim")
            ts = d.get("updated_at", "")
            if ts:
                try:
                    dt = datetime.fromisoformat(ts)
                    t.append(f"🕐 {dt.strftime('%b %d, %Y %H:%M')}\n", style="dim")
                except (ValueError, TypeError):
                    pass
            url = d.get("url", "")
            if url:
                t.append(f"\n🔗 {url}\n", style="blue")
            t.append("\n", style="")
            t.append("[dim]r: mark read · R: read all · o: open in browser[/]\n", style="dim")

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


# ── Contact Profile Screen ───────────────────────────────────────────────────


class ContactProfileScreen(Screen):
    DEFAULT_CSS = """
    ContactProfileScreen {
        align: center middle;
    }
    #profile-container {
        width: 70;
        height: 35;
        border: solid $primary;
        background: $surface;
        padding: 1 2;
    }
    #profile-scroll {
        height: 1fr;
        overflow-y: auto;
    }
    """
    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, profile: dict) -> None:
        super().__init__()
        self._profile = profile

    def compose(self) -> ComposeResult:
        with Vertical(id="profile-container"):
            yield Static(self._render_header(), id="profile-header")
            with ScrollableContainer(id="profile-scroll"):
                yield Static(self._render_body(), id="profile-body")

    def _render_header(self) -> Text:
        contact = self._profile.get("contact", {})
        t = Text()
        name = contact.get("name", "Unknown")
        t.append(f"  {name}\n", style="bold white")
        t.append("─" * 40 + "\n", style="dim")
        for email in contact.get("emails", []):
            t.append(f"  {email}\n", style="cyan")
        for phone in contact.get("phones", []):
            t.append(f"  {phone}\n", style="green")
        counts = contact.get("source_counts", {})
        parts = []
        if counts.get("imessage"):
            parts.append(f"iMsg: {counts['imessage']}")
        if counts.get("gmail"):
            parts.append(f"Gmail: {counts['gmail']}")
        if counts.get("calendar"):
            parts.append(f"Cal: {counts['calendar']}")
        if parts:
            t.append("  " + "  ·  ".join(parts) + "\n", style="dim")
        t.append("[dim]Esc: close[/]\n", style="dim")
        return t

    def _render_body(self) -> Text:
        t = Text()
        timeline = self._profile.get("timeline", [])
        if not timeline:
            t.append("No activity found.\n", style="dim")
            return t
        t.append("\nTimeline\n", style="bold yellow")
        t.append("─" * 38 + "\n", style="dim")
        for item in timeline[:20]:
            src = item.get("source", "")
            src_label = {"imessage": "[iMsg]", "gmail": "[Gmail]", "calendar": "[Cal]"}.get(
                src, f"[{src}]"
            )
            ts_str = item.get("ts") or item.get("start", "")
            try:
                ts_label = datetime.fromisoformat(ts_str).strftime("%b %d %H:%M")
            except (ValueError, TypeError):
                ts_label = ""
            t.append(f"{src_label} ", style="dim")
            if ts_label:
                t.append(f"{ts_label}  ", style="dim cyan")
            body = item.get("body") or item.get("summary", "")
            sender = item.get("sender", "")
            if sender and not item.get("is_me"):
                t.append(f"{sender}: ", style="dim italic")
            t.append(f"{body[:80]}\n", style="white")
        return t

    def action_dismiss(self) -> None:
        self.app.pop_screen()


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
        Binding("ctrl+g", "jump_to_date", "Go to Date"),
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
        self.reminders_data: list[dict] = []
        self.reminder_lists: list[dict] = []
        self.github_data: list[dict] = []
        self.drive_data: list[dict] = []
        self.active_conv: dict | None = None
        self.active_event: dict | None = None
        self.active_reminder: dict | None = None
        self.active_notification: dict | None = None
        self.active_drive_file: dict | None = None
        self._active_filter: str = "all"
        self._rem_list_filter: str = ""  # "" = all lists
        self._editing_reminder: dict | None = None
        self._drive_folder_id: str = ""
        self._drive_folder_stack: list[str] = []
        self._drive_upload_mode: bool = False
        self._drive_new_folder_mode: bool = False
        self._editing_event: dict | None = None
        self._editing_event_field: str = ""  # current field being edited
        self._poll_timer = None
        self._client_closed = False
        self._poll_had_error = False
        self._consecutive_errors = 0
        # Calendar state
        self._calendar_date: date = date.today()
        self._calendar_view_mode: str = "day"  # "day" | "week" | "agenda"
        self._jump_to_date_mode: bool = False
        # Per-tab state: stores selected conversation, messages, detail, etc.
        # keyed by filter name ("all", "imessage", "gmail", "calendar", etc.)
        self._tab_state: dict[str, dict] = {}
        # Gmail compose state
        self._gmail_compose_mode: str = ""  # "" | "to" | "subject" | "body"
        self._gmail_compose_to: str = ""
        self._gmail_compose_subject: str = ""
        # Gmail label browsing
        self._gmail_label_filter: str = "INBOX"
        self._gmail_labels: list[dict] = []
        # Gmail starred conversations (local cache for ★ display)
        self._gmail_starred: set[str] = set()
        # Favorited contact IDs (persisted to ~/.config/inbox/favorites.json)
        self._favorites: set[str] = set()

    def _update_github_badge(self) -> None:
        """Update the GitHub tab label with the unread count badge.

        Attempts to update the tab label. If the label update doesn't
        render (a known Textual issue in some versions), the unread
        count is still visible in the status bar text.
        """
        unread = sum(1 for n in self.github_data if n.get("unread"))
        try:
            tabs = self.query_one("#tabs", Tabs)
            gh_tab = tabs.get_tab("tab-gh")
            if gh_tab is not None:
                label = f"GitHub ({unread})" if unread else "GitHub"
                gh_tab.label = label
        except Exception:
            pass

    def _notification_still_exists(self, notification: dict) -> bool:
        """Check whether a notification is still present in github_data.

        Returns False if github_data is empty or the notification's id
        is not found in the current list. Used to detect stale selections
        after data refreshes.
        """
        if not self.github_data:
            return False
        notif_id = notification.get("id")
        return any(n.get("id") == notif_id for n in self.github_data)

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

    def _save_tab_state(self, tab_name: str) -> None:
        """Save the current tab's state so it can be restored later."""
        state: dict = {}
        if tab_name in ("all", "imessage", "gmail"):
            state["active_conv"] = self.active_conv
            msg_view = self.query_one("#messages", MessageView)
            state["messages"] = list(msg_view.messages) if msg_view.messages else []
        elif tab_name == "calendar":
            state["active_event"] = self.active_event
            state["calendar_date"] = self._calendar_date
            state["calendar_view_mode"] = self._calendar_view_mode
            state["active_conv"] = None
        elif tab_name == "notes":
            # Note detail is in DetailView, already handled via detail reactive
            pass
        elif tab_name == "reminders":
            state["active_reminder"] = self.active_reminder
            state["rem_list_filter"] = self._rem_list_filter
            state["active_conv"] = None
        elif tab_name == "github":
            state["active_notification"] = self.active_notification
            state["active_conv"] = None
        elif tab_name == "drive":
            state["active_drive_file"] = self.active_drive_file
            state["drive_folder_id"] = self._drive_folder_id
            state["drive_folder_stack"] = list(self._drive_folder_stack)
            state["active_conv"] = None
        self._tab_state[tab_name] = state

    def _restore_tab_state(self, tab_name: str) -> None:
        """Restore a tab's previously saved state."""
        state = self._tab_state.get(tab_name, {})
        if not state:
            # No previously saved state for this tab — don't clear anything
            return

        if tab_name in ("all", "imessage", "gmail"):
            # Restore conversation selection and messages
            saved_conv = state.get("active_conv")
            saved_msgs = state.get("messages", [])
            self.active_conv = saved_conv
            self.active_event = None
            self.active_reminder = None
            msg_view = self.query_one("#messages", MessageView)
            if saved_msgs:
                msg_view.messages = saved_msgs
            elif saved_conv:
                # Re-load the thread if we have a conv but no cached messages
                self._load_thread(saved_conv)
            else:
                msg_view.messages = []
        elif tab_name == "calendar":
            self.active_event = state.get("active_event")
            self._calendar_date = state.get("calendar_date", date.today())
            self._calendar_view_mode = state.get("calendar_view_mode", "day")
            self.active_conv = None
            self.active_reminder = None
            if self.active_event:
                self.query_one("#detail-view", DetailView).detail = self.active_event
        elif tab_name == "reminders":
            self.active_reminder = state.get("active_reminder")
            self._rem_list_filter = state.get("rem_list_filter", "")
            self.active_conv = None
            self.active_event = None
            if self.active_reminder:
                self.query_one("#detail-view", DetailView).detail = self.active_reminder
        elif tab_name == "github":
            self.active_notification = state.get("active_notification")
            self.active_conv = None
            self.active_event = None
            self.active_reminder = None
            if self.active_notification:
                self.query_one("#detail-view", DetailView).detail = self.active_notification
        elif tab_name == "drive":
            self.active_drive_file = state.get("active_drive_file")
            self._drive_folder_id = state.get("drive_folder_id", "")
            self._drive_folder_stack = state.get("drive_folder_stack", [])
            self.active_conv = None
            self.active_event = None
            self.active_reminder = None
            self.active_notification = None
            if self.active_drive_file:
                self.query_one("#detail-view", DetailView).detail = self.active_drive_file
        else:
            # For tabs without saved state, just clear active selections
            self.active_conv = None
            self.active_event = None
            self.active_reminder = None

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
        new_filter = tab_map.get(event.tab.id or "", "all")
        # Save state of the tab we're leaving
        if self._active_filter != new_filter:
            self._save_tab_state(self._active_filter)
        self._active_filter = new_filter
        self._render_sidebar()
        self._toggle_views()
        # Restore state of the tab we're entering
        self._restore_tab_state(new_filter)
        # Re-highlight the selected item in the sidebar
        self._restore_sidebar_selection()
        # Auto-load drive files when switching to Drive tab
        if new_filter == "drive" and not self.drive_data:
            self._load_drive_files()

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
            elif self._active_filter == "drive":
                compose_input.placeholder = "Search Drive files… (Enter)"
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
            mode = self._calendar_view_mode
            if mode == "day":
                for e in self.events:
                    lv.append(EventItem(e))
            elif mode in ("week", "agenda"):
                # Group events by date
                events_by_date: dict[str, list[dict]] = {}
                for e in self.events:
                    try:
                        edate = datetime.fromisoformat(e["start"]).date()
                    except (ValueError, KeyError):
                        edate = self._calendar_date
                    key = edate.isoformat()
                    events_by_date.setdefault(key, []).append(e)

                if mode == "week":
                    weekday = self._calendar_date.weekday()
                    monday = self._calendar_date - timedelta(days=weekday)
                    days = [monday + timedelta(days=i) for i in range(7)]
                else:  # agenda
                    days = [self._calendar_date + timedelta(days=i) for i in range(14)]

                for d in days:
                    day_events = events_by_date.get(d.isoformat(), [])
                    # Also include multi-day all-day events
                    for e in self.events:
                        if e.get("all_day"):
                            try:
                                estart = datetime.fromisoformat(e["start"]).date()
                                eend = datetime.fromisoformat(e["end"]).date()
                                if estart < d < eend and e not in day_events:
                                    day_events.append(e)
                            except (ValueError, KeyError):
                                pass
                    is_today = d == date.today()
                    day_label = d.strftime("%a %b %d")
                    if is_today:
                        day_label = f"● {day_label} (today)"
                    header_style = "bold cyan" if is_today else "bold"
                    lv.append(ListItem(Static(Text(f"── {day_label} ──", style=header_style))))
                    if day_events:
                        for e in day_events:
                            lv.append(EventItem(e))
                    else:
                        lv.append(ListItem(Static(Text("  No events", style="dim"))))

            # Build status bar
            n_accts = len(set(e.get("account", "") for e in self.events if e.get("account")))
            date_label = self._calendar_date_label()
            mode_indicator = {
                "day": "📅 Day",
                "week": "📆 Week",
                "agenda": "📋 Agenda",
            }.get(mode, "")
            status = f"[cyan]{date_label}[/]  {mode_indicator}"
            if not self.events:
                status += "  [dim]No events[/]"
            else:
                status += f"  [dim]{len(self.events)} events[/]"
            if n_accts > 1:
                status += f"  [dim]{n_accts} accounts[/]"
            status += "  [dim]v: view · ←→: nav · g: go to date · e: edit[/]"
            self.query_one("#status", Static).update(status)
            return

        if self._active_filter == "notes":
            for n in self.notes_data:
                lv.append(NoteItem(n))
            status = f"[magenta]{len(self.notes_data)} notes[/]"
            self.query_one("#status", Static).update(status)
            return

        if self._active_filter == "reminders":
            filtered = self.reminders_data
            if self._rem_list_filter:
                filtered = [r for r in filtered if r.get("list_name") == self._rem_list_filter]
            if not filtered:
                lv.append(ListItem(Static(Text("  All caught up! 🎉", style="dim green"))))
            else:
                for r in filtered:
                    lv.append(ReminderItem(r))
            list_tag = f" · {self._rem_list_filter}" if self._rem_list_filter else ""
            status = f"[yellow]{len(filtered)} reminders{list_tag}[/]"
            if self.reminder_lists:
                list_names = ", ".join(
                    rl.get("name", "") for rl in self.reminder_lists if rl.get("name")
                )
                status += f"  [dim]f: filter ({list_names})[/]"
            self.query_one("#status", Static).update(status)
            return

        if self._active_filter == "github":
            if not self.github_data:
                lv.append(ListItem(Static(Text("  All clear! 🔔", style="dim green"))))
            else:
                for n in self.github_data:
                    lv.append(NotificationItem(n))
            unread = sum(1 for n in self.github_data if n.get("unread"))
            status = f"[magenta]{len(self.github_data)} notifications[/]"
            if unread:
                status += f"  [yellow]{unread} unread[/]"
            status += "  [dim]r: mark read · R: read all · o: open[/]"
            self.query_one("#status", Static).update(status)
            return

        if self._active_filter == "drive":
            if not self.drive_data:
                folder_msg = "This folder is empty" if self._drive_folder_id else "No files"
                lv.append(ListItem(Static(Text(f"  {folder_msg}", style="dim green"))))
            else:
                for f in self.drive_data:
                    lv.append(DriveItem(f))
            folder_tag = " (subfolder)" if self._drive_folder_id else ""
            status = f"[blue]{len(self.drive_data)} files{folder_tag}[/]"
            status += "  [dim]d: download · u: upload · n: new folder · x: delete[/]"
            if self._drive_folder_id:
                status += "  [dim]Bksp: back[/]"
            self.query_one("#status", Static).update(status)
            return

        if self._active_filter == "all":
            shown = self.conversations
        else:
            shown = [c for c in self.conversations if c.get("source") == self._active_filter]

        # Sort so favorites appear first
        def _is_favorite(c: dict) -> bool:
            cid = c.get("id", "")
            name = c.get("name", "")
            reply_to = c.get("reply_to", "")
            return (
                cid in self._favorites
                or name.lower() in self._favorites
                or reply_to.lower() in self._favorites
            )

        shown = sorted(shown, key=lambda c: 0 if _is_favorite(c) else 1)

        for c in shown:
            # Mark starred conversations for display
            if c.get("source") == "gmail" and c.get("id") in self._gmail_starred:
                c["_starred"] = True
            # Mark favorites for display
            c["_favorite"] = _is_favorite(c)
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
        if self._active_filter == "gmail":
            label_display = self._gmail_label_filter
            status += f"  [cyan]{label_display}[/]"
            status += (
                "  [dim]a:archive d:delete s:star r:read u:unread c:compose l:label D:download[/]"
            )
        else:
            status += f"  [dim]{tab_label}[/]"
        self.query_one("#status", Static).update(status)

    def _restore_sidebar_selection(self) -> None:
        """After _render_sidebar populates the ListView, restore the
        previously selected item (if any) for the active tab."""
        lv = self.query_one("#contact-list", ListView)
        target_index = -1

        if self._active_filter in ("all", "imessage", "gmail") and self.active_conv:
            conv_id = self.active_conv.get("id")
            source = self.active_conv.get("source")
            for i, child in enumerate(lv.children):
                if (
                    isinstance(child, ConversationItem)
                    and child.data.get("id") == conv_id
                    and child.data.get("source") == source
                ):
                    target_index = i
                    break
        elif self._active_filter == "calendar" and self.active_event:
            event_id = self.active_event.get("event_id")
            for i, child in enumerate(lv.children):
                if isinstance(child, EventItem) and child.data.get("event_id") == event_id:
                    target_index = i
                    break
        elif self._active_filter == "reminders" and self.active_reminder:
            rem_id = self.active_reminder.get("id")
            for i, child in enumerate(lv.children):
                if isinstance(child, ReminderItem) and child.data.get("id") == rem_id:
                    target_index = i
                    break
        elif self._active_filter == "notes":
            # Notes restore is handled by _load_note in _restore_tab_state
            pass
        elif self._active_filter == "github" and self.active_notification:
            notif_id = self.active_notification.get("id")
            for i, child in enumerate(lv.children):
                if isinstance(child, NotificationItem) and child.data.get("id") == notif_id:
                    target_index = i
                    break
        elif self._active_filter == "drive" and self.active_drive_file:
            file_id = self.active_drive_file.get("id")
            for i, child in enumerate(lv.children):
                if isinstance(child, DriveItem) and child.data.get("id") == file_id:
                    target_index = i
                    break

        if target_index >= 0:
            lv.index = target_index

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
        # Load persisted favorites before connecting
        try:
            from services import load_favorites as _load_favs

            self._favorites = _load_favs()
        except Exception:
            pass
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
            (
                convos,
                events,
                notes,
                reminders,
                reminder_lists,
                github_data,
                status_override,
                changed,
            ) = self._collect_poll_data()
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
                self.call_from_thread(
                    self._populate,
                    convos,
                    events,
                    notes,
                    reminders,
                    reminder_lists,
                    github_data,
                    status_override,
                )
                return
            self.conversations = convos
            self.call_from_thread(self.query_one("#status", Static).update, status_override)
            return

        # Success path — reset counters
        self._consecutive_errors = 0
        if changed:
            self._poll_had_error = False
            self.call_from_thread(
                self._populate,
                convos,
                events,
                notes,
                reminders,
                reminder_lists,
                github_data,
                status_override,
            )
            return

        self.conversations = convos
        if self._poll_had_error:
            self._poll_had_error = False
            self.call_from_thread(self._render_sidebar)

    def _do_refresh(self) -> None:
        """Fetch all data from the server (runs in worker thread)."""
        convos, events, notes, reminders, reminder_lists, github_data, status_override = (
            self._collect_refresh_data()
        )
        self.call_from_thread(
            self._populate,
            convos,
            events,
            notes,
            reminders,
            reminder_lists,
            github_data,
            status_override,
        )

    def _populate(
        self,
        convos: list[dict],
        events: list[dict],
        notes: list[dict],
        reminders: list[dict] | None = None,
        reminder_lists: list[dict] | None = None,
        github_data: list[dict] | None = None,
        status_override: str | None = None,
    ) -> None:
        self.conversations = convos
        self.events = events
        self.notes_data = notes
        if reminders is not None:
            self.reminders_data = reminders
        if reminder_lists is not None:
            self.reminder_lists = reminder_lists
        if github_data is not None:
            self.github_data = github_data
            self._update_github_badge()
            # Clear active_notification if it's stale — either the data is
            # now empty or the previously selected notification is no longer
            # in the current list (e.g. marked-read on server, API refresh).
            if self.active_notification and not self._notification_still_exists(
                self.active_notification
            ):
                self.active_notification = None
                if self._active_filter == "github":
                    self.query_one("#detail-view", DetailView).detail = None
        self._render_sidebar()
        if status_override:
            self.query_one("#status", Static).update(status_override)

    def _merge_status_errors(self, errors: list[str]) -> str | None:
        unique_errors = list(dict.fromkeys(errors))
        if not unique_errors:
            return None
        return f"[red]{' · '.join(unique_errors)}[/]"

    def _collect_auxiliary_data(
        self,
    ) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict], list[str]]:
        events = self.events
        notes = self.notes_data
        reminders = self.reminders_data
        reminder_lists = self.reminder_lists
        github_data = self.github_data
        errors: list[str] = []

        try:
            events = self._fetch_calendar_for_view()
        except Exception as exc:
            errors.append(_format_request_error("Calendar refresh", exc))

        try:
            notes = self.client.notes(limit=50)
        except Exception as exc:
            errors.append(_format_request_error("Notes refresh", exc))

        try:
            reminders = self.client.reminders(limit=100)
        except Exception as exc:
            errors.append(_format_request_error("Reminders refresh", exc))

        try:
            reminder_lists = self.client.reminder_lists()
        except Exception as exc:
            errors.append(_format_request_error("Reminder lists refresh", exc))

        try:
            github_data = self.client.github_notifications()
        except Exception as exc:
            errors.append(_format_request_error("GitHub refresh", exc))

        return events, notes, reminders, reminder_lists, github_data, errors

    def _collect_refresh_data(
        self,
    ) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict], list[dict], str | None]:
        convos = self.conversations
        errors: list[str] = []

        try:
            convos = self.client.conversations(limit=100)
        except Exception as exc:
            errors.append(_format_request_error("Conversation refresh", exc))

        events, notes, reminders, reminder_lists, github_data, aux_errors = (
            self._collect_auxiliary_data()
        )
        errors.extend(aux_errors)
        return (
            convos,
            events,
            notes,
            reminders,
            reminder_lists,
            github_data,
            self._merge_status_errors(errors),
        )

    def _collect_poll_data(
        self,
    ) -> tuple[
        list[dict], list[dict], list[dict], list[dict], list[dict], list[dict], str | None, bool
    ]:
        try:
            convos = self.client.conversations(limit=100)
        except Exception as exc:
            return (
                self.conversations,
                self.events,
                self.notes_data,
                self.reminders_data,
                self.reminder_lists,
                self.github_data,
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
            return (
                convos,
                self.events,
                self.notes_data,
                self.reminders_data,
                self.reminder_lists,
                self.github_data,
                None,
                False,
            )

        events, notes, reminders, reminder_lists, github_data, errors = (
            self._collect_auxiliary_data()
        )
        return (
            convos,
            events,
            notes,
            reminders,
            reminder_lists,
            github_data,
            self._merge_status_errors(errors),
            True,
        )

    # ── Reminder key handling ─────────────────────────────────────────────

    def on_key(self, event) -> None:
        """Handle single-key shortcuts for the reminders and github tabs.

        Only active when the compose input is NOT focused, so typing
        in compose still works normally.
        """
        compose = self.query_one("#compose", Input)
        if compose.has_focus:
            return

        key = event.key
        # Global: p = open contact profile for selected conversation
        if (
            key == "p"
            and self.active_conv
            and self._active_filter
            in (
                "all",
                "imessage",
                "gmail",
            )
        ):
            event.prevent_default()
            self.action_show_contact_profile()
            return

        # Global: f = toggle favorite for selected conversation
        if (
            key == "f"
            and self.active_conv
            and self._active_filter
            in (
                "all",
                "imessage",
                "gmail",
            )
        ):
            event.prevent_default()
            self.action_toggle_favorite()
            return

        if self._active_filter == "calendar":
            key = event.key
            if key == "right":
                event.prevent_default()
                self._calendar_navigate(1)
            elif key == "left":
                event.prevent_default()
                self._calendar_navigate(-1)
            elif key == "v":
                event.prevent_default()
                self._cycle_calendar_view()
            elif key == "g":
                event.prevent_default()
                self._enter_jump_to_date()
            elif key == "e":
                event.prevent_default()
                self._enter_edit_event()

        elif self._active_filter == "reminders":
            key = event.key
            if key == "c":
                event.prevent_default()
                self.action_complete_reminder()
            elif key == "e":
                event.prevent_default()
                self.action_edit_reminder()
            elif key == "d":
                event.prevent_default()
                self.action_delete_reminder()
            elif key == "f":
                event.prevent_default()
                self.action_filter_reminder_list()

        elif self._active_filter == "gmail":
            key = event.key
            if key == "a":
                event.prevent_default()
                self.action_gmail_archive()
            elif key == "d":
                event.prevent_default()
                self.action_gmail_delete()
            elif key == "s":
                event.prevent_default()
                self.action_gmail_toggle_star()
            elif key == "r":
                event.prevent_default()
                self.action_gmail_mark_read()
            elif key == "u":
                event.prevent_default()
                self.action_gmail_mark_unread()
            elif key == "c":
                event.prevent_default()
                self.action_gmail_compose()
            elif key == "l":
                event.prevent_default()
                self.action_gmail_cycle_label()
            elif key == "shift+d":
                event.prevent_default()
                self.action_gmail_download_attachment()

        elif self._active_filter == "github":
            key = event.key
            if key == "r":
                event.prevent_default()
                self.action_mark_notification_read()
            elif key == "shift+r":
                event.prevent_default()
                self.action_mark_all_notifications_read()
            elif key == "o":
                event.prevent_default()
                self.action_open_notification_url()

        elif self._active_filter == "drive":
            key = event.key
            if key == "d":
                event.prevent_default()
                self.action_drive_download()
            elif key == "u":
                event.prevent_default()
                self.action_drive_upload()
            elif key == "n":
                event.prevent_default()
                self.action_drive_new_folder()
            elif key == "x":
                event.prevent_default()
                self.action_drive_delete()
            elif key == "o":
                event.prevent_default()
                self.action_drive_open_url()
            elif key in ("backspace", "escape"):
                if self._drive_folder_id:
                    event.prevent_default()
                    self.action_drive_go_back()

    # ── Selection ────────────────────────────────────────────────────────

    @on(ListView.Selected, "#contact-list")
    def on_item_selected(self, event: ListView.Selected) -> None:
        item = event.item

        if isinstance(item, DriveItem):
            d = item.data
            mime = d.get("mime_type", "")
            # If it's a folder, navigate into it
            if mime == "application/vnd.google-apps.folder":
                self._drive_folder_stack.append(self._drive_folder_id)
                self._drive_folder_id = d.get("id", "")
                self.active_drive_file = None
                self.query_one("#detail-view", DetailView).detail = None
                self._load_drive_files()
                return
            self.active_drive_file = d
            self.active_event = None
            self.active_reminder = None
            self.active_notification = None
            self.active_conv = None
            self.query_one("#detail-view", DetailView).detail = d
            name = d.get("name", "?")
            acct = d.get("account", "")
            tag = f" · {acct.split(chr(64))[0]}" if acct else ""
            self.query_one("#status", Static).update(f"[bold]{name}[/]  [dim]drive{tag}[/]")
            return

        if isinstance(item, NotificationItem):
            self.active_notification = item.data
            self.active_event = None
            self.active_reminder = None
            self.active_conv = None
            self.query_one("#detail-view", DetailView).detail = item.data
            title = item.data.get("title", "?")
            repo = item.data.get("repo", "")
            tag = f" · {repo}" if repo else ""
            self.query_one("#status", Static).update(f"[bold]{title}[/]  [dim]github{tag}[/]")
            return

        if isinstance(item, ReminderItem):
            self.active_reminder = item.data
            self.active_event = None
            self.query_one("#detail-view", DetailView).detail = item.data
            title = item.data.get("title", "?")
            list_name = item.data.get("list_name", "")
            tag = f" · {list_name}" if list_name else ""
            self.query_one("#status", Static).update(f"[bold]{title}[/]  [dim]reminder{tag}[/]")
            return

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

        # Handle Gmail compose flow
        if self._gmail_compose_mode:
            self._handle_gmail_compose_submit(text)
            return

        if self._active_filter == "calendar":
            # Handle jump-to-date mode
            if self._jump_to_date_mode:
                self._jump_to_date_mode = False
                compose = self.query_one("#compose", Input)
                compose.placeholder = "New event: Title 2pm-3pm @ Location (Enter)"
                parsed = self._parse_user_date(text)
                if parsed:
                    self._calendar_date = parsed
                    self._refresh_calendar_events()
                else:
                    self.query_one("#status", Static).update(
                        f"[red]Invalid date: '{text}' — try YYYY-MM-DD or 'May 1'[/]"
                    )
                return
            # Handle event editing mode
            if self._editing_event is not None:
                edit_target = self._editing_event
                self._editing_event = None
                self._editing_event_field = ""
                compose = self.query_one("#compose", Input)
                compose.placeholder = "New event: Title 2pm-3pm @ Location (Enter)"
                self._do_update_event(edit_target, summary=text)
                return
            self._create_quick_event(text)
            return

        if self._active_filter == "reminders":
            # If we're in edit mode, save the edit instead of creating new
            if hasattr(self, "_editing_reminder") and self._editing_reminder is not None:
                self._do_edit_reminder(self._editing_reminder, new_title=text)
                self._editing_reminder = None
                return
            self._create_reminder(text)
            return

        if self._active_filter == "drive":
            if getattr(self, "_drive_upload_mode", False):
                self._drive_upload_mode = False
                compose = self.query_one("#compose", Input)
                compose.placeholder = "Search Drive files… (Enter)"
                self._do_drive_upload(text)
                return
            if getattr(self, "_drive_new_folder_mode", False):
                self._drive_new_folder_mode = False
                compose = self.query_one("#compose", Input)
                compose.placeholder = "Search Drive files… (Enter)"
                self._do_drive_create_folder(text)
                return
            self._search_drive(text)
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

    # ── Calendar navigation & views ─────────────────────────────────────

    def _calendar_date_label(self) -> str:
        """Format the calendar date for the status bar."""
        d = self._calendar_date
        label = d.strftime("%a, %b %d, %Y")
        if d == date.today():
            label = f"Today · {label}"
        return label

    def _calendar_navigate(self, delta: int) -> None:
        """Navigate calendar by delta days (or weeks in week mode)."""
        if self._calendar_view_mode == "week":
            self._calendar_date += timedelta(days=7 * delta)
        else:
            self._calendar_date += timedelta(days=delta)
        self._refresh_calendar_events()

    def _cycle_calendar_view(self) -> None:
        """Cycle day → week → agenda → day."""
        modes = ["day", "week", "agenda"]
        idx = modes.index(self._calendar_view_mode)
        self._calendar_view_mode = modes[(idx + 1) % len(modes)]
        self._refresh_calendar_events()

    def _enter_jump_to_date(self) -> None:
        """Activate jump-to-date input mode."""
        if self._active_filter != "calendar":
            return
        self._jump_to_date_mode = True
        compose = self.query_one("#compose", Input)
        compose.placeholder = "Go to date: YYYY-MM-DD or 'May 1' (Enter to go, Esc to cancel)"
        compose.clear()
        compose.focus()
        self.query_one("#status", Static).update("[yellow]Type a date and press Enter[/]")

    def action_jump_to_date(self) -> None:
        """Ctrl+G handler for jump-to-date."""
        if self._active_filter != "calendar":
            return
        self._enter_jump_to_date()

    def _parse_user_date(self, text: str) -> date | None:
        """Try to parse a user-entered date string into a date object."""
        text = text.strip()
        if not text:
            return None
        # Try ISO format first: YYYY-MM-DD
        try:
            return date.fromisoformat(text)
        except ValueError:
            pass
        # Try common formats
        for fmt in ("%B %d", "%b %d", "%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%m/%d"):
            try:
                parsed = datetime.strptime(text, fmt)
                if parsed.year == 1900:
                    parsed = parsed.replace(year=date.today().year)
                return parsed.date()
            except ValueError:
                continue
        return None

    def _enter_edit_event(self) -> None:
        """Start editing the selected calendar event."""
        if self._active_filter != "calendar":
            return
        if not self.active_event or not self.active_event.get("event_id"):
            self.query_one("#status", Static).update("[yellow]No event selected[/]")
            return
        self._editing_event = self.active_event
        self._editing_event_field = "summary"
        compose = self.query_one("#compose", Input)
        compose.value = self.active_event.get("summary", "")
        compose.placeholder = "Edit title (Enter to save, Esc to cancel)"
        compose.focus()
        self.query_one("#status", Static).update(
            "[yellow]Editing event title — Enter to save, Esc to cancel[/]"
        )

    @work(thread=True, exit_on_error=False)
    def _do_update_event(self, event: dict, **fields: str | None) -> None:
        status_override = None
        try:
            ok = self.client.update_event(
                event_id=event["event_id"],
                calendar_id=event.get("calendar_id", "primary"),
                account=event.get("account", ""),
                **fields,
            )
        except Exception as exc:
            status_override = f"[red]{_format_request_error('Update event', exc)}[/]"
            ok = False

        if ok:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                "[green]Event updated[/]",
            )
            self._do_refresh_calendar()
        else:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                status_override or "[red]Failed to update event[/]",
            )

    @work(thread=True, exit_on_error=False)
    def _refresh_calendar_events(self) -> None:
        """Fetch events for the current calendar view and update sidebar."""
        try:
            events = self._fetch_calendar_for_view()
        except Exception as exc:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[red]{_format_request_error('Calendar refresh', exc)}[/]",
            )
            return
        self.call_from_thread(self._apply_calendar_events, events)

    def _fetch_calendar_for_view(self) -> list[dict]:
        """Fetch events from the server based on current view mode."""
        if self._calendar_view_mode == "day":
            return self.client.calendar_events(date=self._calendar_date.isoformat())
        elif self._calendar_view_mode == "week":
            # Compute Monday of the current week
            weekday = self._calendar_date.weekday()  # 0=Monday
            monday = self._calendar_date - timedelta(days=weekday)
            sunday = monday + timedelta(days=6)
            return self.client.calendar_events_range(monday.isoformat(), sunday.isoformat())
        else:  # agenda
            end_d = self._calendar_date + timedelta(days=13)
            return self.client.calendar_events_range(
                self._calendar_date.isoformat(), end_d.isoformat()
            )

    def _apply_calendar_events(self, events: list[dict]) -> None:
        """Apply fetched calendar events to the UI."""
        self.events = events
        self._render_sidebar()

    @work(thread=True, exit_on_error=False)
    def _do_refresh_calendar(self) -> None:
        """Refresh calendar data and full sidebar from worker thread."""
        try:
            events = self._fetch_calendar_for_view()
        except Exception as exc:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[red]{_format_request_error('Calendar refresh', exc)}[/]",
            )
            return
        self.call_from_thread(self._apply_calendar_events, events)

    # ── Reminder actions ────────────────────────────────────────────────

    @work(thread=True, exit_on_error=False)
    def _create_reminder(self, text: str) -> None:
        status_override = None
        try:
            list_name = self._rem_list_filter or "Reminders"
            ok = self.client.reminder_create(title=text, list_name=list_name)
        except Exception as exc:
            status_override = f"[red]{_format_request_error('Reminder creation', exc)}[/]"
            ok = False

        if ok:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                "[green]Reminder created[/]",
            )
            self._do_refresh()
        else:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                status_override or "[red]Failed to create reminder[/]",
            )

    def action_complete_reminder(self) -> None:
        if self._active_filter != "reminders":
            return
        if not self.active_reminder or not self.active_reminder.get("id"):
            self.query_one("#status", Static).update("[yellow]No reminder selected[/]")
            return
        title = self.active_reminder.get("title", "?")
        self.query_one("#status", Static).update(f"[yellow]Completing '{title}'...[/]")
        self._do_complete_reminder(self.active_reminder)

    @work(thread=True, exit_on_error=False)
    def _do_complete_reminder(self, reminder: dict) -> None:
        status_override = None
        try:
            ok = self.client.reminder_complete(reminder_id=reminder["id"])
        except Exception as exc:
            status_override = f"[red]{_format_request_error('Complete reminder', exc)}[/]"
            ok = False

        if ok:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[green]Completed '{reminder.get('title')}'[/]",
            )
            self.active_reminder = None
            self.query_one("#detail-view", DetailView).detail = None
            self._do_refresh()
        else:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                status_override or "[red]Failed to complete reminder[/]",
            )

    def action_edit_reminder(self) -> None:
        if self._active_filter != "reminders":
            return
        if not self.active_reminder or not self.active_reminder.get("id"):
            self.query_one("#status", Static).update("[yellow]No reminder selected[/]")
            return
        # Focus the compose input with current title as value for editing
        compose = self.query_one("#compose", Input)
        compose.value = self.active_reminder.get("title", "")
        compose.focus()
        self.query_one("#status", Static).update(
            "[yellow]Edit title in compose — Enter to save, Escape to cancel[/]"
        )
        self._editing_reminder = self.active_reminder

    def action_delete_reminder(self) -> None:
        if self._active_filter != "reminders":
            return
        if not self.active_reminder or not self.active_reminder.get("id"):
            self.query_one("#status", Static).update("[yellow]No reminder selected[/]")
            return
        title = self.active_reminder.get("title", "?")
        self.query_one("#status", Static).update(f"[yellow]Deleting '{title}'...[/]")
        self._do_delete_reminder(self.active_reminder)

    @work(thread=True, exit_on_error=False)
    def _do_delete_reminder(self, reminder: dict) -> None:
        status_override = None
        try:
            ok = self.client.reminder_delete(reminder_id=reminder["id"])
        except Exception as exc:
            status_override = f"[red]{_format_request_error('Delete reminder', exc)}[/]"
            ok = False

        if ok:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[green]Deleted '{reminder.get('title')}'[/]",
            )
            self.active_reminder = None
            self.query_one("#detail-view", DetailView).detail = None
            self._do_refresh()
        else:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                status_override or "[red]Failed to delete reminder[/]",
            )

    @work(thread=True, exit_on_error=False)
    def _do_edit_reminder(self, reminder: dict, new_title: str) -> None:
        status_override = None
        try:
            ok = self.client.reminder_edit(reminder_id=reminder["id"], title=new_title)
        except Exception as exc:
            status_override = f"[red]{_format_request_error('Edit reminder', exc)}[/]"
            ok = False

        if ok:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[green]Updated '{new_title}'[/]",
            )
            self.active_reminder = None
            self.query_one("#detail-view", DetailView).detail = None
            self._do_refresh()
        else:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                status_override or "[red]Failed to edit reminder[/]",
            )

    def action_filter_reminder_list(self) -> None:
        """Cycle through reminder lists as a filter, or show all."""
        if self._active_filter != "reminders":
            return
        if not self.reminder_lists:
            return
        list_names = [rl.get("name", "") for rl in self.reminder_lists if rl.get("name")]
        if not list_names:
            return
        if self._rem_list_filter == "":
            # No filter → first list
            self._rem_list_filter = list_names[0]
        else:
            # Find current index and advance
            try:
                idx = list_names.index(self._rem_list_filter)
                if idx + 1 < len(list_names):
                    self._rem_list_filter = list_names[idx + 1]
                else:
                    # Wrap around: back to all
                    self._rem_list_filter = ""
            except ValueError:
                self._rem_list_filter = list_names[0]
        # Clear active_reminder and detail view — the selected reminder may
        # no longer be visible after the filter change, and actions on a
        # stale reminder could target the wrong item.
        self.active_reminder = None
        self.query_one("#detail-view", DetailView).detail = None
        self._render_sidebar()

    # ── GitHub actions ────────────────────────────────────────────────────

    def action_mark_notification_read(self) -> None:
        """Mark the selected notification as read."""
        if self._active_filter != "github":
            return
        if not self.active_notification or not self.active_notification.get("id"):
            self.query_one("#status", Static).update("[yellow]No notification selected[/]")
            return
        # Guard against stale selection — the notification may have been
        # removed by a concurrent refresh or mark-all-read.
        if not self._notification_still_exists(self.active_notification):
            self.active_notification = None
            self.query_one("#detail-view", DetailView).detail = None
            self.query_one("#status", Static).update("[yellow]Notification no longer available[/]")
            return
        title = self.active_notification.get("title", "?")
        self.query_one("#status", Static).update(f"[yellow]Marking '{title}' as read...[/]")
        self._do_mark_notification_read(self.active_notification)

    @work(thread=True, exit_on_error=False)
    def _do_mark_notification_read(self, notification: dict) -> None:
        # Re-check in case data refreshed between action handler and worker start
        if not self._notification_still_exists(notification):
            self.call_from_thread(
                self.query_one("#status", Static).update,
                "[yellow]Notification no longer available[/]",
            )
            return
        status_override = None
        try:
            ok = self.client.github_mark_read(notification_id=notification["id"])
        except Exception as exc:
            status_override = f"[red]{_format_request_error('Mark read', exc)}[/]"
            ok = False

        if ok:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[green]Marked '{notification.get('title')}' as read[/]",
            )
            self._do_refresh()
        else:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                status_override or "[red]Failed to mark as read[/]",
            )

    def action_mark_all_notifications_read(self) -> None:
        """Mark all GitHub notifications as read."""
        if self._active_filter != "github":
            return
        count = sum(1 for n in self.github_data if n.get("unread"))
        if not count:
            self.query_one("#status", Static).update("[dim]All notifications already read[/]")
            return
        self.query_one("#status", Static).update(
            f"[yellow]Marking {count} notifications as read...[/]"
        )
        self._do_mark_all_notifications_read()

    @work(thread=True, exit_on_error=False)
    def _do_mark_all_notifications_read(self) -> None:
        status_override = None
        try:
            ok = self.client.github_mark_all_read()
        except Exception as exc:
            status_override = f"[red]{_format_request_error('Mark all read', exc)}[/]"
            ok = False

        if ok:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                "[green]All notifications marked as read[/]",
            )
            self._do_refresh()
        else:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                status_override or "[red]Failed to mark all as read[/]",
            )

    def action_open_notification_url(self) -> None:
        """Open the selected notification's URL in the system browser."""
        if self._active_filter != "github":
            return
        if not self.active_notification:
            self.query_one("#status", Static).update("[yellow]No notification selected[/]")
            return
        # Guard against stale selection — the notification may have been
        # removed by a concurrent refresh or mark-all-read.
        if not self._notification_still_exists(self.active_notification):
            self.active_notification = None
            self.query_one("#detail-view", DetailView).detail = None
            self.query_one("#status", Static).update("[yellow]Notification no longer available[/]")
            return
        url = self.active_notification.get("url", "")
        if not url:
            self.query_one("#status", Static).update("[yellow]No URL for this notification[/]")
            return
        webbrowser.open(url)
        self.query_one("#status", Static).update(
            f"[green]Opened {self.active_notification.get('title', 'notification')} in browser[/]"
        )

    # ── Drive actions ────────────────────────────────────────────────────

    @work(thread=True, exit_on_error=False)
    def _load_drive_files(self, query: str = "") -> None:
        """Fetch drive files for the current folder or search query."""
        try:
            files = self.client.drive_files(
                query=query,
                folder_id=self._drive_folder_id,
            )
        except Exception as e:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[red]{_format_request_error('Drive load', e)}[/]",
            )
            return
        self.call_from_thread(self._show_drive_files, files)

    def _show_drive_files(self, files: list[dict]) -> None:
        self.drive_data = files
        self._render_sidebar()

    @work(thread=True, exit_on_error=False)
    def _search_drive(self, query: str) -> None:
        """Search Drive files by name query."""
        try:
            files = self.client.drive_files(
                query=query,
                folder_id=self._drive_folder_id,
            )
        except Exception as e:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[red]{_format_request_error('Drive search', e)}[/]",
            )
            return
        self.call_from_thread(self._show_drive_files, files)

    def action_drive_go_back(self) -> None:
        """Navigate to parent folder."""
        if self._drive_folder_stack:
            self._drive_folder_id = self._drive_folder_stack.pop()
        else:
            self._drive_folder_id = ""
        self.active_drive_file = None
        self.query_one("#detail-view", DetailView).detail = None
        self._load_drive_files()

    def action_drive_download(self) -> None:
        """Download the selected Drive file to ~/Downloads/."""
        if self._active_filter != "drive":
            return
        if not self.active_drive_file or not self.active_drive_file.get("id"):
            self.query_one("#status", Static).update("[yellow]No file selected[/]")
            return
        name = self.active_drive_file.get("name", "file")
        self.query_one("#status", Static).update(f"[yellow]Downloading '{name}'...[/]")
        self._do_drive_download(self.active_drive_file)

    @work(thread=True, exit_on_error=False)
    def _do_drive_download(self, file_data: dict) -> None:
        from pathlib import Path as P

        try:
            content = self.client.drive_download(
                file_id=file_data["id"],
                account=file_data.get("account", ""),
            )
            downloads = P.home() / "Downloads"
            downloads.mkdir(exist_ok=True)
            dest = downloads / file_data.get("name", "download")
            dest.write_bytes(content)
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[green]Downloaded to {dest}[/]",
            )
        except Exception as exc:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[red]{_format_request_error('Download', exc)}[/]",
            )

    def action_drive_upload(self) -> None:
        """Upload a file to the current Drive folder."""
        if self._active_filter != "drive":
            return
        compose = self.query_one("#compose", Input)
        compose.placeholder = "Enter file path to upload (Enter to confirm)"
        compose.focus()
        self._drive_upload_mode = True
        self.query_one("#status", Static).update(
            "[yellow]Type file path and press Enter to upload, Escape to cancel[/]"
        )

    def action_drive_new_folder(self) -> None:
        """Create a new folder in the current Drive folder."""
        if self._active_filter != "drive":
            return
        compose = self.query_one("#compose", Input)
        compose.placeholder = "Enter folder name (Enter to create)"
        compose.focus()
        self._drive_new_folder_mode = True
        self.query_one("#status", Static).update(
            "[yellow]Type folder name and press Enter, Escape to cancel[/]"
        )

    def action_drive_delete(self) -> None:
        """Delete (trash) the selected Drive file."""
        if self._active_filter != "drive":
            return
        if not self.active_drive_file or not self.active_drive_file.get("id"):
            self.query_one("#status", Static).update("[yellow]No file selected[/]")
            return
        name = self.active_drive_file.get("name", "?")
        self.query_one("#status", Static).update(f"[yellow]Trashing '{name}'...[/]")
        self._do_drive_delete(self.active_drive_file)

    @work(thread=True, exit_on_error=False)
    def _do_drive_delete(self, file_data: dict) -> None:
        status_override = None
        try:
            ok = self.client.drive_delete(
                file_id=file_data["id"],
                account=file_data.get("account", ""),
            )
        except Exception as exc:
            status_override = f"[red]{_format_request_error('Delete', exc)}[/]"
            ok = False

        if ok:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[green]Trashed '{file_data.get('name')}'[/]",
            )
            self.call_from_thread(self._clear_drive_selection)
            self._load_drive_files()
        else:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                status_override or "[red]Failed to delete[/]",
            )

    def action_drive_open_url(self) -> None:
        """Open the selected Drive file's web link in the browser."""
        if self._active_filter != "drive":
            return
        if not self.active_drive_file:
            self.query_one("#status", Static).update("[yellow]No file selected[/]")
            return
        url = self.active_drive_file.get("web_link", "")
        if not url:
            self.query_one("#status", Static).update("[yellow]No URL for this file[/]")
            return
        webbrowser.open(url)
        self.query_one("#status", Static).update(
            f"[green]Opened {self.active_drive_file.get('name', 'file')} in browser[/]"
        )

    def _clear_drive_selection(self) -> None:
        self.active_drive_file = None
        self.query_one("#detail-view", DetailView).detail = None

    @work(thread=True, exit_on_error=False)
    def _do_drive_upload(self, file_path: str) -> None:
        try:
            result = self.client.drive_upload(
                file_path=file_path,
                folder_id=self._drive_folder_id,
            )
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[green]Uploaded '{result.get('name', file_path)}'[/]",
            )
            self._load_drive_files()
        except Exception as exc:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[red]{_format_request_error('Upload', exc)}[/]",
            )

    @work(thread=True, exit_on_error=False)
    def _do_drive_create_folder(self, name: str) -> None:
        try:
            result = self.client.drive_create_folder(
                name=name,
                parent_id=self._drive_folder_id,
            )
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[green]Created folder '{result.get('name', name)}'[/]",
            )
            self._load_drive_files()
        except Exception as exc:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[red]{_format_request_error('Create folder', exc)}[/]",
            )

    # ── Gmail actions ────────────────────────────────────────────────────

    def _get_active_gmail_conv(self) -> dict | None:
        """Get the currently selected Gmail conversation, or None."""
        if not self.active_conv:
            return None
        if self.active_conv.get("source") != "gmail":
            return None
        return self.active_conv

    def action_gmail_archive(self) -> None:
        conv = self._get_active_gmail_conv()
        if not conv:
            self.query_one("#status", Static).update("[yellow]No Gmail email selected[/]")
            return
        self.query_one("#status", Static).update("[yellow]Archiving...[/]")
        self._do_gmail_archive(conv)

    @work(thread=True, exit_on_error=False)
    def _do_gmail_archive(self, conv: dict) -> None:
        try:
            ok = self.client.gmail_archive(conv["id"])
        except Exception as exc:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[red]{_format_request_error('Archive', exc)}[/]",
            )
            return
        if ok:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                "[green]Archived[/]",
            )
            self._do_refresh()
        else:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                "[red]Failed to archive[/]",
            )

    def action_gmail_delete(self) -> None:
        conv = self._get_active_gmail_conv()
        if not conv:
            self.query_one("#status", Static).update("[yellow]No Gmail email selected[/]")
            return
        self.query_one("#status", Static).update("[yellow]Deleting...[/]")
        self._do_gmail_delete(conv)

    @work(thread=True, exit_on_error=False)
    def _do_gmail_delete(self, conv: dict) -> None:
        try:
            ok = self.client.gmail_delete(conv["id"])
        except Exception as exc:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[red]{_format_request_error('Delete', exc)}[/]",
            )
            return
        if ok:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                "[green]Deleted[/]",
            )
            self._do_refresh()
        else:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                "[red]Failed to delete[/]",
            )

    def action_gmail_toggle_star(self) -> None:
        conv = self._get_active_gmail_conv()
        if not conv:
            self.query_one("#status", Static).update("[yellow]No Gmail email selected[/]")
            return
        msg_id = conv["id"]
        is_starred = msg_id in self._gmail_starred
        if is_starred:
            self.query_one("#status", Static).update("[yellow]Unstarring...[/]")
        else:
            self.query_one("#status", Static).update("[yellow]Starring...[/]")
        self._do_gmail_toggle_star(conv, is_starred)

    @work(thread=True, exit_on_error=False)
    def _do_gmail_toggle_star(self, conv: dict, was_starred: bool) -> None:
        try:
            if was_starred:
                ok = self.client.gmail_unstar(conv["id"])
            else:
                ok = self.client.gmail_star(conv["id"])
        except Exception as exc:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[red]{_format_request_error('Star toggle', exc)}[/]",
            )
            return
        if ok:
            msg_id = conv["id"]
            if was_starred:
                self._gmail_starred.discard(msg_id)
                label = "Unstarred"
            else:
                self._gmail_starred.add(msg_id)
                label = "Starred ★"
            # Update the conversation data for immediate UI feedback
            conv["_starred"] = not was_starred
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[green]{label}[/]",
            )
            self.call_from_thread(self._render_sidebar)
        else:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                "[red]Failed to toggle star[/]",
            )

    def action_gmail_mark_read(self) -> None:
        conv = self._get_active_gmail_conv()
        if not conv:
            self.query_one("#status", Static).update("[yellow]No Gmail email selected[/]")
            return
        self.query_one("#status", Static).update("[yellow]Marking as read...[/]")
        self._do_gmail_mark_read(conv)

    @work(thread=True, exit_on_error=False)
    def _do_gmail_mark_read(self, conv: dict) -> None:
        try:
            ok = self.client.gmail_mark_read(conv["id"])
        except Exception as exc:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[red]{_format_request_error('Mark read', exc)}[/]",
            )
            return
        if ok:
            conv["unread"] = 0
            self.call_from_thread(
                self.query_one("#status", Static).update,
                "[green]Marked as read[/]",
            )
            self.call_from_thread(self._render_sidebar)
        else:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                "[red]Failed to mark as read[/]",
            )

    def action_gmail_mark_unread(self) -> None:
        conv = self._get_active_gmail_conv()
        if not conv:
            self.query_one("#status", Static).update("[yellow]No Gmail email selected[/]")
            return
        self.query_one("#status", Static).update("[yellow]Marking as unread...[/]")
        self._do_gmail_mark_unread(conv)

    @work(thread=True, exit_on_error=False)
    def _do_gmail_mark_unread(self, conv: dict) -> None:
        try:
            ok = self.client.gmail_mark_unread(conv["id"])
        except Exception as exc:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[red]{_format_request_error('Mark unread', exc)}[/]",
            )
            return
        if ok:
            conv["unread"] = 1
            self.call_from_thread(
                self.query_one("#status", Static).update,
                "[green]Marked as unread[/]",
            )
            self.call_from_thread(self._render_sidebar)
        else:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                "[red]Failed to mark as unread[/]",
            )

    def action_gmail_compose(self) -> None:
        """Start the multi-step compose flow for a new email."""
        self._gmail_compose_mode = "to"
        self._gmail_compose_to = ""
        self._gmail_compose_subject = ""
        compose = self.query_one("#compose", Input)
        compose.placeholder = "To: (email address)"
        compose.clear()
        compose.focus()
        self.query_one("#status", Static).update(
            "[cyan]Compose: Enter recipient email (Escape to cancel)[/]"
        )

    def _handle_gmail_compose_submit(self, text: str) -> None:
        """Handle compose flow steps: to -> subject -> body -> send."""
        compose = self.query_one("#compose", Input)

        if self._gmail_compose_mode == "to":
            if not text or "@" not in text:
                self.query_one("#status", Static).update("[red]Invalid email — must contain @[/]")
                return
            self._gmail_compose_to = text
            self._gmail_compose_mode = "subject"
            compose.placeholder = "Subject:"
            compose.clear()
            self.query_one("#status", Static).update(f"[cyan]To: {text} — Enter subject[/]")
        elif self._gmail_compose_mode == "subject":
            self._gmail_compose_subject = text
            self._gmail_compose_mode = "body"
            compose.placeholder = "Body: (Enter to send)"
            compose.clear()
            self.query_one("#status", Static).update(
                f"[cyan]To: {self._gmail_compose_to} · Subject: {text} — Enter body[/]"
            )
        elif self._gmail_compose_mode == "body":
            self._gmail_compose_mode = ""
            compose.placeholder = "Reply… (Enter to send)"
            compose.clear()
            self.query_one("#status", Static).update("[yellow]Sending...[/]")
            self._do_gmail_compose_send(self._gmail_compose_to, self._gmail_compose_subject, text)

    @work(thread=True, exit_on_error=False)
    def _do_gmail_compose_send(self, to: str, subject: str, body: str) -> None:
        try:
            ok = self.client.gmail_compose(to, subject, body)
        except Exception as exc:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[red]{_format_request_error('Compose send', exc)}[/]",
            )
            return
        if ok:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[green]Sent to {to}[/]",
            )
        else:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                "[red]Failed to send email[/]",
            )

    def action_gmail_cycle_label(self) -> None:
        """Cycle through Gmail labels to filter the conversation list."""
        self._do_gmail_cycle_label()

    @work(thread=True, exit_on_error=False)
    def _do_gmail_cycle_label(self) -> None:
        # Fetch labels if we haven't yet
        if not self._gmail_labels:
            try:
                self._gmail_labels = self.client.gmail_labels()
            except Exception:
                self._gmail_labels = []

        # Build label cycle: common labels + custom user labels
        common = ["INBOX", "SENT", "STARRED", "DRAFT"]
        custom = [
            lbl["id"] for lbl in self._gmail_labels if lbl.get("type") == "user" and lbl.get("id")
        ]
        cycle = common + custom

        # Find current and advance
        try:
            idx = cycle.index(self._gmail_label_filter)
            self._gmail_label_filter = cycle[(idx + 1) % len(cycle)]
        except ValueError:
            self._gmail_label_filter = cycle[0]

        label_name = self._gmail_label_filter
        # Resolve label name for display
        for lbl in self._gmail_labels:
            if lbl.get("id") == self._gmail_label_filter:
                label_name = lbl.get("name", label_name)
                break

        # Fetch conversations for this label
        try:
            convos = self.client.gmail_conversations_by_label(
                label=self._gmail_label_filter, limit=50
            )
        except Exception as exc:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[red]{_format_request_error('Label filter', exc)}[/]",
            )
            return

        # Update conversations with label-filtered results
        # Remove existing gmail convos and add the label-filtered ones
        non_gmail = [c for c in self.conversations if c.get("source") != "gmail"]
        self.conversations = non_gmail + convos
        self.call_from_thread(self._render_sidebar)
        self.call_from_thread(
            self.query_one("#status", Static).update,
            f"[cyan]Gmail label: {label_name}[/]  [dim]l: next label[/]",
        )

    def action_gmail_download_attachment(self) -> None:
        """Download the first attachment from the currently viewed thread."""
        mv = self.query_one("#messages", MessageView)
        if not mv.messages:
            self.query_one("#status", Static).update("[yellow]No messages loaded[/]")
            return
        # Find the first message with attachments
        for msg in mv.messages:
            atts = msg.get("attachments", [])
            if atts:
                att = atts[0]
                self.query_one("#status", Static).update(
                    f"[yellow]Downloading {att.get('filename', 'file')}...[/]"
                )
                self._do_gmail_download_attachment(att)
                return
        self.query_one("#status", Static).update("[yellow]No attachments in this thread[/]")

    @work(thread=True, exit_on_error=False)
    def _do_gmail_download_attachment(self, att: dict) -> None:
        import base64
        from pathlib import Path

        try:
            result = self.client.gmail_attachment(
                att.get("messageId", ""), att.get("attachmentId", "")
            )
            data_b64 = result.get("data", "")
            if not data_b64:
                self.call_from_thread(
                    self.query_one("#status", Static).update,
                    "[red]Empty attachment data[/]",
                )
                return
            raw = base64.urlsafe_b64decode(data_b64)
            filename = att.get("filename", "download")
            dest = Path.home() / "Downloads" / filename
            dest.write_bytes(raw)
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[green]Downloaded to ~/Downloads/{filename}[/]",
            )
        except Exception as exc:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"[red]{_format_request_error('Download', exc)}[/]",
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
        # Cancel Gmail compose flow
        if self._gmail_compose_mode:
            self._gmail_compose_mode = ""
            self._gmail_compose_to = ""
            self._gmail_compose_subject = ""
            compose = self.query_one("#compose", Input)
            compose.placeholder = "Reply… (Enter to send)"
            self.query_one("#status", Static).update("[dim]Compose cancelled[/]")
        # Cancel any in-progress reminder edit
        if hasattr(self, "_editing_reminder") and self._editing_reminder is not None:
            self._editing_reminder = None
            if self._active_filter == "reminders":
                self.query_one("#status", Static).update("[dim]Edit cancelled[/]")
        # Cancel drive upload/folder modes
        if getattr(self, "_drive_upload_mode", False):
            self._drive_upload_mode = False
            if self._active_filter == "drive":
                self.query_one("#compose", Input).placeholder = "Search Drive files… (Enter)"
                self.query_one("#status", Static).update("[dim]Upload cancelled[/]")
        if getattr(self, "_drive_new_folder_mode", False):
            self._drive_new_folder_mode = False
            if self._active_filter == "drive":
                self.query_one("#compose", Input).placeholder = "Search Drive files… (Enter)"
                self.query_one("#status", Static).update("[dim]Folder creation cancelled[/]")
        # Cancel calendar editing/jump-to-date modes
        if self._active_filter == "calendar":
            if self._jump_to_date_mode:
                self._jump_to_date_mode = False
                compose = self.query_one("#compose", Input)
                compose.placeholder = "New event: Title 2pm-3pm @ Location (Enter)"
                self.query_one("#status", Static).update("[dim]Jump cancelled[/]")
            if self._editing_event is not None:
                self._editing_event = None
                self._editing_event_field = ""
                compose = self.query_one("#compose", Input)
                compose.placeholder = "New event: Title 2pm-3pm @ Location (Enter)"
                self.query_one("#status", Static).update("[dim]Edit cancelled[/]")

    # ── Contact profile / favorites ──────────────────────────────────────

    def action_show_contact_profile(self) -> None:
        if not self.active_conv:
            return
        self._bg_load_profile(self.active_conv)

    @work(thread=True, exit_on_error=False)
    def _bg_load_profile(self, conv: dict) -> None:
        contact_id = conv.get("reply_to") or conv.get("name", "")
        if not contact_id:
            return
        try:
            profile = self.client.contacts_profile(contact_id)
        except Exception:
            self.call_from_thread(
                self.query_one("#status", Static).update,
                "[red]Profile load failed[/]",
            )
            return
        self.call_from_thread(self._open_profile_screen, profile)

    def _open_profile_screen(self, profile: dict) -> None:
        self.push_screen(ContactProfileScreen(profile))

    def action_toggle_favorite(self) -> None:
        if not self.active_conv:
            return
        contact_id = (self.active_conv.get("reply_to") or self.active_conv.get("name", "")).lower()
        if not contact_id:
            return
        if contact_id in self._favorites:
            self._favorites.discard(contact_id)
            msg = f"[dim]Removed {contact_id} from favorites[/]"
        else:
            self._favorites.add(contact_id)
            msg = f"[yellow]⭐ Added {contact_id} to favorites[/]"
        try:
            from services import save_favorites as _save_favs

            _save_favs(self._favorites)
        except Exception:
            pass
        self.query_one("#status", Static).update(msg)
        self._render_sidebar()

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
