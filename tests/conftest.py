"""Shared fixtures for inbox tests."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

APPLE_EPOCH = datetime(2001, 1, 1)


def _apple_ts(dt: datetime) -> float:
    """Convert a datetime to Apple epoch seconds."""
    return (dt - APPLE_EPOCH).total_seconds()


@pytest.fixture()
def tmp_reminders_db(tmp_path):
    """Create a temporary Reminders SQLite DB with test data."""
    stores = tmp_path / "Stores"
    stores.mkdir()
    db_path = stores / "Data-test.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """CREATE TABLE ZREMCDBASELIST (
            Z_PK INTEGER PRIMARY KEY,
            Z_ENT INTEGER,
            ZMARKEDFORDELETION INTEGER,
            ZEFFECTIVEMINIMUMSUPPORTEDAPPVERSION INTEGER,
            ZISGROUP INTEGER,
            ZNAME VARCHAR
        )"""
    )
    conn.execute(
        """CREATE TABLE ZREMCDREMINDER (
            Z_PK INTEGER PRIMARY KEY,
            Z_ENT INTEGER,
            ZTITLE VARCHAR,
            ZCOMPLETED INTEGER DEFAULT 0,
            ZFLAGGED INTEGER DEFAULT 0,
            ZPRIORITY INTEGER DEFAULT 0,
            ZMARKEDFORDELETION INTEGER,
            ZEFFECTIVEMINIMUMSUPPORTEDAPPVERSION INTEGER,
            ZDUEDATE TIMESTAMP,
            ZNOTES VARCHAR,
            ZCREATIONDATE TIMESTAMP,
            ZLIST INTEGER REFERENCES ZREMCDBASELIST(Z_PK)
        )"""
    )
    # Insert lists
    conn.execute("INSERT INTO ZREMCDBASELIST (Z_PK, ZNAME) VALUES (1, 'Daily')")
    conn.execute("INSERT INTO ZREMCDBASELIST (Z_PK, ZNAME) VALUES (2, 'Work')")

    now = datetime.now()
    # Insert reminders
    conn.execute(
        "INSERT INTO ZREMCDREMINDER (Z_PK, ZTITLE, ZCOMPLETED, ZFLAGGED, ZPRIORITY, ZDUEDATE, ZCREATIONDATE, ZLIST) "
        "VALUES (1, 'Buy groceries', 0, 0, 0, ?, ?, 1)",
        (_apple_ts(now + timedelta(days=1)), _apple_ts(now)),
    )
    conn.execute(
        "INSERT INTO ZREMCDREMINDER (Z_PK, ZTITLE, ZCOMPLETED, ZFLAGGED, ZPRIORITY, ZDUEDATE, ZCREATIONDATE, ZLIST) "
        "VALUES (2, 'Ship feature', 0, 1, 1, ?, ?, 2)",
        (_apple_ts(now + timedelta(hours=3)), _apple_ts(now)),
    )
    conn.execute(
        "INSERT INTO ZREMCDREMINDER (Z_PK, ZTITLE, ZCOMPLETED, ZFLAGGED, ZPRIORITY, ZCREATIONDATE, ZLIST) "
        "VALUES (3, 'Done task', 1, 0, 0, ?, 1)",
        (_apple_ts(now - timedelta(days=1)),),
    )
    conn.commit()
    conn.close()
    return stores


@pytest.fixture()
def mock_github_token():
    """Patch GitHub token to return a fake token."""
    with patch("services._github_token", return_value="ghp_fake_test_token"):
        yield


@pytest.fixture()
def mock_drive_service():
    """Create a mock Google Drive service."""
    svc = MagicMock()
    return svc
