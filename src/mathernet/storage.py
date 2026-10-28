from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .errors import StorageError, ValidationError
from .fsutil import chmod_private
from .models import GraphDocument
from .rules import validate_graph_rules


class JsonGraphStore:
    """Atomic local JSON persistence for the knowledge graph."""

    def __init__(self, path: Path | str):
        self.path = Path(path).expanduser()

    def load(self) -> GraphDocument:
        if not self.path.exists():
            return GraphDocument()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise StorageError(f"could not read local graph at {self.path}: {error}") from error
        if not isinstance(data, dict):
            raise StorageError(f"local graph at {self.path} must contain a JSON object")
        try:
            document = GraphDocument.from_dict(data)
            validate_graph_rules(document)
            return document
        except ValidationError as error:
            raise StorageError(f"invalid local graph at {self.path}: {error}") from error

    def save(self, document: GraphDocument) -> None:
        try:
            validate_graph_rules(document)
        except ValidationError as error:
            raise StorageError(f"invalid graph document: {error}") from error
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(document.to_dict(), ensure_ascii=False, indent=2) + "\n"
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temp_path = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            chmod_private(temp_path)
            os.replace(temp_path, self.path)
        except OSError as error:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise StorageError(f"could not save local graph at {self.path}: {error}") from error

    def export(self, destination: Path | str, document: GraphDocument | None = None) -> None:
        export_store = JsonGraphStore(destination)
        export_store.save(document or self.load())


def read_json_object(path: Path | str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StorageError(f"could not read JSON file {path}: {error}") from error
    if not isinstance(value, dict):
        raise StorageError(f"JSON file {path} must contain an object")
    return value
