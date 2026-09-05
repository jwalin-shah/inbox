# ORBIT_TASK — Inbox trigger engine (Slice A)

Capture sl.icA objective: arrival-triggered reactions in the inbox.
Slice A = an AutoSlash email price-drop trigger: detect new `from:autoslash.com`
mail via the existing Gmail search/`message_sync` cursor, classify the price
signal, and surface it as a notification/report (notify-only; no sends, no rebook).

Design principle: one trigger engine, pluggable sources (Slice A = AutoSlash/Gmail;
Slice B = iMessage reply think-through). Reuse existing scheduler + notification
generation; add the detection→reaction wiring, not a from-scratch system.

- Source cursor: Gmail `history_id` (message_sync) / gmail search newest-since
- Reaction: parse "lower rate" → structured alert → `/notifications`-style surface
- Follow-up: optional via existing scheduler (Slice B groundwork)
