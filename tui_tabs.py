"""Shared TUI tab metadata for InboxApp and command palette navigation."""

from __future__ import annotations

from typing import TypedDict


class TabMeta(TypedDict):
    id: str
    label: str
    textual_tab_id: str
    mode: str
    action: str
    command_id: str
    command_name: str
    command_description: str


TUI_TABS: tuple[TabMeta, ...] = (
    {
        "id": "all",
        "label": "Now",
        "textual_tab_id": "tab-all",
        "mode": "message",
        "action": "action_filter_all",
        "command_id": "switch_all",
        "command_name": "Switch to All",
        "command_description": "Show all conversations",
    },
    {
        "id": "actionable",
        "label": "Actionable",
        "textual_tab_id": "tab-act",
        "mode": "message",
        "action": "action_filter_actionable",
        "command_id": "switch_actionable",
        "command_name": "Switch to Actionable",
        "command_description": "Show actionable threads",
    },
    {
        "id": "waiting",
        "label": "Waiting On",
        "textual_tab_id": "tab-wait",
        "mode": "message",
        "action": "action_filter_waiting",
        "command_id": "switch_waiting",
        "command_name": "Switch to Waiting On",
        "command_description": "Show waiting-on threads",
    },
    {
        "id": "imessage",
        "label": "iMessage",
        "textual_tab_id": "tab-imsg",
        "mode": "message",
        "action": "action_filter_imsg",
        "command_id": "switch_imessage",
        "command_name": "Switch to iMessage",
        "command_description": "Show iMessage conversations",
    },
    {
        "id": "gmail",
        "label": "Gmail",
        "textual_tab_id": "tab-gmail",
        "mode": "message",
        "action": "action_filter_gmail",
        "command_id": "switch_gmail",
        "command_name": "Switch to Gmail",
        "command_description": "Show Gmail conversations",
    },
    {
        "id": "whatsapp",
        "label": "WhatsApp",
        "textual_tab_id": "tab-wa",
        "mode": "message",
        "action": "action_filter_whatsapp",
        "command_id": "switch_whatsapp",
        "command_name": "Switch to WhatsApp",
        "command_description": "Show WhatsApp conversations",
    },
    {
        "id": "linkedin",
        "label": "LinkedIn",
        "textual_tab_id": "tab-li",
        "mode": "message",
        "action": "action_filter_linkedin",
        "command_id": "switch_linkedin",
        "command_name": "Switch to LinkedIn",
        "command_description": "Show LinkedIn messages",
    },
    {
        "id": "calendar",
        "label": "Calendar",
        "textual_tab_id": "tab-cal",
        "mode": "detail",
        "action": "action_filter_cal",
        "command_id": "switch_calendar",
        "command_name": "Switch to Calendar",
        "command_description": "Show calendar events",
    },
    {
        "id": "notes",
        "label": "Notes",
        "textual_tab_id": "tab-notes",
        "mode": "detail",
        "action": "action_filter_notes",
        "command_id": "switch_notes",
        "command_name": "Switch to Notes",
        "command_description": "Show Apple Notes",
    },
    {
        "id": "reminders",
        "label": "Reminders",
        "textual_tab_id": "tab-rem",
        "mode": "detail",
        "action": "action_filter_rem",
        "command_id": "switch_reminders",
        "command_name": "Switch to Reminders",
        "command_description": "Show Apple Reminders",
    },
    {
        "id": "github",
        "label": "GitHub",
        "textual_tab_id": "tab-gh",
        "mode": "detail",
        "action": "action_filter_gh",
        "command_id": "switch_github",
        "command_name": "Switch to GitHub",
        "command_description": "Show GitHub notifications",
    },
    {
        "id": "drive",
        "label": "Drive",
        "textual_tab_id": "tab-drv",
        "mode": "detail",
        "action": "action_filter_drv",
        "command_id": "switch_drive",
        "command_name": "Switch to Drive",
        "command_description": "Show Google Drive files",
    },
    {
        "id": "health",
        "label": "Health",
        "textual_tab_id": "tab-health",
        "mode": "detail",
        "action": "action_filter_health",
        "command_id": "switch_health",
        "command_name": "Switch to Capture Health",
        "command_description": "Show source capture and egress health",
    },
)

TAB_BY_TEXTUAL_ID = {tab["textual_tab_id"]: tab for tab in TUI_TABS}
TAB_BY_ID = {tab["id"]: tab for tab in TUI_TABS}
