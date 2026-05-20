"""Outbound network audit and allowlist helpers."""

from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

BASE_DIR = Path(__file__).parent
EGRESS_AUDIT_DB = BASE_DIR / ".inbox_egress_audit.sqlite3"
ALLOWLIST_ENV = "INBOX_EGRESS_ALLOWLIST"
LOCAL_ONLY_ENV = "INBOX_LOCAL_ONLY"
DEFAULT_ALLOWED_HOSTS = frozenset(
    {
        "api.github.com",
        "maps.googleapis.com",
    }
)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def local_only_enabled() -> bool:
    return os.getenv(LOCAL_ONLY_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def allowed_hosts() -> set[str]:
    raw = os.getenv(ALLOWLIST_ENV, "").strip()
    if not raw:
        return set(DEFAULT_ALLOWED_HOSTS)
    return {host.strip().lower() for host in raw.split(",") if host.strip()}


def host_allowed(host: str) -> bool:
    host = host.lower()
    return any(host == allowed or host.endswith(f".{allowed}") for allowed in allowed_hosts())


@dataclass
class EgressAuditRecord:
    method: str
    url: str
    host: str
    allowed: bool
    blocked: bool
    status_code: int | None = None
    error: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "url": self.url,
            "host": self.host,
            "allowed": self.allowed,
            "blocked": self.blocked,
            "status_code": self.status_code,
            "error": self.error,
            "timestamp": self.timestamp,
        }


class EgressAuditStore:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or EGRESS_AUDIT_DB
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path, timeout=5.0) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS egress_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    method TEXT NOT NULL,
                    url TEXT NOT NULL,
                    host TEXT NOT NULL,
                    allowed INTEGER NOT NULL,
                    blocked INTEGER NOT NULL,
                    status_code INTEGER,
                    error TEXT NOT NULL DEFAULT '',
                    timestamp TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def record(self, record: EgressAuditRecord) -> None:
        timestamp = record.timestamp or _utc_now_iso()
        with self._lock, sqlite3.connect(self.db_path, timeout=5.0) as conn:
            conn.execute(
                """
                INSERT INTO egress_audit (
                    method, url, host, allowed, blocked, status_code, error, timestamp
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.method,
                    record.url,
                    record.host,
                    int(record.allowed),
                    int(record.blocked),
                    record.status_code,
                    record.error,
                    timestamp,
                ),
            )
            conn.commit()

    def list_recent(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, sqlite3.connect(self.db_path, timeout=5.0) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT method, url, host, allowed, blocked, status_code, error, timestamp
                FROM egress_audit
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            EgressAuditRecord(
                method=row["method"],
                url=row["url"],
                host=row["host"],
                allowed=bool(row["allowed"]),
                blocked=bool(row["blocked"]),
                status_code=row["status_code"],
                error=row["error"],
                timestamp=row["timestamp"],
            ).to_dict()
            for row in rows
        ]


_DEFAULT_STORE: EgressAuditStore | None = None
_DEFAULT_STORE_LOCK = threading.RLock()


def audit_store() -> EgressAuditStore:
    global _DEFAULT_STORE
    with _DEFAULT_STORE_LOCK:
        if _DEFAULT_STORE is None:
            _DEFAULT_STORE = EgressAuditStore()
        assert _DEFAULT_STORE is not None
    return _DEFAULT_STORE


def request(method: str, url: str, **kwargs: Any) -> httpx.Response:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    allowed = host_allowed(host)
    blocked = local_only_enabled() and not allowed
    method_upper = method.upper()

    if blocked:
        audit_store().record(
            EgressAuditRecord(
                method=method_upper,
                url=url,
                host=host,
                allowed=False,
                blocked=True,
                error=f"Blocked by {LOCAL_ONLY_ENV}",
            )
        )
        raise httpx.RequestError(f"Outbound host not allowlisted: {host}")

    try:
        response = httpx.request(method_upper, url, **kwargs)
    except Exception as exc:
        audit_store().record(
            EgressAuditRecord(
                method=method_upper,
                url=url,
                host=host,
                allowed=allowed,
                blocked=False,
                error=str(exc),
            )
        )
        raise

    audit_store().record(
        EgressAuditRecord(
            method=method_upper,
            url=url,
            host=host,
            allowed=allowed,
            blocked=False,
            status_code=response.status_code,
        )
    )
    return response


def get(url: str, **kwargs: Any) -> httpx.Response:
    return request("GET", url, **kwargs)


def patch(url: str, **kwargs: Any) -> httpx.Response:
    return request("PATCH", url, **kwargs)


def put(url: str, **kwargs: Any) -> httpx.Response:
    return request("PUT", url, **kwargs)


def status() -> dict[str, Any]:
    return {
        "local_only": local_only_enabled(),
        "allowlist": sorted(allowed_hosts()),
        "db_path": str(audit_store().db_path),
        "direct_httpx_wrapped": True,
        "coverage_notes": (
            "Audits direct Inbox httpx calls. Google SDK transport auditing is a separate hardening step."
        ),
    }
