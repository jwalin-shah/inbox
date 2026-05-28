from __future__ import annotations

from argparse import Namespace

from scripts import open_ready_export_links, request_personal_data_exports
from scripts import track_data_export_browser as browser_tracker
from scripts import watch_data_export_emails as email_watch


def provider_by_key(model: dict, key: str) -> dict:
    return next(provider for provider in model["providers"] if provider["key"] == key)


def test_status_model_normalizes_existing_state_without_migration():
    state = {
        "updated_at": "2026-05-27T10:00:00",
        "providers": {
            "github": {
                "status": "ready_email_seen",
                "opened_at": "2026-05-27T09:00:00",
                "requested_at": "2026-05-27T09:05:00",
                "last_email_at": "2026-05-27T09:30:00",
                "last_email_title": "Your data export is ready to download",
                "email_events": [{"id": "m1"}],
            }
        },
    }

    model = request_personal_data_exports.build_status_model(state)
    github = provider_by_key(model, "github")
    linkedin = provider_by_key(model, "linkedin")

    assert model["schema"] == "inbox.data_exports.status.v1"
    assert github["stage"] == "ready"
    assert github["ready"] == {"ready_at": "2026-05-27T09:30:00", "source": "email"}
    assert github["manual_boundary"] == "open_download_link_manually"
    assert linkedin["status"] == "not_started"
    assert linkedin["manual_boundary"] == "open_request_page"


def test_email_watch_promotes_confirmation_then_ready_without_downgrade():
    state = {"providers": {"github": {"status": "request_submitted_manually"}}}
    email_watch.update_provider_status(
        state,
        [
            {
                "id": "m1",
                "provider": "github",
                "timestamp": "2026-05-27T10:00:00",
                "title": "Your data export is ready to download",
                "snippet": "Archive is ready.",
                "is_new": True,
            },
            {
                "id": "m2",
                "provider": "github",
                "timestamp": "2026-05-27T09:00:00",
                "title": "Request received",
                "snippet": "We are preparing your export.",
                "is_new": True,
            },
        ],
    )

    provider = state["providers"]["github"]
    assert provider["status"] == "ready_email_seen"
    assert [event["id"] for event in provider["email_events"]] == ["m1", "m2"]


def test_email_watch_preserves_ready_metadata_when_later_email_is_downgrade():
    state = {
        "providers": {
            "github": {
                "status": "ready_email_seen",
                "last_email_at": "2026-05-27T10:00:00",
                "last_email_title": "Your data export is ready to download",
                "last_email_snippet": "Archive is ready.",
            }
        }
    }

    email_watch.update_provider_status(
        state,
        [
            {
                "id": "m2",
                "provider": "github",
                "timestamp": "2026-05-27T11:00:00",
                "title": "Request received",
                "snippet": "We are preparing your export.",
                "is_new": True,
            }
        ],
    )

    provider = state["providers"]["github"]
    assert provider["status"] == "ready_email_seen"
    assert provider["last_email_at"] == "2026-05-27T10:00:00"
    assert provider["last_email_title"] == "Your data export is ready to download"
    assert provider["last_email_snippet"] == "Archive is ready."
    assert provider["email_events"][0]["status"] == "confirmation_email_seen"


def test_email_watch_keeps_newest_ready_metadata():
    state = {"providers": {"apple": {"status": "confirmation_email_seen"}}}

    email_watch.update_provider_status(
        state,
        [
            {
                "id": "newer",
                "provider": "apple",
                "timestamp": "2026-05-24T16:47:34",
                "title": "Your download request is complete.",
                "snippet": "The data download you requested is now complete.",
                "is_new": True,
            },
            {
                "id": "older",
                "provider": "apple",
                "timestamp": "2026-05-17T13:21:04",
                "title": "Your download request is complete.",
                "snippet": "The data download you requested is now complete.",
                "is_new": True,
            },
        ],
    )

    provider = state["providers"]["apple"]
    assert provider["status"] == "ready_email_seen"
    assert provider["last_email_at"] == "2026-05-24T16:47:34"
    assert provider["last_email_title"] == "Your download request is complete."


