import pytest

from memory_store import MemoryStore


def test_save_and_query_memory_entry(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    saved = store.save_entry(
        memory_type="person_preference",
        subject="Alice",
        content="Prefers concise replies.",
        source="email_thread",
        confidence=0.9,
    )

    assert saved["subject"] == "Alice"

    found = store.query_entries(query="concise", limit=5)
    assert len(found) == 1
    assert found[0]["memory_type"] == "person_preference"


def test_open_commitments_filter(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    store.save_entry(
        memory_type="commitment",
        subject="Tax filing",
        content="Finish draft by Friday.",
        status="open",
    )
    store.save_entry(
        memory_type="commitment",
        subject="Old task",
        content="Already done.",
        status="closed",
    )

    commitments = store.list_open_commitments()
    assert len(commitments) == 1
    assert commitments[0]["subject"] == "Tax filing"


# ── New tests for previously uncovered paths ──────────────────────────


def test_get_entry_not_found(tmp_path):
    """get_entry raises KeyError for a non-existent entry ID."""
    store = MemoryStore(tmp_path / "memory.sqlite3")
    with pytest.raises(KeyError, match="Memory entry 999 not found"):
        store.get_entry(999)


def test_query_by_subject(tmp_path):
    """query_entries filters by exact subject match."""
    store = MemoryStore(tmp_path / "memory.sqlite3")
    store.save_entry(memory_type="note", subject="Meeting notes", content="Q3 planning")
    store.save_entry(memory_type="note", subject="Random", content="Other stuff")

    results = store.query_entries(subject="Meeting notes")
    assert len(results) == 1
    assert results[0]["subject"] == "Meeting notes"


def test_query_by_status(tmp_path):
    """query_entries filters by status."""
    store = MemoryStore(tmp_path / "memory.sqlite3")
    store.save_entry(memory_type="task", subject="Active task", content="...", status="active")
    store.save_entry(memory_type="task", subject="Done task", content="...", status="closed")

    results = store.query_entries(status="closed")
    assert len(results) == 1
    assert results[0]["subject"] == "Done task"


def test_update_entry(tmp_path):
    """update_entry changes allowed fields and returns the updated entry."""
    store = MemoryStore(tmp_path / "memory.sqlite3")
    saved = store.save_entry(
        memory_type="task",
        subject="Original title",
        content="Original content",
    )

    updated = store.update_entry(
        saved["id"],
        subject="New title",
        confidence=0.95,
        status="closed",
    )

    assert updated["subject"] == "New title"
    assert updated["confidence"] == 0.95
    assert updated["status"] == "closed"
    # Unchanged fields stay
    assert updated["content"] == "Original content"
    # updated_at should have changed
    assert updated["updated_at"] != saved["updated_at"]


def test_update_entry_not_found(tmp_path):
    """update_entry raises KeyError for a non-existent entry ID."""
    store = MemoryStore(tmp_path / "memory.sqlite3")
    with pytest.raises(KeyError, match="Memory entry 999 not found"):
        store.update_entry(999, subject="Ghost")


def test_update_entry_no_allowed_fields(tmp_path):
    """update_entry returns the entry unchanged when no allowed fields are passed."""
    store = MemoryStore(tmp_path / "memory.sqlite3")
    saved = store.save_entry(memory_type="task", subject="Title", content="Body")
    # Passing only unknown kwargs should be a no-op
    result = store.update_entry(saved["id"], unknown_field="ignored")
    assert result["subject"] == "Title"


def test_delete_entry_existing(tmp_path):
    """delete_entry removes an existing entry and returns True."""
    store = MemoryStore(tmp_path / "memory.sqlite3")
    saved = store.save_entry(memory_type="note", subject="Temp", content="To be deleted")
    assert store.delete_entry(saved["id"]) is True
    with pytest.raises(KeyError):
        store.get_entry(saved["id"])


def test_delete_entry_not_found(tmp_path):
    """delete_entry returns False when the entry does not exist."""
    store = MemoryStore(tmp_path / "memory.sqlite3")
    assert store.delete_entry(999) is False


def test_close_commitment(tmp_path):
    """close_commitment sets status to 'closed' on an existing commitment."""
    store = MemoryStore(tmp_path / "memory.sqlite3")
    saved = store.save_entry(
        memory_type="commitment",
        subject="Ship feature",
        content="Must go out by Friday.",
        status="open",
    )
    closed = store.close_commitment(saved["id"])
    assert closed["status"] == "closed"
    assert closed["subject"] == "Ship feature"


def test_save_entry_with_metadata_and_expires(tmp_path):
    """save_entry stores optional metadata and expires_at fields."""
    store = MemoryStore(tmp_path / "memory.sqlite3")
    saved = store.save_entry(
        memory_type="preference",
        subject="Dark mode",
        content="User prefers dark theme.",
        metadata={"ui": "dark", "version": 2},
        expires_at="2027-01-01T00:00:00+00:00",
    )
    assert saved["metadata"] == {"ui": "dark", "version": 2}
    assert saved["expires_at"] == "2027-01-01T00:00:00+00:00"


def test_capture_persists_people_and_projects_with_capture_provenance(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")

    result = store.capture_and_process(
        "Discuss the street-play project with Harsh.",
        "chatgpt",
        lambda _text: {
            "people": [{"name": "Harsh", "context": "Practice pickup", "relationship": "friend"}],
            "projects": [{"name": "Street play", "description": "Practice logistics", "status": "active"}],
            "commitments": [],
            "action_items": [],
        },
    )

    assert result["capture"]["processing_state"] == "PROCESSED"
    assert {entry["memory_type"] for entry in result["memory_entries"]} == {"person", "project"}
    projects = store.query_entries(memory_type="project")
    assert projects[0]["subject"] == "Street play"
    assert projects[0]["metadata"]["capture_id"] == result["capture"]["capture_id"]


def test_lists_open_life_commitments_separately_from_memory_entries(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    capture = store.lifeops.create_capture("Do thing", source="test")
    store.lifeops.process_capture(
        capture["capture_id"],
        lambda _text: {"commitments": [{"text": "Do thing"}], "action_items": []},
    )

    result = store.list_open_life_commitments()
    assert len(result) == 1
    assert result[0]["title"] == "Do thing"
