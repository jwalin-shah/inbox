from __future__ import annotations

import sqlite3

import contacts
import inbox_server


def test_addressbook_contact_count_counts_named_records_without_copying_values(tmp_path, monkeypatch):
    db_path = tmp_path / "AddressBook-v22.abcddb"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE ZABCDRECORD (Z_PK INTEGER, ZFIRSTNAME TEXT, ZLASTNAME TEXT, ZORGANIZATION TEXT)"
        )
        conn.executemany(
            "INSERT INTO ZABCDRECORD VALUES (?, ?, ?, ?)",
            [(1, "Arav", None, None), (2, None, None, "Example Org"), (3, None, None, None)],
        )
    monkeypatch.setattr(contacts, "_addressbook_paths", lambda: [db_path])

    assert inbox_server._addressbook_contact_count() == 2
