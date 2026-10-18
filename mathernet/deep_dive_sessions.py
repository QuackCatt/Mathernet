from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import NotFoundError, StorageError, SynthesisError, ValidationError
from .rules import validate_bounded_text


MAX_SESSION_MESSAGE_LENGTH = 2_000
MAX_SESSION_REPLY_LENGTH = 12_000


class DeepDiveSessionStore:
    def __init__(self, path: Path | str = "data/deep_dive_sessions.json"):
        self.path = Path(path).expanduser()

    def list(self, formula_id: str) -> list[dict[str, Any]]:
        sessions = self._load().get(formula_id, [])
        if not isinstance(sessions, list):
            return []
        summaries = [self._summary(session) for session in sessions if isinstance(session, dict)]
        return sorted(summaries, key=lambda item: item.get("updated_at", ""), reverse=True)

    def create(self, formula_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        sessions = self._load()
        formula_sessions = sessions.get(formula_id, [])
        if not isinstance(formula_sessions, list):
            formula_sessions = []
        session = self._validated_session(formula_id, payload, create=True)
        formula_sessions.append(session)
        sessions[formula_id] = formula_sessions
        self._save(sessions)
        return session

    def get(self, formula_id: str, session_id: str) -> dict[str, Any]:
        for session in self._formula_sessions(formula_id):
            if session.get("id") == session_id:
                return session
        raise NotFoundError("deep-dive session was not found")

    def append_message(
        self,
        formula_id: str,
        session_id: str,
        role: str,
        content: str,
    ) -> dict[str, Any]:
        session = self.get(formula_id, session_id)
        role = str(role).strip().lower()
        if role not in {"user", "assistant"}:
            raise ValidationError("message role must be user or assistant")
        limit = MAX_SESSION_MESSAGE_LENGTH if role == "user" else MAX_SESSION_REPLY_LENGTH
        content = validate_bounded_text(content, "message", max_length=limit)
        session.setdefault("messages", []).append({
            "role": role,
            "content": content,
            "created_at": _now(),
        })
        session["updated_at"] = _now()
        self._replace(formula_id, session)
        return session

    def delete(self, formula_id: str, session_id: str) -> None:
        sessions = self._load()
        formula_sessions = sessions.get(formula_id, [])
        if not isinstance(formula_sessions, list):
            raise NotFoundError("deep-dive session was not found")
        remaining = [item for item in formula_sessions if item.get("id") != session_id]
        if len(remaining) == len(formula_sessions):
            raise NotFoundError("deep-dive session was not found")
        if remaining:
            sessions[formula_id] = remaining
        else:
            sessions.pop(formula_id, None)
        self._save(sessions)

    def _replace(self, formula_id: str, session: dict[str, Any]) -> None:
        sessions = self._load()
        formula_sessions = sessions.get(formula_id, [])
        sessions[formula_id] = [
            session if item.get("id") == session.get("id") else item
            for item in formula_sessions
            if isinstance(item, dict)
        ]
        self._save(sessions)

    def _formula_sessions(self, formula_id: str) -> list[dict[str, Any]]:
        sessions = self._load().get(formula_id, [])
        return [item for item in sessions if isinstance(item, dict)] if isinstance(sessions, list) else []

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise StorageError(f"could not read deep-dive sessions at {self.path}: {error}") from error
        if not isinstance(value, dict):
            raise StorageError("deep-dive session data must contain an object")
        return value

    def _save(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        temp = self.path.with_suffix(".tmp")
        try:
            temp.write_text(payload, encoding="utf-8")
            os.chmod(temp, 0o600)
            os.replace(temp, self.path)
            os.chmod(self.path, 0o600)
        except OSError as error:
            temp.unlink(missing_ok=True)
            raise StorageError(f"could not write deep-dive sessions: {error}") from error

    def _validated_session(
        self,
        formula_id: str,
        payload: dict[str, Any],
        *,
        create: bool = False,
    ) -> dict[str, Any]:
        session_id = str(payload.get("id", "")).strip()
        if create and not session_id:
            session_id = f"session_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        title = validate_bounded_text(payload.get("title", "Deep dive"), "title", max_length=120) or "Deep dive"
        article = self._validated_article(payload.get("article"))
        if not article:
            if create:
                raise SynthesisError("deep-dive generation returned no usable article")
            raise ValidationError("deep-dive article is required")
        sources = payload.get("sources", [])
        if not isinstance(sources, list):
            raise ValidationError("sources must be a list")
        messages = payload.get("messages", [])
        if not isinstance(messages, list):
            raise ValidationError("messages must be a list")
        now = _now()
        return {
            "id": session_id,
            "formula_id": formula_id,
            "title": title,
            "article": article,
            "sources": sources[:10],
            "warnings": [str(item)[:2_000] for item in payload.get("warnings", []) if str(item).strip()][:20],
            "messages": messages[-100:],
            "created_at": str(payload.get("created_at") or now),
            "updated_at": str(payload.get("updated_at") or now),
        }

    @staticmethod
    def _validated_article(value: Any) -> dict[str, Any]:
        if isinstance(value, str):
            introduction = validate_bounded_text(value, "article.introduction", max_length=80_000)
            return {"introduction": introduction, "sections": []}
        if not isinstance(value, dict):
            raise ValidationError("article must be an object or string")
        introduction = validate_bounded_text(
            value.get("introduction", ""),
            "article.introduction",
            max_length=40_000,
            allow_empty=True,
        )
        sections = value.get("sections", [])
        if not isinstance(sections, list):
            raise ValidationError("article.sections must be a list")
        validated_sections = []
        allowed = {"story", "application", "background", "context", "other"}
        for item in sections[:12]:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind", "")).strip().lower()
            if kind not in allowed:
                continue
            subtitle = validate_bounded_text(item.get("subtitle", ""), "section.subtitle", max_length=160)
            heading = validate_bounded_text(item.get("heading", ""), "section.heading", max_length=240)
            body = validate_bounded_text(item.get("body", ""), "section.body", max_length=8_000)
            if subtitle and heading and body:
                validated_sections.append({
                    "kind": kind,
                    "subtitle": subtitle,
                    "heading": heading,
                    "body": body,
                })
        if not introduction and not validated_sections:
            return {}
        return {"introduction": introduction, "sections": validated_sections}

    @staticmethod
    def _summary(session: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": session.get("id", ""),
            "formula_id": session.get("formula_id", ""),
            "title": session.get("title", "Deep dive"),
            "created_at": session.get("created_at", ""),
            "updated_at": session.get("updated_at", ""),
            "message_count": len(session.get("messages", [])),
        }


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

