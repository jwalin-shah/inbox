"""Command palette registry, fuzzy filter, and NLP intent routing."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tui_tabs import TUI_TABS

# ── Command data model ───────────────────────────────────────────────────────

CommandDict = dict[str, Any]
LlmAvailabilityProvider = Callable[[], bool]
JsonGenerator = Callable[[str, type[Any]], Any]
NlpClassifier = Callable[[str, list[CommandDict]], dict[str, Any] | None]


@dataclass(frozen=True)
class CommandSpec:
    id: str
    label: str
    category: str
    description: str
    action_name: str

    def bind(self, app: Any) -> CommandDict:
        def action() -> None:
            getattr(app, self.action_name)()

        return make_command(self.id, self.label, self.description, self.category, action)


def make_command(
    id: str,
    name: str,
    description: str,
    category: str,
    action: Callable[[], None],
) -> CommandDict:
    return {
        "id": id,
        "name": name,
        "description": description,
        "category": category,
        "action": action,
    }


COMMAND_REGISTRY: tuple[CommandSpec, ...] = (
    *(
        CommandSpec(
            id=tab["command_id"],
            label=tab["command_name"],
            category="Navigate",
            description=tab["command_description"],
            action_name=tab["action"],
        )
        for tab in TUI_TABS
    ),
    CommandSpec(
        id="refresh",
        label="Refresh",
        category="Action",
        description="Reload all data from server",
        action_name="action_refresh",
    ),
    CommandSpec(
        id="quit",
        label="Quit",
        category="Action",
        description="Exit the application",
        action_name="action_quit",
    ),
    CommandSpec(
        id="toggle_ambient",
        label="Toggle Ambient Listening",
        category="Action",
        description="Start or stop ambient audio capture",
        action_name="action_toggle_ambient",
    ),
    CommandSpec(
        id="mark_all_gh_read",
        label="Mark All GitHub Notifications Read",
        category="Action",
        description="Mark all GitHub notifications as read",
        action_name="action_mark_all_notifications_read",
    ),
    CommandSpec(
        id="ask_inbox_assistant",
        label="Ask Inbox Assistant",
        category="AI",
        description="Run a readonly local assistant against the current Inbox context",
        action_name="action_ask_assistant",
    ),
    CommandSpec(
        id="new_event",
        label="New Calendar Event",
        category="Create",
        description="Create a new calendar event",
        action_name="action_new_event",
    ),
    CommandSpec(
        id="delete_event",
        label="Delete Calendar Event",
        category="Create",
        description="Delete the selected calendar event",
        action_name="action_delete_event",
    ),
    CommandSpec(
        id="jump_to_date",
        label="Jump to Date",
        category="Create",
        description="Navigate the calendar to a specific date",
        action_name="action_jump_to_date",
    ),
    CommandSpec(
        id="new_reminder",
        label="New Reminder",
        category="Create",
        description="Switch to Reminders tab to create a reminder",
        action_name="action_filter_rem",
    ),
    CommandSpec(
        id="filter_reminder_list",
        label="Filter Reminder List",
        category="Create",
        description="Filter by reminder list",
        action_name="action_filter_reminder_list",
    ),
    CommandSpec(
        id="gmail_compose",
        label="New Gmail Message",
        category="Create",
        description="Compose a new Gmail message",
        action_name="action_gmail_compose",
    ),
    CommandSpec(
        id="add_account",
        label="Add Google Account",
        category="Settings",
        description="Add a new Google account via OAuth",
        action_name="action_add_account",
    ),
    CommandSpec(
        id="reauth_account",
        label="Re-auth Account",
        category="Settings",
        description="Re-authenticate the current Google account",
        action_name="action_reauth_account",
    ),
)

COMMAND_SPECS: tuple[CommandSpec, ...] = COMMAND_REGISTRY


# ── Fuzzy filter ─────────────────────────────────────────────────────────────


def fuzzy_score(query: str, text: str) -> int:
    """Score query against text. Higher = better match. 0 = no match.

    Scoring tiers:
      3 — exact match (case-insensitive)
      2 — prefix match
      1 — substring match
      0 — no match
    """
    q = query.lower()
    t = text.lower()
    if not q:
        return 1  # empty query matches everything
    if q == t:
        return 3
    if t.startswith(q):
        return 2
    if q in t:
        return 1
    return 0


def filter_commands(query: str, commands: list[CommandDict]) -> list[CommandDict]:
    """Return commands matching query, sorted by score descending."""
    if not query.strip():
        return list(commands)

    scored: list[tuple[int, CommandDict]] = []
    for cmd in commands:
        # Score against name and description; name has higher weight
        name_score = fuzzy_score(query, cmd["name"]) * 2
        desc_score = fuzzy_score(query, cmd["description"])
        cat_score = fuzzy_score(query, cmd["category"])
        total = max(name_score, desc_score, cat_score)
        if total > 0:
            scored.append((total, cmd))

    scored.sort(key=lambda x: -x[0])
    return [cmd for _, cmd in scored]


# ── NLP intent routing ───────────────────────────────────────────────────────

NLP_PROMPT = """\
You are a command classifier for a terminal inbox app.
Given a natural-language query, identify which command best matches.

