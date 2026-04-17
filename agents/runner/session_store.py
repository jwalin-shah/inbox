from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from pathlib import Path

from .paths import sessions_dir
from .result_types import SessionRecord, SessionStep, utc_now


class SessionStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or sessions_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, profile_name: str, goal: str) -> SessionRecord:
        session_id = uuid.uuid4().hex
        record = SessionRecord(
            session_id=session_id,
            profile_name=profile_name,
            goal=goal,
        )
        self.save(record)
        return record

    def load(self, session_id: str) -> SessionRecord:
        payload = json.loads(self._path_for(session_id).read_text(encoding="utf-8"))
        steps = [SessionStep(**step) for step in payload.get("steps", [])]
        payload["steps"] = steps
        return SessionRecord(**payload)

    def save(self, record: SessionRecord) -> None:
        record.updated_at = utc_now()
        data = asdict(record)
        self._path_for(record.session_id).write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def append_step(self, session_id: str, step: SessionStep) -> SessionRecord:
        record = self.load(session_id)
        record.steps.append(step)
        self.save(record)
        return record

    def finalize(self, session_id: str, success: bool, final_message: str) -> SessionRecord:
        record = self.load(session_id)
        record.status = "succeeded" if success else "failed"
        record.final_message = final_message
        self.save(record)
        return record

    def _path_for(self, session_id: str) -> Path:
        return self.root / f"{session_id}.json"
