"""Tests for contacts.py — phone normalization and contact resolution."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import contacts
from contacts import (
    ContactBook,
    _addressbook_paths,
    _digits_only,
    _phone_variants,
    load_contact_map,
)

# ── _digits_only ────────────────────────────────────────────────────────────


class TestDigitsOnly:
    def test_strips_non_digits(self):
        assert _digits_only("+1 (415) 555-1234") == "14155551234"

    def test_returns_none_for_empty(self):
        assert _digits_only("") is None

    def test_returns_none_for_no_digits(self):
        assert _digits_only("abc") is None

    def test_already_clean(self):
        assert _digits_only("4155551234") == "4155551234"

    def test_international_format(self):
        assert _digits_only("+44 20 7946 0958") == "442079460958"


# ── _phone_variants ─────────────────────────────────────────────────────────


class TestPhoneVariants:
    def test_empty_input(self):
        assert _phone_variants("") == []

    def test_no_digits(self):
        assert _phone_variants("hello") == []

    def test_10_digit_us(self):
        variants = _phone_variants("4155551234")
        assert "4155551234" in variants
        assert "+4155551234" in variants
        # Should also have 11-digit variant with leading 1
        assert "14155551234" in variants
        assert "+14155551234" in variants

    def test_11_digit_us_with_leading_1(self):
        variants = _phone_variants("14155551234")
        assert "14155551234" in variants
        assert "+14155551234" in variants
        # Should also have 10-digit short form
        assert "4155551234" in variants
        assert "+4155551234" in variants

    def test_formatted_phone(self):
        variants = _phone_variants("+1 (415) 555-1234")
        assert "14155551234" in variants
        assert "4155551234" in variants

    def test_no_duplicates(self):
        variants = _phone_variants("4155551234")
        assert len(variants) == len(set(variants))

    def test_short_number_no_expansion(self):
        # 7 digits — not 10 or 11, so no US expansion
        variants = _phone_variants("5551234")
        assert variants == ["5551234", "+5551234"]

    def test_international_no_expansion(self):
        # 12 digits — not 10 or 11
        variants = _phone_variants("442079460958")
        assert variants == ["442079460958", "+442079460958"]


# ── ContactBook ─────────────────────────────────────────────────────────────


class TestContactBook:
    def _make_book(self, mapping: dict[str, str]) -> ContactBook:
        book = ContactBook()
        book._map = mapping
        return book

    def test_resolve_direct_hit_email(self):
        book = self._make_book({"alice@example.com": "Alice Smith"})
        assert book.resolve("alice@example.com") == "Alice Smith"

    def test_resolve_case_insensitive_email(self):
        book = self._make_book({"alice@example.com": "Alice Smith"})
        assert book.resolve("Alice@Example.COM") == "Alice Smith"

    def test_resolve_phone_direct(self):
        book = self._make_book({"4155551234": "Bob Jones"})
        assert book.resolve("4155551234") == "Bob Jones"

    def test_resolve_phone_variant_match(self):
        book = self._make_book({"14155551234": "Bob Jones"})
        # Input is 10-digit, but map has 11-digit — variants should match
        assert book.resolve("4155551234") == "Bob Jones"

    def test_resolve_formatted_phone(self):
        book = self._make_book({"+14155551234": "Bob Jones"})
        assert book.resolve("+1 (415) 555-1234") == "Bob Jones"

    def test_resolve_unknown_returns_raw(self):
        book = self._make_book({})
        assert book.resolve("+99999999999") == "+99999999999"

    def test_resolve_empty_returns_empty(self):
        book = self._make_book({"foo": "bar"})
        assert book.resolve("") == ""

    def test_resolve_strips_whitespace(self):
        book = self._make_book({"alice@example.com": "Alice"})
        assert book.resolve("  alice@example.com  ") == "Alice"


# ── _addressbook_paths ─────────────────────────────────────────────────────


class TestAddressbookPaths:
    """Tests for _addressbook_paths() — uses real temp directories on a
    fake home to avoid touching the real filesystem."""

    def _setup_home(self, tmp_path: Path, monkeypatch) -> Path:
        """Create a fake home dir structure and redirect Path.home()."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        return tmp_path / "Library" / "Application Support" / "AddressBook"

    def test_returns_empty_when_no_paths_exist(self, tmp_path, monkeypatch):
        base = self._setup_home(tmp_path, monkeypatch)
        base.mkdir(parents=True)  # directory exists but no DB files
        assert _addressbook_paths() == []

    def test_finds_base_db_v22(self, tmp_path, monkeypatch):
        base = self._setup_home(tmp_path, monkeypatch)
        base.mkdir(parents=True)
        db = base / "AddressBook-v22.abcddb"
        db.touch()
        paths = _addressbook_paths()
        assert len(paths) == 1
        assert paths[0] == db

    def test_falls_back_to_v21_when_v22_missing(self, tmp_path, monkeypatch):
        base = self._setup_home(tmp_path, monkeypatch)
        base.mkdir(parents=True)
        db = base / "AddressBook-v21.abcddb"
        db.touch()
        paths = _addressbook_paths()
        assert len(paths) == 1
        assert paths[0] == db

    def test_falls_back_to_v20(self, tmp_path, monkeypatch):
        base = self._setup_home(tmp_path, monkeypatch)
        base.mkdir(parents=True)
        db = base / "AddressBook-v20.abcddb"
        db.touch()
        paths = _addressbook_paths()
        assert len(paths) == 1
        assert paths[0] == db

    def test_prefers_newer_version_when_multiple_exist(self, tmp_path, monkeypatch):
        base = self._setup_home(tmp_path, monkeypatch)
        base.mkdir(parents=True)
        (base / "AddressBook-v22.abcddb").touch()
        (base / "AddressBook-v21.abcddb").touch()
        (base / "AddressBook-v20.abcddb").touch()
        paths = _addressbook_paths()
        # Should pick v22 (first in iteration order) and break
        assert len(paths) == 1
        assert paths[0].name == "AddressBook-v22.abcddb"

    def test_finds_sources_subdirs(self, tmp_path, monkeypatch):
        base = self._setup_home(tmp_path, monkeypatch)
        base.mkdir(parents=True)
        (base / "AddressBook-v22.abcddb").touch()
        sources = base / "Sources"
        sources.mkdir()
        # Source subdirectory with v22
        src1 = sources / "SourceA"
        src1.mkdir()
        db2 = src1 / "AddressBook-v22.abcddb"
        db2.touch()
        # Another source subdirectory with v21
        src2 = sources / "SourceB"
        src2.mkdir()
        db3 = src2 / "AddressBook-v21.abcddb"
        db3.touch()
        paths = _addressbook_paths()
        assert len(paths) == 3
        assert db2 in paths
        assert db3 in paths

    def test_sources_iterdir_permission_error_is_caught(self, tmp_path, monkeypatch):
        base = self._setup_home(tmp_path, monkeypatch)
        base.mkdir(parents=True)
        (base / "AddressBook-v22.abcddb").touch()
        sources = base / "Sources"
        sources.mkdir()
        # Prevent iterdir from working on Sources
        monkeypatch.setattr(Path, "iterdir", lambda self, sources=sources: (
            (_ for _ in ()) if self != sources else (_raise(PermissionError))
        ))
        paths = _addressbook_paths()
        # Should still return the base DB
        assert len(paths) == 1
        assert paths[0].name == "AddressBook-v22.abcddb"

    def test_only_sources_no_base(self, tmp_path, monkeypatch):
        base = self._setup_home(tmp_path, monkeypatch)
        base.mkdir(parents=True)
        # No base DB files
        sources = base / "Sources"
        sources.mkdir()
        src1 = sources / "SourceA"
        src1.mkdir()
        db = src1 / "AddressBook-v22.abcddb"
        db.touch()
        paths = _addressbook_paths()
        assert len(paths) == 1
        assert paths[0] == db

    def test_sources_falls_back_to_older_versions(self, tmp_path, monkeypatch):
        base = self._setup_home(tmp_path, monkeypatch)
        base.mkdir(parents=True)
        sources = base / "Sources"
        sources.mkdir()
        src = sources / "SourceA"
        src.mkdir()
        # v22 missing, v21 exists
        db = src / "AddressBook-v21.abcddb"
        db.touch()
        paths = _addressbook_paths()
        assert len(paths) == 1
        assert paths[0] == db