def test_email_watch_filters_unknown_resume_export_noise():
    hits = [
        {
            "id": "resume",
            "provider": "unknown",
            "timestamp": "2026-05-27T19:32:26",
            "title": "Forward Deployed Engineer - Jwalin Shah",
            "snippet": "Forward Deployed Engineer - Jwalin Shah",
            "is_new": True,
        },
        {
            "id": "linkedin",
            "provider": "linkedin",
            "timestamp": "2026-05-27T20:00:00",
            "title": "Your LinkedIn data archive is ready",
            "snippet": "Download your archive.",
            "is_new": True,
        },
    ]

    filtered = email_watch.filter_export_hits(hits)

    assert [hit["id"] for hit in filtered] == ["linkedin"]


def test_email_watch_ignores_ready_email_from_prior_request_cycle():
    state = {
        "providers": {
            "linkedin": {
                "status": "request_submitted_manually",
                "requested_at": "2026-05-27T20:41:29",
            }
        }
    }

    email_watch.update_provider_status(
        state,
        [
            {
                "id": "old-ready",
                "provider": "linkedin",
                "timestamp": "2026-05-11T22:41:07",
                "title": "The first installment of your LinkedIn data archive is ready!",
                "snippet": "Download your archive.",
                "is_new": False,
            }
        ],
    )

    provider = state["providers"]["linkedin"]
    assert provider["status"] == "request_submitted_manually"
    assert "last_email_at" not in provider


def test_browser_tracker_records_request_ui_but_preserves_ready_state():
    state = {"providers": {"linkedin": {"status": "ready_email_seen"}}}
    page = browser_tracker.BrowserPage(
        target_id="tab-1",
        websocket_url="ws://127.0.0.1/devtools/page/1",
        url="https://www.linkedin.com/mypreferences/d/download-my-data",
        title="Download your data",
    )

    browser_tracker.update_state_for_page(
        state,
        "linkedin",
        page,
        {
            "href": page.url,
            "title": page.title,
            "htmlLength": 100,
        },
        "request_ui_seen",
        "export request controls visible",
    )

    provider = state["providers"]["linkedin"]
    assert provider["status"] == "ready_email_seen"
    assert provider["last_browser_signal"] == "export request controls visible"


def test_mark_opened_and_requested_do_not_downgrade_ready_state(tmp_path):
    state_path = tmp_path / "exports.json"
    target = next(
        target for target in request_personal_data_exports.EXPORT_TARGETS if target.key == "github"
    )
    state_path.write_text(
        """
{
  "providers": {
    "github": {
      "status": "ready_email_seen",
      "last_email_at": "2026-05-27T10:00:00",
      "last_email_title": "Your data export is ready to download"
    }
  }
}
""".strip()
    )

    request_personal_data_exports.mark_opened(state_path, [target])
    request_personal_data_exports.mark_requested(state_path, [target])

    state = request_personal_data_exports.load_state(state_path)
    provider = state["providers"]["github"]
    assert provider["status"] == "ready_email_seen"
    assert provider["opened_count"] == 1
    assert provider["opened_at"]
    assert provider["requested_at"]
    assert provider["last_email_at"] == "2026-05-27T10:00:00"


def test_open_ready_links_records_download_as_terminal_processor_state(tmp_path):
    state_path = tmp_path / "exports.json"
    open_ready_export_links.update_state(
        state_path,
        [
            {
                "provider": "claude",
                "message_id": "msg-1",
                "subject": "Your data is ready for download",
                "domain": "claude.ai",
                "url": "https://claude.ai/download/export",
            }
        ],
        tmp_path / "downloads",
    )

    state = request_personal_data_exports.load_state(state_path)
    provider = state["providers"]["claude"]
    model = request_personal_data_exports.build_status_model(state)
    claude = provider_by_key(model, "claude")

    assert provider["status"] == "download_link_opened"
    assert claude["stage"] == "download"
    assert claude["download"]["event_count"] == 1


