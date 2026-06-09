from imessage_link_helpers import extract_x_links


def test_extract_x_links_handles_https_and_bare_urls():
    text = (
        "Check https://x.com/neural_avb/status/123?s=42 and "
        "twitter.com/foo/status/456 also x.com/bar/status/789."
    )

    assert extract_x_links(text) == [
        "https://x.com/neural_avb/status/123?s=42",
        "https://twitter.com/foo/status/456",
        "https://x.com/bar/status/789",
    ]


def test_extract_x_links_dedupes_and_strips_trailing_punct():
    text = "Same https://x.com/a/status/1), again https://x.com/a/status/1."

    assert extract_x_links(text) == ["https://x.com/a/status/1"]


def test_extract_x_links_ignores_unrelated_text():
    assert extract_x_links("No social links here.") == []
