from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import NotFoundError, StorageError, ValidationError
from .fsutil import chmod_private
from .rules import validate_bounded_text


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class MapSessionStore:
    def __init__(self, path: Path | str = "data/map_sessions.json"):
        self.path = Path(path).expanduser()

    @property
    def exists(self) -> bool:
        return self.path.exists()

    def list(self) -> list[dict[str, Any]]:
        sessions = [item for item in self._load() if isinstance(item, dict)]
        sessions.sort(key=lambda item: str(item.get("name", "")).casefold())
        sessions.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        sessions.sort(key=lambda item: bool(item.get("pinned", False)), reverse=True)
        return sessions

    def get(self, session_id: str) -> dict[str, Any]:
        for session in self._load():
            if isinstance(session, dict) and session.get("id") == session_id:
                return dict(session)
        raise NotFoundError("map session was not found")

    def create(
        self,
        *,
        name: str,
        formula_ids: list[str] | None = None,
        pinned: bool = False,
    ) -> dict[str, Any]:
        sessions = self._load()
        normalized_name = validate_bounded_text(name, "name", max_length=120)
        normalized_ids = self._formula_ids(formula_ids or [])
        now = _now()
        session_id = f"map_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        session = {
            "id": session_id,
            "name": normalized_name,
            "pinned": bool(pinned),
            "formula_ids": normalized_ids,
            "created_at": now,
            "updated_at": now,
        }
        sessions.append(session)
        self._save(sessions)
        return dict(session)

    def update(
        self,
        session_id: str,
        *,
        name: str | None = None,
        pinned: bool | None = None,
    ) -> dict[str, Any]:
        sessions = self._load()
        for index, item in enumerate(sessions):
            if not isinstance(item, dict) or item.get("id") != session_id:
                continue
            updated = dict(item)
            if name is not None:
                updated["name"] = validate_bounded_text(name, "name", max_length=120)
            if pinned is not None:
                updated["pinned"] = bool(pinned)
            updated["updated_at"] = _now()
            sessions[index] = updated
            self._save(sessions)
            return dict(updated)
        raise NotFoundError("map session was not found")

    def delete(self, session_id: str) -> None:
        sessions = self._load()
        remaining = [
            item for item in sessions
            if not isinstance(item, dict) or item.get("id") != session_id
        ]
        if len(remaining) == len(sessions):
            raise NotFoundError("map session was not found")
        self._save(remaining)

    def add_formula(self, session_id: str, formula_id: str) -> tuple[dict[str, Any], bool]:
        sessions = self._load()
        normalized_id = str(formula_id).strip()
        if not normalized_id:
            raise ValidationError("formula_id must be a non-empty string")
        for index, item in enumerate(sessions):
            if not isinstance(item, dict) or item.get("id") != session_id:
                continue
            updated = dict(item)
            ids = self._formula_ids(item.get("formula_ids", []))
            if normalized_id in ids:
                return dict(updated), False
            ids.append(normalized_id)
            updated["formula_ids"] = ids
            updated["updated_at"] = _now()
            sessions[index] = updated
            self._save(sessions)
            return dict(updated), True
        raise NotFoundError("map session was not found")

    def remove_formula(self, formula_id: str) -> int:
        sessions = self._load()
        removed = 0
        changed = False
        for index, item in enumerate(sessions):
            if not isinstance(item, dict):
                continue
            ids = self._formula_ids(item.get("formula_ids", []))
            remaining = [item_id for item_id in ids if item_id != formula_id]
            if len(remaining) != len(ids):
                changed = True
                removed += len(ids) - len(remaining)
                updated = dict(item)
                updated["formula_ids"] = remaining
                updated["updated_at"] = _now()
                sessions[index] = updated
        if changed:
            self._save(sessions)
        return removed

    def snapshot(self) -> list[dict[str, Any]]:
        return deepcopy(self._load())

    def restore(self, sessions: list[dict[str, Any]]) -> None:
        self._save(deepcopy(sessions))

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise StorageError(f"could not read map sessions at {self.path}: {error}") from error
        if not isinstance(value, list):
            raise StorageError("map session data must contain a list")
        return value

    def _save(self, value: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        temp = self.path.with_suffix(".tmp")
        try:
            temp.write_text(payload, encoding="utf-8")
            chmod_private(temp)
            os.replace(temp, self.path)
            chmod_private(self.path)
        except OSError as error:
            temp.unlink(missing_ok=True)
            raise StorageError(f"could not write map sessions: {error}") from error

    @staticmethod
    def _formula_ids(value: Any) -> list[str]:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValidationError("formula_ids must be a list of strings")
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))
