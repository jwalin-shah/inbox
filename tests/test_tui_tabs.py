from tui_tabs import TAB_BY_ID, TAB_BY_TEXTUAL_ID, TUI_TABS


def test_tui_tabs_have_unique_ids_and_textual_ids():
    ids = [tab["id"] for tab in TUI_TABS]
    textual_ids = [tab["textual_tab_id"] for tab in TUI_TABS]

    assert len(ids) == len(set(ids))
    assert len(textual_ids) == len(set(textual_ids))
    assert set(TAB_BY_ID) == set(ids)
    assert set(TAB_BY_TEXTUAL_ID) == set(textual_ids)


def test_tui_tabs_include_expected_detail_modes():
    detail_tabs = {tab["id"] for tab in TUI_TABS if tab["mode"] == "detail"}
    assert detail_tabs == {"calendar", "notes", "reminders", "github", "drive", "health", "ops"}