def _raise(exc):
    raise exc


# ── load_contact_map ───────────────────────────────────────────────────────


class TestLoadContactMap:
    """Tests for load_contact_map() — mocks _addressbook_paths and sqlite3
    to verify query execution, contact extraction, and error handling."""

    def _fake_db_path(self) -> str:
        return "/fake/AddressBook-v22.abcddb"

    def _mock_conn_with_rows(self, rows: list[tuple]) -> MagicMock:
        """Return a mock sqlite3 connection that yields the given rows."""
        conn = MagicMock()
        cur = conn.cursor.return_value
        # First query: table existence check → return a row (table exists)
        cur.fetchone.return_value = (1,)
        cur.fetchall.return_value = rows
        return conn

    def test_empty_paths_returns_empty_dict(self, monkeypatch):
        monkeypatch.setattr(contacts, "_addressbook_paths", lambda: [])
        assert load_contact_map() == {}

    def test_single_contact_with_phone_and_email(self, monkeypatch):
        monkeypatch.setattr(contacts, "_addressbook_paths", lambda: [self._fake_db_path()])
        rows = [
            (1, "Alice", "Smith", None, None, "+14155551234", "alice@example.com"),
        ]
        mock_conn = self._mock_conn_with_rows(rows)
        with patch("contacts.sqlite3.connect", return_value=mock_conn):
            result = load_contact_map()
        assert "alice@example.com" in result
        assert result["alice@example.com"] == "Alice Smith"
        # Phone variants should also be mapped
        assert "14155551234" in result
        assert result["14155551234"] == "Alice Smith"

    def test_organization_only_contact(self, monkeypatch):
        monkeypatch.setattr(contacts, "_addressbook_paths", lambda: [self._fake_db_path()])
        rows = [
            (2, None, None, None, "Acme Corp", "+14155559999", None),
        ]
        mock_conn = self._mock_conn_with_rows(rows)
        with patch("contacts.sqlite3.connect", return_value=mock_conn):
            result = load_contact_map()
        assert "14155559999" in result
        assert result["14155559999"] == "Acme Corp"

    def test_contact_with_no_name_skipped(self, monkeypatch):
        monkeypatch.setattr(contacts, "_addressbook_paths", lambda: [self._fake_db_path()])
        rows = [
            (3, None, None, None, None, "+19999999999", "ghost@example.com"),
        ]
        mock_conn = self._mock_conn_with_rows(rows)
        with patch("contacts.sqlite3.connect", return_value=mock_conn):
            result = load_contact_map()
        # No name → skipped entirely
        assert result == {}

    def test_contact_with_no_phone_or_email_skipped(self, monkeypatch):
        monkeypatch.setattr(contacts, "_addressbook_paths", lambda: [self._fake_db_path()])
        rows = [
            (4, "Bob", "Jones", None, None, None, None),
        ]
        mock_conn = self._mock_conn_with_rows(rows)
        with patch("contacts.sqlite3.connect", return_value=mock_conn):
            result = load_contact_map()
        # Has name but no phone/email → nothing to map
        assert result == {}

    def test_middle_name_in_parts(self, monkeypatch):
        monkeypatch.setattr(contacts, "_addressbook_paths", lambda: [self._fake_db_path()])
        rows = [
            (5, "John", "Doe", "Michael", None, None, "john@example.com"),
        ]
        mock_conn = self._mock_conn_with_rows(rows)
        with patch("contacts.sqlite3.connect", return_value=mock_conn):
            result = load_contact_map()
        # Middle name is fetched but NOT included in parts — only first + last
        assert result["john@example.com"] == "John Doe"

    def test_missing_table_skips_db(self, monkeypatch):
        monkeypatch.setattr(contacts, "_addressbook_paths", lambda: [self._fake_db_path()])
        conn = MagicMock()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = None  # table doesn't exist
        with patch("contacts.sqlite3.connect", return_value=conn):
            result = load_contact_map()
        assert result == {}
        conn.close.assert_called_once()

    def test_db_exception_is_caught(self, monkeypatch):
        monkeypatch.setattr(contacts, "_addressbook_paths", lambda: [self._fake_db_path()])
        with patch("contacts.sqlite3.connect", side_effect=sqlite3.OperationalError("disk I/O error")):
            result = load_contact_map()
        # Exception is caught, returns empty
        assert result == {}

    def test_multiple_databases_aggregate(self, monkeypatch):
        paths = ["/fake/db1.abcddb", "/fake/db2.abcddb"]
        monkeypatch.setattr(contacts, "_addressbook_paths", lambda: list(paths))

        def connect_side_effect(database, **kwargs):
            conn = MagicMock()
            cur = conn.cursor.return_value
            cur.fetchone.return_value = (1,)
            if "db1" in str(database):
                cur.fetchall.return_value = [
                    (1, "Alice", "Smith", None, None, None, "alice@example.com"),
                ]
            else:
                cur.fetchall.return_value = [
                    (2, "Bob", "Jones", None, None, None, "bob@example.com"),
                ]
            return conn

        with patch("contacts.sqlite3.connect", side_effect=connect_side_effect):
            result = load_contact_map()
        assert result["alice@example.com"] == "Alice Smith"
        assert result["bob@example.com"] == "Bob Jones"

    def test_setdefault_preserves_first_name(self, monkeypatch):
        """When the same phone variant maps to two contacts, first wins."""
        monkeypatch.setattr(contacts, "_addressbook_paths", lambda: [self._fake_db_path()])
        rows = [
            (1, "Alice", "Smith", None, None, "+14155551234", None),
            (2, "Alice", "Jones", None, None, "+14155551234", None),
        ]
        mock_conn = self._mock_conn_with_rows(rows)
        with patch("contacts.sqlite3.connect", return_value=mock_conn):
            result = load_contact_map()
        assert result["14155551234"] == "Alice Smith"  # first wins

    def test_phone_email_lowercased_keys(self, monkeypatch):
        monkeypatch.setattr(contacts, "_addressbook_paths", lambda: [self._fake_db_path()])
        rows = [
            (1, "Alice", "Smith", None, None, "+14155551234", "Alice@Example.COM"),
        ]
        mock_conn = self._mock_conn_with_rows(rows)
        with patch("contacts.sqlite3.connect", return_value=mock_conn):
            result = load_contact_map()
        # Keys are lowercased
        assert "alice@example.com" in result
        assert "ALICE@EXAMPLE.COM" not in result
        assert "14155551234" in result

    def test_email_none_not_mapped(self, monkeypatch):
        monkeypatch.setattr(contacts, "_addressbook_paths", lambda: [self._fake_db_path()])
        rows = [
            (1, "Alice", "Smith", None, None, "+14155551234", None),
        ]
        mock_conn = self._mock_conn_with_rows(rows)
        with patch("contacts.sqlite3.connect", return_value=mock_conn):
            result = load_contact_map()
        # Only phone is mapped, no email
        assert "14155551234" in result
        assert len(result) == len(_phone_variants("+14155551234"))  # all variants


# ── ContactBook.load ───────────────────────────────────────────────────────


class TestContactBookLoad:
    """Tests for ContactBook.load() — the public entry point that delegates
    to load_contact_map()."""

    def test_load_populates_map_and_returns_count(self, monkeypatch):
        fake_map = {
            "alice@example.com": "Alice Smith",
            "4155551234": "Bob Jones",
        }
        monkeypatch.setattr(contacts, "load_contact_map", lambda: fake_map)
        book = ContactBook()
        count = book.load()
        assert count == 2
        assert book._map == fake_map

    def test_load_with_empty_result(self, monkeypatch):
        monkeypatch.setattr(contacts, "load_contact_map", lambda: {})
        book = ContactBook()
        count = book.load()
        assert count == 0
        assert book._map == {}