def test_open_ready_links_can_render_private_download_checklist(tmp_path):
    output_path = tmp_path / "ready-links.md"
    download_dir = tmp_path / "downloads"

    open_ready_export_links.write_links(
        output_path,
        [
            {
                "provider": "github",
                "message_id": "msg-1",
                "subject": "[GitHub] Your data export is ready to download",
                "domain": "github.com",
                "url": "https://github.com/settings/migration/download?token=secret",
            }
        ],
        download_dir,
    )

    text = output_path.read_text()
    assert "Personal Data Export Download Links" in text
    assert str(download_dir) in text
    assert "https://github.com/settings/migration/download?token=secret" in text
    assert "- Done: [ ] downloaded into `_downloads`" in text


def test_request_script_default_path_is_read_only(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        request_personal_data_exports,
        "parse_args",
        lambda: Namespace(
            providers=["github"],
            all=False,
            priority=False,
            list=False,
            status=False,
            json=False,
            state_path=str(tmp_path / "exports.json"),
            dry_run=False,
            open=False,
            record_only=False,
            mark_requested=False,
            delay=0,
            via_cdp=False,
            cdp_url="http://127.0.0.1:9222",
        ),
    )
    opened: list[str] = []
    monkeypatch.setattr(request_personal_data_exports.webbrowser, "open_new_tab", opened.append)

    assert request_personal_data_exports.main() == 0

    assert opened == []
    assert "Dry run only" in capsys.readouterr().out


def test_mark_expired_reopens_provider_request_lane(tmp_path):
    state_path = tmp_path / "exports.json"
    target = next(
        target for target in request_personal_data_exports.EXPORT_TARGETS if target.key == "openai"
    )
    state_path.write_text(
        """
{
  "providers": {
    "openai": {
      "status": "download_link_opened",
      "last_download_opened_at": "2026-05-27T10:00:00",
      "download_dir": "/tmp/downloads"
    }
  }
}
""".strip()
    )

    request_personal_data_exports.mark_expired(state_path, [target], "old signed link expired")

    model = request_personal_data_exports.build_status_model(
        request_personal_data_exports.load_state(state_path)
    )
    openai = provider_by_key(model, "openai")

    assert openai["status"] == "download_link_expired"
    assert openai["stage"] == "request"
    assert openai["manual_boundary"] == "re_request_export_in_browser"
    assert openai["download"]["expired_reason"] == "old signed link expired"


def test_mark_requested_starts_new_cycle_after_expired_download_link(tmp_path):
    state_path = tmp_path / "exports.json"
    target = next(
        target
        for target in request_personal_data_exports.EXPORT_TARGETS
        if target.key == "linkedin"
    )
    state_path.write_text(
        """
{
  "providers": {
    "linkedin": {
      "status": "download_link_expired",
      "last_download_expired_at": "2026-05-27T10:00:00",
      "download_expired_reason": "old signed link expired"
    }
  }
}
""".strip()
    )

    request_personal_data_exports.mark_requested(state_path, [target])

    model = request_personal_data_exports.build_status_model(
        request_personal_data_exports.load_state(state_path)
    )
    linkedin = provider_by_key(model, "linkedin")

    assert linkedin["status"] == "request_submitted_manually"
    assert linkedin["stage"] == "status"
    assert linkedin["manual_boundary"] == "wait_for_ready_email_or_status"
    assert linkedin["download"]["expired_at"] == ""
    assert linkedin["download"]["expired_reason"] == ""


def test_status_model_treats_old_ready_email_as_prior_request_cycle():
    state = {
        "providers": {
            "linkedin": {
                "status": "ready_email_seen",
                "requested_at": "2026-05-27T20:41:29",
                "last_email_at": "2026-05-11T22:41:07",
                "last_email_title": "The first installment of your LinkedIn data archive is ready!",
            }
        }
    }

    model = request_personal_data_exports.build_status_model(state)
    linkedin = provider_by_key(model, "linkedin")

    assert linkedin["status"] == "request_submitted_manually"
    assert linkedin["stage"] == "status"
    assert linkedin["manual_boundary"] == "wait_for_ready_email_or_status"
