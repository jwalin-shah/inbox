"""Static registry of LifeOps observation sources and freshness policies."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SourceDefinition:
    source_id: str
    display_name: str
    source_type: str
    lifecycle: str
    capture_modes: tuple[str, ...]
    authority: str
    freshness_seconds: int | None
    readiness_route: str
    notes: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {"capture_modes": list(self.capture_modes)}


SOURCE_REGISTRY: tuple[SourceDefinition, ...] = (
    SourceDefinition(
        "gmail", "Gmail", "google_api", "live", ("periodic",),
        "Gmail", 1200, "/capture/health", "Incremental history sync is currently 20-minute cadence."
    ),
    SourceDefinition(
        "imessage", "Apple Messages", "local_db", "live", ("periodic",),
        "macOS Messages database", 1200, "/capture/health", "Native local read path; no outbound message action here."
    ),
    SourceDefinition(
        "google_calendar", "Google Calendar", "google_api", "live", ("periodic", "live_read"),
        "Google Calendar", 900, "/capture/health", "Calendar remains live-read outside the message index."
    ),
    SourceDefinition(
        "google_tasks", "Google Tasks", "google_api", "live", ("periodic", "live_read"),
        "Google Tasks", 1800, "/capture/health", "Tasks remain live-read outside the message index."
    ),
    SourceDefinition(
        "google_drive", "Google Drive", "google_api", "live", ("periodic", "live_read"),
        "Google Drive", 3600, "/capture/health", "Drive and document metadata are not copied into message SQLite."
    ),
    SourceDefinition(
        "google_sheets", "Google Sheets", "google_api", "live", ("periodic", "live_read"),
        "Google Drive/Sheets", 3600, "/capture/health", "Sheets are accessed through the Drive-backed connector."
    ),
    SourceDefinition(
        "google_docs", "Google Docs", "google_api", "live", ("periodic", "live_read"),
        "Google Drive/Docs", 3600, "/capture/health", "Docs are accessed through the Drive-backed connector."
    ),
    SourceDefinition(
        "apple_notes", "Apple Notes", "local_db", "live", ("periodic", "live_read"),
        "macOS Notes database", 3600, "/capture/health"
    ),
    SourceDefinition(
        "apple_reminders", "Apple Reminders", "local_db", "live", ("periodic", "live_read"),
        "macOS Reminders store", 3600, "/capture/health"
    ),
    SourceDefinition(
        "apple_contacts", "Apple Contacts", "local_db", "live", ("periodic", "live_read"),
        "macOS AddressBook database", 3600, "/capture/health",
        "Read-only local contact records; notes and relationship claims remain in LifeOps separately.",
    ),
    SourceDefinition(
        "github_notifications", "GitHub Notifications", "external_api", "live", ("periodic", "live_read"),
        "GitHub", 1800, "/capture/health"
    ),
    SourceDefinition(
        "linkedin", "LinkedIn", "browser_or_export", "blocked", ("periodic", "live_read"),
        "LinkedIn Messaging via local OpenHuman export", 1800, "/capture/health",
        "No readable linkedin_data.db is currently present; scanner use requires an explicit signed-in LinkedIn browser session.",
    ),
    SourceDefinition(
        "manual", "Manual Capture", "user_input", "live", ("manual",),
        "User-provided observation", None, "/sources/registry", "Frictionless capture; interpretation happens later."
    ),
    SourceDefinition(
        "browser_share", "Browser Share", "user_input", "planned", ("manual",),
        "User share sheet", None, "/sources/registry"
    ),
    SourceDefinition(
        "location", "Location", "macos_service", "planned", ("push", "periodic"),
        "macOS location services", 60, "/sources/registry"
    ),
    SourceDefinition(
        "sensors", "Physical Sensors", "device", "planned", ("push", "periodic"),
        "Local device or sensor adapter", None, "/sources/registry"
    ),
)


def list_source_definitions() -> list[dict[str, object]]:
    return [source.to_dict() for source in SOURCE_REGISTRY]
