from person_store import PersonProfileStore, person_id_for_external


def test_person_store_keeps_external_identity_and_local_profile_data_separate(tmp_path):
    store = PersonProfileStore(tmp_path / "people.sqlite3")
    person_id = store.ensure_external_contact(
        {
            "id": "harsh@example.com",
            "name": "Harsh Shah",
            "emails": ["harsh@example.com"],
            "phones": ["+1 (408) 555-0100"],
        }
    )

    note = store.add_note(person_id, body="Met through street-play practice.")
    relationship = store.add_relationship(
        person_id,
        label="friend",
        context="Confirmed by Jwalin",
    )
    profile = store.get_profile(person_id)

    assert person_id == person_id_for_external("HARSH@EXAMPLE.COM")
    assert profile["person"]["display_name"] == "Harsh Shah"
    assert {item["kind"] for item in profile["identifiers"]} >= {"contact_id", "email", "phone"}
    assert profile["notes"][0]["note_id"] == note["note_id"]
    assert profile["relationships"][0]["relationship_id"] == relationship["relationship_id"]
    assert profile["authority_rule"]


def test_person_store_does_not_auto_merge_different_external_ids(tmp_path):
    store = PersonProfileStore(tmp_path / "people.sqlite3")
    first = store.ensure_external_contact({"id": "alice@example.com", "name": "Alice"})
    second = store.ensure_external_contact({"id": "+1 408 555 0100", "name": "Alice"})

    assert first != second
    assert len(store.search("Alice")) == 2