Available commands (id: name):
{command_list}

Query: {query}

Respond with JSON. If confident (>=0.6), output:
{{"command_id": "<id>", "confidence": <float>, "args": {{}}}}
If no good match:
{{"command_id": null, "reason": "<brief reason>"}}"""


def _build_command_list(commands: list[CommandDict]) -> str:
    return "\n".join(f"  {c['id']}: {c['name']}" for c in commands)


def llm_is_available(provider: LlmAvailabilityProvider | None = None) -> bool:
    """Return whether NLP classification can use the local LLM."""
    try:
        if provider is not None:
            return provider()

        import services

        return services.llm_is_loaded()
    except Exception:
        return False


def _generate_json(prompt: str, schema: type[Any]) -> Any:
    import services

    return services.generate_json(prompt, schema)


def _result_value(result: Any, key: str, default: Any) -> Any:
    if isinstance(result, dict):
        return result.get(key, default)
    return getattr(result, key, default)


def nlp_classify(
    query: str,
    commands: list[CommandDict],
    *,
    llm_available: LlmAvailabilityProvider | None = None,
    json_generator: JsonGenerator | None = None,
) -> dict[str, Any] | None:
    """Use the LLM to classify a natural-language query into a command.

    Returns a dict with command_id + confidence, or None if LLM is unavailable.
    """
    try:
        if not llm_is_available(llm_available):
            return None

        try:
            from pydantic import BaseModel as _Base
            from pydantic import Field as _Field

            class _NlpResult(_Base):
                command_id: str | None = None
                confidence: float = 0.0
                args: dict[str, Any] = _Field(default_factory=dict)
                reason: str = ""

        except ImportError:
            return None

        prompt = NLP_PROMPT.format(
            command_list=_build_command_list(commands),
            query=query,
        )
        generate = json_generator or _generate_json
        result = generate(prompt, _NlpResult)
        return {
            "command_id": _result_value(result, "command_id", None),
            "confidence": _result_value(result, "confidence", 0.0),
            "args": _result_value(result, "args", {}),
            "reason": _result_value(result, "reason", ""),
        }
    except Exception:
        return None


def resolve_nlp(
    query: str,
    commands: list[CommandDict],
    confidence_threshold: float = 0.6,
    *,
    classifier: NlpClassifier | None = None,
) -> tuple[CommandDict | None, str]:
    """Try NLP classification; return (matched_command_or_None, status_message).

    status_message is used for UI feedback.
    """
    classify = classifier or nlp_classify
    result = classify(query, commands)
    if result is None:
        return None, "LLM unavailable — try exact command name"

    cmd_id = result.get("command_id")
    confidence = result.get("confidence", 0.0)

    if cmd_id is None:
        reason = result.get("reason", "no match")
        return None, f"No command matches — {reason}"

    if confidence < confidence_threshold:
        # Find suggestions via fuzzy
        suggestions = [c["name"] for c in filter_commands(query, commands)[:3]]
        hint = ", ".join(suggestions) if suggestions else "try a different query"
        return None, f"Low confidence — try: {hint}"

    matched = next((c for c in commands if c["id"] == cmd_id), None)
    if matched is None:
        return None, f"Unknown command id: {cmd_id}"

    return matched, ""


# ── Command registry builder ─────────────────────────────────────────────────


def build_commands(app: Any) -> list[CommandDict]:
    """Build the full command list by binding to the app's action_ methods."""
    return [spec.bind(app) for spec in COMMAND_REGISTRY]
