from fastapi.testclient import TestClient

from person_store import PersonProfileStore
from tests.approval_helpers import wrap_approval_lease


def test_people_routes_keep_local_notes_separate_from_contacts(monkeypatch, tmp_path):
    import inbox_server

    inbox_server.state.person_store = PersonProfileStore(tmp_path / "people.sqlite3")
    monkeypatch.setattr(
        inbox_server,
        "contacts_search",
        lambda *_args: [
            {
                "id": "harsh@example.com",
                "name": "Harsh Shah",
                "emails": ["harsh@example.com"],
                "phones": [],
            }
        ],
    )

    with TestClient(inbox_server.app) as client:
        wrap_approval_lease(client)
        found = client.get("/people/search?q=Harsh")
        assert found.status_code == 200
        person_id = found.json()[0]["person"]["person_id"]

        note = client.post(
            f"/people/{person_id}/notes",
            json={"body": "Met through street-play practice."},
        )
        relationship = client.post(
            f"/people/{person_id}/relationships",
            json={"label": "friend", "context": "Confirmed by Jwalin"},
        )
        profile = client.get(f"/people/{person_id}/profile")

    assert note.status_code == 200
    assert relationship.status_code == 200
    assert profile.status_code == 200
    data = profile.json()
    assert data["notes"][0]["body"] == "Met through street-play practice."
    assert data["relationships"][0]["label"] == "friend"
    assert data["external_contact"]["name"] == "Harsh Shah"
    assert data["external_activity"]["status"] == "not_requested"
    assert data["attribution"]["read_only"] is True
