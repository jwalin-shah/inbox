import inbox_server
from identity_link_store import IdentityLinkStore


def test_identity_link_store_upserts_and_reads_provenance(tmp_path):
    store = IdentityLinkStore(tmp_path / "identity.sqlite3")
    first = store.add_link(
        canonical_person_id="person-sheet-1",
        canonical_name="Harsh",
        target_source="contacts",
        target_id="contact-1",
        target_name="Harsh Shah",
        source_refs=[{"source": "google_sheets", "id": "people-row-1"}],
    )
    second = store.add_link(
        canonical_person_id="person-sheet-1",
        canonical_name="Harsh",
        target_source="contacts",
        target_id="contact-1",
        target_name="Harsh Shah Updated",
        confidence=0.9,
        source_refs=[{"source": "manual", "id": "review-1"}],
    )

    assert first["link_id"] != ""
    assert second["link_id"] == first["link_id"]
    assert second["target_name"] == "Harsh Shah Updated"
    assert second["source_refs"] == [{"source": "manual", "id": "review-1"}]
    assert store.list_links(canonical_person_id="person-sheet-1") == [second]


def test_person_and_identity_writes_have_approval_rules():
    assert inbox_server._approval_rule_for_request("POST", "/people/person-1/notes") is not None
    assert inbox_server._approval_rule_for_request("POST", "/people/person-1/relationships") is not None
    assert inbox_server._approval_rule_for_request("POST", "/identity/links") is not None
