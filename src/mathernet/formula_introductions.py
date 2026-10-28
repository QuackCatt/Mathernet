from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import StorageError, ValidationError
from .fsutil import chmod_private
from .rules import validate_bounded_text


class FormulaIntroductionStore:
    def __init__(self, path: Path | str = "data/formula_introductions.json"):
        self.path = Path(path).expanduser()

    def get(self, formula_id: str) -> dict[str, Any] | None:
        item = self._load().get(formula_id)
        if not isinstance(item, dict):
            return None
        return self._validated(formula_id, item)

    def delete(self, formula_id: str) -> bool:
        values = self._load()
        if values.pop(formula_id, None) is None:
            return False
        self._save(values)
        return True

    def save(self, formula_id: str, introduction: str) -> dict[str, Any]:
        formula_id = validate_bounded_text(formula_id, "formula_id", max_length=200)
        introduction = validate_bounded_text(
            introduction,
            "introduction",
            max_length=6_000,
        )
        if not introduction:
            raise ValidationError("introduction must not be empty")
        values = self._load()
        item = {
            "formula_id": formula_id,
            "introduction": introduction,
            "generated_at": _now(),
        }
        values[formula_id] = item
        self._save(values)
        return dict(item)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise StorageError(f"could not read formula introductions at {self.path}: {error}") from error
        if not isinstance(value, dict):
            raise StorageError("formula introduction data must contain an object")
        return value

    def _save(self, value: dict[str, Any]) -> None:
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
            raise StorageError(f"could not write formula introductions: {error}") from error

    @staticmethod
    def _validated(formula_id: str, item: dict[str, Any]) -> dict[str, Any]:
        introduction = validate_bounded_text(
            item.get("introduction", ""),
            "introduction",
            max_length=6_000,
        )
        if not introduction:
            raise ValidationError("stored introduction must not be empty")
        generated_at = str(item.get("generated_at") or _now())
        return {
            "formula_id": formula_id,
            "introduction": introduction,
            "generated_at": generated_at,
        }


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
